-- Migration 002 — Barrières en base pour les invariants constitutionnels (review Phase 1)
-- 1) Event store append-only opposable en base (ADR-010, INV-6) — trigger d'interdiction.
-- 2) Fenêtres de validité cohérentes sur facts et preferences (ADR-005).

-- ── 1) events : UPDATE et DELETE interdits (append-only) ────────────────────
CREATE OR REPLACE FUNCTION forbid_events_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'events est append-only (ADR-010/INV-6) : % interdit', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_append_only
  BEFORE UPDATE OR DELETE ON events
  FOR EACH ROW EXECUTE FUNCTION forbid_events_mutation();

-- ── 2) Temporalité cohérente ────────────────────────────────────────────────
ALTER TABLE facts ADD CONSTRAINT facts_validity_window
  CHECK (valid_until IS NULL OR valid_until > valid_from);

ALTER TABLE preferences ADD CONSTRAINT preferences_validity_window
  CHECK (valid_until IS NULL OR valid_until > valid_from);
