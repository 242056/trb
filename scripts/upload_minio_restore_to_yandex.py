#!/usr/bin/env python3
"""Восстановить PDF из локального MinIO XL volume и залить в Yandex Object Storage."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

from minio import Minio
from minio.error import S3Error

ROOT = Path(__file__).resolve().parents[1]


def extract_pdf_bytes(obj_dir: Path) -> bytes | None:
    part = next(obj_dir.rglob("part.1"), None)
    if part is not None:
        raw = part.read_bytes()
        idx = raw.find(b"%PDF")
        if idx < 0:
            return None
        return raw[idx:]

    meta = obj_dir / "xl.meta"
    if not meta.exists():
        return None
    raw = meta.read_bytes()
    idx = raw.find(b"%PDF")
    if idx < 0:
        return None
    pdf = raw[idx:]
    end = pdf.rfind(b"%%EOF")
    if end >= 0:
        pdf = pdf[: end + 5]
    return pdf


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--src",
        default=str(ROOT / "minio_restore" / "npa-raw"),
        help="Каталог npa-raw из распакованного minio_data",
    )
    parser.add_argument("--endpoint", default=os.environ.get("AWS_ENDPOINT_URL", "https://storage.yandexcloud.net"))
    parser.add_argument("--access-key", default=os.environ.get("AWS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID", ""))
    parser.add_argument(
        "--secret-key",
        default=os.environ.get("AWS_SECRET_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
    )
    parser.add_argument("--bucket", default=os.environ.get("AWS_BUCKET", "explain-npa"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--state", default=str(ROOT / "logs" / "upload_yandex_state.jsonl"))
    args = parser.parse_args()

    if not args.access_key or not args.secret_key:
        print("ERROR: задайте AWS_KEY_ID / AWS_SECRET_KEY", file=sys.stderr)
        return 2

    src = Path(args.src)
    if not src.is_dir():
        print(f"ERROR: нет каталога {src}", file=sys.stderr)
        return 2

    host = args.endpoint.replace("https://", "").replace("http://", "").rstrip("/")
    client = Minio(host, access_key=args.access_key, secret_key=args.secret_key, secure=True, region="ru-central1")
    if not client.bucket_exists(args.bucket):
        print(f"ERROR: бакет {args.bucket} не найден", file=sys.stderr)
        return 2

    dirs = sorted([d for d in src.iterdir() if d.is_dir() and d.name.endswith(".pdf")])
    if args.limit:
        dirs = dirs[: args.limit]

    state_path = Path(args.state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    if state_path.exists():
        for line in state_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ok"):
                done.add(rec["name"])

    pending = [d for d in dirs if d.name not in done]
    print(f"total={len(dirs)} already={len(done)} pending={len(pending)} workers={args.workers}")

    stats = {"ok": 0, "skip": 0, "fail": 0}
    t0 = time.time()

    def upload_one(obj_dir: Path) -> dict:
        name = obj_dir.name
        try:
            # skip if already on remote with same size
            pdf = extract_pdf_bytes(obj_dir)
            if not pdf or not pdf.startswith(b"%PDF"):
                return {"name": name, "ok": False, "error": "extract_failed"}
            try:
                st = client.stat_object(args.bucket, name)
                if st.size == len(pdf):
                    return {"name": name, "ok": True, "skipped": True, "size": len(pdf)}
            except S3Error:
                pass
            client.put_object(
                args.bucket,
                name,
                BytesIO(pdf),
                length=len(pdf),
                content_type="application/pdf",
            )
            return {"name": name, "ok": True, "skipped": False, "size": len(pdf)}
        except Exception as exc:  # noqa: BLE001
            return {"name": name, "ok": False, "error": str(exc)}

    with state_path.open("a", encoding="utf-8") as state_fh, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(upload_one, d): d.name for d in pending}
        for i, fut in enumerate(as_completed(futures), start=1):
            rec = fut.result()
            state_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            state_fh.flush()
            if rec.get("ok"):
                if rec.get("skipped"):
                    stats["skip"] += 1
                else:
                    stats["ok"] += 1
            else:
                stats["fail"] += 1
                print(f"FAIL {rec.get('name')}: {rec.get('error')}", flush=True)
            if i % 50 == 0 or i == len(futures):
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed else 0
                print(
                    f"progress {i}/{len(futures)} ok={stats['ok']} skip={stats['skip']} "
                    f"fail={stats['fail']} {rate:.1f}/s",
                    flush=True,
                )

    print(json.dumps({"stats": stats, "seconds": round(time.time() - t0, 1)}, ensure_ascii=False))
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
