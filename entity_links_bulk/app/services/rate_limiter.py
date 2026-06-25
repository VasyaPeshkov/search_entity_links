from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from ..exceptions import LLMQuotaExceeded
from ..models import LLMUsage
from ..storage.sqlite_store import SQLiteStore


class SlidingWindowRateLimiter:
    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()

                while (
                    self._timestamps
                    and now - self._timestamps[0] >= 60.0
                ):
                    self._timestamps.popleft()

                if (
                    len(self._timestamps)
                    < self.requests_per_minute
                ):
                    self._timestamps.append(now)
                    return

                sleep_for = (
                    60.0
                    - (now - self._timestamps[0])
                    + 0.05
                )

            time.sleep(max(sleep_for, 0.05))


class PersistentLLMBudget:
    """Считает запросы в SQLite и не сбрасывается при перезапуске."""

    def __init__(
        self,
        *,
        store: SQLiteStore,
        model: str,
        timezone_name: str,
        daily_limit: int,
        max_calls_per_run: int,
    ):
        self.store = store
        self.model = model
        self.timezone = ZoneInfo(timezone_name)
        self.daily_limit = daily_limit
        self.max_calls_per_run = max_calls_per_run
        self._run_calls = 0
        self._lock = threading.Lock()

    def current_usage_date(self) -> str:
        return datetime.now(self.timezone).date().isoformat()

    def reserve(self, entity_count: int) -> str:
        """Резервирует запрос непосредственно перед отправкой в API."""

        with self._lock:
            if (
                self.max_calls_per_run > 0
                and self._run_calls >= self.max_calls_per_run
            ):
                raise LLMQuotaExceeded(
                    "Исчерпан LLM_MAX_CALLS_PER_RUN."
                )

            usage_date = self.current_usage_date()
            usage = self.store.reserve_llm_request(
                usage_date=usage_date,
                model=self.model,
                entity_count=entity_count,
                request_limit=self.daily_limit,
            )

            if usage is None:
                raise LLMQuotaExceeded(
                    "Исчерпан суточный лимит LLM: "
                    f"{self.daily_limit} запросов за {usage_date} "
                    "(Pacific Time)."
                )

            self._run_calls += 1
            return usage_date

    def complete(
        self,
        *,
        usage_date: str,
        successful_entities: int,
        failed: bool,
    ) -> None:
        self.store.complete_llm_request(
            usage_date=usage_date,
            model=self.model,
            successful_entities=successful_entities,
            failed=failed,
        )

    def get_usage(self) -> LLMUsage:
        usage_date = self.current_usage_date()
        return self.store.get_llm_usage(
            usage_date,
            self.model,
        )
