# Sample data — try Echoroo without your own recordings

New to Echoroo and don't have field recordings to hand? The
`scripts/fetch_sample_data.py` helper downloads a small set of short,
Creative-Commons-licensed bird recordings from [Xeno-canto](https://xeno-canto.org/)
so you can exercise upload, detection, and review end-to-end.

No audio is committed to this repository — the files are fetched on demand into a
local, git-ignored folder (`sample_data/` by default).

## Prerequisites

- A running Python environment for the backend (`cd apps/api && uv sync`), since
  the script depends on `httpx` (already an Echoroo dependency).
- A **Xeno-canto API key** (free). The Xeno-canto API v3 requires one:
  1. Create an account at <https://xeno-canto.org/>.
  2. Open **Account → API key** and copy the key.
  3. Provide it to the script via `--api-key`, or export it as
     `XENO_CANTO_API_KEY` (the same variable the Echoroo backend uses, so a
     configured `.env` already works).

## Usage

```bash
# From the repository root:
uv run --project apps/api python scripts/fetch_sample_data.py --api-key <YOUR_KEY>

# ...or with the key exported:
export XENO_CANTO_API_KEY=<YOUR_KEY>
uv run --project apps/api python scripts/fetch_sample_data.py --count 8 --out sample_data
```

Options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--api-key` | `$XENO_CANTO_API_KEY` | Xeno-canto API key. |
| `--count` | `6` | Number of recordings to fetch (1–15). |
| `--query` | `grp:birds q:A len:3-12` | Xeno-canto [search query](https://xeno-canto.org/help/search) in tag syntax. |
| `--out` | `sample_data` | Output directory for the audio files + `manifest.json`. |
| `--timeout` | `30` | Per-request timeout (seconds). |

The script keeps each file under 5 MB and the whole batch under 20 MB, and only
accepts Creative Commons *Attribution*-family licenses (`CC BY`, `CC BY-NC`,
`CC BY-SA`, `CC BY-NC-SA`).

On success it prints step-by-step instructions and writes a `manifest.json`
attribution file next to the audio.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Recordings + manifest downloaded. |
| `1` | Xeno-canto API / network / IO failure (message on stderr). |
| `2` | Bad arguments or missing API key. |

## Loading the recordings into Echoroo

The script downloads files locally and prints upload instructions. Programmatic
ingestion is intentionally **not** automated: uploads go through the
authenticated web BFF (`/web-api/v1/.../upload-sessions`), which needs a signed-in
session, a project, a dataset, and S3 storage wired up. The reliable,
low-friction path is the web UI:

1. Start the dev stack: `./scripts/docker.sh dev`.
2. Sign in and create (or open) a **Project**.
3. Create a **Dataset** inside that project.
4. Use the dataset's **Upload** control and select the `.mp3` / `.wav` files
   from `sample_data/` (drag-and-drop works).
5. Run a **detection** on the dataset to see recognitions, then explore the
   review and search screens.

## Attribution and licensing (important)

Each downloaded recording keeps its **original Creative Commons license**. The
generated `sample_data/manifest.json` records, per file:

- `xc_id` — Xeno-canto recording id
- `recordist` — the person who made the recording
- `license` / `license_name` — the exact CC license URL and short label
- `scientific_name` / `common_name` — the species
- `source_url` — the Xeno-canto page for the recording

When you reuse a sample recording (in a demo, screenshot, talk, dataset, etc.)
you **must**:

- **credit the recordist** named in the manifest, and
- **link back** to the recording's `source_url`, and
- **honour the license terms** — e.g. `CC BY-NC` recordings may not be used for
  commercial purposes, and share-alike (`-SA`) licenses require derivatives to
  carry the same license.

These files are for local evaluation only and are **not** redistributed as part
of the Echoroo repository. See the Xeno-canto
[terms of use](https://xeno-canto.org/about/terms) for the authoritative rules.
