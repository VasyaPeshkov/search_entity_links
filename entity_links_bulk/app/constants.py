from __future__ import annotations

CACHE_KEY_VERSION = "v2-minjust"

SOCIAL_DOMAINS: dict[str, set[str]] = {
    "telegram": {"t.me", "telegram.me"},
    "instagram": {"instagram.com"},
    "facebook": {"facebook.com", "fb.com"},
    "x": {"x.com", "twitter.com"},
    "youtube": {"youtube.com", "youtu.be"},
    "vk": {"vk.com"},
    "linkedin": {"linkedin.com"},
    "tiktok": {"tiktok.com"},
    "ok": {"ok.ru"},
    "threads": {"threads.net", "threads.com"},
    "boosty": {"boosty.to"},
    "patreon": {"patreon.com"},
    "dzen": {"dzen.ru"},
    "bluesky": {"bsky.app"},
    "medium": {"medium.com"},
    "livejournal": {"livejournal.com"},
}

BAD_PATH_PARTS: set[str] = {
    "/search",
    "/hashtag/",
    "/explore/",
    "/status/",
    "/posts/",
    "/post/",
    "/share",
    "/sharer",
    "/intent/",
    "/reel/",
    "/stories/",
    "/watch",
    "/results",
    "/tag/",
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

LEGAL_FORM_WORDS: set[str] = {
    "ооо",
    "оао",
    "зао",
    "пао",
    "ано",
    "нко",
    "фонд",
    "ассоциация",
    "автономная",
    "некоммерческая",
    "организация",
    "компания",
    "общество",
    "ограниченной",
    "ответственностью",
    "акционерное",
    "учреждение",
    "limited",
    "ltd",
    "llc",
    "inc",
    "corp",
    "corporation",
    "foundation",
}

MINJUST_PERSON_CATEGORY = "Физические лица"
