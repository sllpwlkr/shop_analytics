from pyspark.sql import SparkSession

def process_customers(spark: SparkSession):
    # 1. Читаем parquet из MinIO
    df = spark.read.parquet("s3a://shop-stage-data/customers/")

    # 2. Удалим дубликаты и приведём колонки (если нужно)
    df_clean = df.dropDuplicates(["email"])
    
    df_clean = df_clean.select( "customer_id","first_name", "last_name", "email", "phone", "created_at"
    )

    # 3. Создаём таблицу Iceberg, если не существует
    spark.sql("""
        CREATE TABLE IF NOT EXISTS analytics.customers (
            customer_id INT,
            first_name STRING,
            last_name STRING,
            email STRING,
            phone STRING,
            created_at TIMESTAMP
        )
        USING iceberg
        PARTITIONED BY (months(created_at))
    """)

    # 4. Записываем данные
    df_clean.writeTo("analytics.customers").overwritePartitions()

