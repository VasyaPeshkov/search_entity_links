from __future__ import annotations

import json
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..config import AppConfig
from ..constants import DEFAULT_USER_AGENT
from ..exceptions import UnsafeURL
from ..models import EntityLink, EntityLinksResult
from ..utils.network import is_public_url
from ..utils.urls import (
    detect_platform,
    is_probable_profile_url,
    normalize_url,
)
from .postprocess import merge_links


def _fetch_html(
    url: str,
    config: AppConfig,
) -> str:
    if not is_public_url(url):
        raise UnsafeURL(
            f"Запрещённый или внутренний URL: {url}"
        )

    response = requests.get(
        url,
        timeout=config.crawler_timeout_seconds,
        allow_redirects=True,
        stream=True,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
        },
    )
    response.raise_for_status()

    if not is_public_url(response.url):
        raise UnsafeURL(
            "Redirect привёл на внутренний адрес: "
            f"{response.url}"
        )

    content_type = response.headers.get(
        "Content-Type",
        "",
    ).lower()

    if (
        "text/html" not in content_type
        and "application/xhtml+xml" not in content_type
    ):
        return ""

    chunks: list[bytes] = []
    total = 0

    for chunk in response.iter_content(
        chunk_size=64 * 1024
    ):
        if not chunk:
            continue

        total += len(chunk)
        if total > config.crawler_max_html_bytes:
            break

        chunks.append(chunk)

    return b"".join(chunks).decode(
        response.encoding or "utf-8",
        errors="replace",
    )


def _extract_same_as(
    value,
    output: list[str],
) -> None:
    if isinstance(value, dict):
        same_as = value.get("sameAs")

        if isinstance(same_as, str):
            output.append(same_as)
        elif isinstance(same_as, list):
            output.extend(
                item
                for item in same_as
                if isinstance(item, str)
            )

        for nested in value.values():
            _extract_same_as(nested, output)

    elif isinstance(value, list):
        for item in value:
            _extract_same_as(item, output)


def _extract_social_links(
    html: str,
    base_url: str,
) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    for tag in soup.find_all("a", href=True):
        absolute = urljoin(
            base_url,
            tag["href"].strip(),
        )
        if detect_platform(absolute) != "website":
            urls.append(absolute)

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        try:
            value = json.loads(
                script.string or script.get_text()
            )
        except (json.JSONDecodeError, TypeError):
            continue

        _extract_same_as(value, urls)

    return list(dict.fromkeys(
        normalize_url(url)
        for url in urls
        if (
            detect_platform(url) != "website"
            and is_probable_profile_url(
                normalize_url(url)
            )
        )
    ))


def enrich_from_official_websites(
    result: EntityLinksResult,
    config: AppConfig,
) -> EntityLinksResult:
    if not config.crawler_enabled:
        return result

    if (
        len(result.links)
        >= config.crawler_skip_if_links_at_least
    ):
        return result

    sites = [
        link
        for link in result.links
        if (
            link.platform == "website"
            and link.confidence
            >= config.crawler_min_site_confidence
        )
    ][:config.crawler_max_sites]

    new_links: list[EntityLink] = []

    for site in sites:
        try:
            html = _fetch_html(site.url, config)
        except Exception:
            continue

        for social_url in _extract_social_links(
            html,
            site.url,
        ):
            new_links.append(
                EntityLink(
                    platform=detect_platform(social_url),
                    url=social_url,
                    confidence=0.97,
                    evidence=(
                        "Ссылка размещена на найденном "
                        f"официальном сайте {site.url}."
                    ),
                    source="official_site",
                    source_urls=[site.url],
                )
            )

    result.links = merge_links(
        result.links,
        new_links,
    )

    if new_links:
        result.resolution_sources.append(
            "official_site_crawler"
        )

    return result
