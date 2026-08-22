"""Bundled, versioned data files shipped inside the ``echoroo`` package.

Sub-packages under here hold *static* reference data that must be available
without a network round trip (offline installs, air-gapped deployments) and
that must be reproducible across environments. Each bundle ships a
``*.meta.json`` sidecar recording the upstream dataset, version, license and
retrieval date so provenance is auditable from the running install.
"""
