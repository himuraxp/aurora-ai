import type { DbClient } from './db.ts';
import { orUndefined } from './db.ts';
import { getOrCreateSource } from './kg.repository.ts';
import type { Goal, GoalStatus, MemoryEvent } from '../models/types.ts';

interface EventRow {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  occurred_at: Date;
  source_id: string | null;
}

interface GoalRow {
  id: string;
  title: string;
  status: GoalStatus;
  metadata: Record<string, unknown>;
  created_at: Date;
  updated_at: Date;
}

function toEvent(row: EventRow): MemoryEvent {
  return {
    id: row.id,
    type: row.type,
    payload: row.payload,
    occurredAt: row.occurred_at,
    sourceId: orUndefined(row.source_id),
  };
}

function toGoal(row: GoalRow): Goal {
  return {
    id: row.id,
    title: row.title,
    status: row.status,
    metadata: row.metadata,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

/**
 * Append-only (ADR-010). La provenance peut être fournie par id direct ou par
 * couple (sourceKind, sourceRef) — résolue idempotemment (traçabilité INV-5).
 */
export async function appendEvent(
  db: DbClient,
  event: {
    type: string;
    payload: Record<string, unknown>;
    sourceId?: string;
    sourceKind?: string;
    sourceRef?: string;
  },
): Promise<MemoryEvent> {
  let sourceId = event.sourceId;
  if (!sourceId && event.sourceKind && event.sourceRef) {
    const source = await getOrCreateSource(db, event.sourceKind, event.sourceRef);
    sourceId = source.id;
  }
  const result = await db.query<EventRow>(
    `INSERT INTO events (type, payload, source_id) VALUES ($1, $2::jsonb, $3) RETURNING *`,
    [event.type, JSON.stringify(event.payload), sourceId ?? null],
  );
  return toEvent(result.rows[0] as EventRow);
}

export async function listEvents(
  db: DbClient,
  type?: string,
  limit = 20,
): Promise<MemoryEvent[]> {
  const result = await db.query<EventRow>(
    `SELECT * FROM events
     WHERE ($1::text IS NULL OR type = $1)
     ORDER BY occurred_at DESC
     LIMIT $2`,
    [type ?? null, limit],
  );
  return result.rows.map(toEvent);
}

export async function insertGoal(
  db: DbClient,
  title: string,
  metadata: Record<string, unknown>,
): Promise<Goal> {
  const result = await db.query<GoalRow>(
    `INSERT INTO goals (title, metadata) VALUES ($1, $2::jsonb) RETURNING *`,
    [title, JSON.stringify(metadata)],
  );
  return toGoal(result.rows[0] as GoalRow);
}

export async function findGoalById(db: DbClient, id: string): Promise<Goal | undefined> {
  const result = await db.query<GoalRow>(`SELECT * FROM goals WHERE id = $1`, [id]);
  const row = result.rows[0];
  return row ? toGoal(row) : undefined;
}

export async function listGoals(
  db: DbClient,
  status: GoalStatus | undefined,
  limit: number,
): Promise<Goal[]> {
  const result = await db.query<GoalRow>(
    `SELECT * FROM goals
     WHERE ($1::text IS NULL OR status = $1)
     ORDER BY created_at DESC
     LIMIT $2`,
    [status ?? null, limit],
  );
  return result.rows.map(toGoal);
}

export async function updateGoal(
  db: DbClient,
  id: string,
  patch: { status?: GoalStatus; title?: string },
): Promise<Goal> {
  const result = await db.query<GoalRow>(
    `UPDATE goals SET
       status = COALESCE($2, status),
       title = COALESCE($3, title),
       updated_at = now()
     WHERE id = $1
     RETURNING *`,
    [id, patch.status ?? null, patch.title ?? null],
  );
  const row = result.rows[0];
  if (!row) {
    throw new Error(`Goal ${id} non retourné par UPDATE.`);
  }
  return toGoal(row);
}
