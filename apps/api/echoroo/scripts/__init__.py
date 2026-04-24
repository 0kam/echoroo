"""Operational scripts for the echoroo API.

These modules are entry points (``python -m echoroo.scripts.<name>``) that
run one-shot administrative tasks such as wipe-guard verification and the
release-time database wipe ritual. They are intentionally kept out of the
import path of the FastAPI application.
"""
