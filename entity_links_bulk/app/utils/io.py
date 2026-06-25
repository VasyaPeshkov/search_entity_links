from __future__ import annotations

import csv
import json
from pathlib import Path

from ..models import EntityInput, StoredResult


def read_entities(path: Path) -> list[EntityInput]:
    if not path.exists():
        raise FileNotFoundError(f"Входной CSV не найден: {path}")

    entities: list[EntityInput] = []

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if "name" not in (reader.fieldnames or []):
            raise ValueError(
                "Во входном CSV обязательна колонка name."
            )

        for row_number, row in enumerate(reader, start=1):
            name = (row.get("name") or "").strip()
            if not name:
                continue

            raw_type = (
                row.get("entity_type")
                or row.get("type")
                or "unknown"
            ).strip().lower()

            if raw_type not in {
                "person", "organization", "unknown"
            }:
                raw_type = "unknown"

            entity_id = (
                row.get("id")
                or row.get("entity_id")
                or str(row_number)
            ).strip()

            entities.append(
                EntityInput(
                    entity_id=entity_id,
                    name=name,
                    entity_type=raw_type,
                )
            )

    return entities


def write_results_jsonl(
    path: Path,
    rows: list[tuple[EntityInput, StoredResult | None]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        for entity, stored in rows:
            value = {
                "id": entity.entity_id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "status": (
                    stored.status
                    if stored is not None
                    else "not_processed"
                ),
                "attempts": (
                    stored.attempts
                    if stored is not None
                    else 0
                ),
                "error": (
                    stored.last_error
                    if stored is not None
                    else None
                ),
                "result": (
                    stored.result.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    if stored is not None
                    and stored.result is not None
                    else None
                ),
            }
            file.write(
                json.dumps(value, ensure_ascii=False) + "\n"
            )


def write_unresolved_csv(
    path: Path,
    rows: list[tuple[EntityInput, StoredResult | None]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "id", "name", "entity_type",
                "status", "attempts", "error",
            ],
        )
        writer.writeheader()

        for entity, stored in rows:
            if stored is not None and stored.status == "success":
                continue

            writer.writerow({
                "id": entity.entity_id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "status": (
                    stored.status
                    if stored is not None
                    else "not_processed"
                ),
                "attempts": (
                    stored.attempts
                    if stored is not None
                    else 0
                ),
                "error": (
                    stored.last_error
                    if stored is not None
                    else ""
                ),
            })
