"""T994 — Grafana Dashboard + Alertmanager SLO alerting config (SC-006).

Contract under test
-------------------
SC-006 specifies that the 2FA login success rate must be monitored via a
Grafana dashboard and that a PagerDuty alert fires when the 30-day success
rate drops below 95% (with a minimum of 1000 trials over the window).

The *runtime* Grafana / Alertmanager infrastructure is a Phase 17 task.
These tests assert that the **configuration artefacts** exist and contain
the mandatory fields. Tests are ``xfail(strict=True)`` when the artefact
directory or file is missing; once Phase 17 creates them, the tests must
pass without modification.

Expected file layout
--------------------
``infra/grafana/dashboards/2fa_login_success_rate.json``
    Grafana dashboard JSON with a panel whose ``thresholds`` include a step
    at ``value=95`` (the SLO floor).

``infra/alertmanager/rules.yml``
    Prometheus / Alertmanager alert rule file containing a rule named
    ``2fa_login_failure_alert`` with ``severity: critical`` and a route to
    PagerDuty.

Repo root
---------
The project root is discovered by walking up from this file until a
``pyproject.toml`` is found so the path is stable regardless of CWD.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains pyproject.toml)."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[4]  # fallback: apps/api level


_REPO_ROOT = _find_repo_root()
# The repo root here is apps/api (contains pyproject.toml). The infra/ dir
# lives two levels up (repo root: echoroo/).
_INFRA_ROOT = _REPO_ROOT.parent.parent / "infra"
_GRAFANA_DASHBOARD = _INFRA_ROOT / "grafana" / "dashboards" / "2fa_login_success_rate.json"
_ALERTMANAGER_RULES = _INFRA_ROOT / "alertmanager" / "rules.yml"


# ---------------------------------------------------------------------------
# Skip/xfail helpers
# ---------------------------------------------------------------------------


def _infra_exists() -> bool:
    return _INFRA_ROOT.exists()


_INFRA_XFAIL_REASON = (
    "SC-006 Phase 17: infra/grafana and infra/alertmanager directories do not "
    "yet exist. Create the Grafana dashboard JSON and Alertmanager rules YAML "
    "as part of Phase 17, then un-xfail these tests."
)


# ---------------------------------------------------------------------------
# T994 tests — Grafana dashboard
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    not _GRAFANA_DASHBOARD.exists(),
    strict=True,
    reason=_INFRA_XFAIL_REASON,
)
def test_grafana_dashboard_file_exists() -> None:
    """infra/grafana/dashboards/2fa_login_success_rate.json must exist."""
    assert _GRAFANA_DASHBOARD.exists(), (
        f"Grafana dashboard not found: {_GRAFANA_DASHBOARD}"
    )
    assert _GRAFANA_DASHBOARD.is_file()
    assert _GRAFANA_DASHBOARD.stat().st_size > 0


@pytest.mark.xfail(
    not _GRAFANA_DASHBOARD.exists(),
    strict=True,
    reason=_INFRA_XFAIL_REASON,
)
def test_grafana_dashboard_slo_threshold_95() -> None:
    """Dashboard must define a SLO threshold panel at value=95 (95% success rate)."""
    assert _GRAFANA_DASHBOARD.exists(), "Dashboard file missing (covered by previous test)"
    raw = _GRAFANA_DASHBOARD.read_text(encoding="utf-8")
    data = json.loads(raw)

    # The JSON structure depends on the Grafana version / panel type. We
    # look for a threshold step at 95 anywhere in the dashboard JSON text
    # as a minimum viable check. The Phase 17 implementer may tighten this
    # to a panel-level assertion.
    dashboard_str = json.dumps(data)
    assert '"value": 95' in dashboard_str or '"value":95' in dashboard_str, (
        "Grafana dashboard must contain a threshold step at value=95 "
        "(the 95% 2FA login success rate SLO floor defined in SC-006). "
        f"Dashboard file: {_GRAFANA_DASHBOARD}"
    )


@pytest.mark.xfail(
    not _GRAFANA_DASHBOARD.exists(),
    strict=True,
    reason=_INFRA_XFAIL_REASON,
)
def test_grafana_dashboard_has_title() -> None:
    """Dashboard must have a non-empty title identifying the 2FA metric."""
    assert _GRAFANA_DASHBOARD.exists()
    data = json.loads(_GRAFANA_DASHBOARD.read_text(encoding="utf-8"))
    title = data.get("title", "")
    assert title, "Grafana dashboard JSON must have a non-empty 'title' field"
    assert "2fa" in title.lower() or "login" in title.lower(), (
        f"Dashboard title {title!r} does not reference 2fa or login — "
        "expected a title like '2FA Login Success Rate'"
    )


# ---------------------------------------------------------------------------
# T994 tests — Alertmanager rules
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    not _ALERTMANAGER_RULES.exists(),
    strict=True,
    reason=_INFRA_XFAIL_REASON,
)
def test_alertmanager_rules_file_exists() -> None:
    """infra/alertmanager/rules.yml must exist."""
    assert _ALERTMANAGER_RULES.exists(), (
        f"Alertmanager rules file not found: {_ALERTMANAGER_RULES}"
    )
    assert _ALERTMANAGER_RULES.is_file()
    assert _ALERTMANAGER_RULES.stat().st_size > 0


@pytest.mark.xfail(
    not _ALERTMANAGER_RULES.exists(),
    strict=True,
    reason=_INFRA_XFAIL_REASON,
)
def test_alertmanager_2fa_failure_alert_exists() -> None:
    """rules.yml must define a ``2fa_login_failure_alert`` rule."""
    assert _ALERTMANAGER_RULES.exists()
    raw = _ALERTMANAGER_RULES.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    # Walk groups → rules looking for the named alert.
    alert_names: list[str] = []
    for group in data.get("groups", []):
        for rule in group.get("rules", []):
            alert_names.append(rule.get("alert", ""))

    assert "2fa_login_failure_alert" in alert_names, (
        "Alertmanager rules.yml must contain an alert named "
        "'2fa_login_failure_alert' (SC-006 PagerDuty alert for 2FA SLO breach). "
        f"Found alerts: {alert_names}"
    )


@pytest.mark.xfail(
    not _ALERTMANAGER_RULES.exists(),
    strict=True,
    reason=_INFRA_XFAIL_REASON,
)
def test_alertmanager_2fa_alert_is_critical_severity() -> None:
    """The 2fa_login_failure_alert must have severity=critical."""
    assert _ALERTMANAGER_RULES.exists()
    raw = _ALERTMANAGER_RULES.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    target_rule: dict | None = None
    for group in data.get("groups", []):
        for rule in group.get("rules", []):
            if rule.get("alert") == "2fa_login_failure_alert":
                target_rule = rule
                break

    assert target_rule is not None, "2fa_login_failure_alert rule not found"
    labels = target_rule.get("labels", {})
    severity = labels.get("severity", "")
    assert severity == "critical", (
        f"2fa_login_failure_alert must have severity=critical (SC-006); got {severity!r}"
    )
