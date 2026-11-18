import type { DbClient } from './db.ts';
import { orUndefined } from './db.ts';
import { PROVENANCE_PRIORITY } from '../models/types.ts';
import type { Preference, PreferenceProvenance } from '../models/types.ts';

interface PreferenceRow {
  id: string;
  subject_id: string;
  domain: string;
  predicate: string;
  value: unknown;
  weight: string;
  confidence: string;
  hardness: 'soft' | 'hard';
  scope: string | null;
  sensitivity: 'normal' | 'sensitive';
  provenance_class: PreferenceProvenance;
  valid_from: Date;
  valid_until: Date | null;
  source_id: string;
  created_at: Date;
}

function toPreference(row: PreferenceRow): Preference {
  return {
    id: row.id,
    subjectId: row.subject_id,
    domain: row.domain,
    predicate: row.predicate,
    value: row.value,
    weight: Number(row.weight),
    confidence: Number(row.confidence),
    hardness: row.hardness,
    scope: orUndefined(row.scope),
    sensitivity: row.sensitivity,
    provenanceClass: row.provenance_class,
    validFrom: row.valid_from,
    validUntil: orUndefined(row.valid_until),
    sourceId: row.source_id,
    createdAt: row.created_at,
  };
}

export async function insertPreference(
  db: DbClient,
  preference: {
    subjectId: string;
    domain: string;
    predicate: string;
    value: unknown;
    weight: number;
    confidence: number;
    hardness: 'soft' | 'hard';
    scope: string | undefined;
    sensitivity: 'normal' | 'sensitive';
    provenanceClass: PreferenceProvenance;
    validFrom: Date | undefined;
    validUntil: Date | undefined;
    sourceId: string;
  },
): Promise<Preference> {
  const result = await db.query<PreferenceRow>(
    `INSERT INTO preferences
       (subject_id, domain, predicate, value, weight, confidence, hardness,
        scope, sensitivity, provenance_class, valid_from, valid_until, source_id)
     VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10, COALESCE($11, now()), $12, $13)
     RETURNING *`,
    [
      preference.subjectId,
      preference.domain,
      preference.predicate,
      JSON.stringify(preference.value),
      preference.weight,
      preference.confidence,
      preference.hardness,
      preference.scope ?? null,
      preference.sensitivity,
      preference.provenanceClass,
      preference.validFrom ?? null,
      preference.validUntil ?? null,
      preference.sourceId,
    ],
  );
  return toPreference(result.rows[0] as PreferenceRow);
}

/**
 * Résolution prioritaire (plan §C) :
 * USER_ASSERTION > EXPLICIT_CORRECTION > REPEATED_BEHAVIOR > SINGLE_OBSERVATION > LLM_INFERENCE,
 * puis weight / confidence / récence. Une préférence expirée n'est jamais retournée.
 */
export async function queryPreferences(
  db: DbClient,
  subjectId: string,
  domain: string | undefined,
  limit: number,
): Promise<Preference[]> {
  const priority = PROVENANCE_PRIORITY.map((p, index) => `WHEN '${p}' THEN ${index}`).join(' ');
  const result = await db.query<PreferenceRow>(
    `SELECT * FROM preferences
     WHERE subject_id = $1
       AND ($2::text IS NULL OR domain = $2)
       AND (valid_until IS NULL OR valid_until > now())
     ORDER BY CASE provenance_class ${priority} END,
              weight DESC, confidence DESC, valid_from DESC
     LIMIT $3`,
    [subjectId, domain ?? null, limit],
  );
  return result.rows.map(toPreference);
}
