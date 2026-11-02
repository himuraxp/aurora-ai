#!/usr/bin/env node
/**
 * Runner de migrations — COPIE DE DISTRIBUTION (ADR-025).
 *
 * Réplique exactement la sémantique du runner upstream
 * (aurora-core/services/aurora-memory/src/scripts/migrate.ts) : table
 * schema_migrations (filename PK, applied_at), un fichier = une transaction
 * (BEGIN / INSERT / COMMIT, ROLLBACK sinon), fichiers *.sql triés, déjà
 * appliquées sautées, erreurs trapées (« [migrate] échec » + exit 1). L'état
 * ainsi produit est compatible avec le runner upstream (même table, mêmes
 * colonnes).
 *
 * Différence assumée : les chemins se résolvent relativement à CE fichier
 * (l'heuristique « racine du repo » de l'upstream est invalide hors du layout
 * aurora-core). DATABASE_URL provient de process.env (prioritaire), sinon du
 * .env à la racine du clone opencode-config — LE MÊME fichier que lit le
 * bundle (heuristique dotenv 3-niveaux au-dessus de dist/ et de scripts/).
 *
 * Usage : node scripts/migrate.mjs   (cwd quelconque)
 */
import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';
import pg from 'pg';
import dotenv from 'dotenv';

const serverRoot = dirname(dirname(fileURLToPath(import.meta.url))); // mcp/aurora-memory/
const configRoot = dirname(fileURLToPath(new URL('../../../', import.meta.url))); // identique au bundle : 3 niveaux au-dessus de dist/ ou scripts/

dotenv.config({ path: join(configRoot, '.env') });

async function run() {
  const DATABASE_URL = process.env.DATABASE_URL;
  if (!DATABASE_URL || !DATABASE_URL.startsWith('postgres')) {
    console.error('[migrate] DATABASE_URL manquante ou invalide (attendu : postgres://…).');
    console.error('  → Renseigne-la dans ' + join(configRoot, '.env') + ' (fichier lu par le bundle) ou exporte-la.');
    process.exit(1);
  }

  const migrationsDir = process.env.MIGRATIONS_DIR ?? join(serverRoot, 'infra', 'migrations');
  const client = new pg.Client({ connectionString: DATABASE_URL });

  try {
    await client.connect();
    await client.query(`CREATE TABLE IF NOT EXISTS schema_migrations (
      filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())`);

    const files = (await readdir(migrationsDir)).filter((f) => f.endsWith('.sql')).sort();
    for (const file of files) {
      const applied = await client.query(`SELECT 1 FROM schema_migrations WHERE filename = $1`, [file]);
      if (applied.rowCount && applied.rowCount > 0) {
        console.log(`= ${file} (déjà appliquée)`);
        continue;
      }
      const sql = await readFile(join(migrationsDir, file), 'utf8');
      await client.query('BEGIN');
      try {
        await client.query(sql);
        await client.query(`INSERT INTO schema_migrations (filename) VALUES ($1)`, [file]);
        await client.query('COMMIT');
        console.log(`+ ${file} appliquée`);
      } catch (error) {
        await client.query('ROLLBACK');
        throw error;
      }
    }
  } finally {
    await client.end();
  }
}

run().catch((error) => {
  console.error('[migrate] échec:', error instanceof Error ? error.message : error);
  process.exit(1);
});
