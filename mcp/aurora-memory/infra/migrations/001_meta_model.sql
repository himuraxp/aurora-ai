-- Migration 001 — Meta-model KG (ADR-005) + contrats d'exécution (plan §F)
-- Source de vérité : PostgreSQL + pgvector (ADR-004). Append-only là où indiqué.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── Sources ─────────────────────────────────────────────────────────────────
-- Chaque fait/événement trace son origine.
CREATE TABLE sources (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind        TEXT NOT NULL,               -- transaction|email|document|user_assertion|llm_inference|system|…
  ref         TEXT NOT NULL,               -- référence externe (chemin, URL, id fournisseur…)
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, ref)
);

-- ── Entities ────────────────────────────────────────────────────────────────
-- Types pilotes Phase 1 (plan §C) : registry applicatif — extension = nouveaux types, sans migration.
CREATE TABLE entities (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type        TEXT NOT NULL,               -- person|project|organization|account|subscription|contract|document|preference…
  name        TEXT NOT NULL,
  metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (type, name)
);
CREATE INDEX entities_type_idx   ON entities (type);
CREATE INDEX entities_name_trgm  ON entities USING gin (name gin_trgm_ops);

-- ── Relations ───────────────────────────────────────────────────────────────
CREATE TABLE relations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id   UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  target_id   UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  type        TEXT NOT NULL,               -- belongs_to|works_on|subscribed_to|knows|…
  metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_id, target_id, type),
  CHECK (source_id <> target_id)
);
CREATE INDEX relations_source_idx ON relations (source_id, type);
CREATE INDEX relations_target_idx ON relations (target_id, type);

-- ── Facts (croyances temporelles + provenance obligatoire) ──────────────────
-- Provenance (plan §C) : FACT > OBSERVATION > INFERENCE ; USER_ASSERTION prioritaire.
CREATE TABLE facts (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id        UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  predicate         TEXT NOT NULL,         -- likes|dislikes|constraint|budget|status|…
  value             JSONB NOT NULL,
  valid_from        TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until       TIMESTAMPTZ,           -- NULL = toujours valide
  source_id         UUID NOT NULL REFERENCES sources(id),
  confidence        NUMERIC(3,2) NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
  provenance_class  TEXT NOT NULL CHECK (provenance_class IN
                      ('FACT','OBSERVATION','INFERENCE','USER_ASSERTION','EXPLICIT_CORRECTION',
                       'REPEATED_BEHAVIOR','SINGLE_OBSERVATION')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX facts_subject_idx ON facts (subject_id, predicate);
CREATE INDEX facts_valid_idx   ON facts (valid_until);

-- ── Preferences (première classe, plan §C/§F — le « il me connaît ») ────────
-- hardness hard exigé USER_ASSERTION|EXPLICIT_CORRECTION (garde applicatif + CHECK).
CREATE TABLE preferences (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id        UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  domain            TEXT NOT NULL,          -- travel|food|tech|finance|…
  predicate         TEXT NOT NULL,          -- likes|dislikes|constraint|budget
  value             JSONB NOT NULL,
  weight            NUMERIC(4,2) NOT NULL DEFAULT 1.0,
  confidence        NUMERIC(3,2) NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
  hardness          TEXT NOT NULL CHECK (hardness IN ('soft','hard')),
  scope             TEXT,
  sensitivity       TEXT NOT NULL DEFAULT 'normal' CHECK (sensitivity IN ('normal','sensitive')),
  provenance_class  TEXT NOT NULL CHECK (provenance_class IN
                      ('USER_ASSERTION','EXPLICIT_CORRECTION','REPEATED_BEHAVIOR',
                       'SINGLE_OBSERVATION','LLM_INFERENCE')),
  valid_from        TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until       TIMESTAMPTZ,
  source_id         UUID NOT NULL REFERENCES sources(id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (hardness = 'soft' OR provenance_class IN ('USER_ASSERTION','EXPLICIT_CORRECTION'))
);
CREATE INDEX preferences_subject_idx ON preferences (subject_id, domain);

-- ── Documents ───────────────────────────────────────────────────────────────
CREATE TABLE documents (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type        TEXT NOT NULL,               -- invoice|contract|email|note|…
  content     TEXT NOT NULL,
  metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_id   UUID REFERENCES sources(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Events (event store append-only, ADR-010) ───────────────────────────────
CREATE TABLE events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type        TEXT NOT NULL,               -- email.received|bank.transaction.created|goal.created|…
  payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_id   UUID REFERENCES sources(id)
);
CREATE INDEX events_type_idx ON events (type, occurred_at DESC);

-- ── Embeddings (pgvector) ───────────────────────────────────────────────────
-- Dimension fixée à la migration ; changer de modèle d'embedding = nouvelle migration (documenté ADR-018).
CREATE TABLE embeddings (
  entity_id   UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
  vector      vector(1536) NOT NULL,
  model       TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX embeddings_vector_idx ON embeddings USING hnsw (vector vector_cosine_ops);

-- ── Goals (contrat §F — storage Phase 1, usage vivant Phase 2) ──────────────
CREATE TABLE goals (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title       TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','blocked','done','abandoned')),
  metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Journal des migrations ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
  filename    TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
