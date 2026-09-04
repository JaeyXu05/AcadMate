from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_DATABASE_URL = "postgresql+psycopg://paper_claw:paper_claw@localhost:5432/paper_claw"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAPER_CLAW_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = DEFAULT_DATABASE_URL
    data_dir: Path = Field(default_factory=lambda: DATA_DIR)
    storage_root: Path | None = None
    arxiv_min_interval_seconds: float = 3.0
    arxiv_max_retries: int = 3
    arxiv_backoff_base_seconds: float = 1.0
    arxiv_backoff_max_seconds: float = 30.0
    arxiv_timeout_seconds: int = 30

    report_language: str = "中文"

    mentor_workflow_agent_timeout_seconds: float = 300.0
    mentor_workflow_tool_timeout_seconds: float = 240.0
    mentor_workflow_max_total_retries: int = 5
    mentor_workflow_deployment_scope: str = "ustc"
    mentor_workflow_model_reasoning_enabled: bool = False
    mentor_workflow_model_max_candidates: int = 5
    mentor_workflow_model_max_tokens: int = 12000
    ustc_faculty_search_endpoint: str = (
        "https://faculty.ustc.edu.cn/system/resource/tsites/advancesearch.jsp"
    )
    ustc_faculty_college_id: str = ""
    ustc_faculty_http_timeout_seconds: float = 15.0
    ustc_faculty_search_page_size: int = 20
    ustc_faculty_search_max_pages: int = 3
    ustc_faculty_search_max_queries: int = 5
    ustc_faculty_max_candidates: int = 30
    mentor_paper_fallback_max_candidates: int = 10
    mentor_paper_fallback_max_results_per_source: int = 20
    mentor_paper_fallback_max_papers_per_candidate: int = 10

    # One chat-agent configuration is shared by every model-backed feature.
    # Keep PAPER_CLAW_* compatibility while also accepting the explicit
    # CHATAGENT_* names used by the combined application environment.
    chat_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CHATAGENT_API_KEY",
            "CHAT_AGENT_API_KEY",
            "PAPER_CLAW_CHAT_API_KEY",
        ),
    )
    chat_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CHATAGENT_BASE_URL",
            "CHATAGENT_API_BASE",
            "CHATAGENT_API_BASE_URL",
            "CHAT_AGENT_BASE_URL",
            "PAPER_CLAW_CHAT_BASE_URL",
        ),
    )
    chat_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CHATAGENT_MODEL",
            "CHATAGENT_MODEL_NAME",
            "CHAT_AGENT_MODEL",
            "PAPER_CLAW_CHAT_MODEL",
        ),
    )
    chat_temperature: float = Field(0.2, validation_alias=AliasChoices("CHATAGENT_TEMPERATURE", "CHATAGENT_CHAT_TEMPERATURE", "PAPER_CLAW_CHAT_TEMPERATURE"))
    chat_max_tokens: int = Field(4096, validation_alias=AliasChoices("CHATAGENT_MAX_TOKENS", "CHATAGENT_CHAT_MAX_TOKENS", "PAPER_CLAW_CHAT_MAX_TOKENS"))
    chat_timeout_seconds: int = Field(120, validation_alias=AliasChoices("CHATAGENT_TIMEOUT_SECONDS", "CHATAGENT_CHAT_TIMEOUT_SECONDS", "PAPER_CLAW_CHAT_TIMEOUT_SECONDS"))
    chat_max_retries: int = Field(2, validation_alias=AliasChoices("CHATAGENT_MAX_RETRIES", "CHATAGENT_CHAT_MAX_RETRIES", "PAPER_CLAW_CHAT_MAX_RETRIES"))
    chat_extra_body: dict[str, Any] | None = Field(default=None, validation_alias=AliasChoices("CHATAGENT_EXTRA_BODY", "PAPER_CLAW_CHAT_EXTRA_BODY"))
    chat_rate_limiter_requests_per_second: float | None = Field(default=None, validation_alias=AliasChoices("CHATAGENT_RATE_LIMITER_REQUESTS_PER_SECOND", "PAPER_CLAW_CHAT_RATE_LIMITER_REQUESTS_PER_SECOND"))
    chat_rate_limiter_check_every_n_seconds: float = Field(0.1, validation_alias=AliasChoices("CHATAGENT_RATE_LIMITER_CHECK_EVERY_N_SECONDS", "PAPER_CLAW_CHAT_RATE_LIMITER_CHECK_EVERY_N_SECONDS"))
    chat_rate_limiter_max_bucket_size: int = Field(10, validation_alias=AliasChoices("CHATAGENT_RATE_LIMITER_MAX_BUCKET_SIZE", "PAPER_CLAW_CHAT_RATE_LIMITER_MAX_BUCKET_SIZE"))
    # Planning is intentionally allowed a deeper, longer reasoning window;
    # reports use a smaller budget because they summarize already-selected facts.
    plan_chat_max_tokens: int = Field(2200, validation_alias=AliasChoices("PAPER_CLAW_PLAN_CHAT_MAX_TOKENS", "PLAN_AGENT_MAX_TOKENS"))
    plan_chat_timeout_seconds: int = Field(180, validation_alias=AliasChoices("PAPER_CLAW_PLAN_CHAT_TIMEOUT_SECONDS", "PLAN_AGENT_TIMEOUT_SECONDS"))
    report_chat_max_tokens: int = Field(900, validation_alias=AliasChoices("PAPER_CLAW_REPORT_CHAT_MAX_TOKENS", "REPORT_AGENT_MAX_TOKENS"))
    report_chat_timeout_seconds: int = Field(55, validation_alias=AliasChoices("PAPER_CLAW_REPORT_CHAT_TIMEOUT_SECONDS", "REPORT_AGENT_TIMEOUT_SECONDS"))

    # Do not share CHATAGENT_* aliases with the chat fields above: pydantic
    # resolves a shared alias on every matching field, so a PAPER_CLAW_CHAT_*
    # value silently overwrites the embedding config too.  The shared-endpoint
    # fallback is implemented explicitly in backend.services.providers.
    embedding_api_key: str | None = Field(default=None, validation_alias=AliasChoices("PAPER_CLAW_EMBEDDING_API_KEY"))
    embedding_base_url: str | None = Field(default=None, validation_alias=AliasChoices("PAPER_CLAW_EMBEDDING_BASE_URL"))
    embedding_provider: str = "openai_compatible"
    embedding_model: str | None = None
    embedding_dimension: int = 1536
    embedding_cache_dir: Path | None = None
    embedding_hf_endpoint: str | None = None
    embedding_hf_disable_xet: bool = False
    embedding_max_context_tokens: int = Field(default=8192, validation_alias=AliasChoices("PAPER_CLAW_EMBEDDING_MAX_CONTEXT_TOKENS", "MAX_CONTEXT_TOKENS", "embedding_max_context_tokens"))
    tokenizer_encoding: str = Field(default="cl100k_base", validation_alias=AliasChoices("PAPER_CLAW_TOKENIZER_ENCODING", "TOKENIZER_ENCODING", "tokenizer_encoding"))
    embedding_timeout_seconds: int = 60
    embedding_max_retries: int = 2

    openalex_email: str | None = Field(default=None, validation_alias=AliasChoices("PAPER_CLAW_OPENALEX_EMAIL", "OPENALEX_EMAIL"))
    openalex_api_key: str | None = Field(default=None, validation_alias=AliasChoices("PAPER_CLAW_OPENALEX_API_KEY", "OPENALEX_API_KEY"))
    openalex_timeout_seconds: int = Field(30, validation_alias=AliasChoices("PAPER_CLAW_OPENALEX_TIMEOUT_SECONDS", "OPENALEX_TIMEOUT_SECONDS"))

    local_ocr_api_key: str = "EMPTY"
    local_ocr_base_url: str | None = None
    local_ocr_model: str = "Logics-Parsing"
    local_ocr_prompt: str = "QwenVL HTML"
    local_ocr_max_tokens: int = 16384
    local_ocr_temperature: float = 0.1
    local_ocr_top_p: float = 0.5
    local_ocr_repetition_penalty: float = 1.05
    local_ocr_dpi: int = 200
    local_ocr_timeout_seconds: int = 300

    llama_parse_api_key: str | None = None
    llama_parse_tier: str = "cost_effective"
    llama_parse_version: str = "latest"
    llama_parse_timeout_seconds: int = 300
    llama_parse_extra_time_per_page_seconds: int = 45
    llama_parse_image_min_pixels: int = 200000

    def model_post_init(self, __context: object) -> None:
        # PAPER_CLAW_DATA_DIR may be relative ("./data"). Resolve it against the
        # repository root, not the process working directory, so data and model
        # caches live in one deterministic location regardless of launch folder.
        data_dir = self.data_dir.expanduser()
        self.data_dir = (data_dir if data_dir.is_absolute() else REPO_ROOT / data_dir).resolve()
        if self.storage_root is None:
            self.storage_root = self.data_dir / "files"
        else:
            storage_root = self.storage_root.expanduser()
            self.storage_root = (
                storage_root
                if storage_root.is_absolute()
                else (REPO_ROOT / storage_root).resolve()
            ).resolve()
        if self.embedding_cache_dir is not None:
            embedding_cache_dir = self.embedding_cache_dir.expanduser()
            self.embedding_cache_dir = (
                embedding_cache_dir
                if embedding_cache_dir.is_absolute()
                else (REPO_ROOT / embedding_cache_dir).resolve()
            ).resolve()
        else:
            self.embedding_cache_dir = self.data_dir / ".embedding_cache"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
