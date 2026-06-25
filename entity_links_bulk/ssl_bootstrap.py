from __future__ import annotations


def configure_system_truststore() -> None:
    """Подключить системное хранилище доверенных CA до импорта requests."""
    try:
        import truststore
    except ImportError as exc:
        raise RuntimeError(
            "Не установлен пакет truststore. Выполните: "
            "python -m pip install -r requirements.txt"
        ) from exc

    truststore.inject_into_ssl()
