# Launch post drafts (copy-paste)

Repo: [https://github.com/dchong1/rss-to-notion](https://github.com/dchong1/rss-to-notion)  
Demo: [README with GIF](https://github.com/dchong1/rss-to-notion#demo) · [full MP4](https://github.com/dchong1/rss-to-notion/blob/main/assets/demo.mp4)

---

## Show HN (title + text)

**Title:** Show HN: RSS and semantic search into a structured Notion knowledge base (Python, Grok, Exa optional)

**Text:**

I wanted one place to track feeds and targeted research: neutral summaries, a small controlled vocabulary for keywords, and cluster tags for “how is this situation evolving?”—without losing URLs and dates.

rss-to-notion pulls from **RSS** (default) or **Exa** (topic search), runs **Grok** for summary + tags, and **upserts** into a Notion DB with a fixed 13-property schema. Taxonomy lives in plain text (`config/keywords.txt`, `config/cluster_tags.txt`). GitHub Actions can run RSS on a schedule.

MIT licensed. Python 3.12. README has setup, schema, and a screen recording.

**Repo:** https://github.com/dchong1/rss-to-notion

**Question for the room:** For personal KB tools, do you prefer rigid schemas like this, or free-form notes with search—and where do you draw the line?

---

## X / Twitter (short)

Built rss-to-notion: RSS or Exa → Grok → structured Notion (tags + keywords from config files). Daily RSS via Actions. Demo on the README. https://github.com/dchong1/rss-to-notion — curious if others use Notion as the sink for pipeline’d reading lists.

---

## Reddit / community variant (1 paragraph)

If you use Notion as a research inbox: this small Python tool ingests RSS (or Exa search on a topic), uses Grok to summarise and tag against your own keyword/cluster lists, and upserts rows into a fixed-schema database—useful if you like ontology-light structure without manual copy-paste. Open source (MIT), docs + GIF in the README: https://github.com/dchong1/rss-to-notion

---

After posting: monitor the thread for an hour and reply to questions—that usually matters more than the title for stars and useful feedback.
