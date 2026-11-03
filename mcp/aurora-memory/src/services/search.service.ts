import type { Pool } from 'pg';
import { countEntitiesByType, searchEntities } from '../repositories/kg.repository.ts';
import type { Entity } from '../models/types.ts';
import type { Embedder } from './embedding.client.ts';

export type SearchMode = 'semantic' | 'structured' | 'structured-fallback';

/**
 * Recherche mémoire (ADR-004/005/022) :
 * - embeddings configurés → similarité cosinus pgvector sur les entités ;
 * - sinon repli déterministe sur la recherche structurée (trigram).
 * Le LLM raisonne sur la base structurée — jamais sur des embeddings nus (ADR-005).
 */
export class SearchService {
  constructor(
    private readonly db: Pool,
    private readonly embedder?: Embedder,
  ) {}

  async search(query: string, limit = 10): Promise<{ mode: SearchMode; results: Entity[] }> {
    if (this.embedder?.configured) {
      try {
        const results = await this.semanticSearch(query, limit);
        if (results.length > 0) {
          return { mode: 'semantic', results };
        }
      } catch (error) {
        // Panne provider ou embedding invalide : dégradation déterministe, pas d'erreur dure —
        // la recherche structurée locale reste disponible. Panne journalisée : un drift de
        // config (clé expirée, dimension) ne doit pas passer inaperçu.
        console.error(
          '[search] repli structuré — provider embeddings en échec:',
          error instanceof Error ? error.message : error,
        );
        return { mode: 'structured-fallback', results: await searchEntities(this.db, query, undefined, limit) };
      }
    }
    return { mode: 'structured', results: await searchEntities(this.db, query, undefined, limit) };
  }

  private async semanticSearch(query: string, limit: number): Promise<Entity[]> {
    if (!this.embedder) {
      return [];
    }
    const vector = await this.embedder.embed(query);
    // JOIN unique ordonné par distance : le classement cosinus est conservé.
    const result = await this.db.query<{
      id: string;
      type: string;
      name: string;
      metadata: Record<string, unknown>;
      created_at: Date;
      updated_at: Date;
    }>(
      `SELECT e.id, e.type, e.name, e.metadata, e.created_at, e.updated_at
       FROM embeddings em
       JOIN entities e ON e.id = em.entity_id
       ORDER BY em.vector <=> $1::vector
       LIMIT $2`,
      [`[${vector.join(',')}]`, limit],
    );
    return result.rows.map((row) => ({
      id: row.id,
      type: row.type,
      name: row.name,
      metadata: row.metadata,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
    }));
  }

  async stats(): Promise<Record<string, number>> {
    return countEntitiesByType(this.db);
  }
}
