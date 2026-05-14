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
#
# Prefer ``rg`` when available (faster, .gitignore-aware), fall back to
# ``grep -RnE`` when it isn't. The previous revision piped ``rg ... ||
# true`` to swallow rg's exit code, which silently masked a missing rg
# binary as a zero-hit success — making the guard always pass on
# environments that lack ripgrep. Both branches below distinguish
# "tool missing" (exit non-zero) from "ran fine but no matches" (exit
# 0 with empty stdout).
hits=""
if command -v rg >/dev/null 2>&1; then
    # ``rg`` exit codes: 0 = matches found, 1 = no matches (success for
    # our purpose), >=2 = real error. Capture stdout into ``hits`` and
    # inspect the exit code explicitly.
    set +e
    hits="$(rg -n "${pattern}" apps/web/src/ \
        --glob '!**/__tests__/**' \
        --glob '!**/lib/types/**')"
    rc=$?
    set -e
    if [[ ${rc} -ge 2 ]]; then
        echo "audit_browser_api_v1.sh: rg exited with ${rc} — aborting" >&2
        exit "${rc}"
    fi
elif command -v grep >/dev/null 2>&1; then
    # ``grep -RnE`` exit codes: 0 = matches found, 1 = no matches, >=2 =
    # real error. The ``--exclude-dir`` flags mirror the rg ``!**/__tests__/**``
    # / ``!**/lib/types/**`` glob exceptions. ``-I`` skips binary files.
    set +e
    hits="$(grep -RnE -I \
        --exclude-dir=__tests__ \
        --exclude-dir=types \
        "${pattern}" apps/web/src/)"
    rc=$?
    set -e
    if [[ ${rc} -ge 2 ]]; then
        echo "audit_browser_api_v1.sh: grep exited with ${rc} — aborting" >&2
        exit "${rc}"
    fi
else
    echo "audit_browser_api_v1.sh: neither rg nor grep is available on PATH" >&2
    exit 2
fi

if [[ -n "${hits}" ]]; then
    echo "found ${pattern} hits in apps/web/src/:" >&2
    echo "${hits}" >&2
    echo "" >&2
    echo "These must be migrated to /web-api/v1/${resource} before this PR can merge." >&2
    exit 1
fi

echo "no /api/v1/${resource} hits in apps/web/src/ (outside documented exceptions)"
exit 0
