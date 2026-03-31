## rss-to-notion v0.1.0

First public milestone: RSS and Exa pipelines to a Notion database, with Grok summarisation and configurable keywords / cluster tags.

### What it does

- **RSS mode (default):** Pull from `config/rss_feeds.txt`, filter by `--since-days`, upsert into Notion.
- **Exa mode:** Semantic search for a `--topic`, relevance threshold for inserts (see README).
- **LLM layer:** Neutral summaries and tagging (keywords + cluster tag + trunk/branch fields) aligned with your taxonomy files.
- **Automation:** Optional daily run via GitHub Actions (RSS; secrets documented in README).

### Requirements

- Python **3.12**
- `pip install -r requirements.txt`
- Notion integration, database with the **13 properties** listed in [README — Notion schema](https://github.com/dchong1/rss-to-notion/blob/main/README.md#notion-schema)
- `.env` from `.env.example`: `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `GROK_API_KEY`; for Exa mode, `EXA_API_KEY`

### Demo

- Inline GIF and full recording: [README — Demo](https://github.com/dchong1/rss-to-notion#demo) (`assets/demo.gif`, `assets/demo.mp4`).

### Docs

- [README](https://github.com/dchong1/rss-to-notion/blob/main/README.md)
- [MIT License](https://github.com/dchong1/rss-to-notion/blob/main/LICENSE)
