"""Race-condition negative security tests for the permissions redesign.

Phase 2.7 introduces the outbox pattern (T080-T084). The tests in this
package assert that:

* the at-most-once log guarantee holds when a worker crashes between
  handler completion and ``mark_done`` (T082, FR-076a, SC-021), and
* a worker stoppage of 5+ minutes flips the system into the
  ``enforce_at_auth_time=true`` fallback mode (T083, FR-076d).

Future phases add additional race-condition tests under this package
(audit chain serialisation, token rotation contention, etc.).
"""
