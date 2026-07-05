# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Echoroo is in a pre-launch state (no external users yet). This section
summarizes the platform's current capabilities at a coarse grain rather than
reconstructing per-commit history.

### Added

- **Data management hierarchy** — Projects → Sites (H3 hexagon cells) →
  Datasets (recorder deployments) → Recordings, with metadata and per-dataset
  license/visibility settings.
- **Automatic ML processing** — on dataset import, BirdNET (v2.4) species
  detection and Perch (V2) embedding generation run asynchronously via Celery
  workers, with GPU/CPU inference configurable through environment variables.
- **Detection review workflow** — a Species List entry point plus card-based
  review UI where users confirm, reject, or re-label ML detections and mark the
  precise time range of each call.
- **Similarity search** — Perch embeddings power reference-audio similarity
  search (stored in pgvector) to find species BirdNET does not cover.
- **Sampling review** — random confirmed-region sampling to generate negative
  data and quality-check ML output.
- **Explore & visualization** — cross-project map/species search over H3 cells,
  dataset spiral plots, and review-progress views.
- **Export** — detection-result CSV (survey reports) and ML-training dataset
  export (positive/negative clips + metadata).
- **Custom models** — SVM classifier training on confirmed data and batch
  inference.
- **Permissions & security** — Public/Restricted visibility, taxon-driven
  auto-obscuring of sensitive coordinates, mandatory 2FA / WebAuthn, KMS
  envelope encryption, and audit logging.
- **Internationalization** — English/Japanese UI via Paraglide-JS with
  URL-based locale routing and GBIF-sourced vernacular (Japanese) species names.
- **BFF architecture** — a `/web-api/v1` backend-for-frontend transport layer in
  front of the FastAPI `/api/v1` programmatic surface.

### Infrastructure

- Docker-based development stack (Postgres 16 + pgvector, Redis, LocalStack)
  orchestrated via `echoroo.sh`.
- CI gates: frontend type-check/lint/tests, backend tests with coverage gate,
  dedicated security tests, permission/response/search lints, supply-chain
  (uv hash chain + pip-audit), opt-in mutation testing and full-stack E2E.

[Unreleased]: https://github.com/0kam/echoroo
