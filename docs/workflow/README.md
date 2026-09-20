# Development workflow

How work is divided between the maintainer and the models on this project.
The design doc template and the accumulated UX rules sit next to this file.

## Decision delegation

The maintainer's review time is the bottleneck. Do not spend it on questions
you can answer.

**Decide yourself, report afterwards** — anything technical: library and
architecture choices, abstractions, PR slicing, test strategy, refactoring
scope, which agent or model runs a task, fallbacks when a tool fails.

**Always ask the maintainer** — anything only they can know:
- domain and product behaviour (how researchers annotate, what a species list
  must show, what a reviewer expects to happen)
- regulatory or compliance requirements (audit retention, data sensitivity)
- facts about infrastructure they operate (mounts, quotas, network exposure)
- anything that changes what a user sees or does, when no existing pattern
  in the app already answers it

Ask in one batch, as options with a recommendation and the consequence of each.

**Take the safe side without asking** — operational choices: keep a backup
before deleting, use a detached checkout instead of switching a shared branch,
leave data in place when unsure. Report what you did.

## Unknowns found mid-task

They always appear. Do not stop.

- Technical unknown: choose the most reversible option, continue, and record it
  under *Assumptions* in the design doc.
- Domain unknown: record it under *Open decisions*, continue with everything
  that does not depend on it, and raise it in the next decision batch.

Never place a domain assumption silently.

## Model roles

| Role | Model | How to run |
| --- | --- | --- |
| Maintainer dialogue, design, slicing, UI/UX, tech selection, exploratory UX verification | Claude Fable | this session |
| Exhaustive design review, code review, functional verification | `gpt-6-astra` | `codex exec -m gpt-6-astra` |
| Implementation of fully specified slices, in parallel | `gpt-5.6-luna` | `codex exec -m gpt-5.6-luna` |
| Implementation where judgement is unavoidable | `gpt-5.6-sol` | `codex exec -m gpt-5.6-sol` |

Reaching for Sol means the slice is under-specified. Fix the slice first.

Run Codex from bash with the prompt in a temp file passed on stdin
(`codex exec -m <model> --sandbox workspace-write --cd <worktree> - < prompt.md`).
The `codex:rescue` subagent cannot select a model; it uses the default in
`~/.codex/config.toml`. Check within 30 seconds that the output file is growing.

Parallel implementers: one worktree per agent, at most two at a time, no
`cd` into the main checkout, no `git reset`/`git checkout` of files, no
`docker commit/save/export`. Only the orchestrator merges.

## Workflow for non-trivial changes

| # | Step | Who |
| --- | --- | --- |
| 0 | Kickoff — collect domain constraints, ask domain questions in one batch | maintainer + Fable |
| 1 | Design doc from [design-doc-template.md](design-doc-template.md) | Fable |
| 2 | Design review — check every claim against the code, slice order, missed risks | Astra |
| 3 | Decision batch — resolve *Open decisions* in one sitting | maintainer |
| 4 | Slice — acceptance criteria per slice, no judgement left to the implementer | Fable |
| 4.5 | UX preview — mock or scenario, only when a slice changes what the user touches | Fable → maintainer |
| 5 | Implement | Luna × N |
| 6 | Review + functional verification as Playwright specs that stay in CI | Astra |
| 6.5 | Exploratory UX verification with screenshots | Fable |
| 7 | UX acceptance | maintainer |

A rejection at step 7 is a normal step, not a failure. Fable fixes it and adds
the reason to [ux-principles.md](ux-principles.md) so it does not recur.

## Verification

- Functional checks belong in Playwright specs, not in a one-off manual run.
- Never call UI work done from tests, curl, or CI alone. Drive it in a browser.
- The dev containers bind-mount the main checkout. To exercise a worktree's
  code: `git -C <main> checkout <sha>` (detached), restart `echoroo-backend`,
  verify, then `git -C <main> checkout main` and restart again.
- Backend tests run in the container:
  `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov <paths>'`
