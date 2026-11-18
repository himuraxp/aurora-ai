#!/usr/bin/env node
/**
 * aurora-memory — serveur MCP (stdio), Phase 1 Aurora OS.
 * Mémoire personnelle = PostgreSQL + pgvector (ADR-003/004/005).
 * OpenCode est un client : il raisonne via les outils structurés, jamais sur des embeddings nus.
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { fileURLToPath } from 'node:url';
import { join, resolve } from 'node:path';
import dotenv from 'dotenv';
import { loadEnv } from './config/env.ts';
import { getPool, closePool } from './repositories/db.ts';

// Charge le .env racine du repo s'il existe (jamais committé — cf. .gitignore).
// src/index.ts → 3 niveaux au-dessus = racine du repo.
dotenv.config({ path: join(fileURLToPath(new URL('../../../', import.meta.url)), '.env') });
import { KgService } from './services/kg.service.ts';
import { PreferencesService } from './services/preferences.service.ts';
import { GoalsService } from './services/goals.service.ts';
import { LessonsService } from './services/lessons.service.ts';
import { SearchService } from './services/search.service.ts';
import { ProjectionService } from './services/projection.service.ts';
import { EmbeddingClient } from './services/embedding.client.ts';
import { buildToolDefinitions } from './tools/index.ts';
import { appendEvent, listEvents } from './repositories/events.repository.ts';
import { upsertRelation, queryRelations } from './repositories/kg.repository.ts';

async function main(): Promise<void> {
  const env = loadEnv();
  const db = getPool(env.DATABASE_URL);
  const embedder = new EmbeddingClient(env);

  const server = new McpServer(
    { name: 'aurora-memory', version: '0.1.0' },
    { capabilities: { tools: {} } },
  );

  const tools = buildToolDefinitions({
    kg: new KgService(db, embedder),
    preferences: new PreferencesService(db),
    goals: new GoalsService(db),
    lessons: new LessonsService(db),
    search: new SearchService(db, embedder),
    projection: new ProjectionService(db, env.AURORA_PROJECTION_ROOT ? resolve(env.AURORA_PROJECTION_ROOT) : undefined),
    events: {
      append: (event) => appendEvent(db, event),
      list: (type, limit) => listEvents(db, type, limit),
    },
    relations: {
      upsert: (sourceId, targetId, type, metadata) => upsertRelation(db, sourceId, targetId, type, metadata),
      query: (entityId, type, limit) => queryRelations(db, entityId, type, limit),
    },
  });

  for (const definition of tools) {
    server.registerTool(definition.name, definition, definition.handler);
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);

  const shutdown = async (): Promise<void> => {
    await closePool();
    process.exit(0);
  };
  process.on('SIGINT', () => void shutdown());
  process.on('SIGTERM', () => void shutdown());
}

main().catch((error: unknown) => {
  console.error('[aurora-memory] démarrage impossible:', error instanceof Error ? error.message : error);
  process.exit(1);
});
