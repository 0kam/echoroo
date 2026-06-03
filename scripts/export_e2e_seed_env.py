#!/usr/bin/env python3
"""Export the seed_e2e_permissions JSON ``env`` block to ``$GITHUB_ENV``.

WS7 Phase 4 (e2e-full CI job): ``echoroo.scripts.seed_e2e_permissions
--confirm`` prints a JSON document to stdout whose top-level ``env`` key is a
flat ``{NAME: value}`` mapping of every fixture identifier the Playwright e2e
specs read (``E2E_OWNER_EMAIL``, ``E2E_OWNER_TOTP_SECRET``,
``E2E_PUBLIC_PROJECT_ID``, ``E2E_RESTRICTED_PROJECT_ID``, the per-role API
keys, …).

This helper reads that JSON from a file (the CI step captures seed stdout to a
file) and appends each ``env`` entry to the GitHub Actions ``$GITHUB_ENV`` file
so later steps — and the Playwright process — see the values as environment
variables.

Design notes:
  * Pure stdlib (json / os / argparse / pathlib / sys); no app deps required.
  * Multi-line values are written using the GitHub Actions heredoc delimiter
    syntax so a value containing a newline cannot break the env file. The
    fixture values are all single-line today, but the heredoc form is robust.
  * A random delimiter token guards against the (astronomically unlikely)
    case where a value contains the literal delimiter string.
  * Keys are validated to match ``[A-Za-z_][A-Za-z0-9_]*`` so a malformed seed
    payload cannot inject arbitrary text into the env file.

Usage::

    python scripts/export_e2e_seed_env.py --seed-json /tmp/e2e-seed.json

``$GITHUB_ENV`` is read from the environment (GitHub Actions sets it). Pass
``--github-env <path>`` to override for local testing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from pathlib import Path

_VALID_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_e2e_seed_env",
        description=(
            "Append the seed_e2e_permissions JSON 'env' block to $GITHUB_ENV "
            "so Playwright e2e specs can read the seeded fixture identifiers."
        ),
    )
    parser.add_argument(
        "--seed-json",
        required=True,
        help="Path to the captured seed_e2e_permissions JSON stdout.",
    )
    parser.add_argument(
        "--github-env",
        default=os.environ.get("GITHUB_ENV"),
        help="Path to the GitHub Actions env file (defaults to $GITHUB_ENV).",
    )
    return parser


def _format_entry(name: str, value: str) -> str:
    """Return a GitHub Actions env-file heredoc block for one NAME=value pair."""
    delimiter = f"EOF_{secrets.token_hex(16)}"
    # Defensive: a value must never contain the random delimiter line.
    while f"\n{delimiter}\n" in f"\n{value}\n":  # pragma: no cover - astronomically unlikely
        delimiter = f"EOF_{secrets.token_hex(16)}"
    return f"{name}<<{delimiter}\n{value}\n{delimiter}\n"


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    github_env = args.github_env
    if not github_env:
        sys.stderr.write(
            "ERROR: $GITHUB_ENV is not set and --github-env was not provided.\n"
        )
        return 2

    seed_path = Path(args.seed_json)
    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: seed JSON file not found: {seed_path}\n")
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"ERROR: seed JSON is not valid JSON: {exc}\n")
        return 2

    env_block = payload.get("env")
    if not isinstance(env_block, dict):
        sys.stderr.write(
            "ERROR: seed JSON has no top-level 'env' object. "
            "Did seed_e2e_permissions change its output schema?\n"
        )
        return 2

    lines: list[str] = []
    exported: list[str] = []
    for name, value in env_block.items():
        if not isinstance(name, str) or not _VALID_KEY.match(name):
            sys.stderr.write(f"ERROR: refusing to export malformed env key: {name!r}\n")
            return 2
        lines.append(_format_entry(name, str(value)))
        exported.append(name)

    with Path(github_env).open("a", encoding="utf-8") as handle:
        handle.write("".join(lines))

    # Log the exported NAMES only (never the values — TOTP secrets / API keys
    # would otherwise leak into the public CI log).
    sys.stdout.write(
        f"Exported {len(exported)} E2E fixture env vars to $GITHUB_ENV:\n"
        + "\n".join(f"  - {name}" for name in sorted(exported))
        + "\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI invocation
    raise SystemExit(main())
