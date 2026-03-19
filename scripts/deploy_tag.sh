#!/usr/bin/env bash
set -euo pipefail

TAG="${1:-}"

if [[ -z "$TAG" ]]; then
  echo "Usage: $0 <tag>" >&2
  exit 1
fi

if ! git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "Tag not found: $TAG" >&2
  exit 1
fi

git fetch --tags --prune
git checkout "$TAG"
docker compose pull || true
docker compose up -d --build

echo "Deployment completed for tag: $TAG"
