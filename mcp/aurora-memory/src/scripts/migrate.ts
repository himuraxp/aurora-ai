/**
 * Runner de migrations — applique infra/migrations/*.sql dans l'ordre, traçées dans schema_migrations.
 * Usage : npm run db:migrate (cwd = services/aurora-memory) — DATABASE_URL obligatoire.
 */
import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { Client } from 'pg';
import dotenv from 'dotenv';
import { loadEnv } from '../config/env.ts';

function repoRoot(): string {
  // src/scripts/migrate.ts → 4 niveaux au-dessus = racine du repo aurora-core
  return join(fileURLToPath(new URL('../../../../', import.meta.url)));
}

async function main(): Promise<void> {
  dotenv.config({ path: join(repoRoot(), '.env') });
  const env = loadEnv(process.env);
  const migrationsDir = process.env['MIGRATIONS_DIR'] ?? join(repoRoot(), 'infra', 'migrations');
  const files = (await readdir(migrationsDir)).filter((f) => f.endsWith('.sql')).sort();

  const client = new Client({ connectionString: env.DATABASE_URL });
  await client.connect();
  try {
    await client.query(`CREATE TABLE IF NOT EXISTS schema_migrations (
      filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())`);

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

main().catch((error: unknown) => {
  console.error('[db:migrate] échec:', error instanceof Error ? error.message : error);
  process.exit(1);
});
