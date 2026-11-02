import { z } from 'zod';

/**
 * Configuration centralisée — seule couche autorisée à lire process.env
 * (cf. frameworks/nodejs.md). Validée au démarrage.
 */
const emptyToUndefined = (value: unknown): unknown =>
  typeof value === 'string' && value.trim() === '' ? undefined : value;

const envSchema = z.object({
  DATABASE_URL: z.string().url().startsWith('postgres'),
  TEST_DATABASE_URL: z.preprocess(emptyToUndefined, z.string().url().startsWith('postgres').optional()),
  EMBEDDING_API_BASE: z.preprocess(emptyToUndefined, z.string().url().optional()),
  EMBEDDING_API_KEY: z.preprocess(emptyToUndefined, z.string().min(1).optional()),
  EMBEDDING_MODEL: z.preprocess(emptyToUndefined, z.string().min(1).optional()),
  /** Dimension du modèle d'embedding — alignée sur la migration 003 (Qwen3-Embedding-8B, ADR-022). */
  EMBEDDING_DIM: z.coerce.number().int().positive().default(4096),
  /** Racine de projection épinglée au démarrage — jamais contrôlée par le LLM. */
  AURORA_PROJECTION_ROOT: z.preprocess(emptyToUndefined, z.string().min(1).optional()),
});

export type Env = z.infer<typeof envSchema>;

export function loadEnv(source: NodeJS.ProcessEnv = process.env): Env {
  const parsed = envSchema.safeParse(source);
  if (!parsed.success) {
    const issues = parsed.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; ');
    throw new Error(`Configuration invalide — ${issues}`);
  }
  return parsed.data;
}
