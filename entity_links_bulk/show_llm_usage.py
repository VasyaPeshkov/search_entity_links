from __future__ import annotations

from app import AppConfig
from app.services.rate_limiter import PersistentLLMBudget
from app.storage import SQLiteStore


def main() -> None:
    config = AppConfig.from_env()
    store = SQLiteStore(config.effective_database_path)
    budget = PersistentLLMBudget(
        store=store,
        model=config.gemini_model,
        timezone_name=config.llm_budget_timezone,
        daily_limit=config.llm_daily_request_budget,
        max_calls_per_run=config.llm_max_calls_per_run,
    )
    usage = budget.get_usage()

    print(f"Дата квоты: {usage.usage_date}")
    print(f"Модель: {usage.model}")
    print(
        f"Запросы: {usage.requests}/"
        f"{config.llm_daily_request_budget}"
    )
    print(f"Сущностей отправлено: {usage.entities_sent}")
    print(f"Сущностей возвращено: {usage.successful_entities}")
    print(f"Неудачных запросов: {usage.failed_requests}")


if __name__ == "__main__":
    main()
