"""RSS feed and cluster tag configuration. Load from file or use built-in defaults."""
import os

# Built-in fallback when config file is missing
DEFAULT_FEEDS = [
    "https://www.technologyreview.com/feed/",
    "https://read.deeplearning.ai/the-batch/rss",
    "https://towardsdatascience.com/feed",
    "https://a16z.com/feed/",
    "https://www.wired.com/feed/rss",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://hnrss.org/frontpage",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://feeds.bloomberg.com/economics/news.rss",
    "https://feeds.bloomberg.com/technology/news.rss",
    "https://feeds.bloomberg.com/green/news.rss",
    "https://feeds.bloomberg.com/politics/news.rss",
    "https://feeds.bloomberg.com/business/news.rss",
    "https://feeds.bloomberg.com/wealth/news.rss",
    "https://feeds.bloomberg.com/industries/news.rss",
    "https://feeds.bloomberg.com/bview/news.rss",
]

# Keyword taxonomy for domain, concept, time_signal (controlled vocabulary)
DEFAULT_KEYWORD_TAXONOMY: dict[str, list[str]] = {
    "domain": [
        "fiscal-policy",
        "energy-storage",
        "energy-geopolitics",
        "monetary-policy",
        "semiconductor-supply-chain",
        "tech-regulation",
        "private-markets",
        "climate-policy",
        "ev-batteries",
        "data-infrastructure",
        "consumer-finance",
        "other",
    ],
    "concept": [
        "crowding-out",
        "debt-monetisation",
        "learning-curves",
        "transmission-mechanism",
        "supply-demand",
        "regulatory-arbitrage",
        "currency-effects",
        "other",
    ],
    "time_signal": [
        "structural-trend",
        "cyclical",
        "near-term-event",
        "historical-case",
    ],
}

# Coarse cluster tags for situation-updates (approach 2+4: broad themes, reuse over time)
DEFAULT_CLUSTER_TAGS = [
    "energy-geopolitics",
    "us-fiscal",
    "monetary-policy",
    "climate-extremes",
    "tech-regulation",
    "private-markets",
    "china-geopolitics",
    "semiconductor-tech",
    "ev-clean-tech",
    "consumer-finance",
    "data-software",
    "other",
]


def feeds_file_path(config_path: str | None = None) -> str:
    """Resolve the path to the RSS feeds config file (explicit arg, env var, or default)."""
    path = config_path or os.environ.get("RSS_FEEDS_FILE")
    if not path:
        path = os.path.join(os.path.dirname(__file__), "..", "config", "rss_feeds.txt")
    return path


def _normalize_feed_url(url: str) -> str:
    """Normalize a feed URL for de-duplication (lowercase, strip trailing slash)."""
    return (url or "").strip().lower().rstrip("/")


def load_feeds(config_path: str | None = None) -> list[str]:
    """Load feed URLs from file. Falls back to DEFAULT_FEEDS if file missing/invalid."""
    path = feeds_file_path(config_path)
    if not os.path.isfile(path):
        return list(DEFAULT_FEEDS)
    feeds = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                feeds.append(line)
    return feeds if feeds else list(DEFAULT_FEEDS)


def append_feeds(
    new_feeds: list[str],
    config_path: str | None = None,
    header: str | None = None,
) -> list[str]:
    """Append feed URLs to the feeds file, skipping any already present.

    De-duplicates against existing feeds (and within new_feeds) using a normalized
    comparison. Creates the file if missing. Returns the feeds actually added.
    """
    path = feeds_file_path(config_path)
    existing = load_feeds(path) if os.path.isfile(path) else []
    seen = {_normalize_feed_url(u) for u in existing}

    to_add: list[str] = []
    for url in new_feeds:
        url = (url or "").strip()
        if not url:
            continue
        norm = _normalize_feed_url(url)
        if norm in seen:
            continue
        seen.add(norm)
        to_add.append(url)

    if not to_add:
        return []

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    needs_newline = os.path.isfile(path) and os.path.getsize(path) > 0
    if needs_newline:
        with open(path) as f:
            needs_newline = not f.read().endswith("\n")
    with open(path, "a") as f:
        if needs_newline:
            f.write("\n")
        if header:
            f.write(f"\n# {header}\n")
        for url in to_add:
            f.write(url + "\n")
    return to_add


def load_cluster_tags(config_path: str | None = None) -> list[str]:
    """Load cluster tags from file. Falls back to DEFAULT_CLUSTER_TAGS if file missing/invalid."""
    path = config_path or os.environ.get("RSS_CLUSTER_TAGS_FILE")
    if not path:
        path = os.path.join(os.path.dirname(__file__), "..", "config", "cluster_tags.txt")
    if not os.path.isfile(path):
        return list(DEFAULT_CLUSTER_TAGS)
    tags = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                tags.append(line)
    return tags if tags else list(DEFAULT_CLUSTER_TAGS)


def load_keywords(config_path: str | None = None) -> dict[str, list[str]]:
    """Load keyword taxonomy from sectioned file. Falls back to DEFAULT_KEYWORD_TAXONOMY if file missing/invalid."""
    path = config_path or os.environ.get("RSS_KEYWORDS_FILE")
    if not path:
        path = os.path.join(os.path.dirname(__file__), "..", "config", "keywords.txt")
    result: dict[str, list[str]] = {
        "domain": [],
        "concept": [],
        "time_signal": [],
    }
    if not os.path.isfile(path):
        return {k: list(v) for k, v in DEFAULT_KEYWORD_TAXONOMY.items()}
    current_section: str | None = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].lower()
                if section in result:
                    current_section = section
                else:
                    current_section = None
                continue
            if current_section and current_section in result:
                result[current_section].append(line)
    for key in result:
        if not result[key]:
            result[key] = list(DEFAULT_KEYWORD_TAXONOMY.get(key, []))
    return result
