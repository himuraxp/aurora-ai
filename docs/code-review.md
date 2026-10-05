# Code Review

Guide for agent-assisted code review.

## Mandatory checklist

### Code

- Does the change exactly meet the need?
- Is there a breaking change?
- Are the project conventions respected?
- Do the tests cover the modified logic?
- Is the code simpler or more complex than before?
- Is there a security risk?
- Is technical debt introduced?

### Functional

- Are all plan criteria implemented?
- Are important edge cases handled or explicitly out of scope?
- Do the proposed checks prove the behavior?
- Is there a UI/accessibility regression?

### Relevance

- Does the solution meet the real need?
- Were out-of-scope files modified?
- Does the solution introduce over-engineering?
- Is human clarification needed?

## Expected verdict

Mergeable / Needs fixes / Needs clarification / Blocked

## Output format

```md
## Verdict

## Blockers

- ...

## Axes

- Code: ...
- Functional: ...
- Relevance: ...

## Suggestions

- ...

## Recommended tests

- ...
```

## Conduct rules

- Be strict but pragmatic.
- Never ask for out-of-scope refactoring.
- Prioritize real risks (security, regression, maintenance).
