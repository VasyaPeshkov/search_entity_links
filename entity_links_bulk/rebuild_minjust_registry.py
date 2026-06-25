from __future__ import annotations

from ssl_bootstrap import configure_system_truststore

configure_system_truststore()

from app import AppConfig
from app.services.minjust_registry import MinjustRegistryService
from app.storage import SQLiteStore


def main() -> None:
    config = AppConfig.from_env()
    store = SQLiteStore(config.effective_database_path)
    service = MinjustRegistryService(config, store)

    service.force_rebuild_registry()

    print(
        "Записей в локальном реестре Минюста: "
        f"{store.minjust_registry_count()}"
    )


if __name__ == "__main__":
    main()
