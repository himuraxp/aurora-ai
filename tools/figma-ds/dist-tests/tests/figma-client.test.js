/**
 * Tests for src/figma-client.ts — HttpError / FigmaQuotaError contracts, and
 * the instanceof-based 403 (variables scope) detection in captureVariables.
 *
 * captureVariables is tested with a minimal stub client (it only calls
 * client.getVariablesLocal) — no HTTP server needed.
 */
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { FigmaQuotaError, HttpError } from '../src/figma-client.js';
import { captureVariables } from '../src/capture.js';
// ── HttpError ────────────────────────────────────────────────────────────────
describe('HttpError', () => {
    test('exposes status, body and message', () => {
        const err = new HttpError(403, '{"err":"Forbidden"}');
        assert.strictEqual(err.status, 403);
        assert.strictEqual(err.body, '{"err":"Forbidden"}');
        assert.strictEqual(err.message, 'HTTP 403: {"err":"Forbidden"}');
        assert.strictEqual(err.name, 'HttpError');
        assert.ok(err instanceof Error);
    });
    test('truncates long bodies in the message but keeps the full body', () => {
        const long = 'x'.repeat(300);
        const err = new HttpError(500, long);
        assert.strictEqual(err.body, long);
        assert.strictEqual(err.message, `HTTP 500: ${'x'.repeat(200)}`);
    });
    test('status is preserved for 4xx client errors (no retry expected)', () => {
        assert.strictEqual(new HttpError(403, '').status, 403);
        assert.strictEqual(new HttpError(429, '').status, 429);
    });
});
// ── FigmaQuotaError ──────────────────────────────────────────────────────────
describe('FigmaQuotaError', () => {
    test('carries resetAt and is a named Error', () => {
        const at = new Date('2026-09-03T12:00:00Z');
        const err = new FigmaQuotaError('quota exhausted', at);
        assert.strictEqual(err.resetAt, at);
        assert.strictEqual(err.name, 'FigmaQuotaError');
        assert.ok(err instanceof Error);
    });
    test('resetAt defaults to null', () => {
        assert.strictEqual(new FigmaQuotaError('quota').resetAt, null);
    });
});
// ── captureVariables — 403 scope detection (instanceof-based) ───────────────
describe('captureVariables', () => {
    function stubClient(getVariablesLocal) {
        return { getVariablesLocal };
    }
    test('HttpError 403 → unavailable with the "Token missing variables scope" reason', async () => {
        const client = stubClient(async () => {
            throw new HttpError(403, 'scope missing');
        });
        const res = await captureVariables(client, 'KEY');
        assert.deepEqual(res, { status: 'unavailable', reason: 'Token missing variables scope' });
    });
    test('HttpError 500 → unavailable with the raw error message (not the scope reason)', async () => {
        const client = stubClient(async () => {
            throw new HttpError(500, 'boom');
        });
        const res = await captureVariables(client, 'KEY');
        assert.strictEqual(res.status, 'unavailable');
        assert.strictEqual(res.reason, 'HTTP 500: boom');
    });
    test('FigmaQuotaError → unavailable with the quota message', async () => {
        const client = stubClient(async () => {
            throw new FigmaQuotaError('Figma API quota exhausted');
        });
        const res = await captureVariables(client, 'KEY');
        assert.strictEqual(res.status, 'unavailable');
        assert.strictEqual(res.reason, 'Figma API quota exhausted');
    });
    test('success → available with the variables payload', async () => {
        const client = stubClient(async () => ({ variables: [{ id: 'v1' }, { id: 'v2' }] }));
        const res = await captureVariables(client, 'KEY');
        assert.strictEqual(res.status, 'available');
        assert.deepEqual(res.variables, [{ id: 'v1' }, { id: 'v2' }]);
    });
});
