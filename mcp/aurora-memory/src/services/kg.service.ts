import type { Pool } from 'pg';
import {
  closeOpenFacts,
  findEntityById,
  getOrCreateSource,
  insertFact,
  queryFacts,
  searchEntities as searchEntitiesRepo,
  upsertEmbedding,
  upsertEntity as upsertEntityRepo,
} from '../repositories/kg.repository.ts';
import type { Fact, FactProvenance, Entity } from '../models/types.ts';
import { DEFAULT_CONFIDENCE, FACT_PROVENANCE, PILOT_ENTITY_TYPES } from '../models/types.ts';
import { InvariantViolationError, NotFoundError } from '../errors.ts';
import { entityEmbeddingText, type Embedder } from './embedding.client.ts';

/**
 * Service KG — croyances structurées avec provenance obligatoire (ADR-005).
 * Invariant : le LLM raisonne sur la base structurée, jamais en embeddings nus.
 */
export class KgService {
  constructor(
    private readonly db: Pool,
    private readonly embedder?: Embedder,
  ) {}

  async upsertEntity(
    type: string,
    name: string,
    metadata: Record<string, unknown>,
  ): Promise<Entity> {
    if (!(PILOT_ENTITY_TYPES as readonly string[]).includes(type)) {
      throw new InvariantViolationError(
        `Type d'entité « ${type} » hors registry Phase 1 (${PILOT_ENTITY_TYPES.join(', ')}). ` +
          `Nouveau type = extension du KG (cf. plan §C), à ajouter au registry explicitement.`,
      );
    }
    const entity = await upsertEntityRepo(this.db, type, name, metadata);
    await this.indexEmbedding(entity);
    return entity;
  }

  /**
   * Indexation vectorielle write-time (ADR-022) — best-effort : l'écriture du KG
   * est la source de vérité, un échec provider ne doit jamais la bloquer.
   * Les entités ratées sont rattrapables par le backfill (idempotent).
   */
  private async indexEmbedding(entity: Entity): Promise<void> {
    if (!this.embedder?.configured) {
      return;
    }
    try {
      const vector = await this.embedder.embed(entityEmbeddingText(entity));
      await upsertEmbedding(this.db, entity.id, vector, this.embedder.model);
    } catch (error) {
      console.error(
        `[kg] indexation embedding ignorée pour « ${entity.type}/${entity.name} »:`,
        error instanceof Error ? error.message : error,
      );
    }
  }

  /**
   * Insère un fait et clôt les faits contradictoires encore valides pour la même
   * (subject, predicate) — révision de croyance, transaction atomique (ADR-005).
   * Les faits antérieurs restent historisés via leur fenêtre de validité.
   */
  async factInsert(input: {
    subjectId: string;
    predicate: string;
    value: unknown;
    provenanceClass: FactProvenance;
    confidence?: number;
    validFrom?: Date;
    validUntil?: Date;
    sourceKind: string;
    sourceRef: string;
  }): Promise<Fact> {
    if (!(FACT_PROVENANCE as readonly string[]).includes(input.provenanceClass)) {
      throw new InvariantViolationError(`Provenance « ${input.provenanceClass} » inconnue.`);
    }
    const entity = await this.requireEntity(input.subjectId);
    const source = await getOrCreateSource(this.db, input.sourceKind, input.sourceRef);
    const confidence = input.confidence ?? DEFAULT_CONFIDENCE[input.provenanceClass];
    const client = await this.db.connect();
    try {
      await client.query('BEGIN');
      await closeOpenFacts(client, entity.id, input.predicate, new Date());
      const fact = await insertFact(client, {
        subjectId: entity.id,
        predicate: input.predicate,
        value: input.value,
        sourceId: source.id,
        confidence,
        provenanceClass: input.provenanceClass,
        validFrom: input.validFrom,
        validUntil: input.validUntil,
      });
      await client.query('COMMIT');
      return fact;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }

  async factQuery(subjectId: string, predicate?: string, limit = 50): Promise<Fact[]> {
    await this.requireEntity(subjectId);
    return queryFacts(this.db, subjectId, predicate, limit);
  }

  async searchEntities(query: string, type?: string, limit = 20): Promise<Entity[]> {
    return searchEntitiesRepo(this.db, query, type, limit);
  }

  private async requireEntity(id: string): Promise<Entity> {
    const entity = await findEntityById(this.db, id);
    if (!entity) {
      throw new NotFoundError(`Entité ${id} introuvable.`);
    }
    return entity;
  }
}
