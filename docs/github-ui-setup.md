# GitHub UI: topics, pins, profile README

Steps you complete on [github.com](https://github.com) (not stored in git). If the [GitHub CLI](https://cli.github.com/) is installed and authenticated (`gh auth login`), you can add **topics** from your machine with [scripts/add-github-topics.sh](../scripts/add-github-topics.sh).

To set **topics** and create the **v0.1.0** GitHub Release in one shot, set `GITHUB_TOKEN` (or `GH_TOKEN`) and run [scripts/follow-up-github.sh](../scripts/follow-up-github.sh). You still need the browser for **profile pins** and an optional **profile README** repo (see below).

## Repository topics (discovery)

1. Open [dchong1/rss-to-notion](https://github.com/dchong1/rss-to-notion).
2. Click the **gear** icon next to **About** (or **Edit repository details**).
3. Under **Topics**, add tags such as: `python`, `notion`, `rss`, `automation`, `knowledge-management`, `llm`, `grok`, `xai`, `exa`, `notion-api` (use the subset you want; any non-empty set helps search).

## Pin this repository on your profile

1. Open your profile [github.com/dchong1](https://github.com/dchong1).
2. Click **Customize your pins**.
3. Select **rss-to-notion** (up to six repos can be pinned).

## Optional: profile README (`dchong1/dchong1`)

Create a public repository named **exactly** the same as your username (`dchong1`), add a `README.md` at the repo root. GitHub shows it above your pinned repos.

Example content you can copy and edit:

```markdown
Hi, I'm Dennis. I build small tools that connect research workflows to where I think.

**Shipped:** [rss-to-notion](https://github.com/dchong1/rss-to-notion) — RSS / Exa → Grok → structured Notion KB (Python).

More: [repositories](https://github.com/dchong1?tab=repositories).
```

Replace the intro line with your own voice; keep link(s) to what you want to showcase.
