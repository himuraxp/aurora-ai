-- Migration 003 — Embeddings Qwen/Qwen3-Embedding-8B, 4096 dimensions (ADR-022).
-- ADR-018 : changer de modèle d'embedding = nouvelle migration.
-- La table embeddings ne contient que des données DÉRIVÉES (reconstructibles
-- via le backfill) : le TRUNCATE rend le changement de dimension déterministe
-- et rejouable, même si une ancienne vector(1536) subsistait.

TRUNCATE embeddings;

DROP INDEX IF EXISTS embeddings_vector_idx;
ALTER TABLE embeddings ALTER COLUMN vector TYPE vector(4096);

-- PAS d'index HNSW : la limite pgvector est de 2000 dimensions pour hnsw,
-- Qwen3-Embedding-8B en produit 4096. À l'échelle personnelle (centaines à
-- milliers d'entités), la distance cosinus exacte par seq scan est en
-- dessous de la milliseconde — et exacte (l'index approximatif ne l'est pas).
-- Réintroduire un index (halfvec, pgvector >= 0.7) uniquement sur besoin mesuré.
