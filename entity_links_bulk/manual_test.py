from __future__ import annotations

from ssl_bootstrap import configure_system_truststore

configure_system_truststore()

from app import AppConfig, EntityResolver
from app.models import EntityInput
from app.storage import SQLiteStore


# Меняй значения прямо здесь.
ENTITY = EntityInput(
    entity_id="manual-1",
    name="The Moscow Times",
    entity_type="organization",
)


def main() -> None:
    config = AppConfig.from_env()
    store = SQLiteStore(config.effective_database_path)
    resolver = EntityResolver.create(config, store)

    if config.minjust_enabled:
        resolver.minjust.ensure_registry()

    result = resolver.resolve_one(ENTITY)

    print(
        result.model_dump_json(
            indent=2,
            exclude_none=True,
        )
    )


if __name__ == "__main__":
    main()
