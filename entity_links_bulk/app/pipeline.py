from __future__ import annotations

from .config import AppConfig
from .models import (
    EntityInput,
    EntityLinksResult,
    GeminiBatchItem,
    GeminiBatchSearchResult,
    StoredResult,
)
from .services.crawler import enrich_from_official_websites
from .services.gemma_search import GeminiBatchSearch
from .services.minjust_registry import MinjustRegistryService
from .services.postprocess import finalize_result, merge_links
from .services.rate_limiter import (
    PersistentLLMBudget,
    SlidingWindowRateLimiter,
)
from .storage.sqlite_store import SQLiteStore
from .utils.names import make_cache_key


class EntityResolver:
    def __init__(
        self,
        config: AppConfig,
        store: SQLiteStore,
        minjust: MinjustRegistryService,
        gemini: GeminiBatchSearch | None,
        budget: PersistentLLMBudget | None,
    ):
        self.config = config
        self.store = store
        self.minjust = minjust
        self.gemini = gemini
        self.budget = budget

    @classmethod
    def create(
        cls,
        config: AppConfig,
        store: SQLiteStore,
    ) -> "EntityResolver":
        rate_limiter = SlidingWindowRateLimiter(
            config.llm_rpm
        )

        budget = (
            PersistentLLMBudget(
                store=store,
                model=config.gemini_model,
                timezone_name=config.llm_budget_timezone,
                daily_limit=config.llm_daily_request_budget,
                max_calls_per_run=config.llm_max_calls_per_run,
            )
            if config.llm_enabled
            else None
        )

        gemini = (
            GeminiBatchSearch(
                config=config,
                rate_limiter=rate_limiter,
                budget=budget,
            )
            if config.llm_enabled and budget is not None
            else None
        )

        minjust = MinjustRegistryService(
            config=config,
            store=store,
        )

        return cls(
            config=config,
            store=store,
            minjust=minjust,
            gemini=gemini,
            budget=budget,
        )

    def cached_or_none(
        self,
        entity: EntityInput,
    ) -> StoredResult | None:
        cache_key = make_cache_key(
            entity.name,
            entity.entity_type,
        )
        stored = self.store.get_result(cache_key)

        if stored is None:
            return None

        if (
            stored.status == "success"
            and self.config.skip_cached_success
        ):
            return stored

        if stored.status == "unresolved":
            if (
                stored.attempts
                >= self.config.max_llm_attempts_per_entity
            ):
                return stored
            if not self.config.reprocess_unresolved:
                return stored

        if stored.status == "failed":
            if (
                stored.attempts
                >= self.config.max_llm_attempts_per_entity
            ):
                return stored
            if not self.config.reprocess_failed:
                return stored

        return None

    def resolve_registry(
        self,
        entity: EntityInput,
    ) -> EntityLinksResult:
        minjust_lookup = self.minjust.lookup(entity)

        return EntityLinksResult(
            entity_id=entity.entity_id,
            input_name=entity.name,
            canonical_name=(
                minjust_lookup.records[0].display_name
                if minjust_lookup.records
                else None
            ),
            entity_type=entity.entity_type,
            ambiguous=minjust_lookup.ambiguous,
            ambiguity_notes=minjust_lookup.ambiguity_notes,
            links=minjust_lookup.links,
            minjust_record_ids=[
                record.record_id
                for record in minjust_lookup.records
            ],
            minjust_registry_numbers=[
                record.registry_number
                for record in minjust_lookup.records
                if record.registry_number is not None
            ],
            minjust_registry_names=[
                record.display_name
                for record in minjust_lookup.records
            ],
            minjust_match_score=minjust_lookup.match_score,
            minjust_has_active_record=(
                minjust_lookup.has_active_record
                if minjust_lookup.records
                else None
            ),
            resolution_sources=(
                ["minjust_registry"]
                if minjust_lookup.records
                else []
            ),
        )

    def should_call_llm(
        self,
        result: EntityLinksResult,
    ) -> bool:
        if not self.config.llm_enabled:
            return False

        if self.config.resolution_mode == "full":
            return True

        if self.config.resolution_mode == "economy":
            return len(result.links) == 0

        return (
            len(result.links)
            < self.config.min_minjust_links_to_skip_llm
        )

    def resolve_one(
        self,
        entity: EntityInput,
    ) -> EntityLinksResult:
        partial = self.resolve_registry(entity)

        if not self.should_call_llm(partial) or self.gemini is None:
            return self.finalize(partial)

        batch = self.search_batch([entity])
        item = next(
            (
                candidate
                for candidate in batch.items
                if candidate.entity_id == entity.entity_id
            ),
            None,
        )

        if item is None:
            return self.finalize(partial)

        return self.merge_gemini_item(
            entity=entity,
            partial=partial,
            item=item,
            batch=batch,
        )

    def search_batch(
        self,
        entities: list[EntityInput],
    ) -> GeminiBatchSearchResult:
        if self.gemini is None:
            return GeminiBatchSearchResult()
        return self.gemini.search_batch(entities)

    def merge_gemini_item(
        self,
        *,
        entity: EntityInput,
        partial: EntityLinksResult,
        item: GeminiBatchItem,
        batch: GeminiBatchSearchResult,
    ) -> EntityLinksResult:
        result = partial.model_copy(deep=True)

        if not result.canonical_name:
            result.canonical_name = item.canonical_name

        result.ambiguous = result.ambiguous or item.ambiguous
        result.ambiguity_notes = list(dict.fromkeys([
            *result.ambiguity_notes,
            *item.ambiguity_notes,
        ]))
        result.aliases_used = list(dict.fromkeys([
            *result.aliases_used,
            *item.aliases_used,
        ]))
        result.search_used = batch.search_used
        result.search_queries = batch.search_queries
        result.grounding_sources = batch.grounding_sources
        result.resolution_sources.append(
            "gemini_google_search_batch"
        )
        result.links = merge_links(
            result.links,
            item.links,
        )
        result.entity_id = entity.entity_id
        result.input_name = entity.name
        result.entity_type = entity.entity_type

        return self.finalize(result)

    def finalize(
        self,
        result: EntityLinksResult,
    ) -> EntityLinksResult:
        result = enrich_from_official_websites(
            result,
            self.config,
        )
        return finalize_result(result, self.config)
