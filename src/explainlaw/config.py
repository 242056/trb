from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://explainlaw:explainlaw@localhost:5432/explainlaw"
    database_sslmode: str = "prefer"

    # Object storage: локальный MinIO или Yandex Object Storage (S3-совместимый).
    # Можно задать AWS_ENDPOINT_URL / AWS_KEY_ID / AWS_SECRET_KEY / AWS_BUCKET
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "explainlaw"
    minio_secret_key: str = "explainlawsecret"
    minio_bucket_raw: str = "npa-raw"
    minio_bucket_snapshots: str = "npa-snapshots"
    minio_secure: bool = False
    minio_region: str = ""
    # Общий prefix внутри бакета (опционально)
    minio_prefix: str = ""

    # Yandex / AWS S3 aliases
    aws_endpoint_url: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_bucket: str = ""
    aws_key_id: str = ""  # AWS_KEY_ID
    aws_secret_key: str = ""  # AWS_SECRET_KEY

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_enabled: bool = True
    # События конвейера (npa.*). На Yandex с ACL только на llm.* — false
    kafka_pipeline_events: bool = True
    kafka_username: str = ""
    kafka_password: str = ""
    kafka_security_protocol: str = "SASL_SSL"
    kafka_sasl_mechanism: str = "SCRAM-SHA-512"
    kafka_ssl_ca_location: str = ""

    # LLM: http | kafka (Qwen worker через топики)
    llm_transport: str = "http"
    kafka_llm_requests_topic: str = "llm.requests"
    kafka_llm_responses_topic: str = "llm.responses"
    kafka_llm_group_id: str = "explainlaw-llm"
    llm_request_timeout: float = 300.0

    pravo_api_base_url: str = "http://publication.pravo.gov.ru"
    pravo_block_president: str = "president"
    pravo_document_type_fz_id: str = "82a8bf1c-3bc7-47ed-827f-7affd43a7f27"
    pravo_catalog_fz_total: int = 7761

    qwen_api_base: str = ""
    qwen_api_key: str = ""
    qwen_model: str = "qwen3-8b"

    gateway_api_base: str = ""
    gateway_api_key: str = ""
    gateway_model: str = "gpt-4o-mini"

    ocr_text_threshold: int = 200
    ocr_enabled: bool = True
    # tesseract | paddle | yandex  (публичного SberOCR API нет)
    ocr_engine: str = "paddle"
    yandex_vision_api_key: str = ""
    yandex_vision_iam_token: str = ""

    digest_min_items: int = 3
    digest_max_items: int = 7
    post_reserve_count: int = 2
    publish_export_dir: str = "logs/published"

    collect_silent_alert_hours: int = 36
    alert_webhook_url: str = ""
    alert_log_path: str = "logs/alerts.jsonl"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Слать дайджест в Telegram при publish --mark-published / weekly
    telegram_publish: bool = True

    # LLM second-look / semantic gate (§9) — только после механики
    gate_llm_verify: bool = True

    # --- Pipeline limits (daily / backfill; CLI перекрывает при явном флаге) ---
    pipeline_process_limit: int | None = None
    pipeline_fetch_missing_limit: int = 3
    pipeline_backfill_limit: int = 500
    pipeline_backfill_pdf_limit: int | None = None
    # Период сбора, если daily без --date (daily|weekly|monthly) — для collect CLI
    collect_period_type: str = "daily"

    # --- Cron (Docker supercronic; расписание и флаги из env) ---
    cron_timezone: str = "Europe/Moscow"
    cron_daily_enabled: bool = True
    cron_daily_schedule: str = "0 8 * * *"
    cron_weekly_enabled: bool = True
    cron_weekly_schedule: str = "0 9 * * 1"
    cron_backfill_enabled: bool = True
    cron_backfill_schedule: str = "0 3 * * 0"
    cron_health_enabled: bool = True
    cron_health_schedule: str = "30 */6 * * *"
    # При старте cron-контейнера сразу прогнать job (прод-тест)
    cron_run_on_start: bool = False
    # daily | weekly | health | smoke
    cron_run_on_start_job: str = "weekly"
    # Лимит документов для smoke / быстрого прод-теста
    pipeline_smoke_process_limit: int = 5

    @field_validator(
        "pipeline_process_limit",
        "pipeline_backfill_pdf_limit",
        mode="before",
    )
    @classmethod
    def _empty_optional_int(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @model_validator(mode="after")
    def apply_aws_object_storage_aliases(self) -> "Settings":
        """Если заданы AWS_* — используем Yandex Object Storage / S3."""
        endpoint = self.aws_endpoint_url.strip()
        key = (self.aws_access_key_id or self.aws_key_id).strip()
        secret = (self.aws_secret_access_key or self.aws_secret_key).strip()
        bucket = self.aws_bucket.strip()

        if not (endpoint or key or secret or bucket):
            return self

        if endpoint:
            self.minio_endpoint = endpoint
            self.minio_secure = endpoint.startswith("https://") or "yandexcloud" in endpoint
            if "yandexcloud" in endpoint and not self.minio_region:
                self.minio_region = "ru-central1"
        if key:
            self.minio_access_key = key
        if secret:
            self.minio_secret_key = secret
        if bucket:
            # Один бакет Yandex для raw + snapshots (имена файлов не пересекаются)
            self.minio_bucket_raw = bucket
            self.minio_bucket_snapshots = bucket
        return self


settings = Settings()
