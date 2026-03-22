# RSS-to-Notion Knowledge Database

Personal knowledge database with two purposes: (1) accurate, first-principles understanding of how things work, and (2) longitudinal tracking of how real-world situations develop over time. Dual retrieval: RSS for trusted recurring sources, Exa for thematic discovery. LLM layer summarises neutrally and tags ontologically for future clustering.

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org)
[![Grok/xAI](https://img.shields.io/badge/Grok_API-xAI-orange)](https://x.ai)
[![Notion](https://img.shields.io/badge/Notion_API-green)](https://developers.notion.com)

## Architecture

```
RSS Feeds ──┐
            ├──► Python pipeline ──► Grok LLM ──► Notion Database
Exa Search ─┘
                              │
                   (summary, entry_type,
                    situation_tag, keywords,
                    trunk_branch, relevance_score)
```

## Notion Schema

Create a Notion database with these 13 properties:

| Property        | Notion Type  | Source                          |
|-----------------|--------------|----------------------------------|
| Title           | Title        | article title                    |
| Summary         | Rich text    | LLM summary                      |
| Keywords        | Multi-select | flattened keyword list           |
| Source_URL      | URL          | article url                      |
| Entry_Type      | Select       | LLM entry_type                   |
| Cluster_Tag     | Select       | LLM situation_tag (if non-null) |
| Trunk_Branch    | Rich text    | LLM trunk_branch                |
| Relevance_Score | Number       | LLM relevance_score              |
| Source_Mode     | Select       | "rss" or "exa"                   |
| Feed_Source     | Rich text    | feed name or "exa-search"        |
| Date_Published  | Date         | article published_date           |
| Date_Added      | Date         | utcnow() on first insert         |
| Last_Updated    | Date         | utcnow() on every upsert         |

Share the database with your Notion integration (••• → Add connections).

## Setup

1. **Copy `.env.example` to `.env`** and fill in your values:

   - `NOTION_TOKEN` – Notion integration token
   - `NOTION_DATABASE_ID` – Target database ID (32 chars) or full Notion database URL
   - `GROK_API_KEY` – xAI API key
   - `EXA_API_KEY` – Exa API key (required for `--mode exa` or `--mode both`)

2. **Install dependencies** (Python 3.12):

   ```bash
   pip install -r requirements.txt
   ```

3. **Create the Notion database** with the 13 properties above and share it with your integration.

## Usage

| Command                                                | What it does                    |
|--------------------------------------------------------|---------------------------------|
| `python src/rss_to_notion.py`                          | RSS mode, last 2 days, default topic |
| `python src/rss_to_notion.py --mode exa`               | Exa discovery, default topic    |
| `python src/rss_to_notion.py --mode both`              | RSS + Exa in parallel            |
| `python src/rss_to_notion.py --topic "X" --mode exa`   | Exa search on custom topic      |
| `python src/rss_to_notion.py --since-days 7`           | RSS, extend lookback window      |

```bash
# List Notion databases shared with your integration
python src/rss_to_notion.py --list-databases
```

## GitHub Actions

A daily workflow runs at 00:00 UTC (08:00 HKT). Configure these secrets:

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`
- `GROK_API_KEY`
- `EXA_API_KEY`
- `RSS_DEFAULT_TOPIC` (topic for Exa search, e.g. `"energy climate macro policy"`)

## Troubleshooting

- **Share the database**: Click ••• on the database page → Add connections → select your integration.
- **Database ID**: Run `python src/rss_to_notion.py --list-databases` to list databases.
- **Property names**: Must match exactly (e.g. `Source_URL`, not `Source URL`).
- **Exa mode**: Requires `EXA_API_KEY` in `.env`.

## Future explorations

- Exa `findSimilar` seeding: pass URL of a saved entry to discover related content
- Notion filtered view per `situation_tag` as a chronological tracker
- Weekly digest: new `trunk_branch` entries grouped by domain
- Obsidian export of `trunk_branch` entries as a concept graph

## Screenshots

1. CLI output
2. Notion table view filtered by Cluster_Tag
3. Single Notion entry showing all fields
