"""Negative security tests for the invitation lifecycle (T530 / T531).

Each module here exercises a single FR from the Phase 10 contract:

* ``test_email_mismatch.py``        — FR-054 NFKC + casefold match.
* ``test_double_accept_idempotency.py`` — FR-053 idempotency-key dedupe.

Tests live at the service layer because the invitation flow's
security-critical decisions (HMAC verify, email hash compare, Redis
dedupe) are all surface-able from the service without spinning up the
full FastAPI middleware chain — the HTTP shape mappings are covered by
``tests/contract/test_invitation_recipient_self_delete.py``.
"""
