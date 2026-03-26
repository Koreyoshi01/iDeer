"""
Profile extraction helpers for discovery inputs.

Supports generic personal homepages and best-effort Google Scholar profile
pages. Scholar often rate-limits or blocks server-side requests, so extraction
there is intentionally resilient and may return partial metadata only.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_TIMEOUT = 20
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}


def _clean_lines(lines: list[str], max_lines: int = 80) -> list[str]:
    cleaned = []
    seen = set()
    for raw in lines:
        line = " ".join(raw.split())
        if len(line) < 3:
            continue
        lowered = line.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(line)
        if len(cleaned) >= max_lines:
            break
    return cleaned


def _fetch_html(url: str) -> str:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.text


def _extract_homepage_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    pieces = []

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title:
        pieces.append(f"Title: {title}")

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        pieces.append(f"Description: {meta_desc['content'].strip()}")

    selectors = ["h1", "h2", "h3", "p", "li"]
    for selector in selectors:
        for node in soup.find_all(selector):
            text = node.get_text(" ", strip=True)
            if text:
                pieces.append(text)

    return "\n".join(_clean_lines(pieces))


def _extract_google_scholar_text(url: str, html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lowered = text.lower()

    if "人机身份验证" in text or "enable javascript" in lowered or "captcha" in lowered:
        parsed = urlparse(url)
        user_id = parse_qs(parsed.query).get("user", [""])[0]
        fallback = [
            "Google Scholar profile URL was provided.",
            f"Scholar user id: {user_id}" if user_id else "Scholar user id: unknown",
            "Direct content extraction was blocked by Scholar anti-bot / JavaScript verification.",
        ]
        return "blocked", "\n".join(fallback)

    pieces = []
    name_node = soup.select_one("#gsc_prf_in")
    if name_node:
        pieces.append(f"Scholar name: {name_node.get_text(' ', strip=True)}")

    affiliation_node = soup.select_one(".gsc_prf_il")
    if affiliation_node:
        pieces.append(f"Affiliation: {affiliation_node.get_text(' ', strip=True)}")

    interest_nodes = soup.select("#gsc_prf_int a")
    if interest_nodes:
        interests = [node.get_text(" ", strip=True) for node in interest_nodes]
        pieces.append(f"Interests: {', '.join(interests)}")

    paper_nodes = soup.select(".gsc_a_t a.gsc_a_at")
    for node in paper_nodes[:20]:
        title = node.get_text(" ", strip=True)
        if title:
            pieces.append(f"Publication: {title}")

    if not pieces:
        pieces.append("\n".join(_clean_lines(text.splitlines())))

    return "ok", "\n".join(_clean_lines(pieces))


def extract_profile_from_url(url: str) -> dict:
    kind = "scholar" if "scholar.google." in url else "homepage"
    result = {
        "url": url,
        "kind": kind,
        "status": "ok",
        "text": "",
        "error": "",
    }

    try:
        html = _fetch_html(url)
        if kind == "scholar":
            status, text = _extract_google_scholar_text(url, html)
            result["status"] = status
            result["text"] = text
        else:
            result["text"] = _extract_homepage_text(html)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["text"] = f"Failed to fetch profile URL: {url}"

    return result


def build_profile_text_from_urls(urls: list[str]) -> tuple[str, list[dict]]:
    sources = []
    parts = []

    for url in urls:
        source = extract_profile_from_url(url)
        sources.append(source)
        header = f"[Profile URL: {url} | kind={source['kind']} | status={source['status']}]"
        body = source.get("text", "").strip()
        if source.get("error"):
            body = f"{body}\nError: {source['error']}".strip()
        if body:
            parts.append(f"{header}\n{body}")

    return "\n\n".join(parts).strip(), sources
