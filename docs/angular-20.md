# Angular 20 — Conventions

> Detailed (agent) version: `frameworks/angular-20.md`

Practical guide for producing modern, maintainable Angular 20 code.

## HTML templates

- Use `@if` / `@else` and `@for (...; track ...)`.
- Stop using `*ngIf`, `*ngFor`, `ngSwitch`.
- Do not use `let` in the `@for` clause.
- Make sure `@if` and `@for` blocks wrap complete HTML tags.
- Never use `@if` or `@for` as an attribute.
- Define a stable `track` in `@for`.
- Avoid complex expressions in the template; prefer `computed()` in TypeScript.

## TypeScript / Components

### Standalone

- All components are standalone.
- No manual NgModule.
- Imports are declared in the component's `imports: []`.

### Injection

- Use `inject()` only.
- Private fields with `#service`.
- Avoid `private`.

### Inputs / Outputs

- `input()` / `input.required<T>()` for data.
- `output()` for events.
- Do not use `@Input()` / `@Output()`.
- Avoid `null`, prefer `undefined`.

### Reactivity

- Use `signal()`, `computed()`, `effect()`.
- Do not use RxJS in components unless there is an existing constraint.
- RxJS is allowed in business services.

### Typing

- Ban `any`.
- Use `unknown` if the type is truly unknown.
- Define explicit interfaces.
- Prefer `undefined` over `null`.

## Tests

- Use Jest.
- `fixture.componentRef.setInput()` for standalone inputs.
- Test visible behaviors and outputs.
- Simple, readable mocks.
- Do not test private implementation details.

## Services

- Business logic isolated in services.
- Components stay presentation/orchestration oriented.

## SCSS

- Preserve existing conventions.
- Avoid duplication and global styles.
- Preserve responsiveness.

## Accessibility

- Label or `aria-label` on every button.
- Explicit critical actions.
- Preserve loading, empty, error states.
