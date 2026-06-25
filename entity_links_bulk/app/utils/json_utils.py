from __future__ import annotations

import json
import re

from ..exceptions import InvalidModelResponse


def extract_json_object(text: str) -> dict:
    text = text.strip()
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise InvalidModelResponse(
            f"В ответе модели отсутствует JSON:\n{text[:1000]}"
        )

    raw = text[start:end + 1]

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidModelResponse(
            f"Модель вернула невалидный JSON: {exc}\n"
            f"{raw[:2000]}"
        ) from exc

    if not isinstance(value, dict):
        raise InvalidModelResponse(
            "Корневой элемент ответа должен быть JSON object."
        )

    return value
