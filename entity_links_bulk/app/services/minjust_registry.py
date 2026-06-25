from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from ..config import AppConfig
from ..constants import DEFAULT_USER_AGENT, MINJUST_PERSON_CATEGORY
from ..exceptions import EntityLinksError
from ..models import (
    EntityInput,
    EntityLink,
    MinjustRegistryRecord,
)
from ..storage.sqlite_store import SQLiteStore
from ..utils.names import (
    extract_search_names,
    match_name_score,
    normalize_entity_name,
    token_key,
)
from ..utils.retry import call_with_retry
from ..utils.urls import (
    detect_platform,
    is_http_url,
    normalize_url,
    repair_registry_url,
)


logger = logging.getLogger(__name__)


class MinjustRegistryError(EntityLinksError):
    """Ошибка официального REST-реестра Минюста."""


@dataclass(slots=True)
class MinjustLookupResult:
    records: list[MinjustRegistryRecord] = field(default_factory=list)
    links: list[EntityLink] = field(default_factory=list)
    match_score: float | None = None
    ambiguous: bool = False
    ambiguity_notes: list[str] = field(default_factory=list)

    @property
    def has_active_record(self) -> bool:
        return any(record.is_active for record in self.records)


class MinjustRegistryService:
    def __init__(
        self,
        config: AppConfig,
        store: SQLiteStore,
    ):
        self.config = config
        self.store = store
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "*/*",
            "Accept-Language": (
                "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
            ),
            "Content-Type": "application/json;charset=utf-8",
            "Origin": config.minjust_origin,
            "Referer": config.minjust_registry_page_url,
            "User-Agent": DEFAULT_USER_AGENT,
        })

        self._records: list[MinjustRegistryRecord] | None = None
        self._normalized_index: dict[str, set[int]] = {}
        self._token_key_index: dict[str, set[int]] = {}
        self._token_index: dict[str, set[int]] = {}

    def ensure_registry(self) -> None:
        if not self.config.minjust_enabled:
            self._records = []
            self._rebuild_indexes()
            return

        existing_count = self.store.minjust_registry_count()
        is_fresh = self.store.minjust_registry_is_fresh(
            self.config.minjust_registry_ttl_hours
        )

        if is_fresh:
            self._load_from_store()
            return

        if (
            existing_count > 0
            and not self.config.minjust_refresh_registry
        ):
            self._load_from_store()
            return

        try:
            records, reported_size = self._download_registry()
            self.store.replace_minjust_registry(
                records=records,
                reported_size=reported_size,
            )
            logger.info(
                "Реестр Минюста обновлён: сохранено %d, "
                "API сообщил %d записей.",
                len(records),
                reported_size,
            )
        except Exception:
            if existing_count > 0:
                logger.exception(
                    "Не удалось обновить реестр Минюста; "
                    "используется локальная копия из SQLite."
                )
            elif self.config.minjust_required:
                raise
            else:
                logger.exception(
                    "Реестр Минюста недоступен, локальной "
                    "копии нет; обработка продолжится без него."
                )

        self._load_from_store()

    def force_rebuild_registry(self) -> None:
        self.store.invalidate_minjust_registry_timestamp()
        self._records = None
        self.ensure_registry()

    def lookup(
        self,
        entity: EntityInput,
    ) -> MinjustLookupResult:
        if not self.config.minjust_enabled:
            return MinjustLookupResult()

        if self._records is None:
            self.ensure_registry()

        records = self._records or []
        if not records:
            return MinjustLookupResult()

        query_names = extract_search_names(
            entity.name,
            entity.entity_type,
        )
        if not query_names:
            return MinjustLookupResult()

        exact_indices: set[int] = set()

        for query_name in query_names:
            exact_indices.update(
                self._normalized_index.get(query_name, set())
            )
            exact_indices.update(
                self._token_key_index.get(
                    token_key(query_name),
                    set(),
                )
            )

        exact_candidates = self._compatible_records(
            exact_indices,
            entity,
        )

        if exact_candidates:
            return self._build_lookup_result(
                entity=entity,
                candidates=exact_candidates,
                force_exact=True,
            )

        candidate_indices: set[int] = set()
        for query_name in query_names:
            for token in query_name.split():
                candidate_indices.update(
                    self._token_index.get(token, set())
                )

        candidates = self._compatible_records(
            candidate_indices,
            entity,
        )

        if not candidates:
            return MinjustLookupResult()

        return self._build_lookup_result(
            entity=entity,
            candidates=candidates,
            force_exact=False,
        )

    def _compatible_records(
        self,
        indices: set[int],
        entity: EntityInput,
    ) -> list[MinjustRegistryRecord]:
        records = self._records or []
        result: list[MinjustRegistryRecord] = []

        for index in indices:
            record = records[index]

            if (
                entity.entity_type != "unknown"
                and record.entity_type != entity.entity_type
            ):
                continue

            result.append(record)

        return result

    def _build_lookup_result(
        self,
        *,
        entity: EntityInput,
        candidates: list[MinjustRegistryRecord],
        force_exact: bool,
    ) -> MinjustLookupResult:
        if force_exact:
            query_normalized = normalize_entity_name(entity.name)
            primary_exact = [
                record
                for record in candidates
                if record.normalized_name == query_normalized
            ]

            if primary_exact:
                candidates = primary_exact
            else:
                distinct_names = list(dict.fromkeys(
                    record.normalized_name
                    for record in candidates
                ))
                if len(distinct_names) > 1:
                    return MinjustLookupResult(
                        match_score=0.99,
                        ambiguous=True,
                        ambiguity_notes=[
                            "Минюст: один короткий вариант имени "
                            "соответствует нескольким записям."
                        ],
                    )

        ranked = sorted(
            (
                (
                    self._record_match_score(entity, record),
                    record,
                )
                for record in candidates
            ),
            key=lambda item: (
                item[0],
                item[1].is_active,
                item[1].registry_number or 0,
            ),
            reverse=True,
        )

        if not ranked:
            return MinjustLookupResult()

        best_score, best_record = ranked[0]

        if force_exact:
            best_score = max(best_score, 0.99)

        if best_score < self.config.minjust_match_threshold:
            return MinjustLookupResult()

        second_distinct_score = 0.0
        second_distinct_name: str | None = None

        for score, record in ranked[1:]:
            if record.normalized_name == best_record.normalized_name:
                continue
            second_distinct_score = score
            second_distinct_name = record.display_name
            break

        if (
            best_score < 0.99
            and best_score - second_distinct_score
            < self.config.minjust_match_margin
        ):
            return MinjustLookupResult(
                match_score=best_score,
                ambiguous=True,
                ambiguity_notes=[
                    "Минюст: близкие совпадения: "
                    f"{best_record.display_name!r} и "
                    f"{second_distinct_name!r}."
                ],
            )

        same_identity = [
            record
            for _, record in ranked
            if record.normalized_name == best_record.normalized_name
        ]

        active = [
            record
            for record in same_identity
            if record.is_active
        ]

        if active:
            selected = active
        else:
            newest_number = max(
                (record.registry_number or 0)
                for record in same_identity
            )
            selected = [
                record
                for record in same_identity
                if (record.registry_number or 0) == newest_number
            ]

        links = self._merge_record_links(selected)

        return MinjustLookupResult(
            records=selected,
            links=links,
            match_score=best_score,
        )

    @staticmethod
    def _record_match_score(
        entity: EntityInput,
        record: MinjustRegistryRecord,
    ) -> float:
        return max(
            (
                match_name_score(
                    entity.name,
                    search_name,
                    (
                        record.entity_type
                        if entity.entity_type == "unknown"
                        else entity.entity_type
                    ),
                )
                for search_name in record.search_names
            ),
            default=0.0,
        )

    @staticmethod
    def _merge_record_links(
        records: list[MinjustRegistryRecord],
    ) -> list[EntityLink]:
        by_url: dict[str, EntityLink] = {}

        for record in records:
            for link in record.links:
                existing = by_url.get(link.url)

                if existing is None:
                    by_url[link.url] = link.model_copy(deep=True)
                    continue

                existing.source_urls = list(dict.fromkeys([
                    *existing.source_urls,
                    *link.source_urls,
                ]))
                existing.confidence = max(
                    existing.confidence,
                    link.confidence,
                )

        return list(by_url.values())

    def _load_from_store(self) -> None:
        self._records = self.store.load_minjust_registry(
            include_excluded=(
                self.config.minjust_include_excluded
            )
        )
        self._rebuild_indexes()

    def _rebuild_indexes(self) -> None:
        self._normalized_index = {}
        self._token_key_index = {}
        self._token_index = {}

        for index, record in enumerate(self._records or []):
            for search_name in record.search_names:
                self._normalized_index.setdefault(
                    search_name,
                    set(),
                ).add(index)

                key = token_key(search_name)
                if key:
                    self._token_key_index.setdefault(
                        key,
                        set(),
                    ).add(index)

                for token in search_name.split():
                    self._token_index.setdefault(
                        token,
                        set(),
                    ).add(index)

    def _download_registry(
        self,
    ) -> tuple[list[MinjustRegistryRecord], int]:
        offset = 0
        reported_size: int | None = None
        raw_by_id: dict[str, dict[str, Any]] = {}

        while reported_size is None or offset < reported_size:
            page = call_with_retry(
                lambda current_offset=offset: self._fetch_page(
                    current_offset
                ),
                max_attempts=self.config.minjust_max_attempts,
                base_delay_seconds=(
                    self.config.minjust_retry_base_delay_seconds
                ),
            )

            page_size = page.get("size")
            values = page.get("values")

            if not isinstance(page_size, int) or page_size < 0:
                raise MinjustRegistryError(
                    "API Минюста вернул некорректное поле size."
                )

            if not isinstance(values, list):
                raise MinjustRegistryError(
                    "API Минюста вернул некорректное поле values."
                )

            if reported_size is None:
                reported_size = page_size

                if (
                    reported_size
                    > self.config.minjust_max_records
                ):
                    raise MinjustRegistryError(
                        "API сообщил слишком большой реестр: "
                        f"{reported_size} > "
                        f"{self.config.minjust_max_records}."
                    )

            if not values:
                if offset < reported_size:
                    raise MinjustRegistryError(
                        "API вернул пустую страницу до конца реестра "
                        f"(offset={offset}, size={reported_size})."
                    )
                break

            for raw in values:
                if not isinstance(raw, dict):
                    continue

                record_id = str(raw.get("id") or "").strip()
                if not record_id:
                    continue

                raw_by_id[record_id] = raw

            offset += len(values)

            logger.info(
                "Минюст: загружено %d/%d записей.",
                min(offset, reported_size),
                reported_size,
            )

            if (
                self.config.minjust_request_delay_seconds > 0
                and offset < reported_size
            ):
                time.sleep(
                    self.config.minjust_request_delay_seconds
                )

        assert reported_size is not None

        records = [
            self._parse_record(raw)
            for raw in raw_by_id.values()
        ]
        records = [record for record in records if record is not None]

        if (
            len(records)
            < self.config.minjust_min_expected_records
        ):
            raise MinjustRegistryError(
                "Получено подозрительно мало записей: "
                f"{len(records)} < "
                f"{self.config.minjust_min_expected_records}."
            )

        return records, reported_size

    def _fetch_page(self, offset: int) -> dict[str, Any]:
        payload = {
            "offset": offset,
            "limit": self.config.minjust_page_size,
            "search": "",
            "facets": {},
            "sort": [
                {
                    "property": "field_1_i",
                    "direction": "desc",
                }
            ],
        }

        response = self.session.post(
            self.config.minjust_api_url,
            json=payload,
            timeout=self.config.minjust_timeout_seconds,
        )
        response.raise_for_status()

        try:
            value = response.json()
        except requests.JSONDecodeError as exc:
            raise MinjustRegistryError(
                "API Минюста вернул не JSON."
            ) from exc

        if not isinstance(value, dict):
            raise MinjustRegistryError(
                "Корень ответа API Минюста должен быть объектом."
            )

        return value

    def _parse_record(
        self,
        raw: dict[str, Any],
    ) -> MinjustRegistryRecord | None:
        record_id = str(raw.get("id") or "").strip()
        display_name = str(raw.get("field_2_s") or "").strip()

        if not record_id or not display_name:
            return None

        category = str(raw.get("field_7_s") or "").strip()
        entity_type = (
            "person"
            if category == MINJUST_PERSON_CATEGORY
            else "organization"
        )

        resources_raw = str(raw.get("field_6_s") or "").strip()
        date_excluded = str(
            raw.get("field_5_s")
            or raw.get("field_5_dt")
            or ""
        ).strip()
        confidence = self.config.minjust_confidence

        if date_excluded:
            confidence = max(0.50, confidence - 0.10)

        links = self._extract_links(
            resources_raw=resources_raw,
            confidence=confidence,
            registry_number=raw.get("field_1_i"),
            date_excluded=date_excluded,
        )

        registry_number = raw.get("field_1_i")
        if not isinstance(registry_number, int):
            try:
                registry_number = int(registry_number)
            except (TypeError, ValueError):
                registry_number = None

        return MinjustRegistryRecord(
            record_id=record_id,
            registry_number=registry_number,
            display_name=display_name,
            normalized_name=normalize_entity_name(display_name),
            token_key=token_key(display_name),
            search_names=extract_search_names(
                display_name,
                entity_type,
            ),
            entity_type=entity_type,
            category=category,
            resources_raw=resources_raw,
            links=links,
            date_included=str(
                raw.get("field_4_s")
                or raw.get("field_15_s")
                or ""
            ).strip(),
            date_excluded=date_excluded,
            inn=str(raw.get("field_9_s") or "").strip(),
            ogrn=str(raw.get("field_10_s") or "").strip(),
            birth_date=str(raw.get("field_12_s") or "").strip(),
            participants_raw=str(
                raw.get("field_13_s") or ""
            ).strip(),
            raw=raw,
        )

    def _extract_links(
        self,
        *,
        resources_raw: str,
        confidence: float,
        registry_number: object,
        date_excluded: str,
    ) -> list[EntityLink]:
        matches = re.findall(
            r"https?://[^\s;,]+",
            resources_raw.replace("\u00a0", " "),
            flags=re.IGNORECASE,
        )

        links: list[EntityLink] = []
        seen: set[str] = set()

        for raw_url in matches:
            cleaned = repair_registry_url(
                raw_url.rstrip(".,:!?)]}»\"")
            )
            url = normalize_url(cleaned)

            if not is_http_url(url) or url in seen:
                continue

            seen.add(url)

            evidence = (
                "URL указан в поле «Информационный ресурс» "
                "официального реестра Минюста РФ"
            )

            if registry_number:
                evidence += f" (запись № {registry_number})"

            if date_excluded:
                evidence += (
                    f"; запись имеет дату исключения "
                    f"{date_excluded}"
                )

            links.append(
                EntityLink(
                    platform=detect_platform(url),
                    url=url,
                    confidence=confidence,
                    evidence=evidence + ".",
                    source="minjust_registry",
                    source_urls=[
                        self.config.minjust_registry_page_url
                    ],
                )
            )

        return links
