/** Ports étroits pour les opérations purement repository exposées en outils MCP. */
export interface EventsPort {
  append: (event: {
    type: string;
    payload: Record<string, unknown>;
    sourceId?: string;
    sourceKind?: string;
    sourceRef?: string;
  }) => Promise<unknown>;
  list: (type?: string, limit?: number) => Promise<unknown>;
}

export interface RelationsPort {
  upsert: (sourceId: string, targetId: string, type: string, metadata: Record<string, unknown>) => Promise<unknown>;
  query: (entityId: string, type?: string, limit?: number) => Promise<unknown>;
}
