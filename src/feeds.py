"""RSS feed configuration. Load from file or use built-in defaults."""
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
