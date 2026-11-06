#!/usr/bin/env node
/**
 * test-opsec-gate.mjs — Reception suite for the OPSEC metadata gate
 * (scripts/hooks/opsec-gate.sh, pure bash + grep, no dependencies).
 *
 * Covers: per-pattern detection (internal GitLab host + .com variant,
 * staff portal, private composer packages, internal project paths, internal
 * route-file naming, project codenames), skip list (gate sources and the
 * acceptance record are never scanned), all four modes (--files, --message,
 * --stdin, --staged with a throwaway git repo), and the permanent
 * false-positive guard: the gate must stay clean on this repository's
 * tracked tree, otherwise the pattern list has drifted.
 *
 * Run: node scripts/test-opsec-gate.mjs   (no node version constraint)
 */

import assert from "node:assert/strict"
import { execFileSync, spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"

const ROOT = path.resolve(new URL("..", import.meta.url).pathname)
const GATE = path.join(ROOT, "scripts/hooks/opsec-gate.sh")

// One leak sample per pattern in PATTERNS[] of opsec-gate.sh.
const SAMPLES = [
  "git clone git@gitlab.infomaniak.ch:group/project.git",
  "git clone git@gitlab.infomaniak.com:group/project.git",
  "portal: internal.infomaniak.com",
  "composer require infomaniak/api-normalization",
  "path: infomaniak/media/site-manager",
  "routes file: api_internal_no_auth.php",
  "project: site-admin3-material",
]

function tmpdir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "opsec-gate-"))
}

function run(args, opts = {}) {
  return spawnSync("bash", [GATE, ...args], { encoding: "utf8", ...opts })
}

// 1. Detection: each sample leaks (per-pattern, via --files)

for (const sample of SAMPLES) {
  const dir = tmpdir()
  const file = path.join(dir, "leak.md")
  fs.writeFileSync(file, `# clean line\n${sample}\n# another clean line\n`)
  const r = run(["--files", file])
  assert.equal(r.status, 1, `gate must fail on sample: ${sample}\n${r.stdout}`)
  assert.match(r.stdout, /OPSEC:/, `report must mention the match: ${sample}`)
}

// 2. Clean content passes (no false positive on ordinary prose)

{
  const dir = tmpdir()
  const file = path.join(dir, "clean.md")
  fs.writeFileSync(file, "# Setup\n\nRun the installer, then configure the provider from the environment.\n")
  const r = run(["--files", file])
  assert.equal(r.status, 0, `gate must pass on clean content\n${r.stdout}`)
}

// 3. Skip list: gate sources and the acceptance record are never scanned

for (const name of ["SECURITY-ACCEPTANCE.md", "opsec-gate.sh", "test-opsec-gate.mjs", "opsec-scan.yml"]) {
  const dir = tmpdir()
  const file = path.join(dir, name)
  fs.writeFileSync(file, SAMPLES.join("\n"))
  const r = run(["--files", file])
  assert.equal(r.status, 0, `skipped basename must not be scanned: ${name}\n${r.stdout}`)
}

// 4. --message mode: commit message channel

{
  const dir = tmpdir()
  const leaky = path.join(dir, "msg.txt")
  fs.writeFileSync(leaky, "feat: add standard\n\ncalibrated on the internal gitlab.infomaniak.ch backend survey\n")
  assert.equal(run(["--message", leaky]).status, 1, "message mode must catch a leaky commit message")
  const clean = path.join(dir, "msg-clean.txt")
  fs.writeFileSync(clean, "feat: add standard\n\nadds the PHP/Laravel framework, WordPress example and detection\n")
  assert.equal(run(["--message", clean]).status, 0, "message mode must pass a clean message")
}

// 5. --stdin mode: free-text channel (PR body)

{
  const r = run(["--stdin"], { input: "body mentioning internal.infomaniak.com and more\n" })
  assert.equal(r.status, 1, "stdin mode must catch a leaky PR body")
  const ok = run(["--stdin"], { input: "body with only public identifiers\n" })
  assert.equal(ok.status, 0, "stdin mode must pass a clean PR body")
}

// 6. --staged mode: end to end on a throwaway git repository

{
  const repo = tmpdir()
  execFileSync("git", ["init", "-q"], { cwd: repo })
  execFileSync("git", ["-C", repo, "config", "user.email", "test@example.com"])
  execFileSync("git", ["-C", repo, "config", "user.name", "test"])
  fs.writeFileSync(path.join(repo, "base.txt"), "initial\n")
  execFileSync("git", ["-C", repo, "add", "base.txt"])
  execFileSync("git", ["-C", repo, "commit", "-qm", "initial"])

  fs.writeFileSync(path.join(repo, "leak.md"), "adds infomaniak/media/site-manager\n")
  fs.writeFileSync(path.join(repo, "SECURITY-ACCEPTANCE.md"), "quotes gitlab.infomaniak.ch for the record\n")
  execFileSync("git", ["-C", repo, "add", "."])

  const r = run(["--staged"], { cwd: repo })
  assert.equal(r.status, 1, "staged mode must catch the leaky addition\n" + r.stdout)
  assert.match(r.stdout, /leak\.md/, "report must name the leaking file")
  assert.doesNotMatch(r.stdout, /SECURITY-ACCEPTANCE\.md matches/, "skipped basename must not appear as a match")

  const cleanRepo = tmpdir()
  execFileSync("git", ["init", "-q"], { cwd: cleanRepo })
  execFileSync("git", ["-C", cleanRepo, "config", "user.email", "test@example.com"])
  execFileSync("git", ["-C", cleanRepo, "config", "user.name", "test"])
  fs.writeFileSync(path.join(cleanRepo, "base.txt"), "initial\n")
  execFileSync("git", ["-C", cleanRepo, "add", "base.txt"])
  const clean = run(["--staged"], { cwd: cleanRepo })
  assert.equal(clean.status, 0, "staged mode must pass clean staging\n" + clean.stdout)
}

// 7. Permanent false-positive guard: the gate must be clean on this
//    repository's tracked tree. A failure here means a pattern drifted and
//    now matches legitimate public content — tune the pattern, not the suite.

{
  const tracked = execFileSync("git", ["ls-files"], { cwd: ROOT, encoding: "utf8" })
    .split("\n")
    .filter(Boolean)
  assert.ok(tracked.length > 100, "sanity: the repository has tracked files")
  const r = run(["--files", ...tracked], { cwd: ROOT })
  assert.equal(r.status, 0, `gate must be clean on the tracked tree (false positive?):\n${r.stdout}`)
}

console.log("opsec-gate reception suite: all assertions passed")
