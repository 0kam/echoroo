# Internal Preview Bootstrap Guide

## 0. This Document's Role

This guide bootstraps an internal preview or internal user trial of Echoroo. It is for operators and product owners who need a working trial environment, initial admin, seed data, and invite path.

The spec/006 [quickstart](../../specs/006-permissions-redesign/quickstart.md) is implementer-focused and includes lower-level development checks. This document stays operator-focused and links out to detailed runbooks such as [release_readiness.md](../runbook/release_readiness.md), [email_verification.md](../runbook/email_verification.md), and [trusted_devices.md](../runbook/trusted_devices.md) instead of duplicating them.

## 1. Prerequisites

- Docker and Docker Compose are installed.
- The repository is cloned locally.
- `.env` is copied from `.env.example`.
- LocalStack KMS values are filled in `.env` for dev:

```bash
AWS_KMS_ENDPOINT=http://localstack:4566
AWS_KMS_REGION=us-east-1
AWS_KMS_CMK_2FA_ALIAS=alias/echoroo-2fa-dev
AWS_KMS_CMK_PII_HASH_ALIAS=alias/echoroo-pii-hash-dev
AWS_KMS_CMK_AUDIT_CHAIN_ALIAS=alias/echoroo-audit-chain-dev
AWS_KMS_CMK_INVITATION_HMAC_ALIAS=alias/echoroo-invitation-hmac-dev
```

## 2. Start Services

Start the dev stack:

```bash
./echoroo.sh start
```

Health checks:

```bash
docker logs echoroo-backend --tail 50
curl http://localhost:8002/health
```

Default ports are frontend `5173` and backend `8002`. The frontend port is driven by `ECHOROO_FRONTEND_PORT` in `.env`; the standard host setup re-publishes it on `3000` (see [DOCKER.md](../../DOCKER.md)). Open the frontend at whichever port the host stack uses — `http://localhost:3000` for the standard SSH-port-forwarded setup, `http://localhost:5173` if the container port is published unchanged. Override the backend port with `ECHOROO_API_PORT`.

## 3. Apply Migrations

The Docker entrypoint does not currently run migrations automatically. Apply them manually before creating users or seed data:

```bash
./echoroo.sh migrate
docker exec echoroo-backend uv run alembic current
```

## 4. Create Initial Superuser

Open `/setup` in the frontend and submit the initial administrator form. One admin is enough for an internal preview; production FR-111 requires at least three active superusers.

The setup screen creates the bootstrap superuser through `POST /api/v1/setup/initialize` and then displays the one-time TOTP secret, TOTP provisioning URI, QR code, 24-hour bootstrap token, and `webauthn_registration_url`.

Save the one-time output immediately. The plaintext TOTP secret and bootstrap token are not recoverable after leaving the success screen.

For the production requirement, register WebAuthn credentials within 24 hours. For preview only, the admin can log in with TOTP without completing WebAuthn registration.

## 5. Seed Initial Data (Optional)

Run the seeders only when the trial needs taxonomy or sensitivity data:

```bash
docker exec echoroo-backend uv run python -m echoroo.scripts.initial_iucn_sync
docker exec echoroo-backend uv run python -m echoroo.scripts.seed_moe_rdb <csv-path> --confirm
```

Role-based test users plus a sample project and dataset come from the seeded-permission E2E fixture. Run `./echoroo.sh seed e2e` to bootstrap the same Viewer / Annotator / Manager users the trial scenarios reference. Its stdout JSON includes credentials and tokens; handle it as sensitive.

## 6. Invite Trial Users

The operator flow is: admin logs in, creates a project, then invites members.

The invitation token API is:

- `POST /web-api/v1/projects/{id}/trusted-users` with session cookies and CSRF.
- `POST /api/v1/projects/{id}/trusted-users` with an API key.

The UI invite screen is not implemented yet. For now, use curl to mint a token and hand out the resulting invitation link through the trial plan or operator channel.

Get the session and CSRF cookie values first:

1. Sign in as the project owner in a normal browser tab.
2. Open DevTools, go to **Application > Cookies > the frontend origin**, and copy the values of `echoroo_session` and `echoroo_csrf`.
3. Paste them into the request. The CSRF cookie value also goes into the `X-CSRF-Token` header (double-submit pattern).

```bash
curl -X POST http://localhost:8002/web-api/v1/projects/{id}/trusted-users \
  -H "Cookie: echoroo_session=<session>; echoroo_csrf=<csrf>" \
  -H "X-CSRF-Token: <csrf>" \
  -H "Content-Type: application/json" \
  -d '{"email":"trial.user@example.com","granted_permissions":["view_media","view_detection","download"],"duration_seconds":7776000}'
```

Implementation reference: [invitation_service.py](../../apps/api/echoroo/services/invitation_service.py).

The trial user follows the link, registers, and joins the project.

## 7. Recommended Trial Scenarios

- Login, project list, detection detail, vote, export.
- File upload by adding a recording.
- Public settings check from spec/006.
- Role-based display differences for Viewer, Annotator, and Manager.

Keep detailed scripts in the trial plan. This document only points to the paths and flows needed to bootstrap the preview.

## 8. Known Limits (Out Of Scope / Known Bugs)

- The `/setup` HTTP endpoint and frontend wizard are functional. With an empty database, open `http://localhost:3001/setup` and create the initial superuser from the browser. The CLI `init_superuser` remains available for automated and non-interactive setup paths.
- Email verification flow is in progress; the trial should not depend on email-verification-required paths.
- 2FA reset admin operation: DB schema exists, admin UI is not implemented.
- API token management UI: not implemented; use CLI or seed data only.
- Trusted device revoke list UI: not implemented.
- Project invitation UI: contracts are defined, but the SvelteKit form is not implemented; use curl as in section 6.
- Detection detail / pending invitation CTA: some E2E coverage is currently skipped.

## 9. Session Stability Check (CSRF Cookie TTL Hotfix)

Before PR #86 the CSRF cookie expired after 15 minutes (`web_access_token_ttl_seconds`) even though the session and refresh cookies lived for 30 days, so any unsafe request after the 15-minute mark returned `403 csrf_failed` and the user appeared to be auto-logged-out. To confirm the fix:

1. Sign in, then leave the tab open for at least 16 minutes (one minute past the old TTL is enough to expose the regression).
2. Trigger one unsafe request (`POST` / `PATCH` / `DELETE`) such as a vote or a comment.
3. Open browser DevTools **Application > Cookies** and check that `echoroo_csrf` shows the same `Max-Age` / `Expires` as `echoroo_refresh` (the long-lived session cookie). Both should be on the order of 30 days, not 15 minutes.
4. A `403 csrf_failed` response or an auto-logout at this point is a regression matching pre-PR-#86 behavior.

## 10. Test Mode (2FA bypass for browser testing)

For Playwright tests and internal preview workflows only, the backend can accept a shared TOTP secret after the user's enrolled TOTP secret fails. Enable it only through development environment configuration:

```bash
TEST_MODE=true
TEST_TOTP_SECRET_BASE32=JBSWY3DPEHPK3PXP
```

Generate a matching browser-test code with either command:

```bash
oathtool --totp -b JBSWY3DPEHPK3PXP
python -c "import pyotp; print(pyotp.TOTP('JBSWY3DPEHPK3PXP').now())"
```

When `TEST_MODE=true` and `TEST_TOTP_SECRET_BASE32` is set in `.env`, the 2FA challenge accepts a code generated from the shared secret for ANY user. The user's enrolled secret is always checked first, and enrolled-secret success does not emit the bypass audit event.

When enabled, startup logs `TEST_MODE is enabled, 2FA shared-secret bypass is ACTIVE. DO NOT use in production. ENVIRONMENT=%s`. A successful shared-secret match emits the audit action `two_factor.test_mode_bypass` with reason `shared_secret_match` and the current environment.

Never enable `TEST_MODE` in production and NEVER ship it to a prod-facing deployment. Startup settings validation refuses `TEST_MODE=true` in production and refuses `TEST_MODE=true` without `TEST_TOTP_SECRET_BASE32`. `compose.dev.yaml` passes these variables through for development; `compose.preview.yaml` intentionally does not.

## 11. Troubleshooting

If the frontend fails, check logs:

```bash
docker logs echoroo-frontend --tail 100
```

If migration fails, the database may not be empty. Check tables:

```bash
docker exec echoroo-db psql -U postgres -c '\dt'
```

If a trial user is stuck logging in, a rate limit may be involved. Check `login_attempts` and clear only the relevant rows:

```bash
docker exec echoroo-db psql -U postgres -c 'SELECT * FROM login_attempts ORDER BY attempted_at DESC LIMIT 20;'
docker exec echoroo-db psql -U postgres -c "DELETE FROM login_attempts WHERE email = 'trial.user@example.com';"
```

Do not use `redis-cli FLUSHALL`; it destroys sessions and Celery state.

For CSRF 403 regressions, confirm the branch includes PR #86:

```bash
git log --oneline --decorate --all --grep '#86'
```

## 12. Related Links

- [specs/006-permissions-redesign/quickstart.md](../../specs/006-permissions-redesign/quickstart.md)
- [docs/runbook/release_readiness.md](../runbook/release_readiness.md)
- [docs/runbook/email_verification.md](../runbook/email_verification.md)
- [docs/runbook/trusted_devices.md](../runbook/trusted_devices.md)
- [DOCKER.md](../../DOCKER.md)
- [CONFIGURATION.md](../../CONFIGURATION.md)
