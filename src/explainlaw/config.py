from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://explainlaw:explainlaw@localhost:5432/explainlaw"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "explainlaw"
    minio_secret_key: str = "explainlawsecret"
    minio_bucket_raw: str = "npa-raw"
    minio_bucket_snapshots: str = "npa-snapshots"
    minio_secure: bool = False

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_enabled: bool = True

    pravo_api_base_url: str = "http://publication.pravo.gov.ru"
    pravo_block_president: str = "president"
    # GUID вида «Федеральный закон» из /api/DocumentTypes?block=president
    pravo_document_type_fz_id: str = "82a8bf1c-3bc7-47ed-827f-7affd43a7f27"
    # Полный каталог ФЗ в API president (~2011–н.в.); уточнить: explainlaw status --refresh
    pravo_catalog_fz_total: int = 7761

    # LLM (OpenAI-compatible API)
    qwen_api_base: str = ""
    qwen_api_key: str = ""
    qwen_model: str = "qwen3-8b"

    gateway_api_base: str = ""
    gateway_api_key: str = ""
    gateway_model: str = "gpt-4o-mini"

    # Минимум символов из PDF до попытки OCR
    ocr_text_threshold: int = 200
    # OCR на сканах очень медленный; для массовой обработки: OCR_ENABLED=false
    ocr_enabled: bool = True

    # Итерация 4 — еженедельный контент (§7.2)
    digest_min_items: int = 3
    digest_max_items: int = 7
    post_reserve_count: int = 2

    # Наблюдаемость (§11)
    collect_silent_alert_hours: int = 36
    alert_webhook_url: str = ""


settings = Settings()
