"""Interactive bootstrap of the initial superuser (Phase 15 T952, FR-112).

quickstart §3 instructs the operator to run this script once after the
release-time wipe (``scripts.wipe_database``) so the platform has at
least one active superuser before the M-of-N approval engine engages.
The CLI sequence is:

1. Generate a TOTP secret + provisioning URI for the new operator.
2. Persist a fresh ``users`` row with the supplied e-mail and a
   temporary Argon2id password hash. ``two_factor_enabled`` is set to
   ``True`` immediately so the bootstrap user clears the global 2FA
   gate from the first request — the TOTP secret is the second factor;
   WebAuthn credentials follow within 24 h (item 6 below).
3. Promote the user via :func:`superuser_service.add_superuser`. The
   creation-time exception (count < :data:`superuser_service.MIN_SUPERUSERS`)
   inserts the row directly without engaging the M-of-N gate, which has
   no quorum to satisfy at genesis time.
4. Mint a one-time, 24-hour bootstrap token persisted into
   ``system_settings['break_glass_credential_setup_token']``. The
   token is the credential the operator surrenders at
   ``/admin/webauthn/register?token=<one_time>`` to enrol their primary
   + backup hardware keys (FR-111 mandates ≥ 2 WebAuthn credentials per
   superuser).
5. Print the TOTP secret + provisioning URI + bootstrap token to
   stdout. The output is intended for IMMEDIATE transfer into the
   operator's secret store — once the script returns, the secret is
   gone (we never persist the plain TOTP secret back to disk).
6. Append a ``superuser:bootstrap`` row to ``platform_audit_log`` so
   the genesis event is forensically linked to the request id printed
   on stdout.

Usage::

    docker exec -it echoroo-backend uv run python -m echoroo.scripts.init_superuser --confirm

The ``--confirm`` flag is mandatory (security checklist §M-2: no
typo-triggered global mutation). Without it the script prints a warning
and exits non-zero. The flag matches the family pattern used by
:mod:`echoroo.scripts.initial_iucn_sync` and
:mod:`echoroo.scripts.seed_moe_rdb` so operator muscle memory is
consistent.

Non-interactive mode
====================
The script is normally interactive. For CI / smoke tests, supply the
fields via ``--email``, ``--password``, and ``--display-name``; the
TOTP secret + bootstrap token are still generated server-side and
written to stdout. ``--non-interactive`` disables the
``input()`` / ``getpass`` prompts entirely so the script can be driven
from an automation pipeline that has already validated the operator's
identity through another channel.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import secrets
import string
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pyotp
import sqlalchemy as sa
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.security import hash_password
from echoroo.models.system import SystemSetting
from echoroo.models.user import User
from echoroo.services.audit_service import AuditLogService
from echoroo.services.superuser_service import (
    add_superuser,
    trigger_post_commit_audit,
)

logger = logging.getLogger("echoroo.scripts.init_superuser")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: TOTP issuer label baked into the provisioning URI. Mirrors
#: :data:`echoroo.services.two_factor_service.ISSUER_NAME` so an
#: existing TOTP authenticator app shows the same label whether the
#: enrollment was driven by the script or by the standard /web-api flow.
ISSUER_NAME: str = "Echoroo"

#: Length of the TOTP base32 secret. Same as the runtime path.
TOTP_SECRET_LENGTH: int = 32

#: Validity window for the WebAuthn-bootstrap one-time token.
BOOTSTRAP_TOKEN_TTL: timedelta = timedelta(hours=24)

#: ``system_settings`` key under which the bootstrap token lives. Read
#: by the admin WebAuthn-registration handler (T953/T954) when the
#: operator follows the URL printed on stdout.
SETTING_BOOTSTRAP_TOKEN: str = "break_glass_credential_setup_token"

#: Audit action for the genesis event. New string — does not collide
#: with the in-flight ``superuser.add.direct`` action emitted by
#: :func:`superuser_service.add_superuser` (we keep both rows so the
#: dashboard can distinguish "promotion via CLI bootstrap" from
#: "promotion via admin endpoint").
AUDIT_ACTION_BOOTSTRAP: str = "superuser:bootstrap"

#: Minimum length of the temporary password the operator chooses /
#: supplies. Short enough for a memorable string at the keyboard; long
#: enough that the Argon2id hash is not trivially brute-forceable
#: between bootstrap and the operator's first password rotation.
MIN_PASSWORD_LENGTH: int = 16

#: Alphabet for the bootstrap one-time token. Avoids glyph-confusable
#: characters so an operator transcribing the URL into a different
#: device cannot mistype ``0`` / ``O`` / ``I`` / ``l``.
TOKEN_ALPHABET: str = "".join(
    ch for ch in string.ascii_letters + string.digits if ch not in {"0", "O", "I", "l"}
)


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser.

    Mirrors the ``--confirm`` pattern used by
    :mod:`echoroo.scripts.initial_iucn_sync` /
    :mod:`echoroo.scripts.seed_moe_rdb`.
    """
    parser = argparse.ArgumentParser(
        prog="echoroo.scripts.init_superuser",
        description=(
            "Bootstrap the initial superuser (Phase 15 T952). Run ONCE "
            "after the release-time wipe so the M-of-N approval engine "
            "has a quorum-eligible operator. Subsequent superusers are "
            "added via the admin endpoint with full M-of-N gating."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Required acknowledgement that this script will INSERT a new "
            "user + superuser row into the database. Without --confirm "
            "the script exits non-zero without touching the database."
        ),
    )
    parser.add_argument(
        "--email",
        default=None,
        help=(
            "Operator e-mail (RFC 5322). When omitted the script "
            "prompts interactively."
        ),
    )
    parser.add_argument(
        "--display-name",
        default=None,
        help="Optional display name. Defaults to the local part of --email.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help=(
            "Temporary password (>= 16 chars). When omitted the script "
            "prompts via ``getpass`` so the secret never lands in shell "
            "history."
        ),
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Disable interactive prompts. All fields must be supplied "
            "via flags. Intended for CI / smoke tests."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def _prompt_email(supplied: str | None, *, interactive: bool) -> str:
    """Validate ``supplied`` (or prompt for one) per RFC 5322."""
    raw = supplied
    if raw is None:
        if not interactive:
            raise SystemExit("--email is required in --non-interactive mode")
        raw = input("Operator e-mail: ").strip()
    try:
        validated = validate_email(raw, check_deliverability=False)
    except EmailNotValidError as exc:
        raise SystemExit(f"invalid e-mail: {exc}") from exc
    return str(validated.normalized)


def _prompt_password(supplied: str | None, *, interactive: bool) -> str:
    """Validate ``supplied`` (or prompt twice for confirmation)."""
    if supplied is not None:
        if len(supplied) < MIN_PASSWORD_LENGTH:
            raise SystemExit(
                f"--password must be >= {MIN_PASSWORD_LENGTH} chars (got {len(supplied)})"
            )
        return supplied
    if not interactive:
        raise SystemExit("--password is required in --non-interactive mode")
    while True:
        first = getpass.getpass("Temporary password: ")
        if len(first) < MIN_PASSWORD_LENGTH:
            print(
                f"  password must be >= {MIN_PASSWORD_LENGTH} chars; please retry",
                file=sys.stderr,
            )
            continue
        second = getpass.getpass("Confirm password: ")
        if first != second:
            print("  passwords did not match; please retry", file=sys.stderr)
            continue
        return first


def _resolve_display_name(supplied: str | None, *, email: str) -> str:
    """Use ``supplied`` when present; otherwise fall back to e-mail local part."""
    if supplied is not None and supplied.strip():
        return supplied.strip()
    return email.split("@", 1)[0]


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------


def _generate_bootstrap_token() -> str:
    """Mint a 32-char URL-safe one-time token for WebAuthn enrolment.

    The token lives in ``system_settings`` (JSONB) for 24 h and is
    consumed once by the admin WebAuthn-registration handler. We use a
    glyph-disambiguated alphabet so an operator typing the URL into a
    different device cannot mistype ``0`` / ``O`` / ``I`` / ``l``.
    """
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(32))


def _security_stamp() -> str:
    """Initial security stamp for the bootstrap user.

    Mirrors :func:`two_factor_service._security_stamp` (64 hex chars)
    so the auth router's stamp comparison treats the row identically to
    one minted via the runtime 2FA path.
    """
    return secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------


async def _bootstrap_initial_superuser(
    *,
    email: str,
    display_name: str,
    password: str,
) -> dict[str, Any]:
    """Run the full bootstrap inside a single :class:`AsyncSession`.

    Steps:

    1. Reject if a row already exists for ``email`` (unique violation
       would surface as a generic IntegrityError; we want a friendlier
       diagnostic).
    2. Generate the TOTP secret + provisioning URI.
    3. INSERT the ``users`` row with ``two_factor_enabled = True`` and
       the encrypted TOTP secret.

       NOTE: The script intentionally stores the TOTP secret as
       ``base32 plaintext`` in a SEPARATE field (``description`` of the
       audit row) is NOT what we want; instead we encrypt it through
       the standard runtime path. To keep the script self-contained
       without depending on the full ``TwoFactorService`` (which needs
       a Redis connection for rate limits we are not exercising here),
       we call the same ``_encrypt_totp_secret`` helper directly.
    4. Promote via :func:`superuser_service.add_superuser` — count is 0
       on a freshly-wiped database, so the creation-time exception
       inserts the superuser row directly with no M-of-N ticket.
    5. Persist the bootstrap token into ``system_settings`` (FK →
       ``superusers.id``, NOT NULL — we now have a fresh superuser id
       to satisfy the constraint).
    6. Append the ``superuser:bootstrap`` audit row via the
       post-commit hook used by every other superuser engine path.
    """
    # Lazy import to keep the CLI startup fast for ``--help``.
    from echoroo.services.two_factor_service import _encrypt_totp_secret  # noqa: PLC0415

    secret = pyotp.random_base32(length=TOTP_SECRET_LENGTH)
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name=ISSUER_NAME,
    )
    encrypted_secret = _encrypt_totp_secret(secret)

    bootstrap_token = _generate_bootstrap_token()
    bootstrap_token_expires = datetime.now(UTC) + BOOTSTRAP_TOKEN_TTL

    async with AsyncSessionLocal() as session:
        await _reject_existing(session, email=email)

        user_row = User(
            id=uuid4(),
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            two_factor_enabled=True,
            two_factor_secret_encrypted=encrypted_secret,
            two_factor_secret_dek_version=1,
            two_factor_backup_codes_hashed=None,
            security_stamp=_security_stamp(),
        )
        session.add(user_row)
        await session.flush()

        outcome = await add_superuser(
            session,
            target_user_id=user_row.id,
            requester_superuser_id=None,
            actor_user_id=None,
            request_id=f"bootstrap-{uuid4()}",
            ip="127.0.0.1",
            user_agent="echoroo.scripts.init_superuser",
        )

        if outcome.status != "direct" or outcome.superuser_id is None:
            # Defensive: the only path that returns ``status='direct'``
            # is the count < MIN_SUPERUSERS branch. Anything else means
            # the database was not in the expected genesis state.
            raise SystemExit(
                f"refusing to continue: add_superuser returned status="
                f"{outcome.status!r} (expected 'direct'). The platform "
                f"already has superusers — use the admin endpoint with "
                f"M-of-N approval instead."
            )

        await _persist_bootstrap_token(
            session,
            superuser_id=outcome.superuser_id,
            token=bootstrap_token,
            expires_at=bootstrap_token_expires,
        )

        await session.commit()

    # Post-commit audit: write the genesis row + the
    # ``superuser.add.direct`` row from ``add_superuser``. We use a
    # fresh session per the SERIALIZABLE upgrade contract documented in
    # :mod:`echoroo.services.audit_service`.
    await _write_bootstrap_audit(
        actor_user_id=user_row.id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail={
            "user_id": str(user_row.id),
            "superuser_id": str(outcome.superuser_id),
            "email": email,
            "display_name": display_name,
            "bootstrap_token_expires_at": bootstrap_token_expires.isoformat(),
        },
    )
    await trigger_post_commit_audit(outcome)

    return {
        "user_id": str(user_row.id),
        "superuser_id": str(outcome.superuser_id),
        "email": email,
        "display_name": display_name,
        "totp_secret_base32": secret,
        "totp_provisioning_uri": provisioning_uri,
        "bootstrap_token": bootstrap_token,
        "bootstrap_token_expires_at": bootstrap_token_expires.isoformat(),
        "webauthn_registration_url": (
            f"/admin/webauthn/register?token={bootstrap_token}"
        ),
    }


async def _reject_existing(session: AsyncSession, *, email: str) -> None:
    """Refuse to bootstrap when a row already exists for ``email``."""
    stmt = sa.select(User.id).where(User.email == email)
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise SystemExit(
            f"refusing to bootstrap: a user with email={email!r} already "
            f"exists. Use the admin promotion flow instead."
        )


async def _persist_bootstrap_token(
    session: AsyncSession,
    *,
    superuser_id: UUID,
    token: str,
    expires_at: datetime,
) -> None:
    """UPSERT the WebAuthn bootstrap token into ``system_settings``.

    Stored as JSONB ``{"token": str, "expires_at": iso}`` so the admin
    handler can read both pieces with a single GET. The
    ``updated_by_id`` FK points at the freshly-minted superuser row,
    satisfying the NOT NULL constraint enforced by Phase 13 P1.
    """
    payload = {"token": token, "expires_at": expires_at.isoformat()}
    record = await session.get(SystemSetting, SETTING_BOOTSTRAP_TOKEN)
    now = datetime.now(UTC)
    if record is None:
        record = SystemSetting(
            key=SETTING_BOOTSTRAP_TOKEN,
            value=payload,
            updated_at=now,
            updated_by_id=superuser_id,
        )
        session.add(record)
    else:
        record.value = payload
        record.updated_at = now
        record.updated_by_id = superuser_id
    await session.flush()


async def _write_bootstrap_audit(
    *,
    actor_user_id: UUID,
    request_id: str,
    ip: str,
    user_agent: str,
    detail: dict[str, Any],
) -> None:
    """Append the ``superuser:bootstrap`` row to ``platform_audit_log``."""
    async with AsyncSessionLocal() as audit_session:
        try:
            await AuditLogService(audit_session).write_platform_event(
                actor_user_id=actor_user_id,
                action=AUDIT_ACTION_BOOTSTRAP,
                request_id=request_id or f"bootstrap-{uuid4()}",
                ip=ip or "127.0.0.1",
                user_agent=user_agent or "echoroo.scripts.init_superuser",
                detail=detail,
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            # Forensic loss is preferable to refusing the bootstrap —
            # the operator already has a working superuser row at this
            # point.
            logger.warning(
                "init_superuser: platform_audit_log write failed (FR-088 "
                "soft alert)",
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = _build_parser().parse_args(argv)

    if not args.confirm:
        logger.error(
            "Refusing to run without --confirm. This script INSERTs a "
            "new user + superuser row and should only be run during the "
            "initial bootstrap (see quickstart §3)."
        )
        return 2

    interactive = not args.non_interactive
    email = _prompt_email(args.email, interactive=interactive)
    password = _prompt_password(args.password, interactive=interactive)
    display_name = _resolve_display_name(args.display_name, email=email)

    try:
        result = asyncio.run(
            _bootstrap_initial_superuser(
                email=email,
                display_name=display_name,
                password=password,
            )
        )
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level entry point
        logger.exception("init_superuser failed: %s", exc)
        return 1

    # Print the structured result so the operator can pipe it into a
    # secret store or runbook checklist. The TOTP secret + bootstrap
    # token are only ever displayed here — once the script returns the
    # plaintext is gone (the encrypted-at-rest copy in the DB cannot be
    # recovered without KMS).
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    sys.stdout.flush()

    sys.stderr.write(
        "\nIMPORTANT: register >= 2 WebAuthn credentials within 24 h via\n"
        f"  {result['webauthn_registration_url']}\n"
        "After the deadline the bootstrap token expires and a new\n"
        "M-of-N approval ticket is required to add another credential.\n"
    )
    sys.stderr.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI invocation
    raise SystemExit(main())
