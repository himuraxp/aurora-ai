import pg from 'pg';

/**
 * Port DB : Pool (service), PoolClient (transactions) ou Client (tests).
 */
export type DbClient = pg.Pool | pg.PoolClient | pg.Client;

let pool: pg.Pool | undefined;

export function getPool(databaseUrl: string): pg.Pool {
  if (!pool) {
    pool = new pg.Pool({ connectionString: databaseUrl, max: 10 });
    // Sans ce handler, une erreur sur client idle (restart PG, réseau) tue le process stdio.
    pool.on('error', (error: Error) => {
      console.error('[aurora-memory] erreur pool pg (client idle):', error.message);
    });
  }
  return pool;
}

export async function closePool(): Promise<void> {
  if (pool) {
    await pool.end();
    pool = undefined;
  }
}

/** Mappe une valeur TIMESTAMPTZ nullable en `undefined` (convention framework : pas de null). */
export function orUndefined<T>(value: T | null): T | undefined {
  return value ?? undefined;
}
