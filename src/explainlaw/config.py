from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://explainlaw:explainlaw@localhost:5432/explainlaw"
    database_sslmode: str = "prefer"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "explainlaw"
    minio_secret_key: str = "explainlawsecret"
    minio_bucket_raw: str = "npa-raw"
    minio_bucket_snapshots: str = "npa-snapshots"
    minio_secure: bool = False

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

    # LLM second-look / semantic gate (§9) — только после механики
    gate_llm_verify: bool = True


settings = Settings()
