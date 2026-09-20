# <Title>

Status: draft | reviewed | decided | in progress | done (<date>)

## Decision

What we are doing, in two or three sentences, and why this over the obvious
alternative.

## Context

The facts that force or constrain the decision. Cite code as `path:line`.
State only what was checked; mark anything inferred as inferred.

## Assumptions

Technical unknowns resolved by choosing the most reversible option.
One line each: what was assumed, why it is reversible, how it would show up if
wrong.

- ...

## Open decisions

Only the maintainer can resolve these. Each blocks the slices listed.

| # | Question | Options (recommended first) | Consequence | Blocks |
| --- | --- | --- | --- | --- |
| 1 | ... | ... | ... | slice N |

## Risks

What breaks, and what detects it.

## Slices

Ordered so that every intermediate state runs. For each slice:

### N. <name>

- **Scope** — files and behaviour touched
- **Out of scope** — what the implementer must not change
- **Acceptance** — observable conditions, including the Playwright spec that
  proves it
- **Depends on** — slices or open decisions
- **UX preview needed** — yes / no

## Review log

| Date | Reviewer | Findings | Resolution |
| --- | --- | --- | --- |
