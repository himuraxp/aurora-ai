import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { Pool } from 'pg';
import { countEntitiesByType } from '../repositories/kg.repository.ts';
import { listEvents, listGoals } from '../repositories/events.repository.ts';
import type { Goal } from '../models/types.ts';
import { BusinessError } from '../errors.ts';

/**
 * Projection docs/ai/ (ADR-013) : la DB est la source de vérité ; la projection est
 * générée ADDITIVEMENT dans <racine épinglée>/docs/ai/projection/ — les 7 fichiers de
 * session (STATUS, PLAN, CHANGELOG, BUFFER, INDEX, WARNINGS, DECISIONS) restent tenus
 * par les agents jusqu'à la bascule complète (fin de la cohabitation, cf. plan).
 *
 * Sécurité (review Phase 1) : la racine est épinglée au démarrage via
 * AURORA_PROJECTION_ROOT et n'est JAMAIS un argument du tool — le LLM n'obtient
 * aucun primitif d'écriture à chemin arbitraire.
 */
export class ProjectionService {
  constructor(
    private readonly db: Pool,
    private readonly projectionRoot: string | undefined,
  ) {}

  async generate(): Promise<{ written: string[] }> {
    if (!this.projectionRoot) {
      throw new BusinessError(
        'CONFIG_MISSING',
        'AURORA_PROJECTION_ROOT non configuré — la projection est désactivée. ' +
          'Définir la variable dans .env (racine absolue du repo cible).',
      );
    }
    const [counts, goals, events] = await Promise.all([
      countEntitiesByType(this.db),
      listGoals(this.db, undefined, 100),
      listEvents(this.db, undefined, 20),
    ]);

    // Confinement : chemin construit uniquement à partir de la racine épinglée.
    const outDir = join(this.projectionRoot, 'docs', 'ai', 'projection');
    await mkdir(outDir, { recursive: true });

    const goalsPath = join(outDir, 'goals.md');
    const snapshotPath = join(outDir, 'kg-snapshot.md');

    await writeFile(goalsPath, renderGoals(goals), 'utf8');
    await writeFile(snapshotPath, renderSnapshot(counts, events), 'utf8');

    return { written: [goalsPath, snapshotPath] };
  }
}

/** Neutralise les métacaractères markdown de table et les sauts de ligne (contenu client). */
function mdSafe(text: string): string {
  return text.replaceAll('|', '\\|').replaceAll('\n', ' ');
}

function renderGoals(goals: Goal[]): string {
  const lines = [
    '# Goals — projection mémoire (généré par aurora-memory)',
    '',
    '> Fichier généré — ne pas éditer à la main. Source : PostgreSQL (ADR-003).',
    '',
  ];
  if (goals.length === 0) {
    lines.push('_Aucun goal en base._', '');
    return lines.join('\n');
  }
  lines.push('| Goal | Statut | Créé le |', '|---|---|---|');
  for (const goal of goals) {
    lines.push(`| ${mdSafe(goal.title)} | ${goal.status} | ${goal.createdAt.toISOString().slice(0, 10)} |`);
  }
  lines.push('');
  return lines.join('\n');
}

function renderSnapshot(counts: Record<string, number>, events: Awaited<ReturnType<typeof listEvents>>): string {
  const lines = [
    '# KG — snapshot mémoire (généré par aurora-memory)',
    '',
    '> Fichier généré — ne pas éditer à la main. Source : PostgreSQL (ADR-003).',
    '',
    '## Entités par type',
    '',
  ];
  const types = Object.keys(counts);
  if (types.length === 0) {
    lines.push('_KG vide._');
  } else {
    lines.push('| Type | Nombre |', '|---|---|');
    for (const type of types) {
      lines.push(`| ${mdSafe(type)} | ${counts[type]} |`);
    }
  }
  lines.push('', '## Derniers événements', '');
  if (events.length === 0) {
    lines.push('_Aucun événement._');
  } else {
    lines.push('| Type | Survenu le |', '|---|---|');
    for (const event of events) {
      lines.push(`| ${mdSafe(event.type)} | ${event.occurredAt.toISOString()} |`);
    }
  }
  lines.push('');
  return lines.join('\n');
}
