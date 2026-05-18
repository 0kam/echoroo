# Echoroo Agent Workflow

## Language
- Communicate with the user in Japanese.
- Keep code, code comments, and product documentation in English unless an existing file clearly uses Japanese for agent-only instructions.

## Standing Operating Mode
- The user wants Codex to operate as an orchestrator by default.
- Treat this file as the user's standing instruction to use subagents for implementation-oriented work in this repository.
- The main Codex agent owns requirements clarification, task decomposition, assignment, review, integration decisions, verification strategy, and final reporting.
- The main Codex agent should avoid editing source code directly. Prefer delegating code exploration, implementation, tests, and verification to the appropriate subagent.
- The main Codex agent may edit agent workflow files, plans, task notes, and other coordination documents when needed.
- The main Codex agent may run or inspect git commands needed for coordination, such as `git status`, `git diff`, `git log`, branch creation, commits, pushes, and PR creation.

## Subagent Usage
- Use explorer subagents for codebase research, architecture questions, dependency tracing, and test-surface discovery.
- Use worker subagents for implementation. Give each worker an explicit ownership boundary: files, modules, or responsibility.
- Use verifier or worker subagents for tests, lint, type checks, CI failure diagnosis, and browser verification.
- Tell every coding subagent that it is not alone in the codebase, must not revert other people's changes, and must adapt to concurrent changes.
- Prefer parallel subagents only when write scopes or research questions are independent.
- If multiple subagents touch the same file or contract, run them sequentially and have the main Codex agent review the handoff.

## Claude Code CLI Review
- Claude Code CLI is available as `claude`.
- Use `claude -p` for non-interactive second-opinion reviews when the decision is high impact or ambiguity is material.
- Use Claude mainly for:
  - design review before large or risky changes,
  - independent code review after subagent implementation,
  - security, data integrity, API contract, UX, or migration risk review,
  - resolving disagreements between candidate approaches.
- Do not send every small task to Claude. Use it when the extra review changes the risk profile.
- The main Codex agent remains the gatekeeper. Claude's advice is input, not an automatic decision.
- By default, ask Claude for review or analysis only; do not ask Claude to edit files unless the user explicitly requests that.

## Suggested Cycle
1. Main Codex clarifies the goal, completion criteria, allowed scope, and verification gates.
2. Main Codex delegates code research to explorer subagents.
3. Main Codex decomposes implementation into independent worker tasks.
4. Worker subagents implement within assigned ownership boundaries.
5. Main Codex reviews the diff and requests fixes from the responsible worker.
6. For risky changes, Main Codex requests a Claude review with a bounded prompt.
7. Verification subagents run the appropriate static checks, tests, and browser checks.
8. Main Codex reports changed files, verification results, residual risk, and recommended next steps.

## Completion Standard
- Do not report completion until the requested behavior is implemented and the relevant verification has been run or a concrete blocker is documented.
- If verification is skipped or unavailable, state exactly what was not run and why.
- Keep final reports concise and focused on changed behavior, files, and verification.

## Active Technologies
- Python 3.11 (FastAPI backend), TypeScript 5.x (SvelteKit 2 / Svelte 5 frontend) + FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, Redis, transactional outbox + registered worker email dispatch, pyotp/WebAuthn, SvelteKit, TanStack Query, Playwright (010-email-verification-trusted-devices)
- PostgreSQL 16+ for users/tokens/trusted devices; Redis for rate limits and replay/lockout counters; secure browser cookies for first-party session and trusted-device secrets (010-email-verification-trusted-devices)

## Recent Changes
- 010-email-verification-trusted-devices: Added Python 3.11 (FastAPI backend), TypeScript 5.x (SvelteKit 2 / Svelte 5 frontend) + FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, Redis, transactional outbox + registered worker email dispatch, pyotp/WebAuthn, SvelteKit, TanStack Query, Playwright

## Speckit Plan Reference
- Current seeded permission E2E planning artifacts live under `specs/007-permission-test-coverage/`.
- Before continuing that work, read `specs/007-permission-test-coverage/plan.md` Rev.6 and `specs/007-permission-test-coverage/e2e-roadmap.md`.
