/**
 * Token resolution tests — ANGULAR_ELEMENTS_GITLAB_TOKEN (nominal, dedicated) vs
 * GITLAB_TOKEN (deprecated transitional fallback). Run with `npm test`.
 *
 * No network access, no real credentials: the .env source is redirected via
 * ANGULAR_ELEMENTS_ENV_FILE so the developer's real ~/.config/opencode/.env
 * never interferes with the assertions.
 */
import { test, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Startup configuration (allowlist, endpoints) — synthetic, never contacted.
process.env.ANGULAR_ELEMENTS_ALLOWED_ORIGINS =
  "https://gitlab.example.com,https://pages.example.com";
process.env.ANGULAR_ELEMENTS_GITLAB_API = "https://gitlab.example.com/api/v4";
process.env.ANGULAR_ELEMENTS_PROJECT_ID = "1234";
process.env.ANGULAR_ELEMENTS_STORYBOOK_BASE =
  "https://pages.example.com/front/angular-elements";

const envFile = path.join(os.tmpdir(), `ae-mcp-token-env-${process.pid}.env`);
fs.writeFileSync(envFile, "GITLAB_TOKEN=_from-env-file\n");
process.env.ANGULAR_ELEMENTS_ENV_FILE = envFile;

const emptyEnvFile = path.join(os.tmpdir(), `ae-mcp-token-empty-${process.pid}.env`);
fs.writeFileSync(emptyEnvFile, "");

after(() => {
  fs.rmSync(envFile, { force: true });
  fs.rmSync(emptyEnvFile, { force: true });
});

const { getToken, validateStartupConfig } = await import("../dist/client.js");

function withCapturedStderr(fn) {
  const lines = [];
  const original = console.error;
  console.error = (...args) => lines.push(args.join(" "));
  try {
    return { result: fn(), lines };
  } finally {
    console.error = original;
  }
}

test("dedicated ANGULAR_ELEMENTS_GITLAB_TOKEN wins over the legacy fallback, no warning", () => {
  process.env.ANGULAR_ELEMENTS_GITLAB_TOKEN = "dedicated-token";
  process.env.GITLAB_TOKEN = "_legacy-token_";
  const { result, lines } = withCapturedStderr(() => getToken());
  assert.equal(result, "dedicated-token");
  assert.equal(lines.length, 0);
});

test("legacy GITLAB_TOKEN (env) is accepted as a fallback, warns exactly once", () => {
  delete process.env.ANGULAR_ELEMENTS_GITLAB_TOKEN;
  const first = withCapturedStderr(() => getToken());
  assert.equal(first.result, "_legacy-token_");
  assert.equal(first.lines.length, 1);
  assert.match(first.lines[0], /deprecated transitional/);
  assert.match(first.lines[0], /ANGULAR_ELEMENTS_GITLAB_TOKEN/);

  // a second resolution does not repeat the warning
  const second = withCapturedStderr(() => getToken());
  assert.equal(second.result, "_legacy-token_");
  assert.equal(second.lines.length, 0);
});

test("a token declared only in the .env file is resolved (same fallback rules)", () => {
  delete process.env.GITLAB_TOKEN;
  const { result, lines } = withCapturedStderr(() => getToken());
  assert.equal(result, "_from-env-file");
  // the once-only warning was already emitted by the previous test
  assert.equal(lines.length, 0);
});

test("no token anywhere fails closed with an explicit error naming the nominal variable", () => {
  delete process.env.ANGULAR_ELEMENTS_GITLAB_TOKEN;
  delete process.env.GITLAB_TOKEN;
  process.env.ANGULAR_ELEMENTS_ENV_FILE = emptyEnvFile;
  try {
    assert.throws(() => getToken(), /ANGULAR_ELEMENTS_GITLAB_TOKEN is not set/);
    // startup validation enforces the same contract, fail-closed
    assert.throws(() => validateStartupConfig(), /ANGULAR_ELEMENTS_GITLAB_TOKEN is not set/);
  } finally {
    process.env.ANGULAR_ELEMENTS_ENV_FILE = envFile;
  }
});
