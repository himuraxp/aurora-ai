# Changelog

## [1.7.0](https://github.com/himuraxp/aurora-ai/compare/v1.6.0...v1.7.0) (2026-10-28)


### Features

* **config:** add Infomaniak official calendar MCP (locked locally via setup-mcp-lock) ([6fa7196](https://github.com/himuraxp/aurora-ai/commit/6fa7196ad30aa9f2fb3e0aa1a0b49ce73a243a82))
* **config:** add Infomaniak official calendar MCP (locked locally) ([5c65f24](https://github.com/himuraxp/aurora-ai/commit/5c65f24710283241adf27087fa5ef0dee4b072f9))
* **config:** Sync model catalog with Infomaniak live API ([f239086](https://github.com/himuraxp/aurora-ai/commit/f239086d6b4ab27682f65617168cde2201a4f19f))
* **mail-triage:** add autonomous IMAP triage engine and kChat digest ([9877fe3](https://github.com/himuraxp/aurora-ai/commit/9877fe33c42a64ad82f0a67f6722bf7b47ade96e))


### Bug Fixes

* **config:** point spark and fixer at catalogue-valid models, refresh docs ([9eb688d](https://github.com/himuraxp/aurora-ai/commit/9eb688d379313659e98cd39f9b6e6fdaf8f21bdb))
* **config:** point spark and fixer at catalogue-valid models, refresh docs ([f95bae6](https://github.com/himuraxp/aurora-ai/commit/f95bae6fee82d8f055c9f187c02835d6f3c9a50e))
* **mail-triage:** require kchat.base_url in private config — no default instance URL ([3b93025](https://github.com/himuraxp/aurora-ai/commit/3b9302522bc2ef65d9df3bd5877f12ce34d64e46))

## [1.6.0](https://github.com/himuraxp/aurora-ai/compare/v1.5.0...v1.6.0) (2026-10-26)


### Features

* **config:** enable experimental background compaction ([b0bd649](https://github.com/himuraxp/aurora-ai/commit/b0bd649ac6374698eeae959a29565cffbd4272fd))
* **config:** enable experimental background compaction ([6e8d75e](https://github.com/himuraxp/aurora-ai/commit/6e8d75e403cf1cc5e63d430aa0788412294ec4c6))
* **config:** enable experimental background compaction ([#58](https://github.com/himuraxp/aurora-ai/issues/58)) ([b0bd649](https://github.com/himuraxp/aurora-ai/commit/b0bd649ac6374698eeae959a29565cffbd4272fd))
* **plugins:** auto-trigger ai-cowork skill on ChatGPT conversation links ([#61](https://github.com/himuraxp/aurora-ai/issues/61)) ([387495e](https://github.com/himuraxp/aurora-ai/commit/387495e8663d45c1e94d1f6d38b16461e16a01b8))

## [1.5.0](https://github.com/himuraxp/aurora-ai/compare/v1.4.0...v1.5.0) (2026-10-24)


### Features

* **config:** enable experimental todo tool for in-session task visibility ([a9b7abd](https://github.com/himuraxp/aurora-ai/commit/a9b7abdfd8fb8d3dd01f12f9a2b628a006828148))
* **config:** enable experimental todo tool for in-session task visibility ([e6b3309](https://github.com/himuraxp/aurora-ai/commit/e6b3309bf37bd2a27efec1798e3ec38550b31c22))
* **config:** enable experimental todo tool for in-session task visibility ([#56](https://github.com/himuraxp/aurora-ai/issues/56)) ([a9b7abd](https://github.com/himuraxp/aurora-ai/commit/a9b7abdfd8fb8d3dd01f12f9a2b628a006828148))

## [1.4.0](https://github.com/himuraxp/aurora-ai/compare/v1.3.0...v1.4.0) (2026-10-24)


### Features

* **graph-engineering:** add execution graph core M1-M4 — transition engine (legal-state table, transitive invalidation, journal-revision staleness), transactional JSONL persistence (checksummed, fsync, rebuildable projection), fenced scheduler (positional fencing, journaled effect protocol), contracts with two-level I9 ([#49](https://github.com/himuraxp/aurora-ai/pull/49))
* **graph-engineering:** add M5 MR-analysis pilot running in shadow-run of the current system — sandbox effects, realEffectEmissions: 0, millisecond metrics ([#50](https://github.com/himuraxp/aurora-ai/pull/50))
* **graph-engineering:** add shadow-read-first skill adapter M7 — forced read-only permissions, effectPolicy refused fail-closed, additive and reversible ([#52](https://github.com/himuraxp/aurora-ai/pull/52))
* **config:** enable experimental todo tool for in-session task visibility ([#56](https://github.com/himuraxp/aurora-ai/pull/56))


### Documentation

* **graph-engineering:** add the binding execution-graph RFC ([#48](https://github.com/himuraxp/aurora-ai/pull/48))
* **graph-engineering:** add ADR for execution graph core decisions (D1-D9, known limitations L1-L3 with PO verdicts) ([#51](https://github.com/himuraxp/aurora-ai/pull/51))
* **graph-engineering:** add final QA report before main PR — before/after comparison, executed gates with artifacts, S1-S7 coverage ([#53](https://github.com/himuraxp/aurora-ai/pull/53))


## [1.3.0](https://github.com/himuraxp/aurora-ai/compare/v1.2.0...v1.3.0) (2026-10-23)


### Features

* **create-mr:** add before/after comparison table for front features ([60a3ad7](https://github.com/himuraxp/aurora-ai/commit/60a3ad7e47f93881ff128bbf5fa82cf6ad8ee9d3))
* **create-mr:** add before/after comparison table for front features ([5330bc1](https://github.com/himuraxp/aurora-ai/commit/5330bc1a1552d8843469e86d8b56ef32f04fb199))
* **create-mr:** single-column Visuel table for new components ([de5158b](https://github.com/himuraxp/aurora-ai/commit/de5158bb0678c2655a176327f9ff5f6456539b7d))
* **create-mr:** single-column Visuel table for new components ([ad3b180](https://github.com/himuraxp/aurora-ai/commit/ad3b1807d04d321f82a673042d4af4ad2f05960c))
* **design-qa:** operationalize Figma quota fallback via browser-debug ([ab46c72](https://github.com/himuraxp/aurora-ai/commit/ab46c72a076c0d887927298b2ffd534707818e50))
* **design-qa:** operationalize Figma quota fallback via browser-debug ([f4c53d2](https://github.com/himuraxp/aurora-ai/commit/f4c53d24e8d640096a6bf08ca515d61bd3c5a303))
* **domain-language:** canonical glossary resolution anchored on the main worktree ([7cf1746](https://github.com/himuraxp/aurora-ai/commit/7cf1746ca0bf0a78326f1c3c7f62e71d525a82bd))
* **domain-language:** canonical glossary resolution anchored on the main worktree ([dfb9554](https://github.com/himuraxp/aurora-ai/commit/dfb955425dfe2be91e3128554b1c049e6b1fc331))
* **health-check:** Add self-healing procedure and --fix repair mode for aurora-memory ([66d4e28](https://github.com/himuraxp/aurora-ai/commit/66d4e2867aeee4c6031bd0a8b03b6da49e3173a1))
* **mcp:** backport security hardening and dedicated token variable for angular-elements ([c716384](https://github.com/himuraxp/aurora-ai/commit/c716384fd669dd5cb19302a68d80868015f75892))
* **mcp:** Harden angular-elements MCP with fail-closed startup validation ([3fbdf2a](https://github.com/himuraxp/aurora-ai/commit/3fbdf2a9cea6c651be5467138a52c3ff720d2d90))
* **meeting:** risk-triaged need-clarification mode reusing the question ledger ([4b8b935](https://github.com/himuraxp/aurora-ai/commit/4b8b9353effb2e334e34b541b2953167b5549a81))
* **meeting:** risk-triaged need-clarification mode reusing the question ledger ([cc2e331](https://github.com/himuraxp/aurora-ai/commit/cc2e331c8dcc5577f5e69a4cfc838a530a3e59c0))
* **review:** add Deep Modules interface-complexity criterion ([530af41](https://github.com/himuraxp/aurora-ai/commit/530af413b39ce34e10bea4721886375ae9e74018))
* **review:** add Deep Modules interface-complexity criterion to architect, simplify and pre-mr-review ([c925d12](https://github.com/himuraxp/aurora-ai/commit/c925d12ecf99cee82090427259ecdb71fae873dd))
* **skills:** Add antislop skill suite from vendor ([ab7f491](https://github.com/himuraxp/aurora-ai/commit/ab7f491c2eb8890447692d1e8813230486c0922b))
* **skills:** add domain-language skill for project ubiquitous-language glossary ([bac2513](https://github.com/himuraxp/aurora-ai/commit/bac25138859c1014edd9adc19895ebc0d5dc1097))
* **skills:** add domain-language skill for project ubiquitous-language glossary ([846dc78](https://github.com/himuraxp/aurora-ai/commit/846dc78d6e18f84b566350deffeeff70eeded093))
* **skills:** vendor antislop skills v3.2.21 from miqdadbadjuber/anti-slop ([4364af2](https://github.com/himuraxp/aurora-ai/commit/4364af21fba7a082c9b773edd78477ffee5b489c))
* **skills:** Vendor antislop-code skill for AI comment hygiene ([6626c91](https://github.com/himuraxp/aurora-ai/commit/6626c918aeb5ffaa63e9680a214d259c0e48411e))
* **task-workflow:** Add Phase 7 MR evidence fail-closed guard ([73be71f](https://github.com/himuraxp/aurora-ai/commit/73be71f4903bb96c87c9d4f94daef3501cea0c53))
* **task-workflow:** Add Trello comment script and task-workflow notify integration ([ba03307](https://github.com/himuraxp/aurora-ai/commit/ba03307ba58d190e52461588aeb865f0392f9508))
* **task-workflow:** conditional implementation contract with risk triage and increment discipline ([8e15cb4](https://github.com/himuraxp/aurora-ai/commit/8e15cb4e74012a0e36e7926d912e2e22e936de1e))
* **task-workflow:** Conditional implementation contract with risk triage and increment discipline ([cafde3e](https://github.com/himuraxp/aurora-ai/commit/cafde3ea17f636873f97a2b5b06317eb68c1d04d))
* **task-workflow:** phase-7 MR evidence guard with template/tableau declaration ([d8db4d5](https://github.com/himuraxp/aurora-ai/commit/d8db4d5dfdd7d982e46cfa0e55243037b221abc3))
* **task-workflow:** post MR link to linked Trello card (step 7bis, hybrid cascade) ([473d0d4](https://github.com/himuraxp/aurora-ai/commit/473d0d4266644647f30735924baed445fe46ba7d))


### Bug Fixes

* **create-mr:** make --dry-run glab-free (CI runners have no glab) ([3a4d15f](https://github.com/himuraxp/aurora-ai/commit/3a4d15fc4a157f37b4bf5d82bb016049ea090a2a))
* **create-mr:** make build_body placeholder replacement newline-safe ([65b63b7](https://github.com/himuraxp/aurora-ai/commit/65b63b73e742475a4a20c3bfaf779c56f38b1d37))
* **create-mr:** replace gh-style -F with multipart builder for glab uploads ([f151329](https://github.com/himuraxp/aurora-ai/commit/f1513294d81335258ed90fd9f10c16a62d3a98d8))
* **create-mr:** replace gh-style -F with multipart builder for glab uploads ([2314357](https://github.com/himuraxp/aurora-ai/commit/2314357f4dc55effb8ca581db35ca9a53ea001b2))
* **health-check:** add fail-closed liveness check for aurora-memory ([3c026f2](https://github.com/himuraxp/aurora-ai/commit/3c026f205b81d63022ee3503eb7e9de4ba124782))
* **health-check:** Add fail-closed liveness check for aurora-memory ([58a91ed](https://github.com/himuraxp/aurora-ai/commit/58a91ed67f19d678128c3106782d611bdbbfa22b))
* **health-check:** Fail when design-qa SKILL.md disappears ([2203624](https://github.com/himuraxp/aurora-ai/commit/2203624e613b63e1241e578e74a6c8efea093dc7))
* **pre-mr-review:** replace stray Cyrillic "через" with "via" in Rule 18 text ([d446df0](https://github.com/himuraxp/aurora-ai/commit/d446df0c92c8ee03950c01ebfd7144152768da14))
* **pre-mr-review:** replace stray Cyrillic через with via in Rule 18 text ([ddd78aa](https://github.com/himuraxp/aurora-ai/commit/ddd78aa00a35366440eb40318b424be606764741))

## [1.2.0](https://github.com/himuraxp/aurora-ai/compare/v1.1.0...v1.2.0) (2026-10-16)


### Features

* Add automated semantic release with release-please ([49617e6](https://github.com/himuraxp/aurora-ai/commit/49617e67e513062ff6b3629e8124ab5c9140d7d5))
* **release:** Automate semantic versioning with release-please ([365b88a](https://github.com/himuraxp/aurora-ai/commit/365b88a75d65366ec0b4c6c52fbcc9d818dc7ade))


### Bug Fixes

* **ci:** Remove GITHUB_TOKEN fallback and require RELEASE_PLEASE_TOKEN ([c13e9d7](https://github.com/himuraxp/aurora-ai/commit/c13e9d7bb2b449fe68d2e235157b7759bf371ccd))
* **release:** Require explicit RELEASE_PLEASE_TOKEN for release-please ([76eae4a](https://github.com/himuraxp/aurora-ai/commit/76eae4aaacc84f993b17dfae1b953968639a050c))

## CHANGELOG

All notable changes to this project are documented here, **grouped by release**.

> This file is **auto-generated by [release-please](https://github.com/googleapis/release-please)**
> from Conventional Commits — do not edit manually. Merging the Release PR on
> `main` publishes the next version (`feat:` → minor, `fix:` → patch,
> `feat!:`/`BREAKING CHANGE:` → major).

Historical entries from before semantic versioning (date-based journal) are
archived in [docs/CHANGELOG-dates.md](docs/CHANGELOG-dates.md).
