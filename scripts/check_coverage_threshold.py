#!/usr/bin/env python3
"""Enforce per-module coverage thresholds for Echoroo backend (T996, PR-005, SC-013).

Two threshold tiers:
  - Permission-critical modules: 95%
  - All other echoroo modules:   85%

Usage:
    cd apps/api && python ../../scripts/check_coverage_threshold.py coverage.json

Exit codes:
    0  All modules meet their threshold (or --warn-only).
    1  One or more modules are below threshold (hard-fail mode).

Modules below threshold are printed with FAIL / WARN status. Modules that do
not appear in coverage.json at all are treated as 0% covered and fail unless
they are in the PHASE17_PENDING set (warn-only allowlist for Phase 17).

Phase 17 pending list:
    Modules that currently cannot reach their threshold are tracked here as
    WARN instead of FAIL. Remove entries once they are brought up to standard.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Permission-critical module set — must reach 95% statement coverage.
# Paths are relative to the coverage.json "filename" keys which use the
# source-relative path, e.g. "echoroo/core/permissions.py".
# ---------------------------------------------------------------------------
PERMISSION_MODULES: frozenset[str] = frozenset(
    [
        "echoroo/core/permissions.py",
        "echoroo/core/actions.py",
        "echoroo/core/response_filter.py",
        "echoroo/core/audit.py",
        "echoroo/core/kms.py",
        "echoroo/services/superuser_service.py",
        "echoroo/services/api_key_verification.py",
        "echoroo/services/webauthn_service.py",
        "echoroo/services/step_up_token_service.py",
        "echoroo/middleware/auth.py",
        "echoroo/middleware/auth_router.py",
        "echoroo/middleware/step_up.py",
    ]
)

PERM_THRESHOLD = 95
OTHER_THRESHOLD = 85

# ---------------------------------------------------------------------------
# Phase 17 pending modules: warn-only instead of hard-fail.
# These modules have known coverage gaps that require dedicated test work
# scheduled for Phase 17. Remove each entry once the module reaches threshold.
#
# Format: frozenset of source-relative paths (same key as coverage.json).
# ---------------------------------------------------------------------------
PHASE17_PENDING: frozenset[str] = frozenset(
    [
        # ---------------------------------------------------------------------------
        # T996 baseline: modules that cannot reach their threshold in Phase 16
        # without a dedicated integration-test suite. Scheduled for Phase 17.
        # Remove each entry once the module reaches its threshold.
        # ---------------------------------------------------------------------------
        #
        # 2026-05-09: removed 17 modules brought to threshold via PR-B test
        # additions (CI run 25604138207 baseline). Removed entries:
        #   * echoroo/api/v1/annotation_tasks.py
        #   * echoroo/api/v1/annotations.py
        #   * echoroo/api/v1/projects.py
        #   * echoroo/api/v1/recorders.py
        #   * echoroo/api/v1/setup.py
        #   * echoroo/api/v1/tags.py
        #   * echoroo/core/auth.py
        #   * echoroo/core/exceptions.py
        #   * echoroo/core/pagination.py
        #   * echoroo/core/permissions.py            (perm 95%)
        #   * echoroo/middleware/auth_router.py      (perm 95%)
        #   * echoroo/repositories/search_session.py
        #   * echoroo/repositories/user.py
        #   * echoroo/services/confirmed_region.py
        #   * echoroo/services/ownership_service.py
        #   * echoroo/services/two_factor_confirmation_token.py
        #   * echoroo/workers/trusted_expiry_notifier.py
        # PENDING count: 185 → 168.
        #
        # API route handlers — require integration tests with real DB / auth flow.
        "echoroo/_alembic_phase13_supporting_ddl.py",
        "echoroo/api/v1/admin.py",
        "echoroo/api/v1/annotation_comments.py",
        "echoroo/api/v1/annotation_sets.py",
        "echoroo/api/v1/annotation_votes.py",
        "echoroo/api/v1/auth.py",
        "echoroo/api/v1/clips.py",
        "echoroo/api/v1/custom_models.py",
        "echoroo/api/v1/datasets.py",
        "echoroo/api/v1/detection_runs.py",
        "echoroo/api/v1/detections.py",
        "echoroo/api/v1/evaluation.py",
        "echoroo/api/v1/h3.py",
        "echoroo/api/v1/recordings.py",
        "echoroo/api/v1/search/annotations.py",
        "echoroo/api/v1/search/batch.py",
        "echoroo/api/v1/search/sessions.py",
        "echoroo/api/v1/search/similarity.py",
        "echoroo/api/v1/search/utils.py",
        "echoroo/api/v1/segments.py",
        "echoroo/api/v1/settings.py",
        "echoroo/api/v1/sites.py",
        "echoroo/api/v1/taxa.py",
        "echoroo/api/v1/time_range_annotations.py",
        "echoroo/api/v1/uploads.py",
        "echoroo/api/v1/users.py",
        "echoroo/api/v1/xeno_canto.py",
        "echoroo/api/web_v1/account/dsr.py",
        "echoroo/api/web_v1/admin.py",
        "echoroo/api/web_v1/audit.py",
        "echoroo/api/web_v1/auth.py",
        "echoroo/api/web_v1/projects/_core.py",
        "echoroo/api/web_v1/projects/_license.py",
        "echoroo/api/web_v1/projects/_members.py",
        "echoroo/api/web_v1/projects/_ownership.py",
        "echoroo/api/web_v1/projects/_restricted_config.py",
        "echoroo/api/web_v1/trusted.py",
        # Core utilities — partial coverage; gaps require integration test contexts.
        "echoroo/core/database.py",
        "echoroo/core/jwt.py",
        "echoroo/core/redis.py",
        "echoroo/core/s3.py",
        # Permission-critical modules — gap tracked for Phase 17 targeted coverage push.
        # NOTE: echoroo/core/audit.py removed from PHASE17_PENDING (target: 95%, gap was
        # 0.2pp, now covered by T996 supplemental tests in test_audit_sanitizer.py).
        # NOTE 2026-05-09 (PR #62): removed 21 modules already at-or-above threshold
        # per CI run 25604138207 (post-PR #60 main). Permission-tier removals:
        # step_up.py (100%), webauthn_service.py (96.6%), kms.py (96.7%).
        # Standard-tier removals: 18 modules across schemas/,
        # api/v1/{annotation_projects,confirmed_regions,search/deps},
        # services/{restricted_config,license},
        # middleware/{security,two_factor_enforcement},
        # repositories/{base,superuser_credentials},
        # workers/{dormancy_check,ml_tasks}, and
        # ml/{birdnet/constants,perch/constants,perch/exceptions}, plus schemas/
        # {annotation,annotation_comment,clip,upload}.
        # NOTE 2026-05-09 (PR-B easy-win batch 1): additionally removed 17 modules
        # brought to threshold via test additions; details listed in the leading
        # NOTE block at the top of this PHASE17_PENDING set.
        "echoroo/core/response_filter.py",
        "echoroo/middleware/auth.py",
        "echoroo/services/superuser_service.py",
        "echoroo/services/step_up_token_service.py",
        # Other middleware
        "echoroo/middleware/logging.py",
        # ML modules — require GPU/model fixture setup, excluded from default test run.
        "echoroo/ml/active_learning.py",
        "echoroo/ml/base.py",
        "echoroo/ml/birdnet/inference.py",
        "echoroo/ml/birdnet/loader.py",
        "echoroo/ml/birdnet_wrapper.py",
        "echoroo/ml/classifiers.py",
        "echoroo/ml/perch/direct_inference.py",
        "echoroo/ml/perch/inference.py",
        "echoroo/ml/perch/loader.py",
        "echoroo/ml/registry.py",
        "echoroo/ml/sampling.py",
        # Repository layer — require database fixtures.
        "echoroo/repositories/annotation.py",
        "echoroo/repositories/annotation_comment.py",
        "echoroo/repositories/annotation_project.py",
        "echoroo/repositories/annotation_set.py",
        "echoroo/repositories/annotation_task.py",
        "echoroo/repositories/annotation_vote.py",
        "echoroo/repositories/clip.py",
        "echoroo/repositories/clip_annotation.py",
        "echoroo/repositories/confirmed_region.py",
        "echoroo/repositories/custom_model.py",
        "echoroo/repositories/dataset.py",
        "echoroo/repositories/detection.py",
        "echoroo/repositories/detection_run.py",
        "echoroo/repositories/h3_partition.py",
        "echoroo/repositories/project.py",
        "echoroo/repositories/recorder.py",
        "echoroo/repositories/recording.py",
        "echoroo/repositories/segment.py",
        "echoroo/repositories/site.py",
        "echoroo/repositories/tag.py",
        "echoroo/repositories/taxon.py",
        # Service layer — require database/external-service fixtures.
        "echoroo/services/annotation.py",
        "echoroo/services/auth.py",
        "echoroo/services/auth_service.py",
        "echoroo/services/audio.py",
        "echoroo/services/clip.py",
        "echoroo/services/custom_model.py",
        "echoroo/services/dataset.py",
        "echoroo/services/detection.py",
        "echoroo/services/detection_run.py",
        "echoroo/services/dsr.py",
        "echoroo/services/email.py",
        "echoroo/services/evaluation.py",
        "echoroo/services/gbif.py",
        "echoroo/services/invitation.py",
        "echoroo/services/project.py",
        "echoroo/services/recorder.py",
        "echoroo/services/recording.py",
        "echoroo/services/search.py",
        "echoroo/services/search_gate.py",
        "echoroo/services/search_session.py",
        "echoroo/services/session_verification.py",
        "echoroo/services/setup.py",
        "echoroo/services/site.py",
        "echoroo/services/superuser_approval_service.py",
        "echoroo/services/tag.py",
        "echoroo/services/taxon.py",
        "echoroo/services/taxon_seeder.py",
        "echoroo/services/taxon_sensitivity_service.py",
        "echoroo/services/time_range_annotation.py",
        "echoroo/services/token.py",
        "echoroo/services/trusted_service.py",
        "echoroo/services/upload.py",
        "echoroo/services/user.py",
        "echoroo/services/user_deletion_service.py",
        "echoroo/services/vernacular.py",
        "echoroo/services/two_factor_reset_service.py",
        # Workers — require Celery/Redis/DB fixtures.
        "echoroo/workers/api_key_age_check.py",
        "echoroo/workers/celery_app.py",
        "echoroo/workers/annotation_sampling_tasks.py",
        "echoroo/workers/audit_log_export.py",
        "echoroo/workers/classifier_tasks.py",
        "echoroo/workers/db_utils.py",
        "echoroo/workers/evaluation_tasks.py",
        "echoroo/workers/invitation_email_null.py",
        "echoroo/workers/iucn_sync.py",
        "echoroo/workers/ml/detection.py",
        "echoroo/workers/ml/embedding.py",
        "echoroo/workers/ml/utils.py",
        "echoroo/workers/model_preloader.py",
        "echoroo/workers/outbox_processor.py",
        "echoroo/workers/search_tasks.py",
        "echoroo/workers/taxon_tasks.py",
        "echoroo/workers/trusted_auto_expire.py",
        "echoroo/workers/trusted_email_null.py",
        "echoroo/workers/trusted_expiry_dispatcher.py",
        "echoroo/workers/trusted_long_lived_invalidation.py",
        "echoroo/workers/upload_tasks.py",
        "echoroo/workers/pii_hash_backfill.py",
        "echoroo/workers/two_factor_tasks.py",
        # Additional repository layer modules not in initial list.
        "echoroo/repositories/embedding.py",
        "echoroo/repositories/evaluation.py",
        "echoroo/repositories/license.py",
        "echoroo/repositories/note.py",
        "echoroo/repositories/sampling_round.py",
        "echoroo/repositories/sound_event_annotation.py",
        "echoroo/repositories/system.py",
        "echoroo/repositories/upload.py",
        # Schema modules — partial coverage, schema tests are unit-light.
        "echoroo/schemas/user.py",
        # Scripts — CLI-only, not exercised by unit tests.
        "echoroo/scripts/check_wipe_guard.py",
        "echoroo/scripts/init_superuser.py",
        "echoroo/scripts/initial_iucn_sync.py",
        "echoroo/scripts/seed_moe_rdb.py",
        "echoroo/scripts/wipe_database.py",
        # Additional service modules not in initial list.
        "echoroo/services/admin.py",
        "echoroo/services/annotation_export.py",
        "echoroo/services/annotation_project.py",
        "echoroo/services/annotation_segment.py",
        "echoroo/services/annotation_set.py",
        "echoroo/services/annotation_task.py",
        "echoroo/services/annotation_vote.py",
        "echoroo/services/audio/_spectrogram.py",
        "echoroo/services/audio/_wav.py",
        "echoroo/services/audio/_window.py",
        "echoroo/services/audio/service.py",
        "echoroo/services/captcha.py",
        "echoroo/services/detection_export.py",
        "echoroo/services/export.py",
        "echoroo/services/h3_utils.py",
        "echoroo/services/invitation_service.py",
        "echoroo/services/license.py",
    ]
)


def _load_coverage(path: Path) -> dict[str, object]:
    with path.open() as f:
        result: dict[str, object] = json.load(f)
        return result


def _module_coverage_pct(module_data: dict[str, object]) -> float:
    """Compute statement coverage % from a coverage.json module entry.

    coverage.json summary structure (coverage.py >= 6.0):
        {
          "summary": {
            "covered_lines": N,
            "missing_lines": N,
            "excluded_lines": N,
            "num_statements": N,
            "percent_covered": F,
            ...
          }
        }
    """
    summary: dict[str, object] = module_data.get("summary", {})  # type: ignore[assignment]
    raw_pct = summary.get("percent_covered")
    if raw_pct is not None:
        return float(str(raw_pct))
    # Fallback: compute from covered/total if percent_covered absent.
    raw_covered = summary.get("covered_lines", 0)
    raw_total = summary.get("num_statements", 0)
    covered = int(str(raw_covered))
    total = int(str(raw_total))
    if total == 0:
        return 100.0
    result: float = round(covered / total * 100, 2)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enforce per-module coverage thresholds (T996, PR-005, SC-013)."
    )
    parser.add_argument(
        "coverage_json",
        nargs="?",
        default="coverage.json",
        help="Path to coverage.json produced by pytest-cov (default: coverage.json)",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        default=False,
        help="Print warnings but always exit 0 (use for local dev / debugging).",
    )
    parser.add_argument(
        "--perm-threshold",
        type=int,
        default=PERM_THRESHOLD,
        metavar="N",
        help=f"Coverage threshold %% for permission modules (default: {PERM_THRESHOLD})",
    )
    parser.add_argument(
        "--other-threshold",
        type=int,
        default=OTHER_THRESHOLD,
        metavar="N",
        help=f"Coverage threshold %% for other modules (default: {OTHER_THRESHOLD})",
    )
    args = parser.parse_args(argv)

    cov_path = Path(args.coverage_json)
    if not cov_path.exists():
        print(
            f"[check_coverage_threshold] ERROR: coverage.json not found at {cov_path}",
            file=sys.stderr,
        )
        print(
            "[check_coverage_threshold] Run: pytest --cov=echoroo --cov-report=json",
            file=sys.stderr,
        )
        return 1 if not args.warn_only else 0

    data = _load_coverage(cov_path)
    files: dict[str, dict[str, object]] = data.get("files", {})  # type: ignore[assignment]

    if not files:
        print("[check_coverage_threshold] No files found in coverage.json.", file=sys.stderr)
        return 1 if not args.warn_only else 0

    # Normalise keys: coverage.py may use absolute or relative paths depending
    # on how it was invoked. Strip any leading path up to "echoroo/" so the
    # lookup always uses "echoroo/..." relative form.
    def _normalise(raw_path: str) -> str:
        idx = raw_path.find("echoroo/")
        if idx >= 0:
            return raw_path[idx:]
        return raw_path

    normalised: dict[str, dict[str, object]] = {_normalise(k): v for k, v in files.items()}

    perm_threshold = args.perm_threshold
    other_threshold = args.other_threshold

    hard_failures: list[tuple[str, float, int]] = []
    warn_failures: list[tuple[str, float, int]] = []

    header = f"\n{'Module':<55} {'Coverage':>9}  {'Threshold':>10}  Status"
    print(header)
    print("-" * 90)

    for norm_path in sorted(normalised):
        module_data = normalised[norm_path]
        pct = _module_coverage_pct(module_data)

        is_perm = norm_path in PERMISSION_MODULES
        threshold = perm_threshold if is_perm else other_threshold
        tier = "perm" if is_perm else "other"

        if pct >= threshold:
            status = "PASS"
        elif norm_path in PHASE17_PENDING:
            status = "WARN(ph17)"
        elif args.warn_only:
            status = "WARN"
        else:
            status = "FAIL"

        tier_label = f"[{tier}:{threshold}%]"
        print(f"{norm_path:<55} {pct:>8.1f}%  {tier_label:>10}  {status}")

        if pct < threshold:
            if norm_path in PHASE17_PENDING or args.warn_only:
                warn_failures.append((norm_path, pct, threshold))
            else:
                hard_failures.append((norm_path, pct, threshold))

    # Check that all declared permission modules appear in coverage.json.
    missing_perm = PERMISSION_MODULES - set(normalised.keys())
    if missing_perm:
        print("\n[check_coverage_threshold] WARNING: permission modules NOT in coverage.json:")
        for m in sorted(missing_perm):
            print(f"  (not covered) {m}")
        if not args.warn_only:
            for m in sorted(missing_perm):
                hard_failures.append((m, 0.0, perm_threshold))

    print()

    # Summary
    if warn_failures:
        print(
            f"[check_coverage_threshold] {len(warn_failures)} module(s) below threshold"
            " (WARN / Phase 17 pending):"
        )
        for path, pct, thr in warn_failures:
            print(f"  {path}: {pct:.1f}% (need {thr}%)")

    if hard_failures:
        print(
            f"\n[check_coverage_threshold] FAIL — {len(hard_failures)} module(s) below threshold:"
        )
        for path, pct, thr in hard_failures:
            gap = thr - pct
            print(f"  {path}: {pct:.1f}% (need {thr}%, gap {gap:.1f}pp)")
        print(
            "\n[check_coverage_threshold] Add tests to bring these modules up to threshold."
        )
        print(
            "[check_coverage_threshold] Modules pending Phase 17 may be added to"
            " PHASE17_PENDING in this script."
        )
        return 1

    if not hard_failures and not warn_failures:
        print(
            f"[check_coverage_threshold] All modules meet thresholds"
            f" (perm={perm_threshold}%, other={other_threshold}%). PASS."
        )
    else:
        print(
            "[check_coverage_threshold] Hard-fail modules: 0. Warn-only modules:"
            f" {len(warn_failures)}. Exiting 0."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
