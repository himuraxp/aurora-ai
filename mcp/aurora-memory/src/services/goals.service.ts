import type { Pool } from 'pg';
import { insertGoal, listGoals, updateGoal } from '../repositories/events.repository.ts';
import { GOAL_TRANSITIONS } from '../models/types.ts';
import type { Goal, GoalStatus } from '../models/types.ts';
import { InvariantViolationError, NotFoundError } from '../errors.ts';

/** Cycle de vie Goal (contrat §F) — transitions fermées, terminaux irréversibles. */
export class GoalsService {
  constructor(private readonly db: Pool) {}

  async create(title: string, metadata: Record<string, unknown>): Promise<Goal> {
    return insertGoal(this.db, title, metadata);
  }

  async list(status?: GoalStatus, limit = 50): Promise<Goal[]> {
    return listGoals(this.db, status, limit);
  }

  /**
   * Transition atomique : SELECT FOR UPDATE verrouille la ligne entre la lecture
   * de l'état courant et l'écriture — deux appels concurrents ne peuvent pas faire
   * retomber un état terminal (review Phase 1, TOCTOU).
   */
  async updateStatus(goalId: string, next: GoalStatus): Promise<Goal> {
    const client = await this.db.connect();
    try {
      await client.query('BEGIN');
      const current = await client.query<{ status: GoalStatus }>(
        `SELECT status FROM goals WHERE id = $1 FOR UPDATE`,
        [goalId],
      );
      const row = current.rows[0];
      if (!row) {
        throw new NotFoundError(`Goal ${goalId} introuvable.`);
      }
      const allowed = GOAL_TRANSITIONS[row.status];
      if (!allowed.includes(next)) {
        throw new InvariantViolationError(
          `Transition de goal interdite : ${row.status} → ${next}. ` +
            `Transitions autorisées depuis « ${row.status} » : ${allowed.join(', ') || 'aucune (état terminal)'}.`,
        );
      }
      const goal = await updateGoal(client, goalId, { status: next });
      await client.query('COMMIT');
      return goal;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }
}
