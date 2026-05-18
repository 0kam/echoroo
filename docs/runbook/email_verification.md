# Runbook: Email Verification Delivery

This runbook covers delivery, retry, dead-letter, and bounce handling for
email verification. The canonical outbox event type is
`auth.email_verification.requested`.

## Controls

- `EMAIL_VERIFICATION_ENFORCEMENT_ENABLED`: blocks protected actions for
  unverified users when enabled.
- `EMAIL_VERIFICATION_TOKEN_TTL_SECONDS`: defaults to 24 hours.
- `EMAIL_VERIFICATION_RESEND_ACTIVE_TOKEN_CAP`: defaults to 1 active token.
- `RESEND_API_KEY` and `EMAIL_FROM`: provider credentials and sender.

Verification tokens are stored hashed in `email_verification_tokens`.
Outbox payloads carry a sealed token envelope for transient delivery; logs
must not contain raw tokens or full verification URLs.

## Normal Delivery Path

1. Registration or resend creates a new token and supersedes older active
   tokens for the same user/purpose.
2. The same database transaction enqueues
   `auth.email_verification.requested` in `outbox_events`.
3. `echoroo.workers.email_verification_dispatcher` validates the payload,
   resolves the token row, and calls `send_verification_email`.
4. `echoroo.workers.outbox_processor.process_outbox_batch` marks the row
   done or retries it. Rows that exhaust the retry budget move to
   `status='dead_letter'`.

Before enabling enforcement, verify a staging registration reaches an inbox
and the matching outbox row is marked done.

## Dead-Letter Response

Alert immediately when any verification-email row reaches
`status='dead_letter'`.

Suggested triage:

```sql
SELECT id, event_type, status, retry_count, last_error, created_at, updated_at
FROM outbox_events
WHERE event_type = 'auth.email_verification.requested'
  AND status = 'dead_letter'
ORDER BY updated_at DESC
LIMIT 20;
```

If dead letters are caused by provider outage or credentials, keep
`EMAIL_VERIFICATION_ENFORCEMENT_ENABLED=false` or disable it until delivery
recovers. Users can still authenticate, but protected-action blocking should
not be enabled while verification mail is not deliverable.

If dead letters are caused by malformed payloads, treat the issue as a code
or migration defect. Do not replay rows until the dispatcher can validate
the current payload shape.

## Bounce And Delivery Failures

SPF, DKIM, and DMARC must be valid before production signup opens. The
provider dashboard or webhook pipeline must expose:

- hard bounces
- soft bounces or deferred delivery
- complaint/spam reports
- delivery failure rate by sender domain

Alert when bounce or delivery-failure rate exceeds the release threshold
defined by operations. If bounces spike after a deploy, pause email
enforcement first, then investigate sender-domain reputation, DNS records,
provider credentials, and template/link formatting.

## Resend And Support

Resend responses are intentionally generic to avoid account enumeration.
Support should not promise whether an address exists. Ask users to check
spam/quarantine, confirm the exact address they registered with, and retry
after rate-limit windows expire.

For verified delivery failures affecting many users, leave token issue and
resend available but keep enforcement disabled until the dead-letter and
bounce alerts are back below threshold.

