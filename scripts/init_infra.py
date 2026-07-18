#!/usr/bin/env python3
"""Инициализация инфраструктуры: миграции БД, бакеты MinIO, топики Kafka."""

import subprocess
import sys

from confluent_kafka.admin import AdminClient, NewTopic

from explainlaw.config import settings
from explainlaw.pipeline.topics import ALL_TOPICS
from explainlaw.storage.object_store import get_storage


def run_migrations() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("Alembic migration failed")


def ensure_minio_buckets() -> None:
    storage = get_storage()
    storage.ensure_buckets()
    print(f"MinIO buckets ready: {settings.minio_bucket_raw}, {settings.minio_bucket_snapshots}")


def ensure_kafka_topics() -> None:
    admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap_servers})
    existing = admin.list_topics(timeout=10).topics
    new_topics = [
        NewTopic(topic, num_partitions=3, replication_factor=1)
        for topic in ALL_TOPICS
        if topic not in existing
    ]
    if new_topics:
        futures = admin.create_topics(new_topics)
        for topic, future in futures.items():
            try:
                future.result()
                print(f"Kafka topic created: {topic}")
            except Exception as exc:
                print(f"Kafka topic {topic}: {exc}")
    else:
        print("Kafka topics already exist")


def main() -> None:
    print("Running database migrations...")
    run_migrations()
    print("Ensuring MinIO buckets...")
    ensure_minio_buckets()
    print("Ensuring Kafka topics...")
    ensure_kafka_topics()
    print("Infrastructure init complete.")


if __name__ == "__main__":
    main()
