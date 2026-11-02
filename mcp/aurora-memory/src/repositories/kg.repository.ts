import type { DbClient } from './db.ts';
import { orUndefined } from './db.ts';
import type { Entity, Fact, FactProvenance, Relation, Source } from '../models/types.ts';

interface EntityRow {
  id: string;
  type: string;
  name: string;
  metadata: Record<string, unknown>;
  created_at: Date;
  updated_at: Date;
}

interface FactRow {
  id: string;
  subject_id: string;
  predicate: string;
  value: unknown;
  valid_from: Date;
  valid_until: Date | null;
  source_id: string;
  confidence: string;
  provenance_class: FactProvenance;
  created_at: Date;
}

interface RelationRow {
  id: string;
  source_id: string;
  target_id: string;
  type: string;
  metadata: Record<string, unknown>;
  created_at: Date;
}

export function toEntity(row: EntityRow): Entity {
  return {
    id: row.id,
    type: row.type,
    name: row.name,
    metadata: row.metadata,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export function toFact(row: FactRow): Fact {
  return {
    id: row.id,
    subjectId: row.subject_id,
    predicate: row.predicate,
    value: row.value,
    validFrom: row.valid_from,
    validUntil: orUndefined(row.valid_until),
    sourceId: row.source_id,
    confidence: Number(row.confidence),
    provenanceClass: row.provenance_class,
    createdAt: row.created_at,
  };
}

function toRelation(row: RelationRow): Relation {
  return {
    id: row.id,
    sourceId: row.source_id,
    targetId: row.target_id,
    type: row.type,
    metadata: row.metadata,
    createdAt: row.created_at,
  };
}

export async function upsertEntity(
  db: DbClient,
  type: string,
  name: string,
  metadata: Record<string, unknown>,
): Promise<Entity> {
  const result = await db.query<EntityRow>(
    `INSERT INTO entities (type, name, metadata)
     VALUES ($1, $2, $3::jsonb)
     ON CONFLICT (type, name) DO UPDATE
       SET metadata = $3::jsonb, updated_at = now()
     RETURNING *`,
    [type, name, JSON.stringify(metadata)],
  );
  return toEntity(result.rows[0] as EntityRow);
}

/**
 * Indexe (ou met à jour) l'embedding d'une entité. Dérivable à volonté :
 * le backfill reconstruit la table (ADR-022).
 */
export async function upsertEmbedding(
  db: DbClient,
  entityId: string,
  vector: number[],
  model: string,
): Promise<void> {
  await db.query(
    `INSERT INTO embeddings (entity_id, vector, model)
     VALUES ($1, $2::vector, $3)
     ON CONFLICT (entity_id) DO UPDATE
       SET vector = $2::vector, model = $3, created_at = now()`,
    [entityId, `[${vector.join(',')}]`, model],
  );
}

export async function findEntityById(db: DbClient, id: string): Promise<Entity | undefined> {
  const result = await db.query<EntityRow>(`SELECT * FROM entities WHERE id = $1`, [id]);
  const row = result.rows[0];
  return row ? toEntity(row) : undefined;
}

export async function searchEntities(
  db: DbClient,
  query: string,
  type?: string,
  limit = 20,
): Promise<Entity[]> {
  // Échappe les wildcards LIKE/ILIKE (% et _) pour un substring littéral.
  const literal = query.replace(/[\\%_]/g, '\\$&');
  const result = await db.query<EntityRow>(
    `SELECT * FROM entities
     WHERE name ILIKE '%' || $1 || '%' ESCAPE '\\'
       AND ($2::text IS NULL OR type = $2)
     ORDER BY updated_at DESC
     LIMIT $3`,
    [literal, type ?? null, limit],
  );
  return result.rows.map(toEntity);
}

export async function countEntitiesByType(db: DbClient): Promise<Record<string, number>> {
  const result = await db.query<{ type: string; count: string }>(
    `SELECT type, count(*)::text AS count FROM entities GROUP BY type ORDER BY type`,
  );
  const counts: Record<string, number> = {};
  for (const row of result.rows) {
    counts[row.type] = Number(row.count);
  }
  return counts;
}

export async function upsertRelation(
  db: DbClient,
  sourceId: string,
  targetId: string,
  type: string,
  metadata: Record<string, unknown>,
): Promise<Relation> {
  const result = await db.query<RelationRow>(
    `INSERT INTO relations (source_id, target_id, type, metadata)
     VALUES ($1, $2, $3, $4::jsonb)
     ON CONFLICT (source_id, target_id, type) DO UPDATE
       SET metadata = $4::jsonb
     RETURNING *`,
    [sourceId, targetId, type, JSON.stringify(metadata)],
  );
  return toRelation(result.rows[0] as RelationRow);
}

export async function queryRelations(
  db: DbClient,
  entityId: string,
  type?: string,
  limit = 50,
): Promise<Relation[]> {
  const result = await db.query<RelationRow>(
    `SELECT * FROM relations
     WHERE (source_id = $1 OR target_id = $1)
       AND ($2::text IS NULL OR type = $2)
     LIMIT $3`,
    [entityId, type ?? null, limit],
  );
  return result.rows.map(toRelation);
}

export async function getOrCreateSource(
  db: DbClient,
  kind: string,
  ref: string,
): Promise<Source> {
  const result = await db.query<{ id: string; kind: string; ref: string; created_at: Date }>(
    `INSERT INTO sources (kind, ref) VALUES ($1, $2)
     ON CONFLICT (kind, ref) DO UPDATE SET kind = EXCLUDED.kind
     RETURNING *`,
    [kind, ref],
  );
  const row = result.rows[0];
  if (!row) {
    throw new Error(`Source non retournée par INSERT (kind=${kind})`);
  }
  return { id: row.id, kind: row.kind, ref: row.ref, createdAt: row.created_at };
}

/**
 * Clôture les faits encore valides pour (subject, predicate) — révision de croyance (ADR-005).
 * Les faits antérieurs restent historisés (fenêtre valid_from..valid_until).
 */
export async function closeOpenFacts(
  db: DbClient,
  subjectId: string,
  predicate: string,
  closedAt: Date,
): Promise<number> {
  const result = await db.query(
    `UPDATE facts
     SET valid_until = $3
     WHERE subject_id = $1 AND predicate = $2 AND valid_until IS NULL`,
    [subjectId, predicate, closedAt],
  );
  return result.rowCount ?? 0;
}

export async function insertFact(
  db: DbClient,
  fact: {
    subjectId: string;
    predicate: string;
    value: unknown;
    sourceId: string;
    confidence: number;
    provenanceClass: FactProvenance;
    validFrom: Date | undefined;
    validUntil: Date | undefined;
  },
): Promise<Fact> {
  const result = await db.query<FactRow>(
    `INSERT INTO facts (subject_id, predicate, value, valid_from, valid_until, source_id, confidence, provenance_class)
     VALUES ($1, $2, $3::jsonb, COALESCE($4, now()), $5, $6, $7, $8)
     RETURNING *`,
    [
      fact.subjectId,
      fact.predicate,
      JSON.stringify(fact.value),
      fact.validFrom ?? null,
      fact.validUntil ?? null,
      fact.sourceId,
      fact.confidence,
      fact.provenanceClass,
    ],
  );
  return toFact(result.rows[0] as FactRow);
}

export async function queryFacts(
  db: DbClient,
  subjectId: string,
  predicate: string | undefined,
  limit: number,
): Promise<Fact[]> {
  const result = await db.query<FactRow>(
    `SELECT * FROM facts
     WHERE subject_id = $1
       AND ($2::text IS NULL OR predicate = $2)
       AND (valid_until IS NULL OR valid_until > now())
     ORDER BY valid_from DESC
     LIMIT $3`,
    [subjectId, predicate ?? null, limit],
  );
  return result.rows.map(toFact);
}
