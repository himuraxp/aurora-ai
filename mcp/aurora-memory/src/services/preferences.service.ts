import type { Pool } from 'pg';
import { insertPreference, queryPreferences } from '../repositories/preferences.repository.ts';
import { findEntityById, getOrCreateSource } from '../repositories/kg.repository.ts';
import type { Preference, PreferenceProvenance } from '../models/types.ts';
import { DEFAULT_CONFIDENCE } from '../models/types.ts';
import { InvariantViolationError, NotFoundError } from '../errors.ts';

/** Provenances autorisées à créer une préférence dure (plan §C — invariant de gouvernance). */
const HARD_ALLOWED_PROVENANCE: readonly PreferenceProvenance[] = ['USER_ASSERTION', 'EXPLICIT_CORRECTION'];

/**
 * Service Preferences — le « il me connaît » (plan §C/§F).
 * Invariant : une inférence ne devient jamais silencieusement une contrainte dure.
 * Le passage soft → hard exige une assertion ou une correction explicite de l'utilisateur.
 */
export class PreferencesService {
  constructor(private readonly db: Pool) {}

  async set(input: {
    subjectId: string;
    domain: string;
    predicate: string;
    value: unknown;
    hardness: 'soft' | 'hard';
    provenanceClass: PreferenceProvenance;
    weight?: number;
    confidence?: number;
    scope?: string;
    sensitivity?: 'normal' | 'sensitive';
    validFrom?: Date;
    validUntil?: Date;
    sourceKind: string;
    sourceRef: string;
  }): Promise<Preference> {
    if (input.hardness === 'hard' && !HARD_ALLOWED_PROVENANCE.includes(input.provenanceClass)) {
      throw new InvariantViolationError(
        `Préférence hard refusée : provenance « ${input.provenanceClass} ». ` +
          `Une contrainte dure exige USER_ASSERTION ou EXPLICIT_CORRECTION (plan §C).`,
      );
    }
    const entity = await this.requireSubject(input.subjectId);
    const source = await getOrCreateSource(this.db, input.sourceKind, input.sourceRef);
    return insertPreference(this.db, {
      subjectId: entity.id,
      domain: input.domain,
      predicate: input.predicate,
      value: input.value,
      weight: input.weight ?? 1.0,
      // Confiance par défaut différenciée par classe de provenance (épistémique).
      confidence: input.confidence ?? DEFAULT_CONFIDENCE[input.provenanceClass],
      hardness: input.hardness,
      scope: input.scope,
      sensitivity: input.sensitivity ?? 'normal',
      provenanceClass: input.provenanceClass,
      validFrom: input.validFrom,
      validUntil: input.validUntil,
      sourceId: source.id,
    });
  }

  async query(subjectId: string, domain?: string, limit = 50): Promise<Preference[]> {
    await this.requireSubject(subjectId);
    return queryPreferences(this.db, subjectId, domain, limit);
  }

  private async requireSubject(subjectId: string) {
    const entity = await findEntityById(this.db, subjectId);
    if (!entity) {
      throw new NotFoundError(`Sujet ${subjectId} introuvable — crée l'entité d'abord.`);
    }
    return entity;
  }
}
