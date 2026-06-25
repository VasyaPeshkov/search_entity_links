from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from ..constants import BAD_PATH_PARTS, SOCIAL_DOMAINS


def repair_registry_url(url: str) -> str:
    """Исправляет только очевидные Unicode-опечатки реестра."""

    value = url.strip().replace("\u00a0", "")
    value = re.sub(
        r"^(https?://)[хХ]\.com",
        r"\1x.com",
        value,
    )
    value = re.sub(
        r"^(https?://)(?:www\.)?youtube\.eom",
        r"\1youtube.com",
        value,
        flags=re.IGNORECASE,
    )
    return value


def normalize_url(url: str) -> str:
    url = repair_registry_url(url)

    if not url:
        return ""

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()

    if host.startswith("www."):
        host = host[4:]

    path = re.sub(r"/+", "/", parsed.path or "/")

    if host in {"t.me", "telegram.me"} and path.startswith("/s/"):
        path = path[2:]

    if path != "/":
        path = path.rstrip("/")

    return urlunparse((scheme, host, path, "", parsed.query, ""))


def is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
        )
    except ValueError:
        return False


def detect_platform(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return "unknown"

    if host.startswith("www."):
        host = host[4:]

    for platform, domains in SOCIAL_DOMAINS.items():
        if any(
            host == domain or host.endswith("." + domain)
            for domain in domains
        ):
            return platform

    return "website"


def is_bad_candidate_url(url: str) -> bool:
    if not is_http_url(url):
        return True

    lowered = url.lower()
    return any(part in lowered for part in BAD_PATH_PARTS)


def is_probable_profile_url(url: str) -> bool:
    if is_bad_candidate_url(url):
        return False

    platform = detect_platform(url)
    path = urlparse(url).path.strip("/")

    if platform == "website":
        return True

    if not path:
        return False

    parts = [part for part in path.split("/") if part]

    if platform in {
        "telegram",
        "instagram",
        "x",
        "vk",
        "ok",
        "threads",
        "boosty",
        "patreon",
        "bluesky",
        "medium",
    }:
        return len(parts) >= 1

    if platform == "facebook":
        return len(parts) >= 1

    if platform == "tiktok":
        return len(parts) == 1 and parts[0].startswith("@")

    if platform == "linkedin":
        return (
            len(parts) >= 2
            and parts[0] in {"in", "company", "school"}
        )

    if platform == "youtube":
        return (
            path.startswith("@")
            or path.startswith("channel/")
            or path.startswith("user/")
            or path.startswith("c/")
        )

    return True
