/** Erreur métier de base — propagation avec contexte, jamais avalée (framework nodejs). */
export class BusinessError extends Error {
  readonly code: string;

  constructor(code: string, message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = 'BusinessError';
    this.code = code;
  }
}

export class NotFoundError extends BusinessError {
  constructor(message: string, options?: { cause?: unknown }) {
    super('NOT_FOUND', message, options);
    this.name = 'NotFoundError';
  }
}

/** Invariant constitutionnel violé (plan §C/§F) — ex : inférence devenue contrainte dure. */
export class InvariantViolationError extends BusinessError {
  constructor(message: string, options?: { cause?: unknown }) {
    super('INVARIANT_VIOLATION', message, options);
    this.name = 'InvariantViolationError';
  }
}
