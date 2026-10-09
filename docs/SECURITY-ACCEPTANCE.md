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

## Defense in depth

Local hook + gitleaks are necessary but **not sufficient** (local config can be
bypassed): `.github/workflows/secret-scan.yml` runs the same scanners
server-side on every push/PR; branch protection should require that check
before integration on `main`. Changes to hooks, gitleaks config and the fixture
suite are security-sensitive paths — review them as such.

Limits: static scanners cannot detect dynamically built values; the fixture
suite documents the detection surface, it does not claim exhaustiveness.
