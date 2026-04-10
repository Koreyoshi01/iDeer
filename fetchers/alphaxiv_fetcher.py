"""Fetch hot papers from alphaXiv explore pages."""

from __future__ import annotations

from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.alphaxiv.org"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}


def _safe_int(text: str) -> int:
    raw = str(text or "").replace(",", "").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


def fetch_explore(
    sort: str = "Hot",
    max_results: int = 30,
    source: str = "GitHub",
    interval: str = "7 Days",
) -> list[dict]:
    response = requests.get(
        f"{BASE_URL}/",
        params={"sort": sort, "source": source, "interval": interval},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    papers: list[dict] = []
    seen_ids: set[str] = set()

    for title_link in soup.find_all("a", href=True):
        href = title_link.get("href", "")
        if not href.startswith("/abs/"):
            continue
        title = title_link.get_text(" ", strip=True)
        if not title:
            continue

        alpha_id = href.split("/abs/", 1)[-1].strip()
        if not alpha_id or alpha_id in seen_ids:
            continue

        card = title_link.find_parent("div", class_="rounded-xl")
        if card is None:
            continue

        summary_node = card.find("p", class_=lambda value: value and "line-clamp-4" in value)
        summary = summary_node.get_text(" ", strip=True) if summary_node else ""

        date_node = card.find("span", class_=lambda value: value and "whitespace-nowrap" in value)
        publish_date = date_node.get_text(" ", strip=True) if date_node else ""

        authors = []
        author_container = card.find("div", class_=lambda value: value and "overflow-x-auto" in value)
        if author_container:
            for author_node in author_container.find_all("div", class_=lambda value: value and "font-normal" in value):
                author_name = author_node.get_text(" ", strip=True)
                if author_name and author_name not in authors:
                    authors.append(author_name)

        tags = []
        for tag_link in card.find_all("a", href=True):
            tag_text = tag_link.get_text(" ", strip=True)
            if tag_text.startswith("#"):
                tags.append(tag_text.lstrip("#").strip())

        blog_url = ""
        resources_url = ""
        repo_url = ""
        likes = 0
        view_count = 0
        resource_count = 0

        links = card.find_all("a", href=True)
        buttons = card.find_all("button")

        for link in links:
            link_href = link.get("href", "")
            link_text = link.get_text(" ", strip=True)
            if link_href.startswith("/overview/"):
                blog_url = urljoin(BASE_URL, link_href)
            elif link_href.startswith("/resources/"):
                resources_url = urljoin(BASE_URL, link_href)
            elif link_href.startswith("http") and "github.com" in link_href:
                repo_url = link_href
                if link_text.isdigit():
                    resource_count = _safe_int(link_text)
            elif link_href == href and link_text.replace(",", "").isdigit():
                view_count = _safe_int(link_text)

        for button in buttons:
            button_text = button.get_text(" ", strip=True)
            if button_text.isdigit():
                likes = max(likes, _safe_int(button_text))

        papers.append(
            {
                "alpha_id": alpha_id,
                "title": title,
                "summary": summary,
                "publish_date": publish_date,
                "authors": authors,
                "tags": tags,
                "likes": likes,
                "resource_count": resource_count,
                "view_count": view_count,
                "paper_url": urljoin(BASE_URL, href),
                "blog_url": blog_url,
                "resources_url": resources_url,
                "repo_url": repo_url,
                "sort": sort,
                "platform_source": source,
                "interval": interval,
            }
        )
        seen_ids.add(alpha_id)

        if len(papers) >= max_results:
            break

    return papers
