#!/usr/bin/env bash
set -euo pipefail
files=(full_cycle_state.json search_cycle_history.json search_delivery_receipts.json search_cycle_report.md internet_leads_state.json social_public_leads_state.json max_public_leads_state.json tender_state.json object_leads_state.json telegram_retry_queue.json)
for path in "${files[@]}"; do
  if [ -f "$path" ]; then git add -- "$path"; fi
done
if git diff --cached --quiet; then exit 0; fi
git config user.name "ecoflot-bot"
git config user.email "ecoflot-bot@users.noreply.github.com"
git commit -m "Persist verified ECOFLOT search state"
for attempt in 1 2 3; do
  git pull --rebase origin main
  if git push origin HEAD:main; then exit 0; fi
  sleep "$((attempt * 2))"
done
echo "STATE_PERSIST_FAILED: recovery artifact is retained" >&2
exit 1
