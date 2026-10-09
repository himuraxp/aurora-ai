/**
 * Figma API client with rate limiting, backoff, and batching
 */
/**
 * Thrown when Figma blocks an endpoint with a long Retry-After
 * (plan-level API quota / content paywall — not a transient burst limit).
 * Retrying is pointless until the quota resets; callers should degrade gracefully.
 */
export class FigmaQuotaError extends Error {
    resetAt;
    constructor(message, resetAt = null) {
        super(message);
        this.name = 'FigmaQuotaError';
        this.resetAt = resetAt;
    }
}
/**
 * Typed HTTP error carrying the response status — replaces substring-based detection.
 */
export class HttpError extends Error {
    status;
    body;
    constructor(status, body) {
        super(`HTTP ${status}: ${body.slice(0, 200)}`);
        this.name = 'HttpError';
        this.status = status;
        this.body = body;
    }
}
export class FigmaClient {
    token;
    baseUrl = 'https://api.figma.com/v1';
    rateLimitConfig;
    requestQueue = [];
    requestCount = 0;
    constructor(token, rateLimitConfig = { maxRequestsPerMinute: 100, burstSize: 10 }) {
        this.token = token;
        this.rateLimitConfig = rateLimitConfig;
    }
    async waitForSlot() {
        const windowMs = 60_000;
        const now = Date.now();
        // Keep only requests from the last minute
        this.requestQueue = this.requestQueue.filter(t => now - t < windowMs);
        if (this.requestQueue.length >= this.rateLimitConfig.maxRequestsPerMinute) {
            // Wait until the oldest request ages out of the 1-minute window
            const oldestInWindow = this.requestQueue[0];
            const waitMs = windowMs - (now - oldestInWindow) + 100;
            await new Promise(resolve => setTimeout(resolve, Math.max(waitMs, 1000)));
            return this.waitForSlot();
        }
    }
    async fetch(endpoint, retries = 3) {
        await this.waitForSlot();
        this.requestQueue.push(Date.now());
        const url = `${this.baseUrl}${endpoint}`;
        const headers = {
            'X-Figma-Token': this.token,
            'Accept': 'application/json'
        };
        try {
            const response = await fetch(url, { headers });
            this.requestCount++;
            if (response.status === 429) {
                const retryAfterHeader = response.headers.get('Retry-After');
                const retryAfter = retryAfterHeader ? parseInt(retryAfterHeader, 10) : NaN;
                // Long Retry-After = plan-level quota (content paywall). Fail fast, never loop.
                if (Number.isNaN(retryAfter) || retryAfter > 120) {
                    const resetAt = Number.isNaN(retryAfter) ? null : new Date(Date.now() + retryAfter * 1000);
                    const humanReset = resetAt ? ` (reset ≈ ${resetAt.toISOString()})` : '';
                    throw new FigmaQuotaError(`Figma API quota exhausted for endpoint ${endpoint}. Retry-After: ${retryAfter}s${humanReset}`, resetAt);
                }
                // Short Retry-After = transient burst limit. Wait exactly what Figma asks,
                // but hard-stop after 3 consecutive bursts to never suspend the process.
                if (retries <= 0) {
                    throw new FigmaQuotaError(`Burst rate limit still hit after 3 retries: ${endpoint}`);
                }
                console.error(`Burst rate limit hit. Waiting ${retryAfter}s... (${retries} bursts left)`);
                await new Promise(resolve => setTimeout(resolve, retryAfter * 1000 + 500));
                return this.fetch(endpoint, retries - 1);
            }
            if (!response.ok) {
                const text = await response.text();
                throw new HttpError(response.status, text);
            }
            return await response.json();
        }
        catch (error) {
            // Quota errors must propagate immediately — retrying changes nothing.
            if (error instanceof FigmaQuotaError)
                throw error;
            // Only retry server errors or network failures, never client errors (4xx).
            const isServerError = error instanceof HttpError && error.status >= 500;
            const isNetworkError = error instanceof TypeError;
            if (retries > 0 && (isServerError || isNetworkError)) {
                const backoffMs = Math.min(1000 * Math.pow(2, 3 - retries), 10000);
                console.error(`Request failed, retrying in ${backoffMs}ms... (${retries} retries left)`);
                await new Promise(resolve => setTimeout(resolve, backoffMs));
                return this.fetch(endpoint, retries - 1);
            }
            throw error;
        }
    }
    async getMe() {
        const data = await this.fetch('/me');
        return data;
    }
    async getFile(key, depth = 1) {
        return this.fetch(`/files/${key}?depth=${depth}`);
    }
    async getStyles(key) {
        return this.fetch(`/files/${key}/styles`);
    }
    async getComponents(key) {
        return this.fetch(`/files/${key}/components`);
    }
    async getComponentSets(key) {
        return this.fetch(`/files/${key}/component_sets`);
    }
    async getVariablesLocal(key) {
        return this.fetch(`/files/${key}/variables/local`);
    }
    async getVersions(key) {
        return this.fetch(`/files/${key}/versions`);
    }
    async getNodes(key, ids, depth = 1) {
        const idsParam = ids.join(',');
        return this.fetch(`/files/${key}/nodes?ids=${idsParam}&depth=${depth}`);
    }
    async batchGetNodes(key, ids, depth = 1) {
        const BATCH_SIZE = 50;
        const result = {};
        for (let i = 0; i < ids.length; i += BATCH_SIZE) {
            const batch = ids.slice(i, i + BATCH_SIZE);
            console.log(`Fetching node batch ${Math.floor(i / BATCH_SIZE) + 1}: ${batch.length} nodes`);
            try {
                const data = await this.getNodes(key, batch, depth);
                Object.assign(result, data.documents || {});
            }
            catch (error) {
                // Quota exhaustion is global: stop batching immediately, let the caller degrade.
                if (error instanceof FigmaQuotaError)
                    throw error;
                console.error(`Failed to fetch batch starting at ${ids[i]}:`, error);
            }
        }
        return result;
    }
    getRequestCount() {
        return this.requestCount;
    }
}
