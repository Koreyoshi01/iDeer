"""
Fetch X/Twitter content via RapidAPI's twitter-api45 endpoints.

The project intentionally uses a single backend here. Previous direct API and
Nitter paths were removed because they required separate credentials or proved
unreliable in practice.
"""

import os
from datetime import datetime, timedelta, timezone

import requests


DEFAULT_RAPIDAPI_HOST = "twitter-api45.p.rapidapi.com"
DEFAULT_TIMEOUT = 30
DEFAULT_DISCOVERY_TIMEOUT = 12


def load_accounts(accounts_file: str) -> list[str]:
    """Load usernames from a text file (one per line, # for comments)."""
    if not os.path.exists(accounts_file):
        print(f"Accounts file not found: {accounts_file}")
        return []

    usernames = []
    with open(accounts_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                usernames.append(line.lstrip("@"))
    return usernames


def _rapidapi_headers(api_key: str, api_host: str) -> dict[str, str]:
    if not api_key:
        raise ValueError("RapidAPI key is required for Twitter/X fetching.")
    return {
        "x-rapidapi-host": api_host,
        "x-rapidapi-key": api_key,
        "Content-Type": "application/json",
    }


def _rapidapi_get(endpoint: str, api_key: str, api_host: str, timeout: int = DEFAULT_TIMEOUT, **params) -> dict:
    url = f"https://{api_host}/{endpoint}"
    response = requests.get(
        url,
        headers=_rapidapi_headers(api_key, api_host),
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _parse_created_at(created_str: str) -> tuple[str, datetime] | tuple[None, None]:
    if not created_str:
        return None, None
    try:
        created_dt = datetime.strptime(created_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        return None, None
    created_dt = created_dt.astimezone(timezone.utc)
    return created_dt.isoformat(), created_dt


def _extract_author(item: dict, fallback_username: str) -> tuple[str, str]:
    author = item.get("author")
    if not isinstance(author, dict):
        author = {}

    author_username = (
        author.get("screen_name")
        or item.get("screen_name")
        or fallback_username
    )
    author_name = (
        author.get("name")
        or item.get("name")
        or fallback_username
    )
    return author_username, author_name


def _build_tweet_url(author_username: str, tweet_id: str) -> str:
    if author_username and tweet_id:
        return f"https://x.com/{author_username}/status/{tweet_id}"
    return ""


def _is_retweet(item: dict, text: str) -> bool:
    return text.startswith("RT @") or bool(item.get("retweeted_tweet"))


def _is_reply(item: dict, text: str) -> bool:
    conversation_id = str(item.get("conversation_id") or "")
    tweet_id = str(item.get("tweet_id") or item.get("id_str") or item.get("id") or "")
    return bool(text.lstrip().startswith("@") and conversation_id and tweet_id and conversation_id != tweet_id)


def _parse_tweet_item(item: dict, fallback_username: str, created_iso: str) -> dict:
    text = item.get("text", "") or item.get("full_text", "")
    author_username, author_name = _extract_author(item, fallback_username)
    tweet_id = str(item.get("tweet_id") or item.get("id_str") or item.get("id") or "")
    is_retweet = _is_retweet(item, text)
    is_reply = _is_reply(item, text)

    quoted_tweet = item.get("quoted_tweet") or item.get("quoted_status") or {}
    quoted_text = quoted_tweet.get("text", "") or quoted_tweet.get("full_text", "")
    quoted_author = (
        quoted_tweet.get("author", {}).get("screen_name")
        or quoted_tweet.get("user", {}).get("screen_name", "")
    )

    entities = item.get("entities", {}) or {}
    urls = [u.get("expanded_url", u.get("url", "")) for u in entities.get("urls", [])]
    media = item.get("media", []) or item.get("extended_entities", {}).get("media", []) or []
    media_urls = [
        media_item.get("media_url_https", media_item.get("media_url", ""))
        for media_item in media
        if isinstance(media_item, dict)
    ]

    return {
        "tweet_id": tweet_id,
        "text": text,
        "author_username": author_username,
        "author_name": author_name,
        "created_at": created_iso,
        "likes": item.get("favorites", item.get("favorite_count", 0)),
        "retweets": item.get("retweets", item.get("retweet_count", 0)),
        "replies": item.get("replies", item.get("reply_count", 0)),
        "is_retweet": is_retweet,
        "is_reply": is_reply,
        "is_quote": bool(quoted_text),
        "quoted_text": quoted_text,
        "quoted_author": quoted_author,
        "media_urls": media_urls,
        "urls": urls,
        "tweet_url": item.get("url", "") or _build_tweet_url(author_username, tweet_id),
        "_x_backend": "rapidapi",
        "_x_retweet_flag_trusted": True,
        # Reply detection is heuristic because this endpoint does not expose a
        # dedicated reply flag on every item shape.
        "_x_reply_flag_trusted": False,
    }


def search_people_rapidapi(
    query: str,
    api_key: str,
    api_host: str = DEFAULT_RAPIDAPI_HOST,
    max_results: int = 20,
    timeout: int = DEFAULT_DISCOVERY_TIMEOUT,
) -> list[dict]:
    """Search accounts by person name using search_type=People."""
    try:
        data = _rapidapi_get(
            "search.php",
            api_key,
            api_host,
            timeout=timeout,
            query=query,
            search_type="People",
        )
    except Exception as e:
        print(f"[rapidapi] Error searching people for '{query}': {e}")
        return []

    results = []
    for item in (data.get("timeline") or [])[:max_results]:
        if item.get("type") != "user":
            continue
        screen_name = item.get("screen_name")
        if not screen_name:
            continue
        results.append({
            "screen_name": screen_name,
            "name": item.get("name", screen_name),
            "followers_count": item.get("followers_count", 0),
            "avatar": item.get("avatar"),
            "verified": item.get("blue_verified", False),
            "profile_url": f"https://x.com/{screen_name}",
        })
    return results


def search_top_tweets_rapidapi(
    query: str,
    api_key: str,
    api_host: str = DEFAULT_RAPIDAPI_HOST,
    max_results: int = 20,
    timeout: int = DEFAULT_DISCOVERY_TIMEOUT,
) -> list[dict]:
    """Search top tweets for a topic or keyword using search_type=Top."""
    try:
        data = _rapidapi_get(
            "search.php",
            api_key,
            api_host,
            timeout=timeout,
            query=query,
            search_type="Top",
        )
    except Exception as e:
        print(f"[rapidapi] Error searching top tweets for '{query}': {e}")
        return []

    results = []
    for item in (data.get("timeline") or [])[:max_results]:
        if item.get("type") != "tweet":
            continue
        created_iso, _ = _parse_created_at(item.get("created_at", ""))
        results.append(_parse_tweet_item(item, fallback_username="", created_iso=created_iso or ""))
    return results


def fetch_user_tweets_rapidapi(
    username: str,
    api_key: str,
    api_host: str = DEFAULT_RAPIDAPI_HOST,
    since_hours: int = 24,
    max_tweets: int = 20,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict]:
    """Fetch recent tweets from an account timeline via RapidAPI."""
    try:
        data = _rapidapi_get(
            "timeline.php",
            api_key,
            api_host,
            timeout=timeout,
            screenname=username,
            count=max_tweets,
        )
    except Exception as e:
        print(f"[rapidapi] Error fetching tweets for @{username}: {e}")
        return []

    since_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    timeline = data.get("timeline") or []
    results = []

    for item in timeline:
        created_iso, created_dt = _parse_created_at(item.get("created_at", ""))
        if not created_dt or created_dt < since_time:
            continue
        results.append(_parse_tweet_item(item, fallback_username=username, created_iso=created_iso))
        if len(results) >= max_tweets:
            break

    return results


def fetch_all_accounts(
    accounts: list[str],
    api_key: str,
    api_host: str = DEFAULT_RAPIDAPI_HOST,
    since_hours: int = 24,
    max_tweets_per_user: int = 20,
) -> list[dict]:
    """Fetch tweets from all configured accounts, deduplicated by tweet_id."""
    all_tweets = []
    seen_ids = set()

    for username in accounts:
        print(f"[rapidapi] Fetching tweets for @{username}...")
        tweets = fetch_user_tweets_rapidapi(
            username=username,
            api_key=api_key,
            api_host=api_host,
            since_hours=since_hours,
            max_tweets=max_tweets_per_user,
        )

        for tweet in tweets:
            tweet_id = tweet.get("tweet_id")
            if tweet_id and tweet_id not in seen_ids:
                seen_ids.add(tweet_id)
                all_tweets.append(tweet)

        print(f"  -> {len(tweets)} tweets from @{username}")

    print(f"[rapidapi] Total: {len(all_tweets)} unique tweets from {len(accounts)} accounts")
    return all_tweets
