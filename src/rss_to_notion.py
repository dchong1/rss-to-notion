"""
RSS-to-Notion Knowledge Database

Personal knowledge database with RSS as primary pipeline for trusted recurring
sources; Exa for targeted thematic discovery when needed. LLM layer summarises
neutrally and tags ontologically for future clustering.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Any, Literal, Optional

import feedparser  # pyright: ignore[reportMissingImports]
import httpx
from dotenv import load_dotenv
from notion_client import Client
from notion_client.helpers import extract_database_id
from openai import OpenAI

# Load .env from project root (parent of src/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from feeds import append_feeds, feeds_file_path, load_cluster_tags, load_feeds, load_keywords

# -----------------------------------------------------------------------------
# Internal article schema (shared between RSS and Exa modes)
# -----------------------------------------------------------------------------
ArticleSchema = dict[str, str]


# -----------------------------------------------------------------------------
# Central Configuration
# -----------------------------------------------------------------------------
@dataclass
class RSSConfig:
    """
    Central configuration for the RSS-to-Notion pipeline.
    Override any field to customize behavior.

    Attributes:
        mode: Retrieval mode: rss (default) or exa.
        topic: Search topic for Exa; used in Grok relevance context.
        exa_num_results: Max results from Exa search (default 5).
        relevance_min: Only upsert Exa articles with relevance_score >= this (default 7).
        since_days: Only include articles published within this many days (RSS and Exa).
        articles_per_feed: Max articles to fetch per RSS feed.
        content_snippet_length: Max chars from article text sent to Grok.
        summary_max_chars: Max chars for Summary in Notion.
        keywords_max: Max keywords stored in Notion.
        discover_num_feeds: Max feeds to suggest in feed-discovery mode.
        rss_feeds: List of RSS feed URLs.
        cluster_tags: Allowed cluster tags for situation-updates (from file or defaults).
        keyword_taxonomy: Allowed keywords per category (domain, concept, time_signal).
        grok_models: Fallback Grok models to try.
    """

    mode: Literal["rss", "exa"] = "rss"
    topic: str = "energy climate macro policy"
    since_days: int = 2
    articles_per_feed: int = 3
    exa_num_results: int = 5
    relevance_min: int = 7
    content_snippet_length: int = 1000
    summary_max_chars: int = 2000
    keywords_max: int = 10
    discover_num_feeds: int = 8
    rss_feeds: list[str] = field(default_factory=load_feeds)
    cluster_tags: list[str] = field(default_factory=load_cluster_tags)
    keyword_taxonomy: dict[str, list[str]] = field(default_factory=load_keywords)
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


def _normalize_url(url: str) -> str:
    """Normalize URL for deduplication (strip fragment, query, trailing slash)."""
    u = (url or "").strip().lower()
    if "#" in u:
        u = u.split("#")[0]
    if "?" in u:
        u = u.split("?")[0]
    return u.rstrip("/")


def fetch_exa_articles(
    topic: str,
    exa_api_key: str,
    num_results: int = 5,
    since_days: Optional[int] = None,
) -> list[ArticleSchema]:
    """Fetch articles from Exa semantic search, return list conforming to ArticleSchema."""
    try:
        from exa_py import Exa
    except ImportError:
        print("Error: exa-py not installed. Run: pip install exa-py")
        return []

    exa = Exa(api_key=exa_api_key)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    search_kwargs: dict = {"num_results": num_results, "contents": {"highlights": True}}
    if since_days is not None and since_days > 0:
        start_dt = now - timedelta(days=since_days)
        search_kwargs["start_published_date"] = start_dt.strftime("%Y-%m-%d")

    try:
        response = exa.search(topic, **search_kwargs)
    except Exception as e:
        print(f"Warning: Exa API error: {e}")
        return []

    articles: list[ArticleSchema] = []
    seen_urls: set[str] = set()
    for result in response.results:
        url = getattr(result, "url", "") or ""
        if not url:
            continue
        norm = _normalize_url(url)
        if norm in seen_urls:
            continue
        seen_urls.add(norm)
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
    """Fetch articles based on mode (rss or exa)."""
    if config.mode == "rss":
        return fetch_rss_articles(config)
    return fetch_exa_articles(
        config.topic,
        exa_api_key,
        num_results=config.exa_num_results,
        since_days=config.since_days,
    )


def _strip_code_fences(raw: str) -> str:
    """Strip a leading/trailing markdown code fence from an LLM response, if present."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return raw.strip()


def _grok_complete(
    client: OpenAI,
    models: list[str],
    system_prompt: str,
    user_prompt: str,
    label: str = "",
) -> str | None:
    """Call Grok with model fallback. Returns the message content, or None on failure."""
    suffix = f" for '{label}'" if label else ""
    for model in models:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err_str = str(e).lower()
            if "model" in err_str or "not found" in err_str:
                print(f"Grok model {model} unavailable, trying fallback: {e}")
                continue
            print(f"Grok API error{suffix}: {e}")
            break
    return None


def suggest_feeds(
    topic: str,
    grok_api_key: str,
    config: Optional[RSSConfig] = None,
) -> list[dict[str, Any]]:
    """Ask Grok to suggest high-quality RSS/Atom feeds for a subject.

    Returns a list of dicts with keys: url, name, reason, already_present.
    Feeds already in the configured feed list are flagged via already_present.
    """
    cfg = config or DEFAULT_CONFIG
    client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1")
    existing = {_normalize_url(u) for u in cfg.rss_feeds}

    system_prompt = (
        "You are a research librarian who curates high-quality RSS/Atom feeds. "
        "You recommend only reputable, actively-maintained sources whose feed endpoints "
        "actually work (the RSS/Atom URL, not a homepage or article page). Prefer primary "
        "sources, established publications, and respected domain experts over content farms "
        "or SEO blogs."
    )
    user_prompt = f"""Suggest up to {cfg.discover_num_feeds} high-quality RSS or Atom feeds for the subject: "{topic}".

Return ONLY a valid JSON object. No preamble, no markdown fences, no trailing commentary:

{{
  "feeds": [
    {{"name": "Source name", "url": "https://example.com/feed.xml", "reason": "one short sentence on why it is high quality and relevant"}}
  ]
}}

Rules:
- "url" must be a direct RSS/Atom feed endpoint, not a homepage or article URL.
- Only include sources you are confident publish a working feed.
- Prefer reputable, primary, or expert sources; avoid low-quality aggregators and content farms.
- Cover a range of perspectives within the subject where possible."""

    content = _grok_complete(
        client, cfg.grok_models, system_prompt, user_prompt, label=f"feed discovery: {topic}"
    )
    if not content:
        return []

    try:
        data = json.loads(_strip_code_fences(content))
    except json.JSONDecodeError as e:
        print(f"Warning: could not parse feed suggestions: {e}")
        return []

    raw_feeds = data.get("feeds") if isinstance(data, dict) else data
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_feeds or []:
        if isinstance(item, str):
            url, name, reason = item, "", ""
        elif isinstance(item, dict):
            url = (item.get("url") or item.get("feed_url") or "").strip()
            name = (item.get("name") or item.get("title") or "").strip()
            reason = (item.get("reason") or "").strip()
        else:
            continue
        if not url:
            continue
        norm = _normalize_url(url)
        if norm in seen:
            continue
        seen.add(norm)
        results.append(
            {
                "url": url,
                "name": name,
                "reason": reason,
                "already_present": norm in existing,
            }
        )
    return results


def validate_feed_url(url: str) -> tuple[bool, str]:
    """Check that a URL resolves to a parseable feed with at least one entry.

    Returns (is_valid, detail). Network/parse errors are reported as invalid.
    """
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        return False, f"parse error: {e}"
    entries = getattr(feed, "entries", None)
    if not entries:
        return False, "no entries found (not a usable feed)"
    feed_meta = getattr(feed, "feed", None)
    title = str(feed_meta.get("title", "")).strip() if isinstance(feed_meta, dict) else ""
    count = len(entries)
    return True, f"{title} ({count} entries)" if title else f"{count} entries"


def discover_feeds(
    topic: str,
    grok_api_key: str,
    config: Optional[RSSConfig] = None,
    feeds_path: Optional[str] = None,
    validate: bool = True,
    assume_yes: bool = False,
) -> list[str]:
    """Suggest feeds for a subject, confirm with the user, and add them to the feed bank.

    Args:
        topic: Subject to find feeds for.
        grok_api_key: xAI API key for Grok.
        config: Optional RSSConfig; uses DEFAULT_CONFIG if not provided.
        feeds_path: Optional override for the feeds file path.
        validate: When True, live-check each suggested feed before offering it.
        assume_yes: When True, auto-confirm every valid, non-duplicate suggestion.

    Returns the list of feed URLs added to the feed file.
    """
    cfg = config or DEFAULT_CONFIG
    if not topic.strip():
        print("No subject provided; nothing to discover.")
        return []

    print(f"\nAsking Grok for high-quality RSS feeds on: {topic!r}\n")
    suggestions = suggest_feeds(topic, grok_api_key, cfg)
    if not suggestions:
        print("No feed suggestions returned.")
        return []

    confirmed: list[str] = []
    for i, s in enumerate(suggestions, 1):
        header = s["name"] or s["url"]
        print(f"[{i}] {header}")
        print(f"    {s['url']}")
        if s["reason"]:
            print(f"    why: {s['reason']}")

        if s["already_present"]:
            print("    (already in your feed list — skipping)\n")
            continue

        if validate:
            ok, detail = validate_feed_url(s["url"])
            print(f"    {'✓ valid' if ok else '✗ invalid'}: {detail}")
            if not ok:
                print("    (skipped: failed validation)\n")
                continue

        if assume_yes:
            confirmed.append(s["url"])
            print("    added (auto-confirmed)\n")
            continue

        ans = input("    Add this feed? [y/N]: ").strip().lower()
        if ans in ("y", "yes"):
            confirmed.append(s["url"])
        print()

    if not confirmed:
        print("No feeds added.")
        return []

    added = append_feeds(confirmed, config_path=feeds_path, header=f"Discovered for: {topic}")
    if added:
        print(f"\nAdded {len(added)} feed(s) to {feeds_file_path(feeds_path)}:")
        for url in added:
            print(f"  + {url}")
        print("\nThese will be pulled automatically on future RSS runs.")
    else:
        print("\nNo new feeds added (all selected feeds were already present).")
    return added


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
        exa_api_key: Exa API key (required when mode is exa).
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

        # Fetch schema to get existing Cluster_Tag and Keywords options; merge with config
        db_schema = notion.databases.retrieve(db_id)
        cluster_prop = db_schema.get("properties", {}).get("Cluster_Tag", {})
        select_opts = cluster_prop.get("select", {}).get("options", [])
        existing_tags = [o["name"] for o in select_opts if o.get("name")]
        allowed_tags = list(dict.fromkeys(cfg.cluster_tags + existing_tags))

        keywords_prop = db_schema.get("properties", {}).get("Keywords", {})
        multi_opts = keywords_prop.get("multi_select", {}).get("options", [])
        existing_keyword_names = [o["name"] for o in multi_opts if o.get("name")]

        def _merge_keyword_category(category: str) -> list[str]:
            config_vals = cfg.keyword_taxonomy.get(category, [])
            notion_vals = [
                n.split(":", 1)[1]
                for n in existing_keyword_names
                if n.startswith(category + ":")
            ]
            return list(dict.fromkeys(config_vals + notion_vals))

        allowed_domain = _merge_keyword_category("domain")
        allowed_concept = _merge_keyword_category("concept")
        allowed_time_signal = _merge_keyword_category("time_signal")

        # ---------------------------------------------------------------------
        # Fetch articles (RSS or Exa)
        # ---------------------------------------------------------------------
        articles = fetch_articles(cfg, exa_api_key=exa_api_key)
        mode_label = "RSS" if cfg.mode == "rss" else "Exa"
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

  "situation_tag": "Pick EXACTLY ONE from this list for every article: {allowed_cluster_tags}. Assign the best-matching theme. Prefer reusing an existing tag when the article clearly fits. Use 'other' only when none of the listed themes apply.",

  "keywords": {{
    "domain": ["pick from: {allowed_domain}"],
    "concept": ["pick from: {allowed_concept}"],
    "entity": ["named organisations, instruments, standards, treaties — only if central to the article; may add new values"],
    "region": ["only if geography is material to the mechanism; may add new values"],
    "time_signal": ["pick exactly one from: {allowed_time_signal}"]
  }},

  "relevance_score": integer 0-10 where: 10 = core mechanism explained or significant situation update, 5 = useful context or corroborating data point, 1 = peripheral or repetitive news item,

  "trunk_branch": "One sentence. Format: '[trunk concept] → [what this article concretely illustrates or updates]'. For situation-updates, include a timestamp signal where possible. For concept-explainers: 'Monetary transmission mechanism → how central bank rate changes propagate to mortgage rates with a 6-12 month lag.' Factual, dateable where possible, no opinion, no forecast."
}}"""

        for article in articles:
            content_snippet = (article["text"] or "")[: cfg.content_snippet_length]
            article_text = f"Title: {article['title']}\n\nContent: {content_snippet}"
            user_prompt = user_prompt_template.format(
                article_text=article_text,
                allowed_cluster_tags=", ".join(allowed_tags),
                allowed_domain=", ".join(allowed_domain),
                allowed_concept=", ".join(allowed_concept),
                allowed_time_signal=", ".join(allowed_time_signal),
            )

            content = _grok_complete(
                client, cfg.grok_models, system_prompt, user_prompt, label=article["title"]
            )
            if content is None:
                continue

            # Parse JSON with fallback on failure
            try:
                processed = json.loads(_strip_code_fences(content))
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

            # Post-process: flatten keywords with type prefix and filter controlled categories
            keywords_obj = processed.get("keywords") or {}
            flattened: list[str] = []
            controlled: dict[str, list[str]] = {
                "domain": allowed_domain,
                "concept": allowed_concept,
                "time_signal": allowed_time_signal,
            }
            for prefix, keys in [
                ("domain", keywords_obj.get("domain", [])),
                ("concept", keywords_obj.get("concept", [])),
                ("entity", keywords_obj.get("entity", [])),
                ("region", keywords_obj.get("region", [])),
                ("time_signal", keywords_obj.get("time_signal", [])),
            ]:
                for k in keys if isinstance(keys, list) else []:
                    val = str(k).strip()
                    if not val:
                        continue
                    full = f"{prefix}:{val}" if not val.startswith(prefix + ":") else val
                    val_to_check = val.split(":", 1)[1] if ":" in val else val
                    if prefix in controlled and val_to_check not in controlled[prefix]:
                        continue
                    flattened.append(full)
            flattened = flattened[: cfg.keywords_max]

            summary = (processed.get("summary") or "")[: cfg.summary_max_chars]
            entry_type = processed.get("entry_type") or "unknown"
            situation_tag = processed.get("situation_tag")
            if situation_tag and situation_tag not in allowed_tags:
                situation_tag = "other" if "other" in allowed_tags else None
            if not situation_tag and "other" in allowed_tags:
                situation_tag = "other"  # Ensure all entries get a Cluster_Tag
            relevance_score = int(processed.get("relevance_score", 0))
            trunk_branch = (processed.get("trunk_branch") or "").strip()

            # Exa: only upsert high-relevance articles
            if article["source_mode"] == "exa" and relevance_score < cfg.relevance_min:
                print(
                    f"Skipped (relevance {relevance_score} < {cfg.relevance_min}): {article['title']}"
                )
                continue

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
                    update_props: dict = {
                        "Summary": {"rich_text": [{"text": {"content": summary}}]},
                        "Keywords": {"multi_select": [{"name": k} for k in flattened]},
                        "Trunk_Branch": {"rich_text": [{"text": {"content": trunk_branch}}]},
                        "Relevance_Score": {"number": relevance_score},
                        "Last_Updated": {"date": {"start": now_iso}},
                    }
                    if situation_tag:
                        update_props["Cluster_Tag"] = {"select": {"name": situation_tag}}
                    notion.pages.update(page_id=page_id, properties=update_props)
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
        choices=["rss", "exa"],
        default=os.environ.get("RSS_MODE", "rss"),
        help="Retrieval mode: rss (default, primary pipeline) or exa (targeted discovery)",
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
        help="Only include articles from last N days (RSS and Exa, default: 2)",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Prompt for mode, topic, and since-days interactively",
    )
    parser.add_argument(
        "--discover-feeds",
        action="store_true",
        help="Suggest high-quality RSS feeds for a subject (--topic), confirm, and add them to the feed list",
    )
    parser.add_argument(
        "--num-feeds",
        type=int,
        default=DEFAULT_CONFIG.discover_num_feeds,
        help="How many feeds to suggest in --discover-feeds (default: 8)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Auto-confirm all valid suggested feeds in --discover-feeds (skip per-feed prompts)",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip live validation of suggested feed URLs in --discover-feeds",
    )
    args = parser.parse_args()

    if args.list_databases:
        if not notion_token:
            print("Error: Set NOTION_TOKEN in .env to list databases")
            raise SystemExit(1)
        list_notion_databases(notion_token)
        raise SystemExit(0)

    # Feed discovery: prompt a subject, get LLM feed suggestions, confirm, add to feed list.
    # Only needs GROK_API_KEY (no Notion access required).
    if args.discover_feeds:
        if not grok_api_key:
            print("Error: Set GROK_API_KEY in .env to discover feeds")
            raise SystemExit(1)
        topic_in = args.topic
        if not args.yes:
            entered = input(f"Subject to find feeds for [{topic_in}]: ").strip()
            topic_in = entered or topic_in
        discover_config = RSSConfig(discover_num_feeds=args.num_feeds)
        try:
            discover_feeds(
                topic_in,
                grok_api_key,
                config=discover_config,
                validate=not args.no_validate,
                assume_yes=args.yes,
            )
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            raise SystemExit(130)
        raise SystemExit(0)

    if args.interactive:
        print("\n--- RSS-to-Notion (interactive) ---\n")
        mode_in = input("Mode (rss/exa/discover) [rss]: ").strip().lower() or "rss"
        if mode_in == "discover":
            if not grok_api_key:
                print("Error: Set GROK_API_KEY in .env to discover feeds")
                raise SystemExit(1)
            topic_in = input("Subject to find feeds for: ").strip() or args.topic
            discover_config = RSSConfig(discover_num_feeds=args.num_feeds)
            try:
                discover_feeds(
                    topic_in,
                    grok_api_key,
                    config=discover_config,
                    validate=not args.no_validate,
                )
            except KeyboardInterrupt:
                print("\nInterrupted by user.")
                raise SystemExit(130)
            raise SystemExit(0)
        if mode_in not in ("rss", "exa"):
            mode_in = "rss"
        if mode_in == "exa":
            topic_in = input("Topic (e.g. iran war and oil price): ").strip()
            if not topic_in:
                topic_in = args.topic
        else:
            topic_in = args.topic
        since_days_in_str = input("Since days [2]: ").strip()
        since_days_in = (
            int(since_days_in_str) if since_days_in_str.isdigit() else args.since_days
        )
        if mode_in == "exa" and not exa_api_key:
            print(
                "Error: EXA_API_KEY required when --mode is exa. "
                "Add EXA_API_KEY to your .env file."
            )
            raise SystemExit(1)
        config = RSSConfig(
            mode=mode_in,
            topic=topic_in,
            since_days=since_days_in,
        )
        if mode_in == "rss":
            print(f"\n[Running RSS feeds (last {since_days_in} days)...]\n")
        else:
            print(f"\nRunning: mode={mode_in}, topic={topic_in!r}, since_days={since_days_in}\n")
    else:
        if args.mode == "exa" and not exa_api_key:
            print(
                "Error: EXA_API_KEY required when --mode is exa. "
                "Add EXA_API_KEY to your .env file."
            )
            raise SystemExit(1)
        config = RSSConfig(
            mode=args.mode,
            topic=args.topic,
            since_days=args.since_days,
        )

    # The Notion pipeline needs all three credentials (discover/list paths exit earlier).
    if not all([notion_token, database_id, grok_api_key]):
        print(
            "Error: Set NOTION_TOKEN, NOTION_DATABASE_ID, and GROK_API_KEY in .env "
            "(copy .env.example to .env and fill in your values)"
        )
        raise SystemExit(1)

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
