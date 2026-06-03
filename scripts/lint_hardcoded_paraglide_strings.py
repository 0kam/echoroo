#!/usr/bin/env python3
"""Lint: hardcoded English UI strings in Svelte markup are forbidden.

Prevents regression of untranslated labels reaching production (the "#9" class
of preview-feedback bug, where an English label such as "Sites & Data" shipped
without a Paraglide ``m.*()`` call). After the i18n sweep, every user-facing
string in a ``.svelte`` template must be emitted through a Paraglide message
function so the URL-routed locale (``/en/*`` / ``/ja/*``) renders the
translated catalogue value. A reintroduced literal silently desynchronises the
non-English locale from the English UI.

Detection strategy (whole-source region-stripping, ``apps/web/src/**/*.svelte``
only). The scanner operates on the ENTIRE file source — NOT line by line — after
blanking out the regions that must never be scanned. This is what lets it find
text that Prettier wraps onto its own line and static text adjacent to
interpolation, both of which a per-line scanner silently missed.

Step 1 — Region stripping (offset/line-number preserving). The whole source is
first cleaned by replacing each ``<script ...>...</script>`` block, each
``<style ...>...</style>`` block, and each ``<!-- ... -->`` comment with
same-length whitespace (newlines preserved). Because the replacement keeps the
exact character/newline count, every offset and line number in the cleaned
string still maps to the original source. This single step:

    * eliminates TypeScript-generics false positives inside ``<script>``
      (``() => Promise<void>`` would otherwise match ``>Promise<``; likewise
      ``Array<Item>`` / ``Map<K,V>`` / ``Record<...>`` / ``Ref<T>``), and CSS
      rules inside ``<style>``; AND
    * fixes comment poisoning: a ``<!-- mention <script> -->`` no longer makes
      the old line state machine skip the rest of the file to EOF; markup that
      FOLLOWS a comment is still scanned; AND
    * ignores commented-out markup entirely.

Step 2 — Markup text nodes (whole cleaned source). Text captured by
``>([^<>]+)<`` (between a closing ``>`` and the next opening ``<``), now
allowing ``{`` / ``}`` inside the run so static text ADJACENT to an
interpolation is captured (``>Estimated clips: {n}<`` → ``Estimated clips:``)
and so a run spanning multiple lines (``<button>\n  Add Note\n</button>``) is
detected. Svelte ``{...}`` interpolations (one level of nesting) are then
length-preservingly blanked so only the STATIC remainder is post-filtered; a
pure-interpolation node collapses to empty and is skipped. ``<kbd>...</kbd>``
content (keyboard keys) is excluded by inspecting the opening tag.

Step 3 — Localizable attribute values (whole cleaned source). ONLY
``aria-label`` / ``placeholder`` / ``title`` / ``alt`` are in scope. Both
quote styles are matched (``title="..."`` AND ``placeholder='...'``), AND
expression attributes (``title={cond ? 'A' : 'B'}``) are scanned for their
string literals. A negative lookbehind anchors the attribute name so prefixed
look-alikes (``data-title=`` / ``subtitle=`` / ``data-alt=``) are NOT matched.

Known limitations (accepted; future follow-ups):

    * ``.ts`` / ``.svelte.ts`` strings are out of scope — only ``.svelte``
      templates are scanned.
    * A same-file DUPLICATE of an already-allowlisted string is not re-flagged
      (the fingerprint is content-keyed; see below).
    * Allowlist GROWTH is not yet CI-enforced; a ``--no-grow`` /
      base-branch-diff guard is a future follow-up.

Each candidate is post-filtered to keep the false-positive rate low; a
candidate is only a violation when, after collapsing whitespace, it:

    * starts with an ASCII uppercase letter ``[A-Z]`` (real sentences/labels),
    * contains at least one ASCII lowercase letter ``[a-z]`` (filters all-caps
      enums / acronyms / table headers like ``STATUS`` / ``ID`` / ``DATE``),
    * is NOT a single token on the brand/proper-noun denylist, and
    * is NOT a single CamelCase / all-caps token (e.g. ``BirdNET`` / ``GBIF``).

``<kbd>...</kbd>`` content (keyboard keys) is excluded: a ``>TEXT<`` match
immediately wrapped by ``<kbd>`` / ``</kbd>`` is skipped.

Suppress individual matches listed in
``scripts/allowlists/hardcoded_paraglide_strings_allowlist.txt`` at the
CONTENT-LEVEL fingerprint level
(``<file>:<normalized-text>:hardcoded-ui-string``). The fingerprint is keyed by
(file, normalized text) and deliberately OMITS the line number. For this lint
the meaningful identity of a violation is the string CONTENT, not its position:
the baseline is large and clusters many entries per file, so a line-pinned
fingerprint would re-surface strings a developer never touched whenever an
unrelated edit near the top of a file shifted all downstream line numbers.
Keying on content avoids that unrelated-edit friction while still surfacing any
NEW or CHANGED string content. (This differs from the license lint, whose token
is a tiny enum where a line discriminator is cheap and meaningful.)

Accepted trade-off: a brand-new DUPLICATE of an already-allowlisted string in
the SAME file is not re-flagged — it collapses to the existing fingerprint.
That is acceptable: the identical string is already an accepted hardcode in
that file. The human-readable violation MESSAGE still includes the source line
number so a developer can locate the offending occurrence.

Excluded from the scan:

    * Non-``.svelte`` files (only Svelte templates are scanned).
    * ``tests/`` and ``specs/`` directory segments.
    * This lint script + its allowlist (they enumerate strings as data).

The unusually large baseline is generated, not hand-written: run
``--write-allowlist`` once to snapshot the CURRENT untranslated strings. NEW
genuine untranslated strings must be TRANSLATED via ``m.*()`` — not added to
the allowlist.

Exit codes:

    0 — no violations (or violations present but ``--fail-on-violation`` unset)
    1 — at least one hardcoded UI string found, with ``--fail-on-violation``
    2 — unexpected internal error

CI wiring (see .github/workflows/ci.yml): blocking ``frontend-paraglide-lint``
job (``--fail-on-violation``); the generated baseline keeps it green today so
it only fails on NEW hardcoded strings.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# --- Step 1: region-stripping markers ------------------------------------
# Non-markup regions that must be blanked (length/newline-preserving) BEFORE
# scanning the whole source. ``re.DOTALL`` lets each block span many lines;
# ``re.IGNORECASE`` tolerates ``<SCRIPT>`` etc. The closing-tag pattern allows
# whitespace before ``>`` (``</script >``).
_SCRIPT_BLOCK_RE = re.compile(
    r"<script\b[^>]*>.*?</script\s*>", re.DOTALL | re.IGNORECASE
)
_STYLE_BLOCK_RE = re.compile(
    r"<style\b[^>]*>.*?</style\s*>", re.DOTALL | re.IGNORECASE
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# --- Step 2: markup text node --------------------------------------------
# Text captured between a closing ``>`` and the next opening ``<``. Unlike the
# old per-line scanner this allows ``{`` / ``}`` in the run (so static text
# adjacent to an interpolation is captured) and, by scanning the WHOLE source,
# matches runs that Prettier wraps across multiple lines.
_MARKUP_TEXT_RE = re.compile(r">([^<>]+)<")

# A svelte ``{...}`` interpolation (one level of brace nesting). Applied
# iteratively, length-preservingly blanking it to spaces, so only the STATIC
# remainder of a text node survives the post-filter. ``<kbd>`` opening-tag
# detection.
_INTERP_RE = re.compile(r"\{[^{}]*\}")
_KBD_OPEN_RE = re.compile(r"<kbd[\s>]", re.IGNORECASE)

# --- Step 3: localizable attribute values --------------------------------
# ONLY these four attributes are in scope. ``class`` / ``style`` / ``href`` /
# ``src`` / ``d`` / ``viewBox`` / ``transform`` / ``fill`` / ``stroke`` /
# ``width`` / ``height`` are out of scope by NOT being in the alternation.
#
# The ``(?<![\w-])`` negative lookbehind anchors the attribute name to a left
# boundary so prefixed look-alikes are NOT matched: ``data-title="..."`` /
# ``subtitle="..."`` / ``data-alt="..."`` are skipped while ``title="..."`` /
# ``alt="..."`` are still flagged.
#
# ``_ATTR_QUOTED_RE`` matches BOTH quote styles (``"..."`` and ``'...'``) via a
# back-referenced delimiter; ``_ATTR_EXPR_RE`` matches expression attributes
# (``title={cond ? 'A' : 'B'}``) whose body is then scanned for string literals
# by ``_STR_LIT_RE``.
_ATTR_QUOTED_RE = re.compile(
    r"""(?<![\w-])(?:aria-label|placeholder|title|alt)\s*=\s*"""
    r"""(['"])((?:(?!\1).)*)\1"""
)
_ATTR_EXPR_RE = re.compile(
    r"""(?<![\w-])(?:aria-label|placeholder|title|alt)\s*=\s*\{([^{}]*)\}"""
)
_STR_LIT_RE = re.compile(r"""(['"])((?:(?!\1).)*)\1""")

# Brand / proper-noun denylist. A single-token candidate that exactly matches
# one of these (case-sensitive) is skipped. Kept deliberately small and
# documented; the generated baseline absorbs everything else.
_BRAND_DENYLIST: frozenset[str] = frozenset(
    {
        "Echoroo",
        "BirdNET",
        "Perch",
        "GBIF",
        "XenoCanto",
        "Xeno",
        "Cornell",
        "H3",
        "S3",
        "URL",
        "ID",
        "API",
        "CSV",
        "JSON",
        "WAV",
        "FLAC",
        "PNG",
    }
)

# A single token (no internal whitespace) that is CamelCase or all-caps —
# e.g. ``BirdNET`` / ``GBIF`` / ``CamelCase`` — is treated as a brand/identifier
# and skipped. Matches a token starting uppercase with at least one further
# uppercase letter and no whitespace.
_CAMEL_OR_ACRONYM_RE = re.compile(r"^[A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*$")

# Directory-segment exclusions (any path containing one of these segments is
# skipped). ``tests`` covers any frontend test directory; ``specs`` covers the
# repo-level spec docs.
EXCLUDED_DIR_SEGMENTS: frozenset[str] = frozenset({"tests", "specs"})

# File-level always-skip suffixes (POSIX, checkout-location independent).
ALWAYS_SKIP_PATHS: tuple[str, ...] = ()

# Default scan root and the file suffix to scan within it.
DEFAULT_WEB_SRC_ROOT = Path("apps/web/src")
_SCAN_SUFFIX = ".svelte"

DEFAULT_ALLOWLIST = Path(
    "scripts/allowlists/hardcoded_paraglide_strings_allowlist.txt"
)

# This script and its allowlist must never flag themselves (they enumerate
# strings as data). Matched by POSIX suffix.
_SELF_PATHS: tuple[str, ...] = (
    "scripts/lint_hardcoded_paraglide_strings.py",
    "scripts/allowlists/hardcoded_paraglide_strings_allowlist.txt",
)

_ALLOWLIST_HEADER = """\
# Allowlist for scripts/lint_hardcoded_paraglide_strings.py (WS7 Phase 2).
#
# Detection: the linter region-strips each .svelte file (blanking <script> /
# <style> blocks and <!-- --> comments length-preservingly) and then scans the
# WHOLE source. It detects MULTI-LINE markup text nodes (text Prettier wraps
# onto its own line), text ADJACENT to a {interpolation}, and localizable
# attributes in single- OR double-quoted AND expression form
# (title={cond ? 'A' : 'B'}). Out of scope: .ts / .svelte.ts strings.
#
# FAIL-CLOSED BASELINE. CONTENT-level fingerprint format. Each non-comment line
# is one fingerprint of the form:
#
#     <file>:<normalized-text>:hardcoded-ui-string  # justification
#
# The fingerprint is keyed by (file, normalized-text) and OMITS the line
# number on purpose. For this lint the meaningful identity of a hardcoded
# string is its free-form CONTENT, not its position in the file. Keying on
# content means MOVING a line (or editing unrelated lines above it) does NOT
# re-surface an already-accepted entry — which matters because this baseline is
# large and clusters many entries per file, so a line-pinned key would fail CI
# on strings the developer never touched. Conversely, ANY new or changed string
# CONTENT produces a different fingerprint and still fails the gate.
#
# Accepted trade-off: a brand-new DUPLICATE of an already-allowlisted string in
# the SAME file is not re-flagged (it collapses to the existing entry). That is
# acceptable — the identical string is already an accepted hardcode in that
# file. (Contrast the license lint, whose token is a tiny enum where a per-line
# discriminator is both cheap and meaningful.)
#
# This file is a GENERATED snapshot of the untranslated strings that existed
# when the gate was introduced. Regenerate with:
#
#     python scripts/lint_hardcoded_paraglide_strings.py --write-allowlist
#
# DO NOT add NEW entries by hand to silence a freshly-introduced label. A new
# genuinely user-facing English string must be TRANSLATED via a Paraglide
# `m.*()` call (and a key added to apps/web/messages/{en,ja}.json) — NOT
# allowlisted. The baseline below only exists to make the gate green on the
# pre-existing tree; it should shrink over time, never grow.
#
# Inline comments use TWO SPACES + ``#``. Lines beginning with ``#`` are
# full-line comments. See scripts/allowlists/README.md.
"""


# ---------------------------------------------------------------------------
# Allowlist loading
# ---------------------------------------------------------------------------


def _load_allowlist(path: Path) -> frozenset[str]:
    """Load a content-level fingerprint allowlist.

    Format: ``<file>:<normalized-text>:hardcoded-ui-string``. Inline comments
    use ``  #`` (two spaces + hash); lines beginning with ``#`` are full-line
    comments. A missing file yields an empty frozenset, so the lint fails CLOSED
    (all violations surface). See scripts/allowlists/README.md.
    """
    if not path.exists():
        return frozenset()
    entries: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.split("  #", 1)[0].strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(stripped)
    return frozenset(entries)


def _violation_fingerprint(rel_str: str, normalized_text: str) -> str:
    """Stable CONTENT-LEVEL fingerprint for one hardcoded-UI-string violation.

    The fingerprint is keyed by (file, normalized text) and deliberately omits
    the source line number. For this lint the meaningful identity is the string
    CONTENT, not its position: the baseline is large and clusters many entries
    per file, so a line-pinned fingerprint would re-surface untouched strings
    whenever an unrelated edit shifted downstream line numbers. Content keying
    avoids that friction while still surfacing any NEW or CHANGED content.

    Trade-off: a new duplicate of an already-allowlisted string in the same
    file collapses to the existing fingerprint and is not re-flagged
    (acceptable — it is already an accepted hardcode there).

    ``normalized_text`` is the whitespace-normalised matched text. It may
    legitimately contain colons; the allowlist is parsed as opaque whole-line
    fingerprints, so embedded colons do not break the round-trip. Newlines are
    never present because the text is captured per-line and re-collapsed.
    """
    return f"{rel_str}:{normalized_text}:hardcoded-ui-string"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _detect_repo_root(start: Path) -> Path:
    candidate = start.resolve()
    for _ in range(8):
        if (candidate / ".git").exists():
            return candidate
        if candidate.parent == candidate:
            return candidate
        candidate = candidate.parent
    return candidate


def _relative_posix(path: Path, repo_root: Path) -> str:
    abs_path = path.resolve()
    try:
        rel = abs_path.relative_to(repo_root.resolve())
    except ValueError:
        rel = path
    return str(rel).replace("\\", "/")


def _is_always_skipped(posix: str) -> bool:
    if any(posix.endswith(suffix) for suffix in ALWAYS_SKIP_PATHS):
        return True
    return any(posix.endswith(suffix) for suffix in _SELF_PATHS)


def _is_excluded_dir(posix: str) -> bool:
    """True when any path segment is an excluded directory (tests / specs)."""
    return any(segment in EXCLUDED_DIR_SEGMENTS for segment in posix.split("/"))


# ---------------------------------------------------------------------------
# Candidate post-filter
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Collapse internal whitespace runs to single spaces and strip ends."""
    return re.sub(r"\s+", " ", text.strip())


def _is_localizable(normalized: str) -> bool:
    """True when ``normalized`` looks like a hardcoded English UI string.

    ``normalized`` must already be whitespace-collapsed. The filter keeps the
    false-positive rate low by requiring a real capitalised, mixed-case label
    and rejecting brand tokens and CamelCase/all-caps identifiers.
    """
    if not normalized:
        return False
    # Must start with an ASCII uppercase letter.
    if not ("A" <= normalized[0] <= "Z"):
        return False
    # Must contain at least one ASCII lowercase letter.
    if not re.search(r"[a-z]", normalized):
        return False
    # Single-token candidates: reject brand/proper nouns and CamelCase/acronyms.
    if " " not in normalized:
        if normalized in _BRAND_DENYLIST:
            return False
        if _CAMEL_OR_ACRONYM_RE.match(normalized):
            return False
    return True


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _blank_match(m: re.Match[str]) -> str:
    """Replace a matched region with same-length whitespace, keeping newlines.

    Every non-newline character becomes a single space; newlines are preserved.
    The result therefore has the EXACT character count and line breaks of the
    original match, so offsets and line numbers in the cleaned string still map
    back onto the original source.
    """
    return re.sub(r"[^\n]", " ", m.group(0))


def _strip_non_markup(source: str) -> str:
    """Blank ``<script>``/``<style>`` blocks and ``<!-- -->`` comments.

    Returns a same-length, same-line-structure copy of ``source`` in which the
    three non-markup regions are replaced by whitespace. This eliminates
    TypeScript-generics / CSS false positives AND comment poisoning (markup
    after a comment is still scanned) in one pass, while preserving offsets so
    line numbers reported against the cleaned string match the original file.
    """
    cleaned = _SCRIPT_BLOCK_RE.sub(_blank_match, source)
    cleaned = _STYLE_BLOCK_RE.sub(_blank_match, cleaned)
    cleaned = _COMMENT_RE.sub(_blank_match, cleaned)
    return cleaned


def _blank_interpolations(content: str) -> str:
    """Length-preservingly blank ``{...}`` runs (one level of nesting) to spaces.

    Iterates so a leftover ``{`` after an inner blank still gets consumed;
    finally replaces any stray ``{`` / ``}`` with a space. The static remainder
    is what the post-filter judges, so a pure-interpolation node collapses to
    whitespace and is skipped.
    """
    while _INTERP_RE.search(content):
        content = _INTERP_RE.sub(lambda mm: " " * len(mm.group(0)), content)
    return content.replace("{", " ").replace("}", " ")


def _record(
    rel_str: str,
    normalized: str,
    line_no: int,
    where: str,
    allowlist: frozenset[str],
    violations: list[tuple[str, str]],
) -> None:
    """Append a ``(message, fingerprint)`` violation unless allowlisted.

    ``where`` is ``"markup"`` or ``"attribute"`` for the human-readable
    message. The fingerprint is content-keyed (no line number); the MESSAGE
    still carries the line number so a developer can locate the occurrence.
    """
    fp = _violation_fingerprint(rel_str, normalized)
    if fp in allowlist:
        return
    message = (
        f"{rel_str}:{line_no}  hardcoded UI string "
        f"'{normalized}' in {where} (use a Paraglide m.*() call)  "
        f"[fingerprint: {fp}]"
    )
    violations.append((message, fp))


def _scan_text(
    rel_str: str, source: str, allowlist: frozenset[str]
) -> list[tuple[str, str]]:
    """Return ``(message, fingerprint)`` pairs for one Svelte source file.

    The whole source is first region-stripped (``<script>`` / ``<style>`` /
    ``<!-- -->`` blanked length-preservingly), then scanned as a single string
    for markup text nodes (multi-line + interpolation-adjacent) and localizable
    attribute values (single/double-quoted + expression). Each candidate that
    survives the post-filter and is not allowlisted produces one violation.
    """
    violations: list[tuple[str, str]] = []
    cleaned = _strip_non_markup(source)

    # --- (A) markup text nodes (whole cleaned source) --------------------
    for match in _MARKUP_TEXT_RE.finditer(cleaned):
        content = match.group(1)
        # Skip <kbd>TEXT</kbd> (keyboard keys): inspect the opening tag that
        # immediately precedes this ">...<" run.
        prev_lt = cleaned.rfind("<", 0, match.start())
        if prev_lt != -1:
            opening = cleaned[prev_lt : match.start() + 1]
            if _KBD_OPEN_RE.match(opening):
                continue
        content = _blank_interpolations(content)
        normalized = _normalize(content)
        if not _is_localizable(normalized):
            continue
        line_no = cleaned.count("\n", 0, match.start(1)) + 1
        _record(rel_str, normalized, line_no, "markup", allowlist, violations)

    # --- (B) quoted localizable attribute values -------------------------
    # The value body may carry svelte ``{...}`` interpolations
    # (``aria-label="Annotation {annotation.id}"``); blank them so only the
    # STATIC remainder is judged and the fingerprint stays interpolation-free.
    for match in _ATTR_QUOTED_RE.finditer(cleaned):
        value = _blank_interpolations(match.group(2))
        normalized = _normalize(value)
        if not _is_localizable(normalized):
            continue
        line_no = cleaned.count("\n", 0, match.start(2)) + 1
        _record(
            rel_str, normalized, line_no, "attribute", allowlist, violations
        )

    # --- (B) expression localizable attribute values ---------------------
    for match in _ATTR_EXPR_RE.finditer(cleaned):
        expr = match.group(1)
        expr_offset = match.start(1)
        for lit in _STR_LIT_RE.finditer(expr):
            normalized = _normalize(lit.group(2))
            if not _is_localizable(normalized):
                continue
            abs_offset = expr_offset + lit.start(2)
            line_no = cleaned.count("\n", 0, abs_offset) + 1
            _record(
                rel_str,
                normalized,
                line_no,
                "attribute",
                allowlist,
                violations,
            )

    return violations


def _iter_scan_files(web_src_root: Path) -> list[Path]:
    """Collect the ``.svelte`` files to scan under the frontend source root."""
    files: list[Path] = []
    if web_src_root.exists():
        for path in sorted(web_src_root.rglob("*")):
            if path.is_file() and path.suffix == _SCAN_SUFFIX:
                files.append(path)
    return files


def find_violations(
    web_src_root: Path,
    allowlist: frozenset[str],
    repo_root: Path | None = None,
) -> list[tuple[str, str]]:
    """Scan the source root and return ``(message, fingerprint)`` pairs."""
    if repo_root is None:
        repo_root = _detect_repo_root(web_src_root)

    violations: list[tuple[str, str]] = []
    for path in _iter_scan_files(web_src_root):
        rel_str = _relative_posix(path, repo_root)
        if _is_always_skipped(rel_str) or _is_excluded_dir(rel_str):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            fp = _violation_fingerprint(rel_str, f"read-error:{exc}")
            violations.append((f"{rel_str}: failed to read ({exc})", fp))
            continue
        violations.extend(_scan_text(rel_str, source, allowlist))
    return violations


# ---------------------------------------------------------------------------
# Allowlist regeneration
# ---------------------------------------------------------------------------


def _write_allowlist(path: Path, fingerprints: list[str]) -> int:
    """Overwrite ``path`` with a sorted, DEDUPED, header-commented baseline.

    Fingerprints are now content-level (no line number), so identical strings
    on different lines of the same file collapse to ONE entry. Deduping via a
    sorted set keeps the baseline minimal and stable.

    Returns the number of fingerprint entries written.
    """
    unique = sorted(set(fingerprints))
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_ALLOWLIST_HEADER, ""]
    lines.extend(unique)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(unique)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--web-src-path",
        type=Path,
        default=DEFAULT_WEB_SRC_ROOT,
        help=(
            "Frontend source root to scan for *.svelte files "
            f"(default: {DEFAULT_WEB_SRC_ROOT})."
        ),
    )
    parser.add_argument(
        "--allowlist-file",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=(
            f"Fingerprint allowlist (default: {DEFAULT_ALLOWLIST}). Each "
            "non-comment line is a stable CONTENT-LEVEL fingerprint of the "
            "form <file>:<normalized-text>:hardcoded-ui-string."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root for path normalisation (default: auto-detect).",
    )
    parser.add_argument(
        "--fail-on-violation",
        action="store_true",
        help="Exit with status 1 if any violations are found.",
    )
    parser.add_argument(
        "--write-allowlist",
        action="store_true",
        help=(
            "Recompute ALL current violations (ignoring the existing "
            "allowlist) and OVERWRITE the allowlist file with their "
            "fingerprints. Use once to generate the fail-closed baseline."
        ),
    )
    args = parser.parse_args()

    try:
        if args.write_allowlist:
            # Regenerate from scratch: ignore the existing allowlist so every
            # current violation is captured into the new baseline.
            all_violations = find_violations(
                args.web_src_path,
                frozenset(),
                repo_root=args.repo_root,
            )
            fingerprints = [violation[1] for violation in all_violations]
            written = _write_allowlist(args.allowlist_file, fingerprints)
            print(
                f"[lint_hardcoded_paraglide_strings] wrote {written} "
                f"baseline entr{'y' if written == 1 else 'ies'} to "
                f"{args.allowlist_file}",
                file=sys.stderr,
            )
            return 0

        allowlist = _load_allowlist(args.allowlist_file)
        violations = find_violations(
            args.web_src_path,
            allowlist,
            repo_root=args.repo_root,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"[lint_hardcoded_paraglide_strings] unexpected error: {exc}",
            file=sys.stderr,
        )
        return 2

    for violation in violations:
        print(violation[0], file=sys.stderr)
    print(
        f"[lint_hardcoded_paraglide_strings] scanned "
        f"web-src={args.web_src_path}: "
        f"{len(violations)} violation(s) found",
        file=sys.stderr,
    )
    if violations and args.fail_on_violation:
        print(
            f"[lint_hardcoded_paraglide_strings] {len(violations)} "
            "violation(s); translate user-facing strings via a Paraglide "
            "m.*() call instead of hardcoding English (WS7 Phase 2)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
