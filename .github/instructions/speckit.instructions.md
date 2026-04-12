---
applyTo: "specs/**"
---

# SpecKit — Spec-Driven Development Instructions

This project uses SpecKit for specification-driven development. All non-trivial features
flow through a structured pipeline before implementation begins.

## Workflow Phases

1. **Specify** — Define requirements with user stories and acceptance scenarios (`spec.md`)
2. **Plan** — Create the technical implementation plan (`plan.md`)
3. **Tasks** — Generate a dependency-ordered, executable task list (`tasks.md`)
4. **Implement** — Execute tasks with test gates

## Spec Structure

Each feature lives in `specs/<###-feature-name>/` and contains:
- `spec.md` — WHAT and WHY (technology-agnostic requirements)
- `plan.md` — HOW (technical design, architecture decisions)
- `tasks.md` — Ordered implementation tasks with priorities and dependencies

## Constitution

The project constitution is at `.specify/memory/constitution.md`. All specs and plans
MUST comply with its six core principles:
1. Pure Calculation Engine
2. API-First Data
3. Strict Layer Separation
4. Dual Interface Parity (CLI + GUI)
5. Simplicity First
6. Mechanic Extensibility

## Templates

Use templates from `.specify/templates/` when creating new specs:
- `spec-template.md` — Feature specification
- `plan-template.md` — Implementation plan
- `tasks-template.md` — Task list
- `checklist-template.md` — Quality checklist

## Rules

- Every `spec.md` must have prioritized user stories (P1, P2, P3) that are independently testable.
- Every `plan.md` must include a Constitution Check section verifying compliance.
- Tasks use the format: `- [ ] [T###] [P] [US#] Description with file path`
  - `[P]` = parallelizable
  - `[US#]` = user story reference
- Engine changes require spot-check or test verification before merging.
