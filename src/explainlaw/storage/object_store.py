import hashlib
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from explainlaw.config import settings


class ObjectStorage:
    """Объектное хранилище сырья (Категория 1) — MinIO/S3."""

    def __init__(self) -> None:
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    def put_raw(
        self,
        *,
        bucket: str,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> tuple[str, str, int]:
        """Сохранить файл, вернуть (storage_path, checksum_sha256, file_size)."""
        checksum = hashlib.sha256(data).hexdigest()
        self._client.put_object(
            bucket,
            object_name,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        storage_path = f"{bucket}/{object_name}"
        return storage_path, checksum, len(data)

    def get_raw(self, bucket: str, object_name: str) -> bytes:
        response = self._client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def get_by_path(self, storage_path: str) -> bytes:
        bucket, object_name = storage_path.split("/", 1)
        return self.get_raw(bucket, object_name)

    def ensure_buckets(self) -> None:
        for bucket in (settings.minio_bucket_raw, settings.minio_bucket_snapshots):
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)


def get_storage() -> ObjectStorage:
    return ObjectStorage()
