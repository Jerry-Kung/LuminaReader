from functools import lru_cache
from urllib.parse import urlparse

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
    )

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    llm_timeout_seconds: float = 60
    llm_temperature: float = 0.2
    llm_return_raw: bool = False
    host: str = "127.0.0.1"
    port: int = 18086
    log_level: str = "INFO"
    cors_allow_origins: str = "http://localhost:3000"
    session_max_entries: int = 100
    session_ttl_seconds: float = 3600.0
    session_log_extracted_text: bool = False
    lumina_data_root: str = ""
    lumina_sqlite_busy_timeout_ms: int = 5000
    lumina_pdf_max_size_mb: int = 100
    thinking_enabled: bool = False
    # V1.2.1：跨页自动上下文（env 仅作 settings.json 缺省时的回退与调参）
    context_expansion_enabled: bool = True
    lumina_context_window_pages: int = Field(default=2, ge=0, le=10)
    lumina_context_max_chars: int = Field(default=16000, ge=1000, le=100_000)
    # V1.2.2：LLM 目录识别的输入样本字符上限（控成本，不喂全书全文）
    lumina_toc_sample_max_chars: int = Field(default=60000, ge=5000, le=300_000)
    # V1.2.3：记忆加工单元的字符预算（超预算章节按页贪心拆分）
    lumina_memory_unit_max_chars: int = Field(default=30000, ge=5000, le=200_000)
    # V1.2.6：记忆加工单元的最小字符数（低于此值的连续小节在同一顶层章节内合并；0 = 关闭合并）
    lumina_memory_unit_min_chars: int = Field(default=6000, ge=0, le=100_000)
    # V1.2.4：概念回查检索参数
    lumina_recall_max_concepts: int = Field(default=20, ge=1, le=100)
    lumina_recall_max_text_pages: int = Field(default=5, ge=1, le=20)
    lumina_recall_snippet_chars: int = Field(default=600, ge=100, le=4000)
    lumina_recall_max_ref_chars: int = Field(default=12000, ge=2000, le=100_000)
    selection_text_max_chars: int = Field(
        default=32000,
        ge=1000,
        le=200_000,
        validation_alias=AliasChoices(
            "LUMINA_SELECTION_TEXT_MAX_CHARS",
            "selection_text_max_chars",
        ),
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


def config_provider_ready(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    if not cfg.openai_api_key.strip():
        return False
    parsed = urlparse(cfg.openai_base_url.strip())
    return bool(parsed.scheme and parsed.netloc)


@lru_cache
def get_settings() -> Settings:
    return Settings()
