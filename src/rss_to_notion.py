"""
RSS-to-Notion Knowledge Database

Fetches recent articles from RSS feeds, processes them with Grok API for
summarization/keywords/relevance, and upserts results into a Notion database.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Optional

import feedparser
import httpx
from dotenv import load_dotenv
from notion_client import Client
from notion_client.helpers import extract_database_id
from openai import OpenAI
from urllib.parse import quote

# Load .env from project root (parent of src/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# -----------------------------------------------------------------------------
# RSS Feeds Configuration
# -----------------------------------------------------------------------------
# Recommended Tech-Focused RSS Feeds (2026-Active)
# Static feeds - add more by appending to this list
RSS_FEEDS = [
    # WIRED – Deep dives into tech, AI, science, culture, and future trends. Often excellent for thoughtful AI/ethics coverage.
    "https://www.wired.com/feed/rss",  # Main
    "https://www.wired.com/feed/tag/ai/latest/rss",  # AI-specific
    "https://www.wired.com/feed/category/science/latest/rss",  # Science
    # TechCrunch – Startups, funding, apps, AI launches, and breaking tech business news. Great volume and timeliness.
    "https://techcrunch.com/feed/",
    # Ars Technica – In-depth tech analysis, policy, hardware, science, and security. Very reliable for technical depth.
    "https://feeds.arstechnica.com/arstechnica/index",  # Main/All
    "https://feeds.arstechnica.com/arstechnica/technology-lab",  # Technology Lab
    # The Verge – Consumer tech, gadgets, reviews, AI impacts, and culture. Clean, modern coverage.
    "https://www.theverge.com/rss/index.xml",
    # BBC News Technology – Global, neutral tech reporting with strong science/environment overlap.
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    # Google News RSS (custom topic aggregator) – use None as placeholder; URL built dynamically with topic + since_days.
    # Format: https://news.google.com/rss/search?q=...&hl=en-US&gl=US&ceid=US:en (use urllib.parse.quote in code)
    None,
    # Bonus Strong Ones (optional - uncomment to include):
    # "https://news.ycombinator.com/rss",  # Hacker News (Y Combinator aggregator)
    # "https://www.technologyreview.com/feed/",  # MIT Technology Review (emerging tech/AI research)
    # "https://www.cnet.com/rss/",  # CNET (gadgets & consumer tech)
    # "https://www.cnet.com/rss/news/",  # CNET news
]


# -----------------------------------------------------------------------------
# Central Configuration
# -----------------------------------------------------------------------------
@dataclass
class RSSConfig:
    """
    Central configuration for the RSS-to-Notion pipeline.
    Override any field to customize behavior.

    Attributes:
        topic: Search topic for Google News; used in Grok relevance context.
        since_days: Only include articles published within this many days.
        articles_per_feed: Max articles to fetch per RSS feed.
        content_snippet_length: Max chars from article description sent to Grok.
        summary_word_range: Summary length in Grok prompt (e.g. "100-150").
        keywords_count: Number of keywords in Grok prompt (e.g. "6-10").
        summary_max_chars: Max chars for Summary in Notion.
        keywords_max: Max keywords stored in Notion.
        rss_feeds: List of RSS feed URLs; None = Google News (built dynamically).
        grok_models: Fallback Grok models to try.
    """

    topic: str = "vibe coding"
    since_days: int = 3
    articles_per_feed: int = 3
    content_snippet_length: int = 1000
    summary_word_range: str = "50-100"
    keywords_count: str = "3-5"
    summary_max_chars: int = 2000
    keywords_max: int = 10
    rss_feeds: list[str | None] = field(default_factory=lambda: list(RSS_FEEDS))
    grok_models: list[str] = field(
        default_factory=lambda: [
            "grok-4-fast-non-reasoning",
            "grok-4-1-fast-non-reasoning",
        ]
    )


DEFAULT_CONFIG = RSSConfig()

def update_notion_with_rss(
    notion_token: str = "",
    database_id: str = "",
    grok_api_key: str = "",
    config: Optional[RSSConfig] = None,
) -> None:
    """
    Fetch recent articles from RSS feeds, process with Grok API, and upsert to Notion.

    Args:
        notion_token: Notion integration token.
        database_id: Notion database ID to upsert into.
        grok_api_key: xAI API key for Grok.
        config: Optional RSSConfig; uses DEFAULT_CONFIG if not provided.
    """
    cfg = config or DEFAULT_CONFIG
    try:
        # Normalize database ID (handles full Notion URLs or raw IDs)
        db_id = extract_database_id(database_id) or database_id.strip()
        if not db_id:
            raise ValueError("Invalid NOTION_DATABASE_ID: provide a database ID or full Notion database URL")

        # Initialize clients
        client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1")
        # Use legacy API (2022-06-28) - notion-client 2.7+ defaults to 2025-09-03 which
        # deprecated databases/query and requires data_source_id for page creation
        notion = Client(auth=notion_token, notion_version="2022-06-28")

        # Verify database access before processing
        resolved = False
        try:
            notion.databases.retrieve(db_id)
            resolved = True
        except Exception as e:
            compact_id = db_id.replace("-", "")
            if compact_id != db_id:
                try:
                    notion.databases.retrieve(compact_id)
                    db_id = compact_id
                    resolved = True
                except Exception:
                    pass
            if not resolved:
                if "404" in str(e) or "not find" in str(e).lower():
                    raise RuntimeError(
                        "Notion 404: Database not found or not shared with your integration.\n\n"
                        "Fix: Open the database in Notion → click ••• (top right) → Add connections → "
                        "select your integration.\n"
                        "If the database is inside a page, also share that parent page with the integration.\n\n"
                        f"Database ID used: {db_id}\n\n"
                        "To list databases you have access to, run: python src/rss_to_notion.py --list-databases"
                    ) from e
                raise RuntimeError(
                    f"Notion database access failed: {e}\n\n"
                    "Ensure: (1) Database is shared with your integration (••• → Add connections), "
                    "(2) NOTION_TOKEN and NOTION_DATABASE_ID are correct."
                ) from e

        cutoff = (datetime.now(timezone.utc) - timedelta(days=cfg.since_days)).replace(tzinfo=None)
        articles = []
        seen_urls = set()

        # ---------------------------------------------------------------------
        # Fetch and parse RSS feeds
        # ---------------------------------------------------------------------
        for feed_spec in cfg.rss_feeds:
            if feed_spec is None:
                # Google News: build dynamic URL with topic + time window
                query = f"{cfg.topic} when:{cfg.since_days}d"
                feed_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
            else:
                feed_url = feed_spec

            try:
                feed = feedparser.parse(feed_url)
            except Exception as e:
                print(f"Warning: Failed to parse feed {feed_url}: {e}")
                continue

            if getattr(feed, "bozo", False) or not feed.entries:
                print(f"Warning: Invalid or empty feed: {feed_url}")
                continue

            for entry in feed.entries[: cfg.articles_per_feed]:
                pub_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if not pub_parsed:
                    continue

                try:
                    pub_dt = datetime(*pub_parsed[:6])
                except (TypeError, ValueError):
                    continue

                if pub_dt < cutoff:
                    continue

                url = (entry.get("link") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                description = (
                    entry.get("summary")
                    or entry.get("description")
                    or (
                        entry.content[0].value
                        if getattr(entry, "content", None) and len(entry.content) > 0
                        else ""
                    )
                )
                description = (description or "").strip()

                articles.append(
                    {
                        "title": (entry.get("title") or "").strip(),
                        "url": url,
                        "description": description,
                        "published": pub_dt.isoformat(),
                        "source": feed.feed.get("title", "Unknown"),
                    }
                )

        # Sort by published descending (most recent first)
        articles.sort(key=lambda a: a["published"], reverse=True)

        print(f"Fetched {len(articles)} unique recent articles from RSS feeds")

        # ---------------------------------------------------------------------
        # Process each article with Grok and upsert to Notion
        # ---------------------------------------------------------------------
        for article in articles:
            content_snippet = (article["description"] or "")[: cfg.content_snippet_length]

            prompt = f"""Analyze this recent article on {cfg.topic}:
Title: {article['title']}
Content: {content_snippet}

Provide:
- A concise summary in {cfg.summary_word_range} words.
- {cfg.keywords_count} relevant keywords as a list.
- Relevance score to '{cfg.topic}' (1-10 integer).

Output ONLY valid JSON, no extra text: {{"summary": str, "keywords": list[str], "relevance_score": int}}"""

            grok_models = cfg.grok_models
            content = None
            for model in grok_models:
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    content = response.choices[0].message.content.strip()
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    if "model" in err_str or "not found" in err_str:
                        print(f"Grok model {model} unavailable, trying fallback: {e}")
                        continue
                    print(f"Grok API error for '{article['title']}': {e}")
                    break
            if content is None:
                continue

            try:
                processed = json.loads(content)
            except json.JSONDecodeError:
                print("Grok parse error, skipping:", article["title"])
                continue

            # Build Notion properties
            properties = {
                "Title": {"title": [{"text": {"content": article["title"]}}]},
                "Summary": {
                    "rich_text": [
                        {"text": {"content": (processed.get("summary") or "")[: cfg.summary_max_chars]}}
                    ]
                },
                "Keywords": {
                    "multi_select": [
                        {"name": str(k).strip()}
                        for k in processed.get("keywords", [])[: cfg.keywords_max]
                    ]
                },
                "Source URL": {"url": article["url"]},
                "Date Added": {"date": {"start": article["published"]}},
                "Last Updated": {
                    "date": {"start": datetime.now(timezone.utc).isoformat()}
                },
            }

            # Upsert: query by Source URL, then update or create
            # Use legacy API for database query (notion-client 2.7+ uses 2025 API which moved query to data_sources)
            try:
                resp = httpx.post(
                    f"https://api.notion.com/v1/databases/{db_id}/query",
                    headers={
                        "Authorization": f"Bearer {notion_token}",
                        "Notion-Version": "2022-06-28",
                        "Content-Type": "application/json",
                    },
                    json={
                        "filter": {
                            "property": "Source URL",
                            "url": {"equals": article["url"]},
                        },
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                query_result = resp.json()
            except Exception as e:
                err_msg = str(e)
                if hasattr(e, "response") and hasattr(e.response, "content"):
                    try:
                        err_body = json.loads(e.response.content)
                        err_msg = err_body.get("message", err_msg)
                    except Exception:
                        pass
                print(f"Notion query error for '{article['title']}': {err_msg}")
                continue

            try:
                if query_result["results"]:
                    page_id = query_result["results"][0]["id"]
                    notion.pages.update(page_id=page_id, properties=properties)
                    print(f"Updated existing entry: {article['title']}")
                else:
                    notion.pages.create(
                        parent={"database_id": db_id},
                        properties=properties,
                    )
                    print(f"Created new entry: {article['title']}")
            except Exception as e:
                err_msg = str(e)
                # Extract Notion API error message if available
                raw = getattr(e, "response", None) or getattr(e, "body", None)
                if raw is not None:
                    try:
                        content = getattr(raw, "content", raw) or getattr(raw, "text", raw)
                        if isinstance(content, bytes):
                            content = content.decode("utf-8", errors="replace")
                        if content:
                            err_body = json.loads(content)
                            err_msg = err_body.get("message", err_msg)
                    except Exception:
                        pass
                print(f"Notion upsert error for '{article['title']}': {err_msg}")
                continue

        print("Update complete.")

    except Exception as e:
        print(f"Error: {e}")
        raise


def list_notion_databases(notion_token: str) -> None:
    """List databases shared with the integration. Run with: python src/rss_to_notion.py --list-databases"""
    notion = Client(auth=notion_token, notion_version="2022-06-28")
    try:
        results = notion.search()
    except Exception as e:
        print(f"Notion token invalid or no access: {e}")
        raise SystemExit(1) from e

    # Filter to databases (2022 API) or data_sources (2025 API)
    all_results = results.get("results", [])
    dbs = [r for r in all_results if r.get("object") in ("database", "data_source")]
    if not dbs:
        print("No databases found. Share a database with your integration first:")
        print("  Open database in Notion → ••• → Add connections → select your integration")
        return

    print("Databases shared with your integration:\n")
    for r in dbs:
        title = "Untitled"
        if "title" in r and r["title"]:
            title = r["title"][0].get("plain_text", "Untitled") if r["title"] else "Untitled"
        elif "title" in r and isinstance(r["title"], str):
            title = r["title"]
        db_id = r.get("id", "")
        print(f"  {title}")
        print(f"    ID: {db_id}")
        print()
    print("Copy a database ID above into NOTION_DATABASE_ID in your .env file.")


if __name__ == "__main__":
    import argparse
    import sys

    notion_token = os.environ.get("NOTION_TOKEN", "")
    database_id = os.environ.get("NOTION_DATABASE_ID", "")
    grok_api_key = os.environ.get("GROK_API_KEY", "")

    parser = argparse.ArgumentParser(description="RSS-to-Notion: fetch articles and upsert to Notion")
    parser.add_argument(
        "--list-databases",
        action="store_true",
        help="List Notion databases shared with your integration",
    )
    parser.add_argument(
        "--topic",
        default=os.environ.get("RSS_TOPIC", DEFAULT_CONFIG.topic),
        help="Search topic for Google News and Grok relevance (default: from RSS_TOPIC env or config)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=int(os.environ.get("RSS_SINCE_DAYS", str(DEFAULT_CONFIG.since_days))),
        help="Only include articles from last N days (default: from RSS_SINCE_DAYS env or config)",
    )
    args = parser.parse_args()

    if args.list_databases:
        if not notion_token:
            print("Error: Set NOTION_TOKEN in .env to list databases")
            raise SystemExit(1)
        list_notion_databases(notion_token)
        raise SystemExit(0)

    if not all([notion_token, database_id, grok_api_key]):
        print(
            "Error: Set NOTION_TOKEN, NOTION_DATABASE_ID, and GROK_API_KEY in .env "
            "(copy .env.example to .env and fill in your values)"
        )
        raise SystemExit(1)

    config = RSSConfig(topic=args.topic, since_days=args.since_days)
    try:
        update_notion_with_rss(
            notion_token=notion_token,
            database_id=database_id,
            grok_api_key=grok_api_key,
            config=config,
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        raise SystemExit(130)
