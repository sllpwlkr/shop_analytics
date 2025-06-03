from pyspark.sql import SparkSession
from pyspark.sql.functions import to_date, col


def process_purchases(spark: SparkSession):
    # 1. Чтение из stage-слоя
    df = spark.read.parquet("s3a://shop-stage-data/purchases/")

    # 2. Очистка и базовая обработка данных
    df_clean = (
        df.dropDuplicates()
        .dropna(subset=["customer_id", "product_id", "purchased_at"])
        # добавляем колонку purchase_date для партиционирования
        .withColumn("purchase_date", to_date(col("purchased_at")))
    )

    # 3. Явное создание таблицы Iceberg, если её нет
    spark.sql("""
        CREATE TABLE IF NOT EXISTS analytics.purchases (
            customer_id INT,
            product_id INT,
            seller_id INT,
            quantity INT,
            price_at_time DOUBLE,
            purchased_at TIMESTAMP,
            purchase_date DATE
        )
        USING iceberg
        PARTITIONED BY (purchase_date)
    """)

    # 4. Запись в таблицу Iceberg (теперь df_clean содержит purchase_date)
    df_clean.writeTo("analytics.purchases").overwritePartitions()

    print("✅ Purchases ETL complete")
