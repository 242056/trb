#!/usr/bin/env python3
"""Резервная копия бакетов MinIO (сырьё НПА) в локальный каталог."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from minio import Minio  # noqa: E402

from explainlaw.config import settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup MinIO buckets")
    parser.add_argument("--out", default="backups/minio", help="Каталог выгрузки")
    parser.add_argument(
        "--buckets",
        nargs="*",
        default=[settings.minio_bucket_raw, settings.minio_bucket_snapshots],
    )
    parser.add_argument("--limit", type=int, help="Лимит объектов на бакет (тест)")
    args = parser.parse_args()

    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = Path(args.out) / stamp
    root.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"created_at": stamp, "buckets": {}}

    for bucket in args.buckets:
        dest = root / bucket
        dest.mkdir(parents=True, exist_ok=True)
        count = 0
        for obj in client.list_objects(bucket, recursive=True):
            if args.limit and count >= args.limit:
                break
            target = dest / obj.object_name
            target.parent.mkdir(parents=True, exist_ok=True)
            client.fget_object(bucket, obj.object_name, str(target))
            count += 1
        manifest["buckets"][bucket] = {"objects": count}
        print(f"{bucket}: {count} objects → {dest}")

    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"OK: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
