"""RSS feed collector — adapted from mi_news_fresh/collectors/rss_feeds.py.
Uses requests + defusedxml (safe XML), NOT feedparser.
"""
import html as html_module
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as ET
import requests

from brand_labels import NON_TECH_CONTEXTS, assign_brand_labels
from seed_data import RSS_FEEDS_KO, RSS_FEEDS_EN, KEYWORDS_KO, KEYWORDS_EN, KEYWORDS_CASE_SENSITIVE
from source_tiers import get_source_tier

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

MAX_FEED_BYTES = 10 * 1024 * 1024  # 10 MB


def _build_proxies() -> dict:
    proxies = {}
    for key in ("HTTPS_PROXY", "https_proxy"):
        if os.environ.get(key):
            proxies["https"] = os.environ[key]
            break
    for key in ("HTTP_PROXY", "http_proxy"):
        if os.environ.get(key):
            proxies["http"] = os.environ[key]
            break
    return proxies


def _is_relevant(title: str, description: str, keywords: list[str], keywords_cs: list[str] | None = None) -> bool:
    text = f"{title} {description}".lower()
    # Negative gate: drop articles whose brand name only appears in sports /
    # humanoid / marathon contexts ('수원 삼성', '삼성 라이온즈', etc.)
    if any(p in text for p in NON_TECH_CONTEXTS):
        return False
    if any(kw in text for kw in keywords):
        return True
    if keywords_cs:
        text_original = f"{title} {description}"
        return any(kw in text_original for kw in keywords_cs)
    return False


def _parse_date(date_str: str) -> Optional[str]:
    if not date_str:
        return None
    date_str = date_str.strip()
    # ISO 8601 / Atom first: "2026-04-19T09:19:50Z", "+09:00", "+0900" (no colon)
    try:
        normalized = re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", date_str.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(normalized)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    # Date only: "2026-04-19"
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        pass
    # RFC 2822 fallback: "Mon, 19 Apr 2026 09:00:00 +0000"
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    return None


def _find_el(item: Element, *tags: str) -> Optional[Element]:
    for tag in tags:
        el = item.find(tag)
        if el is not None:
            return el
    return None


def _extract_text(el: Optional[Element]) -> str:
    """Extract all text from an XML element, unescape HTML entities, strip tags."""
    if el is None:
        return ""
    raw = "".join(el.itertext())
    clean = re.sub(r"<[^>]+>", "", raw)
    return html_module.unescape(clean).strip()


def _fetch_feed(
    url: str,
    source_name: str,
    lang: str,
    keywords: list[str],
    keywords_cs: list[str] | None = None,
) -> list[dict]:
    try:
        with requests.get(
            url, headers=HEADERS, timeout=15, stream=True,
            proxies=_build_proxies() or None
        ) as resp:
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "")
            if "xml" not in ct and "rss" not in ct and "atom" not in ct:
                logger.warning("Unexpected Content-Type '%s' for %s", ct, source_name)

            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65_536):
                total += len(chunk)
                if total > MAX_FEED_BYTES:
                    logger.warning("Feed too large (>10MB), skipping: %s", source_name)
                    return []
                chunks.append(chunk)

        content = b"".join(chunks)
        if b"<html" in content[:200].lower():
            logger.warning("Feed returned HTML (likely blocked): %s", source_name)
            return []

        root = ET.fromstring(content)
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        articles: list[dict] = []
        for item in items:
            title_el = _find_el(item, "title", "{http://www.w3.org/2005/Atom}title")
            title = _extract_text(title_el)

            link_el = _find_el(item, "link", "{http://www.w3.org/2005/Atom}link")
            if link_el is None:
                continue
            link = (link_el.text or link_el.get("href", "") or "").strip()
            if not link:
                continue

            desc_el = _find_el(
                item,
                "description", "summary",
                "{http://www.w3.org/2005/Atom}summary",
                "{http://www.w3.org/2005/Atom}content",
            )
            description = _extract_text(desc_el)

            if not _is_relevant(title, description, keywords, keywords_cs):
                continue

            # Date: try pubDate / published / updated (Atom)
            date_el = _find_el(
                item,
                "pubDate", "published",
                "{http://www.w3.org/2005/Atom}published",
                "{http://www.w3.org/2005/Atom}updated",
                "{http://purl.org/dc/elements/1.1/}date",
            )
            published_at = _parse_date(date_el.text if date_el is not None else "")

            # Skip articles published before 2025
            if published_at and published_at < "2025-01-01":
                continue

            # Publisher name: prefer <source> tag (Google News RSS items)
            source_el = item.find("source")
            publisher_name = (source_el.text or "").strip() if source_el is not None else ""
            effective_source = publisher_name if publisher_name else source_name

            found_kws = [kw for kw in keywords if kw in (title + description).lower()]

            articles.append({
                "url": link,
                "title": title,
                "description": description[:500] if description else None,
                "source_name": effective_source,
                "source_tier": get_source_tier(link, effective_source),
                "language": lang,
                "published_at": published_at,
                "keywords": ",".join(found_kws[:10]),
                "brand_labels": assign_brand_labels(title, description or ""),
            })
        return articles

    except Exception as e:
        logger.warning("Feed error [%s | %s]: %s", source_name, url, e)
        return []


def fetch_all_feeds() -> tuple[int, int]:
    """Collect all RSS feeds. Returns (total_new, total_skipped)."""
    from database import insert_articles

    all_articles: list[dict] = []
    for name, url in RSS_FEEDS_KO.items():
        all_articles.extend(_fetch_feed(url, name, "ko", KEYWORDS_KO))
    for name, url in RSS_FEEDS_EN.items():
        all_articles.extend(_fetch_feed(url, name, "en", KEYWORDS_EN, KEYWORDS_CASE_SENSITIVE))

    if not all_articles:
        return 0, 0
    return insert_articles(all_articles)
