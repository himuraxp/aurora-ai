import type { Pool } from 'pg';
import { appendEvent } from '../repositories/events.repository.ts';
import { getOrCreateSource } from '../repositories/kg.repository.ts';
import { findLessonById, insertLesson, listLessons, updateLessonStatus } from '../repositories/lessons.repository.ts';
import { DEFAULT_CONFIDENCE, LESSON_TRANSITIONS, HUMAN_SOURCE_KINDS } from '../models/types.ts';
import type { Lesson, LessonInitialStatus, LessonProvenance, LessonStatus } from '../models/types.ts';
import { InvariantViolationError, NotFoundError } from '../errors.ts';

const HUMAN_KINDS = new Set<string>(HUMAN_SOURCE_KINDS);

export interface LessonCreateInput {
  title: string;
  lesson: string;
  context: Record<string, unknown>;
  scope?: string;
  provenanceClass: LessonProvenance;
  confidence?: number;
  validUntil?: Date;
  supersedesId?: string;
  initialStatus?: LessonInitialStatus;
  sourceKind: string;
  sourceRef: string;
}

/** Cycle de vie des leçons (ADR-024) — transitions fermées, ratification humaine opposable. */
export class LessonsService {
  constructor(private readonly db: Pool) {}

  async create(input: LessonCreateInput): Promise<Lesson> {
    // Pré-validation FK : supersedesId doit pointer une leçon existante (erreur structurée,
    // jamais une erreur PostgreSQL brute — contrat d'erreurs MCP, review livrable 1).
    if (input.supersedesId) {
      const previous = await findLessonById(this.db, input.supersedesId);
      if (!previous) {
        throw new NotFoundError(`Leçon à remplacer ${input.supersedesId} introuvable.`);
      }
    }
    const source = await getOrCreateSource(this.db, input.sourceKind, input.sourceRef);
    const confidence = input.confidence ?? DEFAULT_CONFIDENCE[input.provenanceClass];
    return insertLesson(this.db, {
      title: input.title,
      lesson: input.lesson,
      context: input.context,
      scope: input.scope,
      confidence,
      provenanceClass: input.provenanceClass,
      initialStatus: input.initialStatus ?? 'candidate',
      sourceId: source.id,
      supersedesId: input.supersedesId,
      validUntil: input.validUntil,
    });
  }

  async list(status?: LessonStatus, scope?: string, limit = 50): Promise<Lesson[]> {
    return listLessons(this.db, status, scope, limit);
  }

  /**
   * Transition atomique : SELECT FOR UPDATE verrouille la ligne entre la lecture
   * de l'état courant et l'écriture (pattern goals, review Phase 1 — TOCTOU).
   * Garde de ratification : → ratified exige une source humaine (ADR-024) —
   * l'agent ne peut ni se ratifier ni contourner le garde en passant 'candidate'.
   */
  async transition(input: {
    lessonId: string;
    next: LessonStatus;
    actorKind: string;
    actorRef?: string;
    reason?: string;
  }): Promise<Lesson> {
    const client = await this.db.connect();
    try {
      await client.query('BEGIN');
      const current = await client.query<{ status: LessonStatus }>(
        `SELECT status FROM lessons WHERE id = $1 FOR UPDATE`,
        [input.lessonId],
      );
      const row = current.rows[0];
      if (!row) {
        throw new NotFoundError(`Lesson ${input.lessonId} introuvable.`);
      }
      const allowed = LESSON_TRANSITIONS[row.status];
      if (!allowed.includes(input.next)) {
        throw new InvariantViolationError(
          `Transition de leçon interdite : ${row.status} → ${input.next}. ` +
            `Transitions autorisées depuis « ${row.status} » : ${allowed.join(', ') || 'aucune (état terminal)'}.`,
        );
      }
      const actor = input.actorKind.trim().toLowerCase();
      if (input.next === 'ratified' && !HUMAN_KINDS.has(actor)) {
        throw new InvariantViolationError(
          `Ratification refusée : la transition → ratified exige une source humaine ` +
            `(${HUMAN_SOURCE_KINDS.join('|')}) — reçu « ${input.actorKind} ». ` +
            `Une leçon apprise par l'agent reste candidate : une inférence ne devient jamais une contrainte dure (ADR-005/024).`,
        );
      }
      const updated = await updateLessonStatus(client, input.lessonId, input.next);
      // Journal append-only (ADR-010/014) — même transaction que l'UPDATE. La valeur
      // journalisée est celle exacte sur laquelle le garde a décidé (normalisée).
      await appendEvent(client, {
        type: 'lesson.transition',
        payload: {
          lessonId: input.lessonId,
          from: row.status,
          to: input.next,
          actorKind: actor,
          actorKindRaw: input.actorKind,
          reason: input.reason ?? null,
        },
        sourceKind: input.actorKind,
        sourceRef: input.actorRef ?? input.reason ?? `lesson:${input.lessonId}`,
      });
      await client.query('COMMIT');
      return updated;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }
}
