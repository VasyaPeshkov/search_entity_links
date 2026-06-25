from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import AppConfig
from .exceptions import LLMQuotaExceeded
from .models import EntityInput, EntityLinksResult
from .pipeline import EntityResolver
from .storage.sqlite_store import SQLiteStore
from .utils.io import (
    read_entities,
    write_results_jsonl,
    write_unresolved_csv,
)
from .utils.names import (
    belongs_to_shard,
    make_cache_key,
)


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PendingEntity:
    entity: EntityInput
    search_entity: EntityInput
    cache_key: str
    partial: EntityLinksResult


@dataclass(slots=True)
class RunStats:
    total_input: int = 0
    selected_for_shard: int = 0
    processed: int = 0
    cached: int = 0
    success: int = 0
    unresolved: int = 0
    failed: int = 0
    llm_pending: int = 0
    llm_batches: int = 0


class BulkRunner:
    def __init__(self, config: AppConfig):
        self.config = config
        self.store = SQLiteStore(
            config.effective_database_path
        )
        self.resolver = EntityResolver.create(
            config=config,
            store=self.store,
        )

    def run(self) -> RunStats:
        entities = read_entities(self.config.input_csv)

        selected = [
            entity
            for entity in entities
            if belongs_to_shard(
                make_cache_key(
                    entity.name,
                    entity.entity_type,
                ),
                self.config.shard_count,
                self.config.shard_index,
            )
        ]

        if self.config.max_entities_per_run > 0:
            selected = selected[
                :self.config.max_entities_per_run
            ]

        stats = RunStats(
            total_input=len(entities),
            selected_for_shard=len(selected),
        )

        if self.config.minjust_enabled:
            self.resolver.minjust.ensure_registry()

        pending = self._registry_pass(selected, stats)
        stats.llm_pending = len(pending)

        if pending:
            self._llm_pass(pending, stats)

        output_rows = [
            (
                entity,
                self.store.get_result(
                    make_cache_key(
                        entity.name,
                        entity.entity_type,
                    )
                ),
            )
            for entity in selected
        ]

        write_results_jsonl(
            self.config.effective_output_jsonl,
            output_rows,
        )
        write_unresolved_csv(
            self.config.effective_unresolved_csv,
            output_rows,
        )

        logger.info(
            "Готово: selected=%d, processed=%d, cached=%d, "
            "success=%d, unresolved=%d, failed=%d, "
            "llm_pending=%d, llm_batches=%d",
            stats.selected_for_shard,
            stats.processed,
            stats.cached,
            stats.success,
            stats.unresolved,
            stats.failed,
            stats.llm_pending,
            stats.llm_batches,
        )

        if self.resolver.budget is not None:
            usage = self.resolver.budget.get_usage()
            logger.info(
                "LLM usage %s: %d/%d requests, "
                "%d entities sent, %d successful entities, "
                "%d failed requests",
                usage.usage_date,
                usage.requests,
                self.config.llm_daily_request_budget,
                usage.entities_sent,
                usage.successful_entities,
                usage.failed_requests,
            )

        logger.info(
            "Результаты: %s",
            self.config.effective_output_jsonl,
        )
        logger.info(
            "Нерешённые: %s",
            self.config.effective_unresolved_csv,
        )

        return stats

    def _registry_pass(
        self,
        selected: list[EntityInput],
        stats: RunStats,
    ) -> list[PendingEntity]:
        pending_by_key: dict[str, PendingEntity] = {}

        for index, entity in enumerate(selected, start=1):
            cache_key = make_cache_key(
                entity.name,
                entity.entity_type,
            )

            cached = self.resolver.cached_or_none(entity)
            if cached is not None:
                self._count_stored_status(cached.status, stats)
                stats.cached += 1
                continue

            # Одинаковые нормализованные имя и тип ищем один раз.
            if cache_key in pending_by_key:
                stats.cached += 1
                continue

            stats.processed += 1

            try:
                partial = self.resolver.resolve_registry(entity)
            except Exception as exc:
                logger.exception(
                    "Ошибка локального сопоставления %s (%s)",
                    entity.name,
                    entity.entity_type,
                )
                self.store.save_failure(
                    cache_key=cache_key,
                    input_name=entity.name,
                    entity_type=entity.entity_type,
                    error=str(exc),
                )
                stats.failed += 1
                continue

            if self.resolver.should_call_llm(partial):
                pending_by_key[cache_key] = PendingEntity(
                    entity=entity,
                    search_entity=EntityInput(
                        entity_id=cache_key,
                        name=entity.name,
                        entity_type=entity.entity_type,
                    ),
                    cache_key=cache_key,
                    partial=partial,
                )
            else:
                self._save_final(
                    entity=entity,
                    cache_key=cache_key,
                    result=self.resolver.finalize(partial),
                    stats=stats,
                    increment_attempt=False,
                )

            if (
                self.config.progress_every > 0
                and index % self.config.progress_every == 0
            ):
                logger.info(
                    "Registry pass %d/%d: pending LLM=%d, "
                    "success=%d, cached=%d, failed=%d",
                    index,
                    len(selected),
                    len(pending_by_key),
                    stats.success,
                    stats.cached,
                    stats.failed,
                )

        return list(pending_by_key.values())

    def _llm_pass(
        self,
        pending: list[PendingEntity],
        stats: RunStats,
    ) -> None:
        batch_size = self.config.llm_batch_size

        for start in range(0, len(pending), batch_size):
            chunk = pending[start:start + batch_size]

            try:
                batch_result = self.resolver.search_batch([
                    item.search_entity
                    for item in chunk
                ])
                stats.llm_batches += 1

            except LLMQuotaExceeded as exc:
                logger.warning("LLM остановлен: %s", exc)
                self._save_budget_deferred(
                    pending[start:],
                    str(exc),
                    stats,
                )
                break

            except Exception as exc:
                logger.exception(
                    "Ошибка пакетного LLM-запроса для %d сущностей",
                    len(chunk),
                )
                self._save_failed_batch(chunk, str(exc), stats)
                continue

            items_by_id = {
                item.entity_id: item
                for item in batch_result.items
            }

            for pending_item in chunk:
                item = items_by_id.get(
                    pending_item.search_entity.entity_id
                )

                if item is None:
                    partial = self.resolver.finalize(
                        pending_item.partial
                    )

                    if partial.links:
                        self._save_final(
                            entity=pending_item.entity,
                            cache_key=pending_item.cache_key,
                            result=partial,
                            stats=stats,
                            increment_attempt=False,
                        )
                    else:
                        self.store.save_unresolved(
                            cache_key=pending_item.cache_key,
                            input_name=pending_item.entity.name,
                            entity_type=(
                                pending_item.entity.entity_type
                            ),
                            result=partial,
                            reason=(
                                "Gemini не вернула entity_id из "
                                "пакетного запроса."
                            ),
                            increment_attempt=True,
                        )
                        stats.unresolved += 1
                    continue

                result = self.resolver.merge_gemini_item(
                    entity=pending_item.entity,
                    partial=pending_item.partial,
                    item=item,
                    batch=batch_result,
                )

                self._save_final(
                    entity=pending_item.entity,
                    cache_key=pending_item.cache_key,
                    result=result,
                    stats=stats,
                    increment_attempt=not bool(result.links),
                )

            logger.info(
                "LLM batch %d-%d/%d: returned=%d",
                start + 1,
                min(start + len(chunk), len(pending)),
                len(pending),
                len(batch_result.items),
            )

    def _save_budget_deferred(
        self,
        items: list[PendingEntity],
        reason: str,
        stats: RunStats,
    ) -> None:
        for item in items:
            partial = self.resolver.finalize(item.partial)

            if partial.links:
                self._save_final(
                    entity=item.entity,
                    cache_key=item.cache_key,
                    result=partial,
                    stats=stats,
                    increment_attempt=False,
                )
            else:
                self.store.save_unresolved(
                    cache_key=item.cache_key,
                    input_name=item.entity.name,
                    entity_type=item.entity.entity_type,
                    result=partial,
                    reason=reason,
                    # Лимит не является попыткой поиска сущности.
                    increment_attempt=False,
                )
                stats.unresolved += 1

    def _save_failed_batch(
        self,
        items: list[PendingEntity],
        error: str,
        stats: RunStats,
    ) -> None:
        for item in items:
            partial = self.resolver.finalize(item.partial)

            if partial.links:
                self._save_final(
                    entity=item.entity,
                    cache_key=item.cache_key,
                    result=partial,
                    stats=stats,
                    increment_attempt=False,
                )
            else:
                self.store.save_unresolved(
                    cache_key=item.cache_key,
                    input_name=item.entity.name,
                    entity_type=item.entity.entity_type,
                    result=partial,
                    reason=f"Ошибка пакетного LLM-запроса: {error}",
                    increment_attempt=True,
                )
                stats.unresolved += 1

    def _save_final(
        self,
        *,
        entity: EntityInput,
        cache_key: str,
        result: EntityLinksResult,
        stats: RunStats,
        increment_attempt: bool,
    ) -> None:
        if result.links:
            self.store.save_success(
                cache_key=cache_key,
                input_name=entity.name,
                entity_type=entity.entity_type,
                result=result,
            )
            stats.success += 1
        else:
            self.store.save_unresolved(
                cache_key=cache_key,
                input_name=entity.name,
                entity_type=entity.entity_type,
                result=result,
                reason="Ссылки не найдены.",
                increment_attempt=increment_attempt,
            )
            stats.unresolved += 1

    @staticmethod
    def _count_stored_status(
        status: str,
        stats: RunStats,
    ) -> None:
        if status == "success":
            stats.success += 1
        elif status == "unresolved":
            stats.unresolved += 1
        else:
            stats.failed += 1
