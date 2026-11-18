-- Migration 005 — Cycle de vie des leçons (ADR-024)
-- Source : position v2 ratifiée (boucle cowork 2026-11-02) — livrable 1 « learning loop ».
-- Les leçons capturent corrections et échecs ; elles ne deviennent jamais des instructions
-- sans ratification humaine (garde applicatif + journal append-only dans events).

CREATE TABLE lessons (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status            TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN
                      ('observed','candidate','ratified','rejected','superseded','expired')),
  title             TEXT NOT NULL,
  lesson            TEXT NOT NULL,               -- le contenu actionnable de la leçon
  context           JSONB NOT NULL DEFAULT '{}'::jsonb,  -- mission/projet/cause — jamais de secret
  scope             TEXT,                        -- périmètre (projet, zone) ; NULL = global
  confidence        NUMERIC(3,2) NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
  provenance_class  TEXT NOT NULL CHECK (provenance_class IN
                      ('FACT','OBSERVATION','INFERENCE','USER_ASSERTION','EXPLICIT_CORRECTION',
                       'REPEATED_BEHAVIOR','SINGLE_OBSERVATION','LLM_INFERENCE')),
  source_id         UUID NOT NULL REFERENCES sources(id),
  supersedes_id     UUID REFERENCES lessons(id),
  valid_from        TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until       TIMESTAMPTZ,                 -- NULL = valide jusqu'à déchéance explicite
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX lessons_status_idx ON lessons (status, valid_until);
CREATE INDEX lessons_scope_idx  ON lessons (scope);
CREATE INDEX lessons_supersedes_idx ON lessons (supersedes_id);
CREATE INDEX lessons_source_idx ON lessons (source_id);

-- Fenêtre de validité cohérente (principe instauré par la migration 002 pour facts/preferences).
ALTER TABLE lessons ADD CONSTRAINT lessons_validity_window
  CHECK (valid_until IS NULL OR valid_until > valid_from);
