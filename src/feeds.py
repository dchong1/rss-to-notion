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


def load_feeds(config_path: str | None = None) -> list[str]:
    """Load feed URLs from file. Falls back to DEFAULT_FEEDS if file missing/invalid."""
    path = config_path or os.environ.get("RSS_FEEDS_FILE")
    if not path:
        path = os.path.join(os.path.dirname(__file__), "..", "config", "rss_feeds.txt")
    if not os.path.isfile(path):
        return list(DEFAULT_FEEDS)
    feeds = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                feeds.append(line)
    return feeds if feeds else list(DEFAULT_FEEDS)


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
