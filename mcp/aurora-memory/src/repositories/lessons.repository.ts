import type { DbClient } from './db.ts';
import { orUndefined } from './db.ts';
import type { Lesson, LessonInitialStatus, LessonProvenance, LessonStatus } from '../models/types.ts';

interface LessonRow {
  id: string;
  status: LessonStatus;
  title: string;
  lesson: string;
  context: Record<string, unknown>;
  scope: string | null;
  confidence: string; // NUMERIC → string côté pg, converti par toLesson
  provenance_class: LessonProvenance;
  source_id: string;
  supersedes_id: string | null;
  valid_from: Date;
  valid_until: Date | null;
  created_at: Date;
  updated_at: Date;
}

function toLesson(row: LessonRow): Lesson {
  return {
    id: row.id,
    status: row.status,
    title: row.title,
    lesson: row.lesson,
    context: row.context,
    scope: orUndefined(row.scope),
    confidence: Number(row.confidence),
    provenanceClass: row.provenance_class,
    sourceId: row.source_id,
    supersedesId: orUndefined(row.supersedes_id),
    validFrom: row.valid_from,
    validUntil: orUndefined(row.valid_until),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export interface LessonInsert {
  title: string;
  lesson: string;
  context: Record<string, unknown>;
  scope?: string;
  confidence: number;
  provenanceClass: LessonProvenance;
  initialStatus: LessonInitialStatus;
  sourceId: string;
  supersedesId?: string;
  validUntil?: Date;
}

export async function insertLesson(db: DbClient, input: LessonInsert): Promise<Lesson> {
  const result = await db.query<LessonRow>(
    `INSERT INTO lessons (status, title, lesson, context, scope, confidence, provenance_class, source_id, supersedes_id, valid_until)
     VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10) RETURNING *`,
    [
      input.initialStatus,
      input.title,
      input.lesson,
      JSON.stringify(input.context),
      input.scope ?? null,
      input.confidence,
      input.provenanceClass,
      input.sourceId,
      input.supersedesId ?? null,
      input.validUntil ?? null,
    ],
  );
  return toLesson(result.rows[0] as LessonRow);
}

export async function findLessonById(db: DbClient, id: string): Promise<Lesson | undefined> {
  const result = await db.query<LessonRow>(`SELECT * FROM lessons WHERE id = $1`, [id]);
  const row = result.rows[0];
  return row ? toLesson(row) : undefined;
}

export async function listLessons(
  db: DbClient,
  status: LessonStatus | undefined,
  scope: string | undefined,
  limit: number,
): Promise<Lesson[]> {
  const result = await db.query<LessonRow>(
    `SELECT * FROM lessons
     WHERE ($1::text IS NULL OR status = $1)
       AND ($2::text IS NULL OR scope = $2)
     ORDER BY created_at DESC
     LIMIT $3`,
    [status ?? null, scope ?? null, limit],
  );
  return result.rows.map(toLesson);
}

export async function updateLessonStatus(
  db: DbClient,
  id: string,
  status: LessonStatus,
): Promise<Lesson> {
  // Déchéance expired : ferme la fenêtre de validité (COALESCE préserve une date antérieure).
  const result = await db.query<LessonRow>(
    `UPDATE lessons SET
       status = $2,
       valid_until = CASE WHEN $2 = 'expired' THEN COALESCE(valid_until, now()) ELSE valid_until END,
       updated_at = now()
     WHERE id = $1
     RETURNING *`,
    [id, status],
  );
  const row = result.rows[0];
  if (!row) {
    throw new Error(`Lesson ${id} non retournée par UPDATE.`);
  }
  return toLesson(row);
}
