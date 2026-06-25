from __future__ import annotations

from dataclasses import dataclass, field

from ..utils.urls import is_http_url


@dataclass(slots=True)
class GroundingInfo:
    search_used: bool
    search_queries: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)


def extract_grounding_info(response) -> GroundingInfo:
    search_queries: list[str] = []
    source_urls: list[str] = []
    has_search_entry_point = False

    for candidate in getattr(
        response,
        "candidates",
        None,
    ) or []:
        metadata = getattr(
            candidate,
            "grounding_metadata",
            None,
        )

        if metadata is None:
            continue

        if getattr(
            metadata,
            "search_entry_point",
            None,
        ) is not None:
            has_search_entry_point = True

        for query in (
            getattr(metadata, "web_search_queries", None)
            or []
        ):
            if isinstance(query, str) and query.strip():
                search_queries.append(query.strip())

        for chunk in (
            getattr(metadata, "grounding_chunks", None)
            or []
        ):
            web = getattr(chunk, "web", None)
            if web is None:
                continue

            uri = getattr(web, "uri", None)
            if uri and is_http_url(uri):
                source_urls.append(uri)

    search_queries = list(dict.fromkeys(search_queries))
    source_urls = list(dict.fromkeys(source_urls))

    return GroundingInfo(
        search_used=bool(
            search_queries
            or source_urls
            or has_search_entry_point
        ),
        search_queries=search_queries,
        source_urls=source_urls,
    )
