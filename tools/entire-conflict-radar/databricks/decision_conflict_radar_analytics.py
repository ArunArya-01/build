# Databricks notebook source
"""Aggregate Decision Conflict Radar JSONL evidence in Databricks.

Inputs are supplied by the local `entire-conflict-databricks run` adapter:
- input_path: DBFS/Volume path to exported radar evidence JSONL
- output_path: DBFS/Volume directory for aggregate JSON outputs
"""

from pyspark.sql import functions as F


dbutils.widgets.text("input_path", "")
dbutils.widgets.text("output_path", "")

input_path = dbutils.widgets.get("input_path").strip()
output_path = dbutils.widgets.get("output_path").strip()

if not input_path:
    raise ValueError("input_path is required")
if not output_path:
    raise ValueError("output_path is required")

raw = spark.read.json(input_path)

records = (
    raw.withColumn("score", F.coalesce(F.col("score").cast("int"), F.lit(0)))
    .withColumn("path", F.coalesce(F.col("path"), F.lit("")))
    .withColumn("symbol", F.coalesce(F.col("symbol"), F.lit("")))
    .withColumn("risk_level", F.coalesce(F.col("risk_level"), F.lit("LOW")))
)

by_path = (
    records.where(F.col("path") != "")
    .groupBy("path")
    .agg(
        F.count("*").alias("conflict_count"),
        F.avg("score").alias("average_score"),
        F.max("score").alias("max_score"),
        F.collect_set("risk_level").alias("risk_levels"),
    )
    .orderBy(F.desc("conflict_count"), F.desc("max_score"), F.asc("path"))
)

by_symbol = (
    records.where(F.col("symbol") != "")
    .groupBy("symbol")
    .agg(
        F.count("*").alias("conflict_count"),
        F.avg("score").alias("average_score"),
        F.max("score").alias("max_score"),
        F.collect_set("risk_level").alias("risk_levels"),
    )
    .orderBy(F.desc("conflict_count"), F.desc("max_score"), F.asc("symbol"))
)

risk_frequency = (
    records.groupBy("risk_level")
    .agg(
        F.count("*").alias("conflict_count"),
        F.avg("score").alias("average_score"),
        F.max("score").alias("max_score"),
    )
    .orderBy(F.desc("conflict_count"), F.desc("max_score"), F.asc("risk_level"))
)

term_source = records.select(F.explode_outer("conflict_terms").alias("term"), "score", "risk_level")
recurring_terms = (
    term_source.where(F.col("term").isNotNull() & (F.col("term") != ""))
    .groupBy("term")
    .agg(
        F.count("*").alias("term_count"),
        F.avg("score").alias("average_score"),
        F.max("score").alias("max_score"),
        F.collect_set("risk_level").alias("risk_levels"),
    )
    .orderBy(F.desc("term_count"), F.desc("max_score"), F.asc("term"))
)

by_path.coalesce(1).write.mode("overwrite").json(f"{output_path}/conflict_frequency_by_path")
by_symbol.coalesce(1).write.mode("overwrite").json(f"{output_path}/conflict_frequency_by_symbol")
risk_frequency.coalesce(1).write.mode("overwrite").json(f"{output_path}/risk_frequency")
recurring_terms.coalesce(1).write.mode("overwrite").json(f"{output_path}/recurring_conflict_terms")
