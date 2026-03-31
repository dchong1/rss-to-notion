#!/usr/bin/env bash
# Add repository topics via GitHub CLI. Requires: gh auth login
set -euo pipefail
REPO="${1:-dchong1/rss-to-notion}"

topics=(
  python notion rss automation knowledge-management llm grok xai exa notion-api
)

args=()
for t in "${topics[@]}"; do
  args+=(--add-topic "$t")
done

exec gh repo edit "$REPO" "${args[@]}"
