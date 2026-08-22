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

    chat_api_key: str | None = None
    chat_base_url: str | None = None
    chat_model: str | None = None
    chat_temperature: float = 0.2
    chat_max_tokens: int = 4096
    chat_timeout_seconds: int = 60
    chat_max_retries: int = 2
    chat_extra_body: dict[str, Any] | None = None
    chat_rate_limiter_requests_per_second: float | None = None
    chat_rate_limiter_check_every_n_seconds: float = 0.1
    chat_rate_limiter_max_bucket_size: int = 10

    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int = 1536
    embedding_max_context_tokens: int = Field(default=8192, validation_alias=AliasChoices("PAPER_CLAW_EMBEDDING_MAX_CONTEXT_TOKENS", "MAX_CONTEXT_TOKENS", "embedding_max_context_tokens"))
    tokenizer_encoding: str = Field(default="cl100k_base", validation_alias=AliasChoices("PAPER_CLAW_TOKENIZER_ENCODING", "TOKENIZER_ENCODING", "tokenizer_encoding"))
    embedding_timeout_seconds: int = 60
    embedding_max_retries: int = 2

    openalex_email: str | None = None
    openalex_api_key: str | None = None
    openalex_timeout_seconds: int = 30

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
        self.data_dir = self.data_dir.expanduser().resolve()
        if self.storage_root is None:
            self.storage_root = self.data_dir / "files"
        else:
            self.storage_root = self.storage_root.expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
