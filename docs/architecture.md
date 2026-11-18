# Architecture

Guide for breaking down features and making architectural decisions in an Angular / TypeScript context.

## Principles

- **KISS** above all (Keep It Simple, Stupid).
- Avoid premature abstractions.
- Respect the existing architecture.
- Isolate risks.
- Prefer mergeable increments.

## Expected deliverable

For any non-trivial feature, produce:

```md
## Goal

## Probably impacted files

## Implementation plan

## Risks

## Tests
```

## Use INDEX.md to navigate

Before proposing a plan, consult `docs/ai/INDEX.md` to identify the project's key modules and files without scanning the whole codebase.
Aurora automatically loads `INDEX.md` and `WARNINGS.md` at startup if `docs/ai/` exists.

Update `INDEX.md` if the project structure or conventions change significantly.

## Questions to ask yourself

- Does it add more complexity than needed?
- Can this change be split into independent steps?
- Is there a regression risk identified in `WARNINGS.md`?
- Would the project conventions be violated?
- Did I consult `INDEX.md` before proposing?

## Anti-patterns

- Over-engineered patterns without business justification.
- Massive change without an intermediate plan.
- Listing files without consulting `INDEX.md` first.

- Ignoring testing and typing standards.
