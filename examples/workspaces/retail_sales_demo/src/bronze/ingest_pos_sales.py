"""使用 Auto Loader 摄取 POS Parquet 的 Mock PySpark 风格样例。"""

from common.parameters import RuntimeParameters, read_runtime_parameters
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

POS_SCHEMA = StructType(
    [
        StructField("business_date", DateType(), False),
        StructField("store_id", StringType(), False),
        StructField("transaction_id", StringType(), False),
        StructField("line_id", StringType(), False),
        StructField("product_id", StringType(), False),
        StructField("customer_id", StringType(), True),
        StructField("quantity", DecimalType(18, 3), False),
        StructField("gross_amount", DecimalType(18, 2), False),
        StructField("discount_amount", DecimalType(18, 2), False),
        StructField("net_amount", DecimalType(18, 2), False),
        StructField("currency_code", StringType(), False),
        StructField("sale_ts", TimestampType(), False),
    ]
)


def read_pos_stream(spark: SparkSession, parameters: RuntimeParameters) -> DataFrame:
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.schemaEvolutionMode", "rescue")
        .option("cloudFiles.schemaLocation", f"{parameters.checkpoint_path}/schema")
        .option("rescuedDataColumn", "_rescued_data")
        .schema(POS_SCHEMA)
        .load(parameters.source_path)
    )


def prepare_bronze_rows(source: DataFrame, parameters: RuntimeParameters) -> DataFrame:
    prepared = source.select(
        F.col("business_date"),
        F.col("store_id"),
        F.col("transaction_id"),
        F.col("line_id"),
        F.col("product_id"),
        F.col("customer_id"),
        F.col("quantity"),
        F.col("gross_amount"),
        F.col("discount_amount"),
        F.col("net_amount"),
        F.col("currency_code"),
        F.col("sale_ts"),
        F.current_timestamp().alias("_ingest_ts"),
        F.col("_metadata.file_path").alias("_source_file"),
        F.col("_rescued_data"),
        F.sha2(
            F.concat_ws(
                "||",
                F.col("business_date").cast("string"),
                F.col("store_id"),
                F.col("transaction_id"),
                F.col("line_id"),
            ),
            256,
        ).alias("source_record_hash"),
    )
    if parameters.processing_date is not None:
        return prepared.where(F.col("business_date") == F.lit(parameters.processing_date))
    return prepared


def main() -> None:
    parameters = read_runtime_parameters()
    spark = SparkSession.builder.getOrCreate()
    source = read_pos_stream(spark, parameters)
    bronze_rows = prepare_bronze_rows(source, parameters)
    query = (
        bronze_rows.writeStream.option("checkpointLocation", parameters.checkpoint_path)
        .trigger(availableNow=True)
        .toTable(f"{parameters.catalog}.bronze.pos_sales_raw")
    )
    query.awaitTermination()


if __name__ == "__main__":
    main()
