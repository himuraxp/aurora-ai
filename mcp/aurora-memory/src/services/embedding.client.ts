import type { Env } from '../config/env.ts';

interface EmbeddingResponse {
  data?: Array<{ embedding?: number[] }>;
}

const EMBED_TIMEOUT_MS = 3000; // un embed sain ≈ 100-500 ms — au-delà, repli/échec rapide
/** Limite de sécurité : le texte source d'un embedding ne dépassera jamais cette taille. */
const MAX_EMBED_TEXT_CHARS = 8000;
/** Clés de metadata incluses dans le contenu indexé (heuristique déterministe, ADR-022). */
const CONTENT_METADATA_KEYS = ['description', 'summary', 'role', 'notes'] as const;

/**
 * Contrat d'embeddings injectable (tests : fake déterministe).
 * `configured` reflète la présence de la configuration provider.
 */
export interface Embedder {
  readonly configured: boolean;
  readonly model: string;
  embed(text: string): Promise<number[]>;
}

/**
 * Client provider d'embeddings compatible OpenAI (ADR-022 : Qwen/Qwen3-Embedding-8B
 * via Infomaniak). Un seul point de code parle au provider — SearchService (requête)
 * et l'indexation write-time du KG (ériture) partagent ce client.
 */
export class EmbeddingClient implements Embedder {
  constructor(private readonly env: Env) {}

  get configured(): boolean {
    return Boolean(
      this.env.EMBEDDING_API_BASE && this.env.EMBEDDING_API_KEY && this.env.EMBEDDING_MODEL,
    );
  }

  get model(): string {
    return this.env.EMBEDDING_MODEL ?? '';
  }

  async embed(text: string): Promise<number[]> {
    if (!this.configured) {
      throw new Error('Embeddings non configurés (EMBEDDING_API_BASE / EMBEDDING_API_KEY / EMBEDDING_MODEL).');
    }
    const response = await fetch(`${this.env.EMBEDDING_API_BASE}/embeddings`, {
      method: 'POST',
      signal: AbortSignal.timeout(EMBED_TIMEOUT_MS),
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${this.env.EMBEDDING_API_KEY}`,
      },
      body: JSON.stringify({ model: this.env.EMBEDDING_MODEL, input: text }),
    });
    if (!response.ok) {
      throw new Error(`Provider d'embeddings en échec (${response.status}) — ne pas exposer la clé.`);
    }
    const payload = (await response.json()) as EmbeddingResponse;
    const embedding = payload.data?.[0]?.embedding;
    if (
      !embedding ||
      embedding.length !== this.env.EMBEDDING_DIM ||
      embedding.some((component) => !Number.isFinite(component))
    ) {
      throw new Error(
        `Embedding invalide : attendu ${this.env.EMBEDDING_DIM} dimensions numériques, reçu ${embedding?.length ?? 0}.`,
      );
    }
    return embedding;
  }
}

/**
 * Contenu indexé pour une entité : type + nom + champs descriptifs de metadata.
 * Fonction pure, partagée par l'indexation write-time et le backfill — le même
 * texte produit toujours le même contenu (re-indexation cohérente).
 */
export function entityEmbeddingText(entity: {
  type: string;
  name: string;
  metadata: Record<string, unknown>;
}): string {
  const parts = [`${entity.type}: ${entity.name}`];
  for (const key of CONTENT_METADATA_KEYS) {
    const value = entity.metadata[key];
    if (typeof value === 'string' && value.trim() !== '') {
      parts.push(`${key}: ${value.trim()}`);
    }
  }
  // Troncature sur points de code (pas de surrogate pair coupée → jamais rejet provider).
  return Array.from(parts.join('\n')).slice(0, MAX_EMBED_TEXT_CHARS).join('');
}
