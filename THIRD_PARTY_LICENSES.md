# Third-Party Licenses

Echoroo itself is licensed under the **GNU GPL v3** (see [LICENSE](LICENSE)).
This document lists the **direct runtime dependencies** of each application and
their licenses.

> **Scope & accuracy.** Only direct runtime dependencies are listed (test /
> lint / build tooling is omitted). License identifiers below are best-effort
> [SPDX](https://spdx.org/licenses/) values looked up from the upstream
> projects; where a value could not be confidently determined it is marked
> *see upstream*. Always confirm against the version actually installed.
>
> **Transitive dependencies** pulled in by the packages below retain their own
> licenses and are not enumerated here. Use `uv export` (backend) or
> `npm ls` / a license scanner (frontend) to produce a full transitive report.
>
> **Machine-learning model weights** (BirdNET, Perch) are downloaded at runtime
> and are **not** Python/npm dependencies — their licensing is described
> separately in [MODEL_LICENSES.md](MODEL_LICENSES.md).

## Backend — `apps/api` (Python)

Source: `apps/api/pyproject.toml` `[project.dependencies]`.

| Package | License (SPDX, best-effort) |
|---------|-----------------------------|
| fastapi | MIT |
| uvicorn[standard] | BSD-3-Clause |
| sqlalchemy[asyncio] | MIT |
| pydantic[email] | MIT |
| pydantic-settings | MIT |
| pyjwt | MIT |
| passlib[argon2] | BSD-2-Clause |
| argon2-cffi | MIT |
| python-multipart | Apache-2.0 |
| fastapi-limiter | MIT |
| redis | MIT |
| httpx | BSD-3-Clause |
| alembic | MIT |
| asyncpg | Apache-2.0 |
| psycopg2-binary | LGPL-3.0-or-later (with OpenSSL exception) |
| h3 | Apache-2.0 |
| soundfile | BSD-3-Clause |
| mutagen | GPL-2.0-or-later |
| numpy | BSD-3-Clause |
| scipy | BSD-3-Clause |
| matplotlib | Matplotlib License (BSD-style, PSF-based) |
| torch | BSD-3-Clause |
| torchaudio | BSD-2-Clause |
| Pillow | MIT-CMU (HPND) |
| boto3 | Apache-2.0 |
| celery[redis] | BSD-3-Clause |
| birdnet | MIT (library code; model weights differ — see MODEL_LICENSES.md) |
| tensorflow[and-cuda] | Apache-2.0 |
| pgvector | MIT |
| scikit-learn | BSD-3-Clause |
| joblib | BSD-3-Clause |
| pyotp | MIT |
| webauthn | BSD-3-Clause |
| cryptography | Apache-2.0 OR BSD-3-Clause |

## Frontend — `apps/web` (npm)

Source: `apps/web/package.json` `dependencies` (devDependencies excluded).

| Package | License (SPDX, best-effort) |
|---------|-----------------------------|
| @inlang/paraglide-js | Apache-2.0 |
| @simplewebauthn/browser | MIT |
| @sveltejs/kit | MIT |
| @tanstack/svelte-query | MIT |
| h3-js | Apache-2.0 |
| maplibre-gl | BSD-3-Clause |
| otplib | see upstream |
| qrcode | MIT |
| svelte | MIT |
| wavesurfer.js | BSD-3-Clause |

## Notes on copyleft dependencies

- **`mutagen`** is GPL-2.0-or-later and **`psycopg2-binary`** is
  LGPL-3.0-or-later. Echoroo's own GPL-3.0 license is compatible with linking
  these; redistributors should nonetheless review their obligations.

If you redistribute Echoroo, ensure the corresponding license texts of the
bundled dependencies are made available as required by their terms.
