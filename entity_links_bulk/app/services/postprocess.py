from __future__ import annotations

from ..config import AppConfig
from ..models import EntityLink, EntityLinksResult
from ..utils.urls import (
    detect_platform,
    is_http_url,
    is_probable_profile_url,
    normalize_url,
)


def merge_links(
    current: list[EntityLink],
    additional: list[EntityLink],
) -> list[EntityLink]:
    by_url: dict[str, EntityLink] = {}

    for link in [*current, *additional]:
        normalized = normalize_url(link.url)
        if not normalized:
            continue

        link.url = normalized
        link.platform = detect_platform(normalized)

        existing = by_url.get(normalized)
        if existing is None:
            by_url[normalized] = link
            continue

        merged_source_urls = list(dict.fromkeys([
            *existing.source_urls,
            *link.source_urls,
        ]))

        if link.confidence > existing.confidence:
            link.source_urls = merged_source_urls
            if (
                existing.evidence
                and existing.evidence not in link.evidence
            ):
                link.evidence = (
                    f"{link.evidence} "
                    f"Дополнительное подтверждение: "
                    f"{existing.evidence}"
                )
            by_url[normalized] = link
        else:
            existing.source_urls = merged_source_urls
            if (
                link.evidence
                and link.evidence not in existing.evidence
            ):
                existing.evidence = (
                    f"{existing.evidence} "
                    f"Дополнительное подтверждение: "
                    f"{link.evidence}"
                )

    return list(by_url.values())


def sanitize_links(
    result: EntityLinksResult,
    config: AppConfig,
) -> EntityLinksResult:
    clean: list[EntityLink] = []

    for link in result.links:
        normalized = normalize_url(link.url)

        if not is_probable_profile_url(normalized):
            continue

        if link.confidence < config.min_confidence:
            continue

        link.url = normalized
        link.platform = detect_platform(normalized)
        link.source_urls = list(dict.fromkeys(
            normalize_url(source)
            for source in link.source_urls
            if is_http_url(source)
        ))
        clean.append(link)

    result.links = merge_links([], clean)
    return result


def finalize_result(
    result: EntityLinksResult,
    config: AppConfig,
) -> EntityLinksResult:
    result = sanitize_links(result, config)
    result.links.sort(
        key=lambda item: item.confidence,
        reverse=True,
    )
    result.resolution_sources = list(
        dict.fromkeys(result.resolution_sources)
    )
    result.needs_human_review = (
        result.ambiguous
        or not result.links
        or any(
            link.confidence
            < config.human_review_threshold
            for link in result.links
        )
    )
    return result
