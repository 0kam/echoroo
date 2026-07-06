#!/usr/bin/env python3
"""Download a handful of CC-licensed sample recordings from Xeno-canto.

This is a **developer convenience** script for people evaluating Echoroo who
do not have their own field recordings yet. It downloads a small set of short,
Creative-Commons-licensed bird recordings from the public `Xeno-canto`_ API
into a local folder, writes an attribution manifest alongside them, and prints
instructions for loading them into a project via the web UI.

No audio is vendored into the git repository — the files are fetched on demand
and land in a git-ignored output directory (``sample_data/`` by default).

.. _Xeno-canto: https://xeno-canto.org/

Licensing
---------
Every downloaded file keeps its original Creative Commons license. The generated
``manifest.json`` records, for each file, the Xeno-canto id, recordist, license,
species, and source page URL so the attribution obligations of the CC license
can be honoured. See ``docs/sample-data.md`` for the full attribution guidance.

Xeno-canto API key
------------------
The Xeno-canto API v3 requires an API key (free — create an account at
https://xeno-canto.org/ and copy the key from *Account → API key*). Provide it
via ``--api-key`` or the ``XENO_CANTO_API_KEY`` environment variable. This is
the same variable the Echoroo backend uses, so a configured ``.env`` already
works.

Usage
-----
::

    uv run python scripts/fetch_sample_data.py --api-key <KEY>
    # or, with XENO_CANTO_API_KEY exported:
    uv run python scripts/fetch_sample_data.py --count 8 --out sample_data

Exit codes
----------
0  — recordings + manifest downloaded successfully
1  — a Xeno-canto API / network / IO failure occurred
2  — invalid arguments or missing API key
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# Xeno-canto API v3 search endpoint (matches the backend integration —
# see ``echoroo/api/v1/xeno_canto.py::XENO_CANTO_BASE_URL``).
XENO_CANTO_BASE_URL = "https://xeno-canto.org/api/3/recordings"

# Per-file download ceiling. Short clips are a few hundred KB; this guards
# against accidentally pulling a multi-minute soundscape that blows the
# "keep it small" budget.
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

# Total download budget across all files (keeps the script well under 20 MB).
MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 20 MB

# Only accept files whose license is a Creative Commons "Attribution" family
# license (attribution required, redistribution permitted). We record the
# exact license per file in the manifest regardless. Matched case-insensitively
# against the ``lic`` URL returned by the API (e.g.
# ``//creativecommons.org/licenses/by-nc/4.0/``).
_ACCEPTED_LICENSE_FRAGMENTS: tuple[str, ...] = (
    "creativecommons.org/licenses/by/",
    "creativecommons.org/licenses/by-nc/",
    "creativecommons.org/licenses/by-sa/",
    "creativecommons.org/licenses/by-nc-sa/",
)

# Default search: high-quality, short bird recordings. Xeno-canto query tags:
#   grp:birds  — birds only
#   q:A        — highest quality rating
#   len:3-12   — 3 to 12 seconds (short, keeps files tiny)
DEFAULT_QUERY = "grp:birds q:A len:3-12"

_USER_AGENT = "Echoroo-sample-data/2.0 (+https://github.com/)"


class SampleDataError(Exception):
    """Typed failure raised for any recoverable Xeno-canto / IO problem."""


@dataclass(frozen=True)
class SampleRecording:
    """One downloaded recording plus the metadata needed for attribution."""

    xc_id: str
    file_name: str
    scientific_name: str
    common_name: str
    recordist: str
    license: str
    license_name: str
    quality: str
    length: str
    country: str
    source_url: str
    download_url: str
    bytes: int


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("XENO_CANTO_API_KEY"),
        help=(
            "Xeno-canto API key. Defaults to the XENO_CANTO_API_KEY "
            "environment variable."
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=6,
        help="Number of recordings to download (default: 6, max: 15).",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help=(
            "Xeno-canto search query in tag syntax "
            f"(default: {DEFAULT_QUERY!r})."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("sample_data"),
        help="Output directory for audio files + manifest (default: sample_data).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Per-request timeout in seconds (default: 30).",
    )
    return parser.parse_args(argv)


def _license_display_name(license_url: str) -> str:
    """Derive a short human-readable license label from a CC license URL."""
    lowered = license_url.lower()
    for slug, name in (
        ("by-nc-sa", "CC BY-NC-SA"),
        ("by-nc-nd", "CC BY-NC-ND"),
        ("by-nc", "CC BY-NC"),
        ("by-sa", "CC BY-SA"),
        ("by-nd", "CC BY-ND"),
        ("/by/", "CC BY"),
    ):
        if slug in lowered:
            return name
    return license_url or "unknown"


def _is_accepted_license(license_url: str) -> bool:
    lowered = license_url.lower()
    return any(frag in lowered for frag in _ACCEPTED_LICENSE_FRAGMENTS)


def _normalize_url(raw: str) -> str:
    """Xeno-canto returns protocol-relative URLs (``//...``); add https."""
    if raw.startswith("//"):
        return f"https:{raw}"
    return raw


def _search(
    client: httpx.Client, *, query: str, api_key: str
) -> list[dict[str, Any]]:
    """Call the Xeno-canto v3 search API and return the recordings list."""
    try:
        resp = client.get(
            XENO_CANTO_BASE_URL,
            params={"query": query, "key": api_key},
            headers={"User-Agent": _USER_AGENT},
        )
    except httpx.TimeoutException as exc:
        raise SampleDataError(
            "Xeno-canto search timed out. Try again or narrow --query."
        ) from exc
    except httpx.RequestError as exc:
        raise SampleDataError(
            f"Could not reach Xeno-canto: {exc}"
        ) from exc

    if resp.status_code in (401, 403):
        raise SampleDataError(
            "Xeno-canto rejected the API key (HTTP "
            f"{resp.status_code}). Check --api-key / XENO_CANTO_API_KEY "
            "(create one at https://xeno-canto.org/ → Account → API key)."
        )
    if resp.status_code != 200:
        raise SampleDataError(
            f"Xeno-canto search returned HTTP {resp.status_code}."
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise SampleDataError(
            "Xeno-canto search returned a non-JSON body."
        ) from exc

    recordings = payload.get("recordings")
    if not isinstance(recordings, list) or not recordings:
        raise SampleDataError(
            "Xeno-canto search returned no recordings for query "
            f"{query!r}. Try a broader --query."
        )
    return recordings


def _download_one(
    client: httpx.Client,
    raw: dict[str, Any],
    out_dir: Path,
) -> SampleRecording | None:
    """Download a single recording; return None if it should be skipped."""
    license_url = _normalize_url(str(raw.get("lic") or ""))
    if not _is_accepted_license(license_url):
        return None

    download_url = _normalize_url(str(raw.get("file") or ""))
    if not download_url:
        return None

    xc_id = str(raw.get("id") or "unknown")
    file_field = str(raw.get("file-name") or "")
    suffix = Path(file_field).suffix or ".mp3"
    dest = out_dir / f"XC{xc_id}{suffix}"

    try:
        with client.stream(
            "GET",
            download_url,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as resp:
            if resp.status_code != 200:
                return None
            content_length = resp.headers.get("content-length")
            if content_length is not None and int(content_length) > MAX_FILE_BYTES:
                return None
            written = 0
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    written += len(chunk)
                    if written > MAX_FILE_BYTES:
                        fh.close()
                        dest.unlink(missing_ok=True)
                        return None
                    fh.write(chunk)
    except (httpx.RequestError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise SampleDataError(
            f"Failed to download XC{xc_id}: {exc}"
        ) from exc

    scientific = f"{raw.get('gen') or ''} {raw.get('sp') or ''}".strip()
    return SampleRecording(
        xc_id=xc_id,
        file_name=dest.name,
        scientific_name=scientific,
        common_name=str(raw.get("en") or ""),
        recordist=str(raw.get("rec") or ""),
        license=license_url,
        license_name=_license_display_name(license_url),
        quality=str(raw.get("q") or ""),
        length=str(raw.get("length") or ""),
        country=str(raw.get("cnt") or ""),
        source_url=_normalize_url(str(raw.get("url") or "")),
        download_url=download_url,
        bytes=dest.stat().st_size,
    )


def _write_manifest(
    out_dir: Path, query: str, recordings: list[SampleRecording]
) -> Path:
    manifest_path = out_dir / "manifest.json"
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "xeno-canto.org (API v3)",
        "query": query,
        "attribution_note": (
            "Each recording is licensed under the Creative Commons license "
            "named in its 'license' field. When you reuse a recording you MUST "
            "credit the recordist and link back to 'source_url', and honour "
            "the license terms (e.g. NonCommercial for BY-NC). "
            "See docs/sample-data.md."
        ),
        "recordings": [asdict(r) for r in recordings],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def _print_instructions(out_dir: Path, recordings: list[SampleRecording]) -> None:
    total_kb = sum(r.bytes for r in recordings) / 1024
    print()
    print(f"Downloaded {len(recordings)} recording(s) ({total_kb:.0f} KB) to {out_dir}/")
    print("Attribution manifest: " + str(out_dir / "manifest.json"))
    print()
    print("To load these into Echoroo:")
    print("  1. Start the dev stack:  ./scripts/docker.sh dev")
    print("  2. Sign in and create (or open) a Project.")
    print("  3. Create a Dataset inside the project.")
    print("  4. Use the dataset's Upload button and select the .mp3/.wav files")
    print(f"     from {out_dir}/ (drag-and-drop is supported).")
    print("  5. Once uploaded, run a detection to see recognitions.")
    print()
    print("Attribution reminder — please credit each recordist per its license:")
    for r in recordings:
        name = r.common_name or r.scientific_name or f"XC{r.xc_id}"
        print(f"  - {name}: {r.recordist} ({r.license_name}) {r.source_url}")


def run(argv: list[str]) -> int:
    args = _parse_args(argv)

    if not args.api_key:
        print(
            "[fetch_sample_data] no Xeno-canto API key. Pass --api-key or set "
            "XENO_CANTO_API_KEY (create one at https://xeno-canto.org/ → "
            "Account → API key).",
            file=sys.stderr,
        )
        return 2
    if args.count < 1 or args.count > 15:
        print(
            "[fetch_sample_data] --count must be between 1 and 15.",
            file=sys.stderr,
        )
        return 2

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with httpx.Client(timeout=args.timeout) as client:
            candidates = _search(client, query=args.query, api_key=args.api_key)
            downloaded: list[SampleRecording] = []
            total_bytes = 0
            for raw in candidates:
                if len(downloaded) >= args.count:
                    break
                record = _download_one(client, raw, out_dir)
                if record is None:
                    continue
                total_bytes += record.bytes
                if total_bytes > MAX_TOTAL_BYTES:
                    (out_dir / record.file_name).unlink(missing_ok=True)
                    break
                downloaded.append(record)
    except SampleDataError as exc:
        print(f"[fetch_sample_data] {exc}", file=sys.stderr)
        return 1

    if not downloaded:
        print(
            "[fetch_sample_data] no CC-licensed recordings matched. Try a "
            "different --query.",
            file=sys.stderr,
        )
        return 1

    manifest_path = _write_manifest(out_dir, args.query, downloaded)
    _print_instructions(out_dir, downloaded)
    print(f"\n[fetch_sample_data] wrote manifest to {manifest_path}", file=sys.stderr)
    return 0


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
