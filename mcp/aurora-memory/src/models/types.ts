/** Classes de provenance — priorité de résolution (plan §C, ADR-005). */
export const PROVENANCE_PRIORITY = [
  'USER_ASSERTION',
  'EXPLICIT_CORRECTION',
  'REPEATED_BEHAVIOR',
  'SINGLE_OBSERVATION',
  'LLM_INFERENCE',
] as const;

export type PreferenceProvenance = (typeof PROVENANCE_PRIORITY)[number];

/** Provenance des faits bruts (peut être mesurée, donc FACT autorisé). */
export const FACT_PROVENANCE = [
  'FACT',
  'OBSERVATION',
  'INFERENCE',
  'USER_ASSERTION',
  'EXPLICIT_CORRECTION',
  'REPEATED_BEHAVIOR',
  'SINGLE_OBSERVATION',
] as const;
export type FactProvenance = (typeof FACT_PROVENANCE)[number];

/** Toutes les classes de provenance (faits + préférences confondus). */
export type ProvenanceClass = FactProvenance | PreferenceProvenance;

/** Confiance par défaut différenciée par classe de provenance (review Phase 1 — épistémique). */
export const DEFAULT_CONFIDENCE: Record<ProvenanceClass, number> = {
  FACT: 1.0,
  OBSERVATION: 0.7,
  INFERENCE: 0.5,
  USER_ASSERTION: 1.0,
  EXPLICIT_CORRECTION: 1.0,
  REPEATED_BEHAVIOR: 0.8,
  SINGLE_OBSERVATION: 0.6,
  LLM_INFERENCE: 0.5,
};

export const PILOT_ENTITY_TYPES = [
  'person',
  'project',
  'organization',
  'account',
  'subscription',
  'contract',
  'document',
  'preference',
] as const;
export type PilotEntityType = (typeof PILOT_ENTITY_TYPES)[number];

export const GOAL_STATUSES = ['active', 'paused', 'blocked', 'done', 'abandoned'] as const;
export type GoalStatus = (typeof GOAL_STATUSES)[number];

/** Transitions autorisées du cycle de vie d'un Goal (contrat §F). */
export const GOAL_TRANSITIONS: Record<GoalStatus, readonly GoalStatus[]> = {
  active: ['paused', 'blocked', 'done', 'abandoned'],
  paused: ['active', 'done', 'abandoned'],
  blocked: ['active', 'done', 'abandoned'],
  done: [],
  abandoned: [],
};

/**
 * Cycle de vie des leçons (ADR-024) — l'orchestrateur et les agents écrivent en
 * observed|candidate ; la ratification passe par une source humaine (garde applicatif).
 */
export const LESSON_STATUSES = ['observed', 'candidate', 'ratified', 'rejected', 'superseded', 'expired'] as const;
export type LessonStatus = (typeof LESSON_STATUSES)[number];

/** Transitions fermées (ADR-024) : terminaux irréversibles ; ratified ne peut que se déchoir. */
export const LESSON_TRANSITIONS: Record<LessonStatus, readonly LessonStatus[]> = {
  observed: ['candidate', 'rejected', 'expired'],
  candidate: ['ratified', 'rejected', 'superseded', 'expired'],
  ratified: ['superseded', 'expired'],
  rejected: [],
  superseded: [],
  expired: [],
};

/** Ratification réservée aux sources humaines — l'agent ne se ratifie jamais (ADR-024). */
export const HUMAN_SOURCE_KINDS = ['user', 'human', 'user_assertion', 'explicit_correction'] as const;

/** Provenance des leçons (origine de la leçon — la ratification, elle, est tracée par transition). */
export const LESSON_PROVENANCE = [...FACT_PROVENANCE, 'LLM_INFERENCE'] as const;
export type LessonProvenance = (typeof LESSON_PROVENANCE)[number];

/** Statuts admissibles à la création — une leçon ne naît jamais ratifiée (ADR-024). */
export type LessonInitialStatus = 'observed' | 'candidate';

export interface Entity {
  id: string;
  type: string;
  name: string;
  metadata: Record<string, unknown>;
  createdAt: Date;
  updatedAt: Date;
}

export interface Relation {
  id: string;
  sourceId: string;
  targetId: string;
  type: string;
  metadata: Record<string, unknown>;
  createdAt: Date;
}

export interface Fact {
  id: string;
  subjectId: string;
  predicate: string;
  value: unknown;
  validFrom: Date;
  validUntil: Date | undefined;
  sourceId: string;
  confidence: number;
  provenanceClass: FactProvenance;
  createdAt: Date;
}

export interface Preference {
  id: string;
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
  validFrom: Date;
  validUntil: Date | undefined;
  sourceId: string;
  createdAt: Date;
}

export interface Goal {
  id: string;
  title: string;
  status: GoalStatus;
  metadata: Record<string, unknown>;
  createdAt: Date;
  updatedAt: Date;
}

/** Leçon du cycle de vie d'apprentissage (ADR-024). */
export interface Lesson {
  id: string;
  status: LessonStatus;
  title: string;
  lesson: string;
  context: Record<string, unknown>;
  scope: string | undefined;
  confidence: number;
  provenanceClass: LessonProvenance;
  sourceId: string;
  supersedesId: string | undefined;
  validFrom: Date;
  validUntil: Date | undefined;
  createdAt: Date;
  updatedAt: Date;
}

export interface MemoryEvent {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  occurredAt: Date;
  sourceId: string | undefined;
}

export interface Source {
  id: string;
  kind: string;
  ref: string;
  createdAt: Date;
}
