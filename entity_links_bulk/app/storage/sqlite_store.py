from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..models import (
    EntityLink,
    EntityLinksResult,
    EntityType,
    MinjustRegistryRecord,
    StoredResult,
    LLMUsage,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class SQLiteStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS results (
                    cache_key TEXT PRIMARY KEY,
                    input_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS minjust_registry (
                    record_id TEXT PRIMARY KEY,
                    registry_number INTEGER,
                    display_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    token_key TEXT NOT NULL,
                    search_names_json TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    resources_raw TEXT NOT NULL,
                    links_json TEXT NOT NULL,
                    date_included TEXT NOT NULL,
                    date_excluded TEXT NOT NULL,
                    inn TEXT NOT NULL,
                    ogrn TEXT NOT NULL,
                    birth_date TEXT NOT NULL,
                    participants_raw TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS
                    idx_minjust_normalized_name
                    ON minjust_registry(normalized_name);

                CREATE INDEX IF NOT EXISTS
                    idx_minjust_token_key
                    ON minjust_registry(token_key);

                CREATE INDEX IF NOT EXISTS
                    idx_minjust_entity_type
                    ON minjust_registry(entity_type);

                CREATE INDEX IF NOT EXISTS
                    idx_minjust_registry_number
                    ON minjust_registry(registry_number);

                CREATE TABLE IF NOT EXISTS llm_daily_usage (
                    usage_date TEXT NOT NULL,
                    model TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    entities_sent INTEGER NOT NULL DEFAULT 0,
                    successful_entities INTEGER NOT NULL DEFAULT 0,
                    failed_requests INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (usage_date, model)
                );

                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

    def get_result(self, cache_key: str) -> StoredResult | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM results WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()

        if row is None:
            return None

        result = (
            EntityLinksResult.model_validate_json(
                row["result_json"]
            )
            if row["result_json"]
            else None
        )

        return StoredResult(
            cache_key=row["cache_key"],
            input_name=row["input_name"],
            entity_type=row["entity_type"],
            status=row["status"],
            result=result,
            attempts=row["attempts"],
            last_error=row["last_error"],
        )

    def save_success(
        self,
        cache_key: str,
        input_name: str,
        entity_type: EntityType,
        result: EntityLinksResult,
    ) -> None:
        self._save_result(
            cache_key=cache_key,
            input_name=input_name,
            entity_type=entity_type,
            status="success",
            result=result,
            error=None,
            increment_attempt=False,
        )

    def save_unresolved(
        self,
        cache_key: str,
        input_name: str,
        entity_type: EntityType,
        result: EntityLinksResult | None,
        reason: str,
        increment_attempt: bool = False,
    ) -> None:
        self._save_result(
            cache_key=cache_key,
            input_name=input_name,
            entity_type=entity_type,
            status="unresolved",
            result=result,
            error=reason,
            increment_attempt=increment_attempt,
        )

    def save_failure(
        self,
        cache_key: str,
        input_name: str,
        entity_type: EntityType,
        error: str,
    ) -> None:
        self._save_result(
            cache_key=cache_key,
            input_name=input_name,
            entity_type=entity_type,
            status="failed",
            result=None,
            error=error,
            increment_attempt=True,
        )

    def _save_result(
        self,
        *,
        cache_key: str,
        input_name: str,
        entity_type: EntityType,
        status: str,
        result: EntityLinksResult | None,
        error: str | None,
        increment_attempt: bool,
    ) -> None:
        result_json = (
            result.model_dump_json()
            if result is not None
            else None
        )
        now = _utc_now().isoformat()

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT attempts FROM results WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()

            attempts = (
                int(existing["attempts"])
                if existing is not None
                else 0
            )
            if increment_attempt:
                attempts += 1

            connection.execute(
                """
                INSERT INTO results (
                    cache_key, input_name, entity_type, status,
                    result_json, attempts, last_error, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    input_name = excluded.input_name,
                    entity_type = excluded.entity_type,
                    status = excluded.status,
                    result_json = excluded.result_json,
                    attempts = excluded.attempts,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    cache_key,
                    input_name,
                    entity_type,
                    status,
                    result_json,
                    attempts,
                    error,
                    now,
                ),
            )

    def replace_minjust_registry(
        self,
        records: list[MinjustRegistryRecord],
        reported_size: int,
    ) -> None:
        """Транзакционно заменяет локальную копию реестра."""

        now = _utc_now().isoformat()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM minjust_registry")
            connection.executemany(
                """
                INSERT INTO minjust_registry (
                    record_id,
                    registry_number,
                    display_name,
                    normalized_name,
                    token_key,
                    search_names_json,
                    entity_type,
                    category,
                    resources_raw,
                    links_json,
                    date_included,
                    date_excluded,
                    inn,
                    ogrn,
                    birth_date,
                    participants_raw,
                    raw_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.record_id,
                        record.registry_number,
                        record.display_name,
                        record.normalized_name,
                        record.token_key,
                        json.dumps(
                            record.search_names,
                            ensure_ascii=False,
                        ),
                        record.entity_type,
                        record.category,
                        record.resources_raw,
                        json.dumps(
                            [
                                link.model_dump(mode="json")
                                for link in record.links
                            ],
                            ensure_ascii=False,
                        ),
                        record.date_included,
                        record.date_excluded,
                        record.inn,
                        record.ogrn,
                        record.birth_date,
                        record.participants_raw,
                        json.dumps(
                            record.raw,
                            ensure_ascii=False,
                        ),
                        now,
                    )
                    for record in records
                ],
            )

            metadata = {
                "minjust_registry_updated_at": now,
                "minjust_registry_reported_size": str(reported_size),
                "minjust_registry_stored_size": str(len(records)),
            }

            connection.executemany(
                """
                INSERT INTO metadata(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value
                """,
                list(metadata.items()),
            )

    def load_minjust_registry(
        self,
        include_excluded: bool = True,
    ) -> list[MinjustRegistryRecord]:
        query = "SELECT * FROM minjust_registry"
        parameters: tuple[object, ...] = ()

        if not include_excluded:
            query += " WHERE date_excluded = ''"

        with self._connect() as connection:
            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        return [self._row_to_minjust_record(row) for row in rows]

    @staticmethod
    def _row_to_minjust_record(
        row: sqlite3.Row,
    ) -> MinjustRegistryRecord:
        return MinjustRegistryRecord(
            record_id=row["record_id"],
            registry_number=row["registry_number"],
            display_name=row["display_name"],
            normalized_name=row["normalized_name"],
            token_key=row["token_key"],
            search_names=json.loads(row["search_names_json"]),
            entity_type=row["entity_type"],
            category=row["category"],
            resources_raw=row["resources_raw"],
            links=[
                EntityLink.model_validate(item)
                for item in json.loads(row["links_json"])
            ],
            date_included=row["date_included"],
            date_excluded=row["date_excluded"],
            inn=row["inn"],
            ogrn=row["ogrn"],
            birth_date=row["birth_date"],
            participants_raw=row["participants_raw"],
            raw=json.loads(row["raw_json"]),
        )

    def minjust_registry_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM minjust_registry"
            ).fetchone()
        return int(row["count"])

    def minjust_registry_is_fresh(
        self,
        ttl_hours: int,
    ) -> bool:
        if self.minjust_registry_count() == 0:
            return False

        updated_at = _parse_datetime(
            self.get_metadata("minjust_registry_updated_at")
        )
        if updated_at is None:
            return False

        return (
            _utc_now() - updated_at
            <= timedelta(hours=ttl_hours)
        )

    def invalidate_minjust_registry_timestamp(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM metadata
                WHERE key = 'minjust_registry_updated_at'
                """
            )

    def reserve_llm_request(
        self,
        *,
        usage_date: str,
        model: str,
        entity_count: int,
        request_limit: int,
    ) -> LLMUsage | None:
        """Атомарно резервирует один фактически отправляемый запрос."""

        now = _utc_now().isoformat()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM llm_daily_usage
                WHERE usage_date = ? AND model = ?
                """,
                (usage_date, model),
            ).fetchone()

            requests = int(row["requests"]) if row else 0
            if requests >= request_limit:
                connection.rollback()
                return None

            entities_sent = (
                int(row["entities_sent"]) if row else 0
            ) + entity_count
            requests += 1

            connection.execute(
                """
                INSERT INTO llm_daily_usage (
                    usage_date, model, requests, entities_sent,
                    successful_entities, failed_requests, updated_at
                )
                VALUES (?, ?, ?, ?, 0, 0, ?)
                ON CONFLICT(usage_date, model) DO UPDATE SET
                    requests = excluded.requests,
                    entities_sent = excluded.entities_sent,
                    updated_at = excluded.updated_at
                """,
                (
                    usage_date,
                    model,
                    requests,
                    entities_sent,
                    now,
                ),
            )

        return self.get_llm_usage(usage_date, model)

    def complete_llm_request(
        self,
        *,
        usage_date: str,
        model: str,
        successful_entities: int,
        failed: bool,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE llm_daily_usage
                SET successful_entities = successful_entities + ?,
                    failed_requests = failed_requests + ?,
                    updated_at = ?
                WHERE usage_date = ? AND model = ?
                """,
                (
                    max(successful_entities, 0),
                    1 if failed else 0,
                    _utc_now().isoformat(),
                    usage_date,
                    model,
                ),
            )

    def get_llm_usage(
        self,
        usage_date: str,
        model: str,
    ) -> LLMUsage:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM llm_daily_usage
                WHERE usage_date = ? AND model = ?
                """,
                (usage_date, model),
            ).fetchone()

        if row is None:
            return LLMUsage(usage_date=usage_date, model=model)

        return LLMUsage(
            usage_date=row["usage_date"],
            model=row["model"],
            requests=int(row["requests"]),
            entities_sent=int(row["entities_sent"]),
            successful_entities=int(row["successful_entities"]),
            failed_requests=int(row["failed_requests"]),
        )

    def get_metadata(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row["value"]) if row is not None else None
