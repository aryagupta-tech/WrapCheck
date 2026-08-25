from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_mode: str = "demo"
    cors_origins: str = "http://localhost:3000"
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 8123
    clickhouse_secure: bool = False
    clickhouse_database: str = "wrapcheck"
    clickhouse_user: str = "default"
    clickhouse_password: str = "wrapcheck-local"
    clickhouse_connect_timeout: int = 3
    clickhouse_receive_timeout: int = 10
    clickhouse_mcp_url: str = "http://clickhouse-mcp:8000/mcp"
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    google_genai_use_vertexai: bool = True
    gemini_model: str = "gemini-3.5-flash"
    curated_reference_gcs_uri: str | None = None
    curated_clean_gcs_uri: str | None = None
    curated_flawed_gcs_uri: str | None = None
    curated_media_bucket: str | None = None
    cloud_tasks_queue: str | None = None
    cloud_tasks_service_account: str | None = None
    cloud_run_backend_url: str | None = None
    demo_quota_secret: str = "change-me-in-live-mode"
    demo_runs_per_10_minutes: int = 3
    upload_deliveries_per_10_minutes: int = 3
    global_runs_per_10_minutes: int = 100
    max_upload_mb: int = 500
    blocking_confidence_threshold: float = 0.8

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def live_ready(self) -> bool:
        return bool(self.google_cloud_project and self.google_genai_use_vertexai)

    @property
    def release_gate_ready(self) -> bool:
        return bool(
            self.live_ready
            and self.curated_reference_gcs_uri
            and self.curated_clean_gcs_uri
            and self.curated_flawed_gcs_uri
            and self.curated_media_bucket
            and self.demo_quota_secret != "change-me-in-live-mode"
        )

    @property
    def media_handoff_ready(self) -> bool:
        return bool(
            self.live_ready
            and self.clickhouse_mcp_url
            and self.demo_quota_secret != "change-me-in-live-mode"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
