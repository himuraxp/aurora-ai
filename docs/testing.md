# Testing

> This guide covers Angular and Node.js/NestJS tests. For Astro, see `frameworks/astro.md`.

Guide for writing useful, readable and maintainable tests.

## General principles

- Test the public behavior, not the private implementation.
- Keep mocks simple and explicit.
- Reuse the project's existing test patterns.
- One test = one expected behavior.
- Name explicitly: `should emit updated event when button clicked`.
- Isolate external dependencies with simple stubs.
- Favor light integration tests over overly mocked unit tests.

## Jest + Angular standalone

- Use `fixture.componentRef.setInput()` for standalone inputs.
- Test the outputs and visible conditional states.
- Test user interactions.
- Do not over-mock Angular.

## Node.js / NestJS

- Jest unit and integration tests.
- Mock external dependencies (DB, API) with stubs.
- Test routes/controllers in light integration.
- See `frameworks/nodejs.md` and `frameworks/nestjs.md` for details.

## Anti-patterns

- Fragile tests based on the internal DOM.
- Unnecessarily complex mocks.
- Tests that don't fail when the behavior changes.
- Code coverage without business value.
