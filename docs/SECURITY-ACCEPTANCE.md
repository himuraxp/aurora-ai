# Security acceptance — public repository posture

Status: 2026-10-09, following a full-repository secrets audit (tip + complete
history + reflog orphans + ignored files + git config). Audit verdict: **0 real
credentials** in any reachable surface. This document records the risk
acceptances and the publication policy. It is the reference for every
`.gitleaksignore` entry: no ignore line without a matching class here.

## Publication policy (three classes)

| Class | Examples | Rule |
|---|---|---|
| Public | public API URLs, fictitious paths (`acme-group`), variables without values | Allowed |
| Internal metadata | internal hosts, namespaces, project ids, file keys, internal file paths | Anonymize at tip by default (env-config or placeholder) |
| Secrets | tokens, credentials, private keys | Forbidden — hook + gitleaks + CI block them |

## Accepted risks (option B — no history rewrite)

### F-02 — GitLab registry exposure (commit `cc39a6e`)

- Exposed: internal GitLab host, namespaces, project ids. **No credential** in
  the blob.
- Risk: infrastructure reconnaissance (OSINT), not authentication.
- Why no purge: `git filter-repo` + force-push breaks every existing clone and
  does not remove data from clones, forks, PR references or caches; GitHub
  Support assistance is conditional and not guaranteed for infrastructure
  metadata. Benefit/risk ratio unfavourable.
- Reopening criteria: if the exposed metadata identifies a particularly
  sensitive component (admin surface, critical environment, unauthenticated
  endpoint) — reassess with the infrastructure security owner.

### F-04 — professional email in commit authorship (~49 commits)

- Exposed: author/committer email on historic commits. Not a technical
  compromise; spam/targeting surface only.
- Mitigation: noreply address configured for all new commits (effective since
  `8cba184`); ensure automated tooling also commits with the noreply identity.
- Reopening criteria: none foreseen (information is already public by design of
  Git metadata on GitHub).

### Internal metadata still present in history (same class as F-02)

- GitLab hosts/namespaces in historic docs and skills.
- Figma DS `file_key` (commit `13b470c`, two files) — a document identifier,
  **not** a credential (API access requires `FIGMA_TOKEN`). Removed from the
  tip (env-config `FIGMA_DS_FILE_KEY`); historic copies stay public — ignored
  by fingerprint in `.gitleaksignore`.

## Resolved at tip (2026-10-09, no open item)

- **F-01** hook: ERE patterns repaired, fail-closed gitleaks (absent tool or
  tool error blocks the commit; explicit per-commit escape:
  `HOOK_SKIP_GITLEAKS=1`), e2e fixture suite wired into health-check + CI.
- **F-03** internal examples: env-config (`ANGULAR_ELEMENTS_*`,
  `FIGMA_DS_FILE_KEY`), anonymized skill examples, no internal endpoint
  hard-coded at tip.
- **F-07** internal hosts: GitLab host derived from the git remote where the
  remote is the source of truth (`deployment-changelog`, `create-mr`), doc
  examples use `gitlab.example.com`, direct AI model endpoints kept in live
  config only.

## OPSEC wave 2026-11-06 (class-2 regressions, audit-driven)

A security audit detected a new class-2 wave at the tip and re-opened
**F-02 / F-03 / F-07** (same classes as 2026-10-09). Everything was fixed at
the tip in this wave; **no open item** remains at the tip after it:

- **PHP standard** (`frameworks/php`) cited internal artifacts — private
  registry packages, auth mechanisms, route patterns, CI templates, version
  matrix — replaced by a generic standard at the tip (PR #81); the PR body
  itself was edited to drop the internal references.
- **Class-2 regressions fixed the same day**:
  - `skills/allow-command`: internal project, source paths, full commit SHA
    → neutral placeholders (`acme-group/example-project`, `apps/example/...`,
    `abc123def456`, `gitlab.example.com`).
  - `skills/deployment-changelog`: internal portal, payload taxonomy and
    hard-coded events endpoint → neutral values + private local config
    (`INFOMANIAK_EVENTS_*` in `~/.config/opencode/.env`, fail-closed at
    runtime); the engine (Bearer headers, pagination, calls) is kept.
  - Internal GitLab host in doc examples and test fixtures
    (`task-workflow`, `create-mr`, `mr-review`, `allow-command`,
    `scripts/task-workflow/tests`) → `gitlab.example.com`.
  - Test fixtures: task-workflow (project path, Trello shortLink, MR numbers
    → 1234/1235/12350), new-worktree tracker ids (`rm-1234`,
    `trello-EX12345`), user/project paths → placeholders.
- **Residual findings, pass 2 (same day)**:
  - **(f) feature-planner registry — private-config / public-engine**: the
    tracked `projects-registry.example.json` carried real project names as
    aliases at the tip; the full live registry (real host, namespaces, ids)
    existed only on disk in the untracked, git-ignored
    `projects-registry.json` (git-ignored since `8cba184` — never tracked at
    the tip, but present in git history `cc39a6e`..`8cba184`: history-rewrite
    item, out of scope, same class as `v1.8.0`/`68d4c04`). The live data now
    lives only in `~/.config/opencode/gitlab-feature-planner-registry.private.json`
    (outside any repo; re-backed-up 2026-11-06). `resolve_project.py` reads
    the private registry first and `--record` always writes to it — a repo
    file can never receive real namespaces/ids again. Both in-repo registries
    are placeholder templates sharing one vocabulary
    (`gitlab.example.com`, `acme-group/*`, ids 1001-1004, `validated:false`);
    the pattern is documented in `skills/gitlab-feature-planner/SKILL.md`.
  - **(g) `docs/ai/` sanitized (STATUS / CHANGELOG / BUFFER / INDEX / PLAN /
    WARNINGS)**: internal GitLab host → `gitlab.example.com`, real Trello card
    ids / terminal handles / workflow hashes / project ids → placeholders,
    credential metadata removed with a pointer back to this file (GitLab PAT
    scopes/expirations/fingerprints/numeric ids; Trello token sha256
    fingerprints). Scope extended beyond the original 3 files to
    every class-2 project identifier in the session memory (same leak class,
    mechanical replacements). `docs/ai/` is git-ignored and untracked since
    `c4aeddc` (local-only, not shipped at the tip); older versions with real
    values exist in git history in the tracked window (`4989736`..`c4aeddc`):
    history-rewrite item, out of scope. The files are rewritten at the end of
    every session, so real values can re-enter the local copies at any time
    (erosion by session) — re-sanitized in this pass.
    `WARNINGS.md:301` (heavy PAT metadata) remains out of scope, flagged in
    the Fixer report.
  - **(h) `config/.env.example` completed**: `INFOMANIAK_EVENTS_ENDPOINT=` and
    `BEARER_EVENT=` added (one-line comment pointing to
    `skills/deployment-changelog`) — the engine consumes these variables and
    the example must document them without ever carrying real values.
  - **(i) OPSEC gate installed**: `scripts/hooks/opsec-gate.sh` (patterns for
    internal hosts, private package names, internal project paths and naming
    conventions) wired as `pre-commit` + `commit-msg` hooks and enforced
    server-side by `.github/workflows/opsec-scan.yml` — tree, commit
    messages and PR description scanned. Reception suite
    `scripts/test-opsec-gate.mjs` wired into `health-check`.
- **F-02 reopening criterion triggered**: the pre-wave tip documented a
  private events endpoint — the "sensitive component / unauthenticated
  endpoint" reopening criterion from F-02 above applies; reassessment with
  the infrastructure security owner is required.
- **History rewrite deferred** (decision coordinated out-of-repo): the
  release wave's commit message and tag `v1.8.0` still reference internal
  metadata and remain reachable in history; option B (no history rewrite)
  stands on the same benefit/risk ratio as F-02.

## Defense in depth

Local hook + gitleaks are necessary but **not sufficient** (local config can be
bypassed): `.github/workflows/secret-scan.yml` runs the same scanners
server-side on every push/PR; branch protection should require that check
before integration on `main`. Changes to hooks, gitleaks config and the fixture
suite are security-sensitive paths — review them as such.

Limits: static scanners cannot detect dynamically built values; the fixture
suite documents the detection surface, it does not claim exhaustiveness.
