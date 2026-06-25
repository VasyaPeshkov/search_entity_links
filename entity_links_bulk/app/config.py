from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw is not None and raw.strip() else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw is not None and raw.strip() else default


def _env_path(name: str, default: str) -> Path:
    raw = os.getenv(name, default).strip()
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True, slots=True)
class AppConfig:
    input_csv: Path
    output_jsonl: Path
    unresolved_csv: Path
    database_path: Path

    resolution_mode: str
    max_entities_per_run: int
    skip_cached_success: bool
    reprocess_unresolved: bool
    reprocess_failed: bool
    max_llm_attempts_per_entity: int
    log_level: str
    progress_every: int

    shard_count: int
    shard_index: int

    minjust_enabled: bool
    minjust_required: bool
    minjust_api_url: str
    minjust_registry_page_url: str
    minjust_origin: str
    minjust_refresh_registry: bool
    minjust_registry_ttl_hours: int
    minjust_page_size: int
    minjust_request_delay_seconds: float
    minjust_timeout_seconds: float
    minjust_max_attempts: int
    minjust_retry_base_delay_seconds: float
    minjust_min_expected_records: int
    minjust_max_records: int
    minjust_include_excluded: bool
    minjust_match_threshold: float
    minjust_match_margin: float
    minjust_confidence: float
    min_minjust_links_to_skip_llm: int

    llm_enabled: bool
    gemini_api_key: str
    gemini_model: str
    llm_require_grounding: bool
    llm_batch_size: int
    llm_rpm: int
    llm_daily_request_budget: int
    llm_budget_timezone: str
    llm_max_calls_per_run: int
    llm_max_attempts: int
    llm_retry_base_delay_seconds: float
    llm_temperature: float
    llm_max_output_tokens: int

    crawler_enabled: bool
    crawler_timeout_seconds: float
    crawler_max_html_bytes: int
    crawler_max_sites: int
    crawler_min_site_confidence: float
    crawler_skip_if_links_at_least: int

    min_confidence: float
    human_review_threshold: float

    @classmethod
    def from_env(cls) -> "AppConfig":
        config = cls(
            input_csv=_env_path("INPUT_CSV", "data/entities.csv"),
            output_jsonl=_env_path("OUTPUT_JSONL", "data/results.jsonl"),
            unresolved_csv=_env_path(
                "UNRESOLVED_CSV", "data/unresolved.csv"
            ),
            database_path=_env_path(
                "DATABASE_PATH", "data/entity_links.sqlite3"
            ),

            resolution_mode=os.getenv(
                "RESOLUTION_MODE", "economy"
            ).strip().lower(),
            max_entities_per_run=_env_int(
                "MAX_ENTITIES_PER_RUN", 0
            ),
            skip_cached_success=_env_bool(
                "SKIP_CACHED_SUCCESS", True
            ),
            reprocess_unresolved=_env_bool(
                "REPROCESS_UNRESOLVED", True
            ),
            reprocess_failed=_env_bool(
                "REPROCESS_FAILED", True
            ),
            max_llm_attempts_per_entity=_env_int(
                "MAX_LLM_ATTEMPTS_PER_ENTITY", 2
            ),
            log_level=os.getenv(
                "LOG_LEVEL", "INFO"
            ).strip().upper(),
            progress_every=_env_int("PROGRESS_EVERY", 50),

            shard_count=_env_int("SHARD_COUNT", 1),
            shard_index=_env_int("SHARD_INDEX", 0),

            minjust_enabled=_env_bool("MINJUST_ENABLED", True),
            minjust_required=_env_bool("MINJUST_REQUIRED", True),
            minjust_api_url=os.getenv(
                "MINJUST_API_URL",
                "https://reestrs.minjust.gov.ru/rest/registry/"
                "39b95df9-9a68-6b6d-e1e3-e6388507067e/values",
            ).strip(),
            minjust_registry_page_url=os.getenv(
                "MINJUST_REGISTRY_PAGE_URL",
                "https://minjust.gov.ru/ru/pages/"
                "reestr-inostryannykh-agentov/",
            ).strip(),
            minjust_origin=os.getenv(
                "MINJUST_ORIGIN", "https://minjust.gov.ru"
            ).strip(),
            minjust_refresh_registry=_env_bool(
                "MINJUST_REFRESH_REGISTRY", True
            ),
            minjust_registry_ttl_hours=_env_int(
                "MINJUST_REGISTRY_TTL_HOURS", 24
            ),
            minjust_page_size=_env_int(
                "MINJUST_PAGE_SIZE", 200
            ),
            minjust_request_delay_seconds=_env_float(
                "MINJUST_REQUEST_DELAY_SECONDS", 0.2
            ),
            minjust_timeout_seconds=_env_float(
                "MINJUST_TIMEOUT_SECONDS", 30.0
            ),
            minjust_max_attempts=_env_int(
                "MINJUST_MAX_ATTEMPTS", 3
            ),
            minjust_retry_base_delay_seconds=_env_float(
                "MINJUST_RETRY_BASE_DELAY_SECONDS", 2.0
            ),
            minjust_min_expected_records=_env_int(
                "MINJUST_MIN_EXPECTED_RECORDS", 500
            ),
            minjust_max_records=_env_int(
                "MINJUST_MAX_RECORDS", 10_000
            ),
            minjust_include_excluded=_env_bool(
                "MINJUST_INCLUDE_EXCLUDED", True
            ),
            minjust_match_threshold=_env_float(
                "MINJUST_MATCH_THRESHOLD", 0.84
            ),
            minjust_match_margin=_env_float(
                "MINJUST_MATCH_MARGIN", 0.04
            ),
            minjust_confidence=_env_float(
                "MINJUST_CONFIDENCE", 0.98
            ),
            min_minjust_links_to_skip_llm=_env_int(
                "MIN_MINJUST_LINKS_TO_SKIP_LLM", 1
            ),

            llm_enabled=_env_bool("LLM_ENABLED", True),
            gemini_api_key=(
                os.getenv("GEMINI_API_KEY")
                or os.getenv("GOOGLE_API_KEY")
                or ""
            ).strip(),
            gemini_model=(
                os.getenv("GEMINI_MODEL")
                or os.getenv("GEMMA_MODEL")
                or "gemini-2.5-flash-lite"
            ).strip(),
            llm_require_grounding=_env_bool(
                "LLM_REQUIRE_GROUNDING", True
            ),
            llm_batch_size=_env_int("LLM_BATCH_SIZE", 5),
            llm_rpm=_env_int("LLM_RPM", 5),
            llm_daily_request_budget=_env_int(
                "LLM_DAILY_REQUEST_BUDGET", 480
            ),
            llm_budget_timezone=os.getenv(
                "LLM_BUDGET_TIMEZONE", "America/Los_Angeles"
            ).strip(),
            llm_max_calls_per_run=_env_int(
                "LLM_MAX_CALLS_PER_RUN", 480
            ),
            llm_max_attempts=_env_int(
                "LLM_MAX_ATTEMPTS", 2
            ),
            llm_retry_base_delay_seconds=_env_float(
                "LLM_RETRY_BASE_DELAY_SECONDS", 2.0
            ),
            llm_temperature=_env_float(
                "LLM_TEMPERATURE", 0.0
            ),
            llm_max_output_tokens=_env_int(
                "LLM_MAX_OUTPUT_TOKENS", 8192
            ),

            crawler_enabled=_env_bool(
                "CRAWLER_ENABLED", False
            ),
            crawler_timeout_seconds=_env_float(
                "CRAWLER_TIMEOUT_SECONDS", 12.0
            ),
            crawler_max_html_bytes=_env_int(
                "CRAWLER_MAX_HTML_BYTES", 2_000_000
            ),
            crawler_max_sites=_env_int(
                "CRAWLER_MAX_SITES", 3
            ),
            crawler_min_site_confidence=_env_float(
                "CRAWLER_MIN_SITE_CONFIDENCE", 0.80
            ),
            crawler_skip_if_links_at_least=_env_int(
                "CRAWLER_SKIP_IF_LINKS_AT_LEAST", 4
            ),

            min_confidence=_env_float(
                "MIN_CONFIDENCE", 0.45
            ),
            human_review_threshold=_env_float(
                "HUMAN_REVIEW_THRESHOLD", 0.70
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.resolution_mode not in {
            "economy", "balanced", "full"
        }:
            raise ValueError(
                "RESOLUTION_MODE должен быть economy, "
                "balanced или full."
            )

        if self.shard_count < 1:
            raise ValueError(
                "SHARD_COUNT должен быть не меньше 1."
            )

        if not 0 <= self.shard_index < self.shard_count:
            raise ValueError(
                "SHARD_INDEX должен быть в диапазоне "
                "0 <= SHARD_INDEX < SHARD_COUNT."
            )

        if self.llm_enabled and not self.gemini_api_key:
            raise ValueError(
                "LLM_ENABLED=true, но GEMINI_API_KEY пуст. "
                "Заполни ключ или установи LLM_ENABLED=false."
            )

        if not 1 <= self.llm_batch_size <= 10:
            raise ValueError(
                "LLM_BATCH_SIZE должен быть от 1 до 10."
            )

        if self.llm_rpm < 1:
            raise ValueError(
                "LLM_RPM должен быть не меньше 1."
            )

        if self.llm_daily_request_budget < 1:
            raise ValueError(
                "LLM_DAILY_REQUEST_BUDGET должен быть положительным."
            )

        if self.max_llm_attempts_per_entity < 1:
            raise ValueError(
                "MAX_LLM_ATTEMPTS_PER_ENTITY должен быть положительным."
            )

        try:
            ZoneInfo(self.llm_budget_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                "Неизвестная временная зона LLM_BUDGET_TIMEZONE: "
                f"{self.llm_budget_timezone}"
            ) from exc

        if not 1 <= self.minjust_page_size <= 1000:
            raise ValueError(
                "MINJUST_PAGE_SIZE должен быть от 1 до 1000."
            )

        if self.minjust_min_expected_records < 1:
            raise ValueError(
                "MINJUST_MIN_EXPECTED_RECORDS должен быть положительным."
            )

        if (
            self.minjust_max_records
            < self.minjust_min_expected_records
        ):
            raise ValueError(
                "MINJUST_MAX_RECORDS не может быть меньше "
                "MINJUST_MIN_EXPECTED_RECORDS."
            )

    @property
    def effective_database_path(self) -> Path:
        return self._with_shard_suffix(self.database_path)

    @property
    def effective_output_jsonl(self) -> Path:
        return self._with_shard_suffix(self.output_jsonl)

    @property
    def effective_unresolved_csv(self) -> Path:
        return self._with_shard_suffix(self.unresolved_csv)

    def _with_shard_suffix(self, path: Path) -> Path:
        if self.shard_count == 1:
            return path

        return path.with_name(
            f"{path.stem}.shard-{self.shard_index}-of-"
            f"{self.shard_count}{path.suffix}"
        )
