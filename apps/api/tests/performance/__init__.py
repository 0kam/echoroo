"""Performance test suite (NFR-001, NFR-004, FR-093, SC-006, SC-014, SC-015).

Tests in this package measure latency budgets (p50 / p95 / p99) and
concurrency invariants for the critical hot paths defined in the Phase 16
permission-redesign specification.

Markers
-------
All tests carry ``@pytest.mark.performance`` so CI can deselect them with::

    pytest -m "not performance"

CI skip
-------
Latency assertions are inherently environment-sensitive. Tests that carry
``@pytest.mark.skipif(os.getenv("CI") == "true", ...)`` are *intended* to
run locally or in a dedicated perf environment, not in shared CI runners
where scheduling jitter routinely inflates p95 numbers by 10-50×.

k6 scenarios
------------
The ``scenarios/`` sub-directory contains k6 placeholder scripts. Python
smoke tests assert the files exist and (when k6 is installed) pass ``k6
validate``. Actual load execution is performed out-of-band by the CI
infrastructure team.
"""
