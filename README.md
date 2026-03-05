# RSS-to-Notion Knowledge Database

Fetches recent articles from RSS feeds, processes them with the Grok API for summarization, keywords, and relevance scoring, then upserts results into a Notion database.

## Setup

1. **Copy `.env.example` to `.env`** and fill in your values:
   - `NOTION_TOKEN` – Notion integration token
   - `NOTION_DATABASE_ID` – Target database ID (32 chars) or full Notion database URL
   - `GROK_API_KEY` – xAI API key

2. **Install dependencies** (use the same Python you will run the script with):

   ```bash
   pip install -r requirements.txt
   ```

3. **Create a Notion database** with these properties:
   - **Title** (Title)
   - **Summary** (Rich text)
   - **Keywords** (Multi-select)
   - **Source URL** (URL)
   - **Date Added** (Date)
   - **Last Updated** (Date)

   Share the database with your Notion integration (••• → Add connections).

## Running

**Important:** Use the same Python interpreter that has the packages installed. If you see `ModuleNotFoundError: No module named 'feedparser'`, you are likely using a different Python (e.g. Homebrew vs conda).

```bash
# From project root
python src/rss_to_notion.py
```

### Config options

Parameters are in `RSSConfig` in `src/rss_to_notion.py`. Override via CLI or env:

| Option | CLI | Env | Default |
|--------|-----|-----|---------|
| Topic | `--topic "AI ethics"` | `RSS_TOPIC` | `vibe coding` |
| Days | `--since-days 14` | `RSS_SINCE_DAYS` | `3` |

```bash
python src/rss_to_notion.py --topic "AI ethics" --since-days 14
```

For other parameters (articles per feed, summary length, RSS feeds, etc.), edit `RSSConfig` or pass a custom config when calling `update_notion_with_rss()` programmatically. RSS feed URLs are defined in `RSS_FEEDS` at the top of the script.

**Alternative Python:** If you use Homebrew Python, install there first:

```bash
/opt/homebrew/bin/python3 -m pip install -r requirements.txt
/opt/homebrew/bin/python3 src/rss_to_notion.py
```

## Troubleshooting

### Python interpreter mismatch

Packages may be installed in one Python (e.g. conda) while the script runs with another (e.g. Homebrew). Verify which Python has the packages:

```bash
python -c "import feedparser; print('OK')"
/opt/homebrew/bin/python3 -c "import feedparser; print('OK')"
```

### .env not loaded

Ensure `.env` is in the project root and contains real values (no placeholders):

```bash
python -c "
from dotenv import load_dotenv
import os
load_dotenv('.env')
t = os.environ.get('NOTION_TOKEN','')
print('NOTION_TOKEN set:', bool(t) and not t.startswith('nsecret_'))
"
```

### Notion errors

- **Share the database**: Click ••• on the database page → Add connections → select your integration. If the database is inside a page, share that parent page too.
- **Find the correct database ID**: Run `python src/rss_to_notion.py --list-databases` to list databases shared with your integration
- Check that property names and types match exactly (Title, Summary, Keywords, Source URL, Date Added, Last Updated)
- `NOTION_DATABASE_ID` accepts the 32-char ID or the full Notion database URL

### Grok API errors

- Verify your xAI API key is valid
- The script tries `grok-4-fast-non-reasoning` first, then falls back to `grok-4-1-fast-non-reasoning` if the model is unavailable
