#!/usr/bin/env bash
# scripts/audit_browser_api_v1.sh — spec/009 per-PR static legacy-call guard.
#
# Usage:
#   bash scripts/audit_browser_api_v1.sh <resource>
# e.g.:
#   bash scripts/audit_browser_api_v1.sh projects
#   bash scripts/audit_browser_api_v1.sh admin/licenses
#
# Returns non-zero if any `/api/v1/<resource>` hit is found in
# apps/web/src/ outside the documented exception scopes (tests + types).
# Used as the per-PR static guard in spec/009 quickstart.md.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <resource>" >&2
    echo "  e.g. $0 projects" >&2
    echo "  e.g. $0 admin/licenses" >&2
    exit 2
fi

resource="$1"
pattern="/api/v1/${resource}"

# Find any matching call in apps/web/src/, excluding the documented test
# fixtures and type-only references (audited separately by PR J).
hits="$(rg -n "${pattern}" apps/web/src/ \
    --glob '!**/__tests__/**' \
    --glob '!**/lib/types/**' || true)"

if [[ -n "${hits}" ]]; then
    echo "❌ found ${pattern} hits in apps/web/src/:" >&2
    echo "${hits}" >&2
    echo "" >&2
    echo "These must be migrated to /web-api/v1/${resource} before this PR can merge." >&2
    exit 1
fi

echo "✅ no /api/v1/${resource} hits in apps/web/src/ (outside documented exceptions)"
exit 0
