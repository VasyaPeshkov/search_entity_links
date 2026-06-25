from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

from ..constants import CACHE_KEY_VERSION, LEGAL_FORM_WORDS
from ..models import EntityType


def normalize_entity_name(name: str) -> str:
    value = unicodedata.normalize("NFKC", name)
    value = value.lower().replace("ё", "е")
    value = re.sub(r"[«»\"'`()\[\]{}]", " ", value)
    value = re.sub(
        r"[^a-zа-я0-9]+",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    return " ".join(value.split())


def _tokens(name: str) -> list[str]:
    return normalize_entity_name(name).split()


def token_key(name: str) -> str:
    return " ".join(sorted(_tokens(name)))


def organization_token_key(name: str) -> str:
    tokens = [
        token
        for token in _tokens(name)
        if token not in LEGAL_FORM_WORDS
    ]
    return " ".join(sorted(tokens))


def extract_search_names(
    display_name: str,
    entity_type: EntityType,
) -> list[str]:
    """
    Строит варианты имени для локального поиска.

    Примеры:
    - ФИО с псевдонимом в кавычках;
    - полное юридическое наименование и короткое имя в кавычках;
    - варианты в круглых скобках.
    """

    raw_candidates: list[str] = [display_name]

    quote_positions = [
        position
        for marker in ('"', "«")
        if (position := display_name.find(marker)) >= 0
    ]
    if quote_positions:
        prefix = display_name[:min(quote_positions)].strip(" ,;:-")
        if prefix:
            raw_candidates.append(prefix)

    quoted_parts = re.findall(
        r'"([^\"]+)"|«([^»]+)»',
        display_name,
    )
    for straight, russian in quoted_parts:
        value = (straight or russian).strip()
        if not value:
            continue
        raw_candidates.append(value)
        raw_candidates.extend(
            part.strip()
            for part in re.split(r"[,;]", value)
            if part.strip()
        )

    for parenthesized in re.findall(r"\(([^)]+)\)", display_name):
        value = parenthesized.strip()
        if value:
            raw_candidates.append(value)

    normalized: list[str] = []

    for candidate in raw_candidates:
        value = normalize_entity_name(candidate)
        if value:
            normalized.append(value)

        if entity_type == "organization":
            short = organization_token_key(candidate)
            if short:
                normalized.append(short)

        if entity_type == "person":
            tokens = value.split()
            if len(tokens) >= 3:
                normalized.extend([
                    f"{tokens[0]} {tokens[1]}",
                    f"{tokens[1]} {tokens[0]}",
                    f"{tokens[0]} {tokens[-1]}",
                    f"{tokens[-1]} {tokens[0]}",
                ])

    return list(dict.fromkeys(normalized))


def make_cache_key(name: str, entity_type: EntityType) -> str:
    normalized = normalize_entity_name(name)
    return hashlib.sha256(
        f"{CACHE_KEY_VERSION}:{entity_type}:{normalized}".encode(
            "utf-8"
        )
    ).hexdigest()


def belongs_to_shard(
    cache_key: str,
    shard_count: int,
    shard_index: int,
) -> bool:
    return int(cache_key[:16], 16) % shard_count == shard_index


def match_name_score(
    expected: str,
    actual: str,
    entity_type: EntityType,
) -> float:
    expected_normalized = normalize_entity_name(expected)
    actual_normalized = normalize_entity_name(actual)

    if not expected_normalized or not actual_normalized:
        return 0.0

    if expected_normalized == actual_normalized:
        return 1.0

    if entity_type == "organization":
        expected_tokens = organization_token_key(expected).split()
        actual_tokens = organization_token_key(actual).split()
    else:
        expected_tokens = _tokens(expected)
        actual_tokens = _tokens(actual)

    if not expected_tokens or not actual_tokens:
        return 0.0

    expected_set = set(expected_tokens)
    actual_set = set(actual_tokens)

    if expected_set == actual_set:
        return 0.99

    intersection = len(expected_set & actual_set)
    union = len(expected_set | actual_set)
    jaccard = intersection / union if union else 0.0
    containment = intersection / min(
        len(expected_set),
        len(actual_set),
    )

    sequence = SequenceMatcher(
        None,
        " ".join(expected_tokens),
        " ".join(actual_tokens),
    ).ratio()

    sorted_sequence = SequenceMatcher(
        None,
        " ".join(sorted(expected_tokens)),
        " ".join(sorted(actual_tokens)),
    ).ratio()

    return max(
        sequence * 0.45
        + jaccard * 0.35
        + containment * 0.20,
        sorted_sequence * 0.55
        + jaccard * 0.30
        + containment * 0.15,
    )
