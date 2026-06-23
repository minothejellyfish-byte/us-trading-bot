#!/bin/bash
# US Git Auto-Commit — mirrors TASI git commit pattern
# Commits all changes to the US trading bot repo with timestamp
# Runs via cron every 30 minutes during market hours

set -e

REPO_DIR="/home/mino/us-exec"
LOG_FILE="$REPO_DIR/logs/git_commit.log"

cd "$REPO_DIR"

# Ensure log dir exists
mkdir -p "$REPO_DIR/logs"

# Skip if no changes
if git diff --quiet && [ -z "$(git status --porcelain)" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') — Nothing to commit" >> "$LOG_FILE"
    exit 0
fi

# Generate commit message
BRANCH=$(git branch --show-current)
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')
CHANGED_FILES=$(git status --short | wc -l)
COMMIT_MSG="Auto-commit: $TIMESTAMP ($CHANGED_FILES files changed)"

# Stage all (respect .gitignore)
git add -A

# Commit
git commit -m "$COMMIT_MSG" --quiet >> "$LOG_FILE" 2>&1 || true

# Push (if remote exists)
if git remote get-url origin >/dev/null 2>&1; then
    git push origin "$BRANCH" --quiet >> "$LOG_FILE" 2>&1 && \
        echo "$(date '+%Y-%m-%d %H:%M:%S') — ✅ Pushed $CHANGED_FILES files" >> "$LOG_FILE" || \
        echo "$(date '+%Y-%m-%d %H:%M:%S') — ⚠️ Push failed (check credentials)" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') — ✅ Committed $CHANGED_FILES files (no remote)" >> "$LOG_FILE"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') — Done" >> "$LOG_FILE"
