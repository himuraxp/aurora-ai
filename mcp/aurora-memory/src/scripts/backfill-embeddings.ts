/**
 * Backfill des embeddings d'entités (ADR-022) — idempotent et rejouable.
 * Cible : entités sans embedding, ou indexées avec un modèle différent du modèle courant.
 *
 * Usage (cwd = services/aurora-memory) :
 *   npm run embeddings:backfill               # applique
 *   npm run embeddings:backfill -- --dry-run  # liste sans écrire
 *   npm run embeddings:backfill -- --force    # ré-embede tout (modèle changé)
 *   npm run embeddings:backfill -- --limit 50
 */
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import type { Pool } from 'pg';
import dotenv from 'dotenv';
import { loadEnv, type Env } from '../config/env.ts';
import { getPool, closePool } from '../repositories/db.ts';
import { upsertEmbedding } from '../repositories/kg.repository.ts';
import { EmbeddingClient, entityEmbeddingText, type Embedder } from '../services/embedding.client.ts';

export interface BackfillOptions {
  /** Ré-embede toutes les entités, même déjà indexées avec le modèle courant. */
  force?: boolean;
  /** Plafond d'entités traitées par exécution. */
  limit?: number;
  /** Liste les cibles sans écrire. */
  dryRun?: boolean;
}

export interface BackfillResult {
  /** Entités éligibles trouvées. */
  candidates: number;
  /** Embeddings écrits (0 en dry-run). */
  embedded: number;
  /** Échecs provider (l'entité reste à rattraper au prochain run). */
  failed: number;
  mode: 'dry-run' | 'applied';
}

interface EntityRow {
  id: string;
  type: string;
  name: string;
  metadata: Record<string, unknown>;
}

/**
 * Coeur du backfill, injectable (db + embedder) pour les tests.
 * Séquentiel volontairement : volume personnel, le batching n'est pas un besoin mesuré.
 */
export async function runBackfill(
  db: Pool,
  embedder: Embedder,
  options: BackfillOptions = {},
): Promise<BackfillResult> {
  const { force = false, limit = 1000, dryRun = false } = options;
  if (!embedder.configured) {
    throw new Error('Embeddings non configurés (EMBEDDING_API_BASE / EMBEDDING_API_KEY / EMBEDDING_MODEL).');
  }

  const selection = force
    ? `SELECT e.id, e.type, e.name, e.metadata
       FROM entities e
       ORDER BY e.created_at ASC
       LIMIT $1`
    : `SELECT e.id, e.type, e.name, e.metadata
       FROM entities e
       LEFT JOIN embeddings em ON em.entity_id = e.id
       WHERE em.entity_id IS NULL OR em.model <> $2
       ORDER BY e.created_at ASC
       LIMIT $1`;
  const params = force ? [limit] : [limit, embedder.model];

  const result = await db.query<EntityRow>(selection, params);
  const rows = result.rows;

  if (dryRun) {
    return { candidates: rows.length, embedded: 0, failed: 0, mode: 'dry-run' };
  }

  let embedded = 0;
  let failed = 0;
  for (const row of rows) {
    const entity = { type: row.type, name: row.name, metadata: row.metadata ?? {} };
    try {
      const vector = await embedder.embed(entityEmbeddingText(entity));
      await upsertEmbedding(db, row.id, vector, embedder.model);
      embedded += 1;
    } catch (error) {
      failed += 1;
      console.error(
        `[backfill] échec embedding « ${row.type}/${row.name} »:`,
        error instanceof Error ? error.message : error,
      );
    }
  }
  return { candidates: rows.length, embedded, failed, mode: 'applied' };
}

function repoRoot(): string {
  // src/scripts/backfill-embeddings.ts → 4 niveaux au-dessus = racine du repo aurora-core
  return join(fileURLToPath(new URL('../../../../', import.meta.url)));
}

async function main(): Promise<void> {
  dotenv.config({ path: join(repoRoot(), '.env') });
  const env: Env = loadEnv(process.env);
  const args = process.argv.slice(2);
  const limitIndex = args.indexOf('--limit');
  const rawLimit = limitIndex >= 0 ? Number(args[limitIndex + 1]) : undefined;
  if (rawLimit !== undefined && (!Number.isInteger(rawLimit) || rawLimit <= 0)) {
    console.error('[embeddings:backfill] --limit doit être un entier positif (reçu: ' + args[limitIndex + 1] + ')');
    process.exit(1);
  }
  const options: BackfillOptions = {
    force: args.includes('--force'),
    dryRun: args.includes('--dry-run'),
    limit: rawLimit,
  };

  const db = getPool(env.DATABASE_URL);
  try {
    const summary = await runBackfill(db, new EmbeddingClient(env), options);
    console.log(
      `[backfill] mode=${summary.mode} candidats=${summary.candidates} embeddes=${summary.embedded} echecs=${summary.failed}`,
    );
    if (summary.mode === 'applied' && summary.embedded === 0 && summary.failed > 0) {
      process.exit(1); // provider en échec : ne pas masquer, re-jouer quand rétabli
    }
  } finally {
    await closePool();
  }
}

// CLI uniquement (les tests importent runBackfill directement).
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch((error: unknown) => {
    console.error('[embeddings:backfill] échec:', error instanceof Error ? error.message : error);
    process.exit(1);
  });
}
