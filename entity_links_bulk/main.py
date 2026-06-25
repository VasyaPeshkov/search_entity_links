from __future__ import annotations

from ssl_bootstrap import configure_system_truststore

configure_system_truststore()

import json
import logging
from pathlib import Path

from app import AppConfig, BulkRunner


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        ),
    )


def print_entity_links(results_path: Path) -> None:
    """Печатает итоговые ссылки: имя сущности: [список ссылок]."""
    if not results_path.exists():
        raise FileNotFoundError(
            f"Файл результатов не найден: {results_path}"
        )

    with results_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Некорректный JSON в файле "
                    f"{results_path}, строка {line_number}."
                ) from exc

            name = str(row.get("name") or "").replace(
                "\r", " "
            ).replace("\n", " ").strip()

            result = row.get("result") or {}
            raw_links = result.get("links") or []

            urls: list[str] = []
            seen: set[str] = set()

            for link in raw_links:
                if not isinstance(link, dict):
                    continue

                url = str(link.get("url") or "").strip()
                if not url or url in seen:
                    continue

                seen.add(url)
                urls.append(url)

            print(
                f"{name}: "
                f"{json.dumps(urls, ensure_ascii=False)}"
            )


def main() -> None:
    config = AppConfig.from_env()
    configure_logging(config.log_level)

    runner = BulkRunner(config)
    runner.run()

    print_entity_links(config.effective_output_jsonl)


if __name__ == "__main__":
    main()
