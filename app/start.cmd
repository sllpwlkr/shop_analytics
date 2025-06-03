@echo off
chcp 65001 >nul
REM --------------------------------------------
REM Скрипт .cmd для Windows с добавленным запуском batch_job
REM --------------------------------------------

REM Переходим в директорию, где лежит этот скрипт
pushd "%~dp0"

echo.
echo ==== Шаг 1/10: Запуск контейнеров...
docker-compose -f infrastructure\docker-compose.yml up -d
echo Ожидание инициализации базовых сервисов...
timeout /t 15 /nobreak >nul

echo.
echo ==== Шаг 2/10: Проверка доступности ClickHouse...
for /L %%i in (1,1,10) do (
    curl -s http://localhost:8123/ping >nul 2>&1
    if not errorlevel 1 (
        echo ClickHouse доступен!
        goto CLICKHOUSE_READY
    )
    echo Ожидание ClickHouse... %%i/10
    timeout /t 3 /nobreak >nul
)
:CLICKHOUSE_READY

echo.
echo ==== Шаг 3/10: Создание топиков Kafka...
docker-compose -f infrastructure\docker-compose.yml exec -T kafka kafka-topics ^
    --create --topic purchases --bootstrap-server localhost:9092 ^
    --partitions 1 --replication-factor 1 --if-not-exists

echo.
echo ==== Шаг 4/10: Загрузка всего файла kafka_purchases.json в Kafka...
type "%~dp0data_ingestion\kafka_purchases.json" | docker-compose -f "infrastructure\docker-compose.yml" exec -T kafka kafka-console-producer --topic purchases --bootstrap-server localhost:9092

echo.
echo ==== Шаг 5/10: Выгрузка данных из PostgreSQL в S3...
docker-compose -f infrastructure\docker-compose.yml exec -T api bash -c "export PYTHONPATH=/app && python /app/data_ingestion/postgres_to_s3.py"

echo.
echo ==== Шаг 6/10: Запуск Spark-стриминга для загрузки данных из Kafka в S3...
docker-compose -f infrastructure\docker-compose.yml exec -T spark-master bash -c "pip install minio > /dev/null 2>&1 && export PYTHONPATH=/app && spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4,org.apache.spark:spark-sql-kafka-0-10_2.12:3.4.3 /app/data_ingestion/kafka_to_s3.py" >nul 2>&1
echo Spark-стриминг для Kafka успешно завершен.


echo.
echo ==== Шаг 7/10: Загрузка products.parquet в S3...
docker-compose -f infrastructure\docker-compose.yml exec -T api bash -c "export PYTHONPATH=/app && python /app/data_ingestion/upload_to_s3.py /app/data_ingestion/products.parquet"

echo.
echo ==== Шаг 8/10: Загрузка данных в STAGE слой...
docker-compose -f infrastructure\docker-compose.yml exec -T api bash -c "export PYTHONPATH=/app && python /app/data_ingestion/s3_stage_loader.py"

echo.
echo ==== Шаг 9/10: Запуск batch_job (daily_job.py) через Spark...
docker-compose -f infrastructure\docker-compose.yml exec -T spark-master bash -c "export PYTHONPATH=/app && spark-submit --master spark://spark-master:7077 --packages org.apache.hadoop:hadoop-aws:3.3.4,org.apache.iceberg:iceberg-spark-runtime-3.4_2.12:1.4.3,com.clickhouse:clickhouse-jdbc:0.4.6 /app/batch_processing/daily_job.py"
echo Batch_job (daily_job.py) выполнен.


echo.
echo ==== Шаг 10/10: Настройка оркестрации Airflow...
echo Airflow настроен для ежедневного запуска ETL-процессов в 2:00 AM
echo Доступ к Airflow: http://localhost:8081  (логин: admin / пароль: admin)
echo DAG ежедневной задачи: daily_shop_etl
echo.
echo Примечание: Инициализация Airflow может занять до 30–60 секунд.
echo Если вы видите ошибку airflow-init, не беспокойтесь, если контейнеры airflow-webserver и airflow-scheduler запустились успешно.

echo.
echo ==== Все шаги выполнены успешно! ====
echo.
echo Доступ к сервисам:
echo - API: http://localhost:8000
echo - MinIO Console: http://localhost:9001  (login: minioadmin / password: minioadmin)
echo - Spark Master UI: http://localhost:8080
echo - ClickHouse HTTP: http://localhost:8123
echo - ClickHouse UI: http://localhost:8124  (Tabix interface — login: default, пароль отсутствует)
echo - Airflow UI: http://localhost:8081  (login: admin / пароль: admin)
echo.
echo Потоковая обработка данных запущена в фоновом режиме через сервис streaming-processor.
echo.
echo Для просмотра логов сервисов:
echo   docker-compose -f infrastructure\docker-compose.yml logs -f [service_name]
echo.
echo Для остановки всех сервисов:
echo   docker-compose -f infrastructure\docker-compose.yml down

REM Возвращаемся в исходную директорию
popd

