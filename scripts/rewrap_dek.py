#!/usr/bin/env python3
"""Phase 17 backlog A-8 — DEK rewrap CLI for TOTP CMK rotation.

Re-encrypts every TOTP secret DEK that is still wrapped under the
**old** CMK so it can be decrypted under the **new** CMK after the
rotation grace window closes. The plaintext DEK never leaves AWS KMS:
the rewrap uses ``kms:ReEncrypt`` which performs decrypt + encrypt
atomically inside the KMS service (FR-091b).

This script is the runbook companion to
``docs/runbook/dek_rewrap.md``. The expected operational flow is:

  1. Stand up the new CMK and create the alias
     ``alias/echoroo-totp-dek`` (or whatever
     ``two_factor_dek_cmk_alias_new`` is configured as).
  2. Re-point the previous alias suffix to the old CMK
     (``alias/echoroo-totp-dek-old``) and set the env vars
     ``AWS_KMS_CMK_2FA_DEK_ALIAS_OLD`` + ``AWS_KMS_CMK_2FA_DEK_KID_OLD``
     to enter the rotation grace window.
  3. Run this script with ``--dry-run`` to preview the workload.
  4. Re-run with ``--confirm`` to perform the rewrap.
  5. After completion (and after monitoring confirms zero stale
     records), unset the ``..._OLD`` env vars and schedule the previous
     CMK for deletion via ``echoroo.core.kms_ops.schedule_cmk_deletion``
     (30-day window per ``docs/runbook/cmk_rotation.md``).

Usage:

    uv run --project apps/api python scripts/rewrap_dek.py \\
        --source-alias alias/echoroo-totp-dek-old \\
        --destination-alias alias/echoroo-totp-dek \\
        --old-version 1 \\
        --new-version 2 \\
        --dry-run

    # After review:
    uv run --project apps/api python scripts/rewrap_dek.py \\
        --source-alias alias/echoroo-totp-dek-old \\
        --destination-alias alias/echoroo-totp-dek \\
        --old-version 1 \\
        --new-version 2 \\
        --confirm

Concurrency contract:
    Each row is updated with an optimistic guard
    (``WHERE id = :id AND two_factor_secret_dek_version = :old_version
    AND two_factor_secret_encrypted = :old_payload``) so an in-flight
    2FA enrollment / reset that races with the batch (e.g. a user
    re-enrolls between SELECT and UPDATE) is silently skipped — the
    new write already carries ``kid_new`` and does not need rewrap.
    These skips are reported as ``WARN`` lines and counted in the
    ``skipped`` summary so the operator can confirm the workload is
    converging.
"""

from __future__ import annotations

import argparse
import asyncio
import struct
import sys
from collections.abc import Sequence
from typing import Any

# The script is intentionally thin around ``echoroo.core.kms`` and the
# ``users`` table so it stays independent of the FastAPI app lifecycle.
# Run via ``uv run --project apps/api python scripts/rewrap_dek.py`` so
# the apps/api source tree is on PYTHONPATH automatically — no
# ``sys.path`` manipulation here (Codex plan review §(d)).
from sqlalchemy import func, select, update

from echoroo.core import kms
from echoroo.core.database import AsyncSessionLocal
from echoroo.models.user import User

WRAPPED_DEK_LEN_BYTES = 4


async def _rewrap_batch(
    session: Any,
    *,
    destination_key_id: str,
    source_key_id: str | None,
    old_version: int,
    new_version: int,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    """Process one batch of users still carrying ``old_version``.

    Returns a per-batch summary with ``processed`` (rows pulled from the
    DB), ``rewrapped`` (rows whose payload was written under
    ``new_version``), ``skipped`` (rows whose optimistic guard failed —
    a concurrent enrollment / reset moved them already), and ``failed``
    (rows where the KMS rewrap itself raised).
    """
    rows = (
        await session.execute(
            select(
                User.id,
                User.two_factor_secret_encrypted,
                User.two_factor_secret_dek_version,
            )
            .where(
                User.two_factor_secret_dek_version == old_version,
                User.two_factor_secret_encrypted.is_not(None),
            )
            .limit(batch_size)
        )
    ).all()

    summary: dict[str, int] = {"processed": 0, "rewrapped": 0, "skipped": 0, "failed": 0}

    for row in rows:
        summary["processed"] += 1
        try:
            payload: bytes = row.two_factor_secret_encrypted
            if len(payload) < WRAPPED_DEK_LEN_BYTES:
                print(
                    f"WARN user_id={row.id} payload too short ({len(payload)}b) — skipping",
                    file=sys.stderr,
                )
                summary["failed"] += 1
                continue
            wrapped_len = struct.unpack("<I", payload[:WRAPPED_DEK_LEN_BYTES])[0]
            wrapped_start = WRAPPED_DEK_LEN_BYTES
            wrapped_end = wrapped_start + wrapped_len
            if wrapped_len <= 0 or len(payload) <= wrapped_end:
                print(
                    f"WARN user_id={row.id} wrapped_len={wrapped_len} invalid — skipping",
                    file=sys.stderr,
                )
                summary["failed"] += 1
                continue
            wrapped_old = payload[wrapped_start:wrapped_end]
            rest = payload[wrapped_end:]  # nonce + ciphertext (unchanged)

            wrapped_new = kms.rewrap_dek(
                wrapped_old,
                destination_key_id=destination_key_id,
                source_key_id=source_key_id,
            )
            new_payload = struct.pack("<I", len(wrapped_new)) + wrapped_new + rest

            if dry_run:
                print(
                    f"DRY-RUN user_id={row.id} would rewrap "
                    f"(old_wrapped_len={len(wrapped_old)} new_wrapped_len={len(wrapped_new)})"
                )
                summary["skipped"] += 1
                continue

            # Optimistic update: the row may have been mutated by a
            # concurrent enrollment / 2FA reset between SELECT and
            # UPDATE. The combined version + payload guard ensures we
            # only overwrite the exact ciphertext we just rewrapped.
            result = await session.execute(
                update(User)
                .where(
                    User.id == row.id,
                    User.two_factor_secret_dek_version == old_version,
                    User.two_factor_secret_encrypted == payload,
                )
                .values(
                    two_factor_secret_encrypted=new_payload,
                    two_factor_secret_dek_version=new_version,
                )
            )
            rowcount = getattr(result, "rowcount", 0) or 0
            if rowcount == 0:
                print(
                    f"WARN user_id={row.id} optimistic update lost — concurrent change",
                    file=sys.stderr,
                )
                summary["skipped"] += 1
                continue
            summary["rewrapped"] += 1
        except Exception as exc:  # noqa: BLE001 — script-level batch is best effort
            print(f"ERROR user_id={row.id}: {exc}", file=sys.stderr)
            summary["failed"] += 1

    if not dry_run:
        await session.commit()
    return summary


async def _amain(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Re-encrypt TOTP secret DEKs from an old CMK to a new CMK.",
    )
    parser.add_argument(
        "--source-alias",
        required=True,
        help=(
            "Source CMK alias (e.g. alias/echoroo-totp-dek-old). Used to "
            "resolve --old-version and as an explicit SourceKeyId hint to "
            "AWS KMS ReEncrypt."
        ),
    )
    parser.add_argument(
        "--destination-alias",
        required=True,
        help="Destination CMK alias (e.g. alias/echoroo-totp-dek).",
    )
    parser.add_argument(
        "--old-version",
        type=int,
        required=True,
        help="DEK version stamp present on rows that need rewrapping (e.g. 1).",
    )
    parser.add_argument(
        "--new-version",
        type=int,
        required=True,
        help="DEK version stamp to write after rewrap (e.g. 2).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Rows per batch (default: 100).",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=10000,
        help="Safety cap on the number of batches per invocation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the workload without writing to the database.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to perform the actual rewrap (mutually exclusive with --dry-run).",
    )
    parser.add_argument(
        "--no-source-key-id",
        action="store_true",
        help=(
            "Skip the SourceKeyId hint and let KMS auto-resolve from "
            "ciphertext metadata. Useful when the source alias has been "
            "unset already and only the destination alias remains."
        ),
    )
    args = parser.parse_args(argv)

    if args.dry_run == args.confirm:
        print(
            "ERROR: specify exactly one of --dry-run or --confirm",
            file=sys.stderr,
        )
        return 2
    if args.old_version == args.new_version:
        print(
            "ERROR: --old-version and --new-version must differ",
            file=sys.stderr,
        )
        return 2

    # --dry-run is a *preview only*: it MUST NOT call KMS (Codex Round 1
    # R1-C1). We resolve the destination key id only for the --confirm
    # path so a typo in --destination-alias surfaces during the real run.
    if args.dry_run:
        async with AsyncSessionLocal() as session:
            count = (
                await session.execute(
                    select(func.count(User.id)).where(
                        User.two_factor_secret_dek_version == args.old_version,
                        User.two_factor_secret_encrypted.is_not(None),
                    )
                )
            ).scalar_one()
            samples = (
                await session.execute(
                    select(
                        User.id, func.length(User.two_factor_secret_encrypted)
                    )
                    .where(
                        User.two_factor_secret_dek_version == args.old_version,
                        User.two_factor_secret_encrypted.is_not(None),
                    )
                    .limit(5)
                )
            ).all()
        print(
            f"DRY-RUN: {count} row(s) would be rewrapped "
            f"(old_version={args.old_version} -> new_version={args.new_version})"
        )
        print(f"Source CMK alias:      {args.source_alias}")
        print(f"Destination CMK alias: {args.destination_alias}")
        print(f"Batch size:            {args.batch_size}")
        print(f"Max batches:           {args.max_batches}")
        print("Sample rows (id, payload_size_bytes):")
        for row in samples:
            print(f"  {row[0]}  size={row[1]} bytes")
        print("\nNo KMS API calls were made. No DB writes were made.")
        print("Re-run with --confirm to perform the actual rewrap.")
        return 0

    destination_key_id = kms._resolve_key_id(args.destination_alias)
    source_key_id = (
        None if args.no_source_key_id else kms._resolve_key_id(args.source_alias)
    )

    totals: dict[str, int] = {"processed": 0, "rewrapped": 0, "skipped": 0, "failed": 0}
    converged = False
    async with AsyncSessionLocal() as session:
        for batch_idx in range(args.max_batches):
            summary = await _rewrap_batch(
                session,
                destination_key_id=destination_key_id,
                source_key_id=source_key_id,
                old_version=args.old_version,
                new_version=args.new_version,
                batch_size=args.batch_size,
                dry_run=False,
            )
            for k in totals:
                totals[k] += summary[k]
            if summary["processed"] == 0:
                converged = True
                break
            print(f"Batch {batch_idx + 1}: {summary}")

        # Codex Round 1 R1-H1: when the for-loop exhausts ``max_batches``
        # without an empty probe batch, residual rows may still carry the
        # old version. A naive ``return 0 if totals['failed'] == 0`` would
        # report a false success in that case. Probe the database to
        # confirm convergence before reporting exit 0.
        if not converged:
            remaining = (
                await session.execute(
                    select(func.count(User.id)).where(
                        User.two_factor_secret_dek_version == args.old_version,
                        User.two_factor_secret_encrypted.is_not(None),
                    )
                )
            ).scalar_one()
            if remaining > 0:
                print(f"\nTotal: {totals}", file=sys.stderr)
                print(
                    f"ERROR: max_batches ({args.max_batches}) reached before "
                    f"convergence — {remaining} row(s) still carry "
                    f"old_version={args.old_version}. Re-run with "
                    "--max-batches greater than the current value.",
                    file=sys.stderr,
                )
                return 2

    print(f"\nTotal: {totals}")
    return 0 if totals["failed"] == 0 else 1


def main() -> int:
    return asyncio.run(_amain(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
