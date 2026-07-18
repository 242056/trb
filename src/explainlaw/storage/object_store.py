import hashlib
import logging
from io import BytesIO
from urllib.parse import urlparse

from minio import Minio

from explainlaw.config import settings

logger = logging.getLogger(__name__)


def _parse_endpoint(endpoint: str) -> tuple[str, bool]:
    """Возвращает (host[:port], secure). Принимает host или https://host."""
    raw = (endpoint or "").strip()
    if not raw:
        return "localhost:9000", False
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.netloc or parsed.path
        secure = parsed.scheme == "https"
        return host, secure
    return raw, settings.minio_secure


class ObjectStorage:
    """Объектное хранилище сырья (Категория 1) — MinIO / Yandex Object Storage (S3)."""

    def __init__(self) -> None:
        host, secure = _parse_endpoint(settings.minio_endpoint)
        kwargs: dict = {
            "access_key": settings.minio_access_key,
            "secret_key": settings.minio_secret_key,
            "secure": secure,
        }
        if settings.minio_region:
            kwargs["region"] = settings.minio_region
        self._client = Minio(host, **kwargs)
        self._host = host
        self._secure = secure

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
        # Опциональный prefix внутри бакета (для одного бакета Yandex)
        key = self._object_key(object_name)
        self._client.put_object(
            bucket,
            key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        storage_path = f"{bucket}/{key}"
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
        seen: set[str] = set()
        for bucket in (settings.minio_bucket_raw, settings.minio_bucket_snapshots):
            if bucket in seen:
                continue
            seen.add(bucket)
            if not self._client.bucket_exists(bucket):
                try:
                    if settings.minio_region:
                        self._client.make_bucket(bucket, location=settings.minio_region)
                    else:
                        self._client.make_bucket(bucket)
                    logger.info("Создан бакет %s на %s", bucket, self._host)
                except Exception:
                    # На Yandex бакет часто уже создан в консоли — права create могут отсутствовать
                    logger.warning(
                        "Бакет %s недоступен для create; ожидаем, что он уже существует",
                        bucket,
                        exc_info=True,
                    )

    @staticmethod
    def _object_key(object_name: str) -> str:
        prefix = (settings.minio_prefix or "").strip().strip("/")
        if not prefix:
            return object_name
        return f"{prefix}/{object_name}"


def get_storage() -> ObjectStorage:
    return ObjectStorage()
