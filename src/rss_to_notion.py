"""
RSS-to-Notion Knowledge Database

Personal knowledge database with dual retrieval: RSS for trusted recurring
sources, Exa for thematic discovery. LLM layer summarises neutrally and tags
ontologically for future clustering.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Literal, Optional

import feedparser
import httpx
from dotenv import load_dotenv
from notion_client import Client
from notion_client.helpers import extract_database_id
from openai import OpenAI

# Load .env from project root (parent of src/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# -----------------------------------------------------------------------------
# Internal article schema (shared between RSS and Exa modes)
# -----------------------------------------------------------------------------
ArticleSchema = dict[str, str]


# -----------------------------------------------------------------------------
# RSS Feeds Configuration
# -----------------------------------------------------------------------------
# Domain-specific feeds: energy, climate, macro, policy, regulation
RSS_FEEDS = [
    "https://www.iea.org/feed",
    "https://www.carbonbrief.org/feed",
    "https://www.ft.com/energy?format=rss",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.bis.org/rss/work.rss",
    "https://www.federalreserve.gov/feeds/press_all.xml",
    "https://www.imf.org/en/News/rss?language=eng",
    "https://www.sfc.hk/en/rss/news",
    "https://feeds.feedburner.com/NberWorkingPapers",
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
        mode: Retrieval mode: rss, exa, or both.
        topic: Search topic for Exa; used in Grok relevance context.
        since_days: Only include RSS articles published within this many days.
        articles_per_feed: Max articles to fetch per RSS feed.
        content_snippet_length: Max chars from article text sent to Grok.
        summary_max_chars: Max chars for Summary in Notion.
        keywords_max: Max keywords stored in Notion.
        rss_feeds: List of RSS feed URLs.
        grok_models: Fallback Grok models to try.
    """

    mode: Literal["rss", "exa", "both"] = "rss"
    topic: str = "energy climate macro policy"
    since_days: int = 2
    articles_per_feed: int = 3
    content_snippet_length: int = 1000
    summary_max_chars: int = 2000
    keywords_max: int = 10
    rss_feeds: list[str] = field(default_factory=lambda: list(RSS_FEEDS))
    grok_models: list[str] = field(
        default_factory=lambda: [
            "grok-4-fast-non-reasoning",
            "grok-4-1-fast-non-reasoning",
        ]
    )


DEFAULT_CONFIG = RSSConfig()


def fetch_rss_articles(config: RSSConfig) -> list[ArticleSchema]:
    """Fetch articles from RSS feeds, return list conforming to ArticleSchema."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.since_days)).replace(tzinfo=None)
    articles: list[ArticleSchema] = []
    seen_urls: set[str] = set()

    for feed_url in config.rss_feeds:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"Warning: Failed to parse feed {feed_url}: {e}")
            continue

        if getattr(feed, "bozo", False) or not feed.entries:
            print(f"Warning: Invalid or empty feed: {feed_url}")
            continue

        source = feed.feed.get("title", "Unknown")
        for entry in feed.entries[: config.articles_per_feed]:
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

            text = (
                entry.get("summary")
                or entry.get("description")
                or (
                    entry.content[0].value
                    if getattr(entry, "content", None) and len(entry.content) > 0
                    else ""
                )
            )
            text = (text or "").strip()

            articles.append(
                {
                    "title": (entry.get("title") or "").strip(),
                    "url": url,
                    "source": source,
                    "source_mode": "rss",
                    "published_date": pub_dt.isoformat(),
                    "text": text,
                }
            )

    articles.sort(key=lambda a: a["published_date"], reverse=True)
    return articles


def fetch_exa_articles(topic: str, exa_api_key: str, num_results: int = 10) -> list[ArticleSchema]:
    """Fetch articles from Exa semantic search, return list conforming to ArticleSchema."""
    try:
        from exa_py import Exa
    except ImportError:
        print("Error: exa-py not installed. Run: pip install exa-py")
        return []

    exa = Exa(api_key=exa_api_key)
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        response = exa.search(
            topic,
            num_results=num_results,
            contents={"highlights": True},
        )
    except Exception as e:
        print(f"Warning: Exa API error: {e}")
        return []

    articles: list[ArticleSchema] = []
    for result in response.results:
        url = getattr(result, "url", "") or ""
        if not url:
            continue
        title = getattr(result, "title", "") or "Untitled"
        pub_date = getattr(result, "published_date", None) or now_iso
        # Prefer highlights (key passages); fallback to text or title
        text_parts: list[str] = []
        if hasattr(result, "highlights") and result.highlights:
            text_parts.extend(result.highlights)
        if hasattr(result, "text") and result.text:
            text_parts.append(result.text)
        text = "\n\n".join(text_parts) if text_parts else title

        articles.append(
            {
                "title": title,
                "url": url,
                "source": "exa-search",
                "source_mode": "exa",
                "published_date": pub_date if isinstance(pub_date, str) else now_iso,
                "text": text,
            }
        )
    return articles


def fetch_articles(
    config: RSSConfig,
    exa_api_key: str = "",
) -> list[ArticleSchema]:
    """Fetch articles based on mode; deduplicate by URL when mode is both."""
    if config.mode == "rss":
        return fetch_rss_articles(config)
    if config.mode == "exa":
        return fetch_exa_articles(config.topic, exa_api_key)

    # mode == "both": run in parallel, dedupe by URL
    all_articles: list[ArticleSchema] = []
    seen_urls: set[str] = set()

    def run_rss() -> list[ArticleSchema]:
        return fetch_rss_articles(config)

    def run_exa() -> list[ArticleSchema]:
        return fetch_exa_articles(config.topic, exa_api_key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_rss = executor.submit(run_rss)
        future_exa = executor.submit(run_exa)
        for future in as_completed([future_rss, future_exa]):
            for article in future.result():
                url = article["url"]
                if url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(article)

    all_articles.sort(key=lambda a: a["published_date"], reverse=True)
    return all_articles


def update_notion_with_rss(
    notion_token: str = "",
    database_id: str = "",
    grok_api_key: str = "",
    exa_api_key: str = "",
    config: Optional[RSSConfig] = None,
) -> None:
    """
    Fetch articles (RSS and/or Exa), process with Grok API, and upsert to Notion.

    Args:
        notion_token: Notion integration token.
        database_id: Notion database ID to upsert into.
        grok_api_key: xAI API key for Grok.
        exa_api_key: Exa API key (required when mode is exa or both).
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

        # ---------------------------------------------------------------------
        # Fetch articles (RSS, Exa, or both)
        # ---------------------------------------------------------------------
        articles = fetch_articles(cfg, exa_api_key=exa_api_key)
        mode_label = "RSS" if cfg.mode == "rss" else "Exa" if cfg.mode == "exa" else "RSS+Exa"
        print(f"Fetched {len(articles)} unique articles ({mode_label})")

        # ---------------------------------------------------------------------
        # Process each article with Grok and upsert to Notion
        # ---------------------------------------------------------------------
        system_prompt = """You are a research assistant helping build a personal knowledge database with two purposes: (1) accurate understanding of how things work from first principles, and (2) tracking how real-world situations develop over time.

Your job is to summarise faithfully and tag precisely. You are not an analyst, commentator, or advisor. You do not take positions, make predictions, or characterise outcomes as good or bad. You report what is, what changed, and what the established mechanism says should follow — and you flag when evidence is contested or incomplete.

The reader has a finance and quantitative background. Precise language, numbers, and mechanisms are welcome. Opinions and forecasts are not."""

        user_prompt_template = """Analyse the following article and return ONLY a valid JSON object.
No preamble, no markdown fences, no trailing commentary.

Article:
{article_text}

Return exactly this structure:

{{
  "summary": "3-5 sentences. Cover: (1) what happened or what is being claimed, (2) the mechanism or reason given, (3) what is known vs contested — if sources disagree or evidence is thin, say so plainly. Do not editorialize. Do not characterise outcomes as positive or negative. Do not use hedged forecast language ('poised to', 'could reshape', 'may signal'). If a logical consequence follows from an established mechanism (e.g. higher debt servicing costs crowd out discretionary spending), state it as a mechanical consequence, not a prediction. Write as a neutral record that will still be accurate to read in 2 years.",

  "entry_type": "one of: concept-explainer | situation-update | data-release | policy-change | historical-case. Use situation-update for articles tracking the evolution of an ongoing development (e.g. US debt ceiling, Fed rate path, China property sector). Use concept-explainer when the article primarily explains how something works.",

  "situation_tag": "If entry_type is situation-update, provide a short stable slug that groups related updates together over time. Examples: 'us-fiscal-trajectory', 'fed-rate-cycle-2024-26', 'china-ev-export-growth', 'eu-carbon-border-adjustment'. Use null for all other entry types.",

  "keywords": {{
    "domain": ["primary subject area, e.g. fiscal-policy, energy-storage, monetary-policy, semiconductor-supply-chain"],
    "concept": ["underlying principle or mechanism at play, e.g. concept:crowding-out, concept:debt-monetisation, concept:learning-curves"],
    "entity": ["named organisations, instruments, standards, treaties — only if central to the article"],
    "region": ["only if geography is material to the mechanism"],
    "time_signal": ["pick exactly one: structural-trend | cyclical | near-term-event | historical-case"]
  }},

  "relevance_score": integer 0-10 where: 10 = core mechanism explained or significant situation update, 5 = useful context or corroborating data point, 1 = peripheral or repetitive news item,

  "trunk_branch": "One sentence. Format: '[trunk concept] → [what this article concretely illustrates or updates]'. For situation-updates, include a timestamp signal where possible. For concept-explainers: 'Monetary transmission mechanism → how central bank rate changes propagate to mortgage rates with a 6-12 month lag.' Factual, dateable where possible, no opinion, no forecast."
}}"""

        for article in articles:
            content_snippet = (article["text"] or "")[: cfg.content_snippet_length]
            article_text = f"Title: {article['title']}\n\nContent: {content_snippet}"
            user_prompt = user_prompt_template.format(article_text=article_text)

            grok_models = cfg.grok_models
            content: str | None = None
            for model in grok_models:
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
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

            # Parse JSON with fallback on failure
            try:
                # Strip markdown code fences if present
                raw = content.strip()
                if raw.startswith("```"):
                    lines = raw.split("\n")
                    raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                processed = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"Warning: LLM parse failure for '{article['title']}': {e}. Using fallback.")
                processed = {
                    "summary": content[: cfg.summary_max_chars],
                    "entry_type": "unknown",
                    "situation_tag": None,
                    "keywords": {},
                    "relevance_score": 0,
                    "trunk_branch": "",
                }

            # Post-process: flatten keywords with type prefix
            keywords_obj = processed.get("keywords") or {}
            flattened: list[str] = []
            for prefix, keys in [
                ("domain", keywords_obj.get("domain", [])),
                ("concept", keywords_obj.get("concept", [])),
                ("entity", keywords_obj.get("entity", [])),
                ("region", keywords_obj.get("region", [])),
                ("time_signal", keywords_obj.get("time_signal", [])),
            ]:
                for k in keys if isinstance(keys, list) else []:
                    val = str(k).strip()
                    if val and not val.startswith(prefix + ":"):
                        flattened.append(f"{prefix}:{val}")
                    elif val:
                        flattened.append(val)
            flattened = flattened[: cfg.keywords_max]

            summary = (processed.get("summary") or "")[: cfg.summary_max_chars]
            entry_type = processed.get("entry_type") or "unknown"
            situation_tag = processed.get("situation_tag")
            relevance_score = int(processed.get("relevance_score", 0))
            trunk_branch = (processed.get("trunk_branch") or "").strip()

            now_iso = datetime.now(timezone.utc).isoformat()

            # Upsert: query by Source_URL
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
                            "property": "Source_URL",
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
                    # Update: only Summary, Keywords, Trunk_Branch, Relevance_Score, Last_Updated
                    notion.pages.update(
                        page_id=page_id,
                        properties={
                            "Summary": {"rich_text": [{"text": {"content": summary}}]},
                            "Keywords": {
                                "multi_select": [{"name": k} for k in flattened],
                            },
                            "Trunk_Branch": {"rich_text": [{"text": {"content": trunk_branch}}]},
                            "Relevance_Score": {"number": relevance_score},
                            "Last_Updated": {"date": {"start": now_iso}},
                        },
                    )
                    print(f"Updated existing entry: {article['title']}")
                else:
                    # Create: all 13 properties
                    properties = {
                        "Title": {"title": [{"text": {"content": article["title"]}}]},
                        "Summary": {"rich_text": [{"text": {"content": summary}}]},
                        "Keywords": {"multi_select": [{"name": k} for k in flattened]},
                        "Source_URL": {"url": article["url"]},
                        "Entry_Type": {"select": {"name": entry_type}},
                        "Trunk_Branch": {"rich_text": [{"text": {"content": trunk_branch}}]},
                        "Relevance_Score": {"number": relevance_score},
                        "Source_Mode": {"select": {"name": article["source_mode"]}},
                        "Feed_Source": {"rich_text": [{"text": {"content": article["source"]}}]},
                        "Date_Published": {"date": {"start": article["published_date"]}},
                        "Date_Added": {"date": {"start": now_iso}},
                        "Last_Updated": {"date": {"start": now_iso}},
                    }
                    if situation_tag:
                        properties["Cluster_Tag"] = {"select": {"name": situation_tag}}
                    notion.pages.create(
                        parent={"database_id": db_id},
                        properties=properties,
                    )
                    print(f"Created new entry: {article['title']}")
            except Exception as e:
                err_msg = str(e)
                raw = getattr(e, "response", None) or getattr(e, "body", None)
                if raw is not None:
                    try:
                        resp_content = getattr(raw, "content", raw) or getattr(raw, "text", raw)
                        if isinstance(resp_content, bytes):
                            resp_content = resp_content.decode("utf-8", errors="replace")
                        if resp_content:
                            err_body = json.loads(resp_content)
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

    notion_token = os.environ.get("NOTION_TOKEN", "")
    database_id = os.environ.get("NOTION_DATABASE_ID", "")
    grok_api_key = os.environ.get("GROK_API_KEY", "")
    exa_api_key = os.environ.get("EXA_API_KEY", "")

    parser = argparse.ArgumentParser(description="RSS-to-Notion: fetch articles and upsert to Notion")
    parser.add_argument(
        "--list-databases",
        action="store_true",
        help="List Notion databases shared with your integration",
    )
    parser.add_argument(
        "--mode",
        choices=["rss", "exa", "both"],
        default=os.environ.get("RSS_MODE", "rss"),
        help="Retrieval mode: rss (default), exa, or both",
    )
    parser.add_argument(
        "--topic",
        default=os.environ.get("RSS_TOPIC", DEFAULT_CONFIG.topic),
        help="Topic for Exa search and Grok context (default: from RSS_TOPIC env or config)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=int(os.environ.get("RSS_SINCE_DAYS", str(DEFAULT_CONFIG.since_days))),
        help="Only include RSS articles from last N days (default: 2)",
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

    if args.mode in ("exa", "both") and not exa_api_key:
        print(
            "Error: EXA_API_KEY required when --mode is exa or both. "
            "Add EXA_API_KEY to your .env file."
        )
        raise SystemExit(1)

    config = RSSConfig(mode=args.mode, topic=args.topic, since_days=args.since_days)
    try:
        update_notion_with_rss(
            notion_token=notion_token,
            database_id=database_id,
            grok_api_key=grok_api_key,
            exa_api_key=exa_api_key,
            config=config,
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        raise SystemExit(130)
