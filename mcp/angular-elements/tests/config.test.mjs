/**
 * Security policy tests (F-01 allowlist, F-05 encoding) — run with `npm test`
 * (compiles src/ to dist/ then executes node:test against dist/client.js).
 *
 * No network access, no real credentials: every value is synthetic.
 */
import { test } from "node:test";
import assert from "node:assert/strict";

// Allowlist used by every validateEndpoint call below.
process.env.ANGULAR_ELEMENTS_ALLOWED_ORIGINS =
  "https://gitlab.example.com,https://pages.example.com";

const { validateEndpoint, getAllowedOrigins, buildGitlabFileUrl, buildGitlabTreeUrl, assertGitlabUrl } =
  await import("../dist/client.js");

const ORIGINS = ["https://gitlab.example.com", "https://pages.example.com"];

// ─── F-01 — endpoint allowlist ────────────────────────────────────────────────

test("validateEndpoint accepts an exact allowed HTTPS origin", () => {
  const url = validateEndpoint("https://gitlab.example.com/api/v4", "test", ORIGINS);
  assert.equal(url.origin, "https://gitlab.example.com");
  assert.equal(url.pathname, "/api/v4");
});

test("validateEndpoint keeps the base path (api/v4 must survive URL construction)", () => {
  const url = validateEndpoint("https://gitlab.example.com/api/v4", "test", ORIGINS);
  assert.equal(url.pathname, "/api/v4");
});

test("validateEndpoint rejects non-HTTPS origins", () => {
  assert.throws(() => validateEndpoint("http://gitlab.example.com/api/v4", "test", ORIGINS), /HTTPS/);
});

test("validateEndpoint rejects origins outside the allowlist", () => {
  assert.throws(
    () => validateEndpoint("https://evil.example.com/api/v4", "test", ORIGINS),
    /ANGULAR_ELEMENTS_ALLOWED_ORIGINS/,
  );
});

test("validateEndpoint rejects domain-suffix lookalikes (exact origin match)", () => {
  assert.throws(
    () => validateEndpoint("https://gitlab.example.com.evil.io/api/v4", "test", ORIGINS),
    /ANGULAR_ELEMENTS_ALLOWED_ORIGINS/,
  );
});

test("validateEndpoint rejects embedded credentials", () => {
  assert.throws(
    () => validateEndpoint("https://user:pass@gitlab.example.com/api/v4", "test", ORIGINS),
    /credentials/,
  );
});

test("validateEndpoint rejects invalid URLs", () => {
  assert.throws(() => validateEndpoint("not a url", "test", ORIGINS), /not a valid URL/);
});

test("getAllowedOrigins rejects an empty or malformed allowlist", () => {
  const previous = process.env.ANGULAR_ELEMENTS_ALLOWED_ORIGINS;
  try {
    process.env.ANGULAR_ELEMENTS_ALLOWED_ORIGINS = "not-a-url";
    assert.throws(() => getAllowedOrigins(), /comma-separated list of exact HTTPS origins/);
    process.env.ANGULAR_ELEMENTS_ALLOWED_ORIGINS = "  ";
    assert.throws(() => getAllowedOrigins(), /comma-separated list of exact HTTPS origins/);
  } finally {
    process.env.ANGULAR_ELEMENTS_ALLOWED_ORIGINS = previous;
  }
});

// ─── F-05 — URL construction & encoding ──────────────────────────────────────

test("buildGitlabFileUrl encodes special characters in the ref (URLSearchParams, single pass)", () => {
  process.env.ANGULAR_ELEMENTS_GITLAB_API = "https://gitlab.example.com/api/v4";
  process.env.ANGULAR_ELEMENTS_PROJECT_ID = "1234";
  process.env.ANGULAR_ELEMENTS_STORYBOOK_BASE = "https://pages.example.com/front/angular-elements";
  process.env.ANGULAR_ELEMENTS_REF = "feature/ik-button v2";

  const url = buildGitlabFileUrl("projects/button/src/ik-button/ik-button.component.ts");
  assert.equal(url.origin, "https://gitlab.example.com");
  assert.equal(url.pathname, "/api/v4/projects/1234/repository/files/projects%2Fbutton%2Fsrc%2Fik-button%2Fik-button.component.ts/raw");
  // ref encoded exactly once: "/" -> %2F, " " -> %20
  assert.equal(url.searchParams.get("ref"), "feature/ik-button v2");
  assert.ok(url.search.includes("ref=feature%2Fik-button+"), `unexpected encoding: ${url.search}`);
});

test("buildGitlabFileUrl does not allow traversal via ref (query param, encoded)", () => {
  process.env.ANGULAR_ELEMENTS_REF = "../../etc/passwd";
  const url = buildGitlabFileUrl("projects/button/src/x.ts");
  // the ref lives in the query string, fully encoded — never in the path
  assert.ok(!url.pathname.includes(".."), url.pathname);
  assert.equal(url.searchParams.get("ref"), "../../etc/passwd");
});

test("buildGitlabFileUrl encodes spaces in path segments", () => {
  process.env.ANGULAR_ELEMENTS_REF = "main";
  const url = buildGitlabFileUrl("projects/my comp/src/Docs.mdx");
  assert.ok(url.pathname.includes("my%20comp"), url.pathname);
});

test("buildGitlabTreeUrl encodes path and ref via URLSearchParams", () => {
  process.env.ANGULAR_ELEMENTS_REF = "release/2.1";
  const url = buildGitlabTreeUrl("projects/button/src", 50);
  assert.equal(url.pathname, "/api/v4/projects/1234/repository/tree");
  assert.equal(url.searchParams.get("path"), "projects/button/src");
  assert.equal(url.searchParams.get("ref"), "release/2.1");
  assert.equal(url.searchParams.get("per_page"), "50");
  assert.ok(url.search.includes("ref=release%2F2.1"), `unexpected encoding: ${url.search}`);
});

test("buildGitlabFileUrl rejects a non-numeric project id (path-injection guard)", () => {
  process.env.ANGULAR_ELEMENTS_PROJECT_ID = "1234/../../evil";
  assert.throws(() => buildGitlabFileUrl("x.ts"), /numeric GitLab project id/);
});

// ─── F-01 bis — chemin de base restreint + garde token (tour 2) ───────────────

test("validateEndpoint enforces the exact GitLab API path (/api/v4)", () => {
  assert.throws(
    () => validateEndpoint("https://gitlab.example.com/evil", "test", ORIGINS, { requirePath: "/api/v4" }),
    /exactly "\/api\/v4"/,
  );
  // trailing slash tolerated, path stays /api/v4
  const ok = validateEndpoint("https://gitlab.example.com/api/v4/", "test", ORIGINS, {
    requirePath: "/api/v4",
  });
  assert.equal(ok.origin, "https://gitlab.example.com");
});

test("validateEndpoint forbids a root-path Storybook base", () => {
  assert.throws(
    () => validateEndpoint("https://pages.example.com", "test", ORIGINS, { forbidRootPath: true }),
    /application sub-path/,
  );
  assert.doesNotThrow(() =>
    validateEndpoint("https://pages.example.com/front/angular-elements", "test", ORIGINS, {
      forbidRootPath: true,
    }),
  );
});

test("assertGitlabUrl refuses to send the token to a non-GitLab origin", () => {
  // base GitLab validée = https://gitlab.example.com (cachée par les tests précédents)
  assert.doesNotThrow(() =>
    assertGitlabUrl(new URL("https://gitlab.example.com/api/v4/projects/1234/repository/files/x/raw")),
  );
  assert.throws(
    () => assertGitlabUrl(new URL("https://pages.example.com/front/angular-elements/index.json")),
    /Refusing to send the GitLab token/,
  );
  assert.throws(
    () => assertGitlabUrl(new URL("https://gitlab.example.com.evil.io/api/v4/x")),
    /Refusing to send the GitLab token/,
  );
});
