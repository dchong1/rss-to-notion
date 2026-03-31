#!/usr/bin/env bash
# Run follow-ups: set repository topics + create GitHub Release v0.1.0 (if missing).
# Requires one of:
#   - GITHUB_TOKEN or GH_TOKEN with repo scope (classic: repo or public_repo); fine-grained: Contents R/W, Metadata R/W, and Administration R/W for topics.
# Or use GitHub CLI after `gh auth login` instead:
#   ./scripts/add-github-topics.sh && gh release create v0.1.0 --title "rss-to-notion v0.1.0" --notes-file docs/RELEASE-v0.1.0-body.md
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_FULL="${1:-dchong1/rss-to-notion}"
TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"

if [[ -z "$TOKEN" ]]; then
  echo "No GITHUB_TOKEN or GH_TOKEN in environment." >&2
  echo "Create a token at https://github.com/settings/tokens then run:" >&2
  echo "  export GITHUB_TOKEN=ghp_..." >&2
  echo "  $0" >&2
  exit 1
fi

BODY_FILE="$ROOT/docs/RELEASE-v0.1.0-body.md"
if [[ ! -f "$BODY_FILE" ]]; then
  echo "Missing $BODY_FILE" >&2
  exit 1
fi

api() {
  curl -sS -f -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$@"
}

echo "Setting topics on ${REPO_FULL}..."
api -X PUT "https://api.github.com/repos/${REPO_FULL}/topics" \
  -d '{"names":["python","notion","rss","automation","knowledge-management","llm","grok","xai","exa","notion-api"]}' >/dev/null
echo "Topics updated."

if api "https://api.github.com/repos/${REPO_FULL}/releases/tags/v0.1.0" >/dev/null 2>&1; then
  echo "Release v0.1.0 already exists — skipping create."
  exit 0
fi

BODY_JSON=$(jq -Rs '{"tag_name":"v0.1.0","name":"rss-to-notion v0.1.0","body":.}' <"$BODY_FILE")
echo "Creating release v0.1.0..."
api -X POST "https://api.github.com/repos/${REPO_FULL}/releases" \
  -d "$BODY_JSON" | jq -r '.html_url // .message // .'
echo "Done."
