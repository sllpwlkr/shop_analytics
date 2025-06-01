from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
import os, sys

# Добавляем в sys.path путь к data_ingestion, utils и batch_processing
PROJECT_HOME = os.getenv("PROJECT_HOME", "/opt/airflow")
sys.path.insert(0, os.path.join(PROJECT_HOME, "data_ingestion"))
sys.path.insert(0, os.path.join(PROJECT_HOME, "utils"))
sys.path.insert(0, os.path.join(PROJECT_HOME, "batch_processing"))

# Проверяем, что папки существуют
for path in [
    os.path.join(PROJECT_HOME, "data_ingestion"), 
    os.path.join(PROJECT_HOME, "utils"),
    os.path.join(PROJECT_HOME, "batch_processing")
]:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

# Импортируем наши функции
try:
    from data_ingestion.upload_to_s3 import upload_products_from_parquet
    from data_ingestion.postgres_to_s3 import export_customers
    from data_ingestion.s3_stage_loader import main as stage_loader_main
except ImportError as e:
    import logging
    logging.error(f"Import error: {e}")
    # Альтернативный импорт, если первый не удается
    try:
        sys.path.append("/opt/airflow")
        from upload_to_s3 import upload_products_from_parquet
        from postgres_to_s3 import export_customers
        from s3_stage_loader import main as stage_loader_main
    except ImportError as e2:
        logging.error(f"Alternative import also failed: {e2}")

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="daily_shop_etl",
    default_args=default_args,
    description="Ежедневная загрузка товаров, клиентов и создание аналитики",
    start_date=datetime(2025, 6, 2, 2, 0),
    schedule_interval="0 2 * * *",
    catchup=False,
    tags=["shop", "etl", "daily"],
) as dag:

    task_upload_products = PythonOperator(
        task_id="upload_products_to_raw",
        python_callable=upload_products_from_parquet,
        op_kwargs={
            "local_parquet_path": "/opt/airflow/data_ingestion/products.parquet"
        },
    )

    task_export_customers = PythonOperator(
        task_id="export_customers_to_raw",
        python_callable=export_customers,
    )

    task_stage_loader = PythonOperator(
        task_id="copy_raw_to_stage_with_validation",
        python_callable=stage_loader_main,
    )
    
    # Задача для запуска Spark-джобы с интеграцией batch_processing
    task_run_batch_processing = SparkSubmitOperator(
        task_id='run_batch_processing',
        application='/opt/airflow/batch_processing/daily_job.py',
        conn_id='spark_default',
        verbose=True,
        packages=[
            'org.apache.hadoop:hadoop-aws:3.3.4',
            'org.apache.iceberg:iceberg-spark-runtime-3.4_2.12:1.4.3',
            'com.clickhouse:clickhouse-jdbc:0.4.6'
        ],
        conf={
            'spark.sql.catalog.iceberg': 'org.apache.iceberg.spark.SparkCatalog',
            'spark.sql.catalog.iceberg.type': 'hadoop',
            'spark.sql.catalog.iceberg.warehouse': 's3a://analytics/',
            'spark.hadoop.fs.s3a.endpoint': 'http://minio:9000',
            'spark.hadoop.fs.s3a.access.key': 'minioadmin',
            'spark.hadoop.fs.s3a.secret.key': 'minioadmin',
            'spark.hadoop.fs.s3a.path.style.access': 'true',
            'spark.sql.extensions': 'org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions'
        }
    )

    # Задаем последовательность выполнения задач
    task_upload_products >> task_export_customers >> task_stage_loader >> task_run_batch_processing