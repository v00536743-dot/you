#!/usr/bin/env bash
# One command for all checks. Fails on any error.
#   bash tools/check_all.sh            offline: compile, schema, unit, integration, e2e, bad cases
#   SHORTS_NETWORK=1 bash tools/check_all.sh    + network tests (sites, YouTube, TTS service)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"

echo "== doctor"
"$PY" tools/shorts.py doctor > /dev/null || { "$PY" tools/shorts.py doctor; echo "doctor: missing required tools"; exit 1; }

echo "== compile"
"$PY" -m compileall -q tools tests

echo "== schema + example plans"
"$PY" tools/shorts.py validate schema/plan.example.json
"$PY" tools/shorts.py validate tests/fixtures/plan.offline.json
for f in examples/*.plan.json; do
  [ -e "$f" ] || continue
  "$PY" tools/shorts.py validate "$f"
done

echo "== no long dashes in user-facing skill texts"
if grep -rn $'\u2014\|\u2013' SKILL.md ROUTER.md reference/ tools/shortskit/meta/ 2>/dev/null; then
  echo "long dash found"; exit 1
fi

echo "== evals file"
"$PY" -c "import json;d=json.load(open('evals/cases.json'));assert len(d['cases'])>=10;print(len(d['cases']),'cases')"

echo "== tests"
"$PY" -m pytest tests -q -p no:cacheprovider
echo "ALL CHECKS PASSED"
