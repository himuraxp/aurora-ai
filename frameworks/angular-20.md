---
description: Expert Angular 20
mode: subagent
---

# Angular 20

## Objectif

Produire du code Angular moderne, standalone, typé, maintenable et aligné avec les conventions Angular 20+.

## Templates HTML

Utiliser les nouveaux blocs Angular :

```html
@if (condition()) {
  <div>...</div>
} @else {
  <div>...</div>
}

@for (item of items(); track item.id) {
  <div>...</div>
}
```

Règles :

- Ne pas utiliser `*ngIf`.
- Ne pas utiliser `*ngFor`.
- Ne pas utiliser `ngSwitch` sauf contrainte projet explicite.
- Ne pas utiliser `let` dans la clause `@for`.
- Les blocs `@if` et `@for` doivent entourer des balises HTML complètes.
- Ne jamais utiliser `@if` ou `@for` comme attribut.
- Toujours définir un `track` stable dans `@for`.
- Éviter les expressions complexes dans le template.
- Préférer des `computed()` côté TypeScript.

## TypeScript / composants

### Standalone

- Composants standalone uniquement.
- Pas de NgModule manuel.
- Imports déclarés dans `imports: []` du composant.

### Injection

Utiliser `inject()` :

```ts
readonly #service = inject(MyService);
```

Règles :

- Ne pas injecter via `constructor`.
- Utiliser les champs privés `#service`.
- Éviter `private`.

### Inputs / Outputs

Utiliser les APIs modernes :

```ts
readonly user = input.required<User>();
readonly updated = output<string>();
```

Règles :

- Ne pas utiliser `@Input()`.
- Ne pas utiliser `@Output()`.
- Préférer `input.required<T>()` quand la donnée est obligatoire.
- Éviter les valeurs `null`; préférer `undefined`.

### Réactivité

Utiliser :

```ts
signal()
computed()
effect()
```

Règles :

- Utiliser `computed()` pour dériver l'état.
- Utiliser `effect()` uniquement pour les effets nécessaires.
- Ne pas utiliser RxJS dans les composants sauf contrainte existante.
- RxJS reste acceptable dans les services métier.
- Éviter les subscriptions manuelles dans les composants.

### Typage

- Ne pas utiliser `any`.
- Préférer `unknown` si le type est réellement inconnu.
- Définir des interfaces explicites.
- Éviter `null`; utiliser `undefined`.
- Ne pas élargir les types inutilement.

## Services

- Logique métier dans les services.
- RxJS autorisé dans les services métier.
- Les composants restent orientés présentation/orchestration.

## Tests

- Utiliser Jest.
- Préférer `fixture.componentRef.setInput()` pour les inputs standalone.
- Tester les comportements visibles et les outputs.
- Mock minimal et lisible.
- Ne pas tester les détails d'implémentation privés.

## UI / accessibilité

- Les boutons doivent avoir un libellé ou un `aria-label`.
- Les actions critiques doivent être explicites.
- Préserver les états loading, empty, error.
- Ne pas casser le responsive.

## SCSS

- Préserver les conventions existantes.
- Éviter la duplication.
- Ne pas ajouter de styles globaux sans nécessité.
- Préférer des classes lisibles et spécifiques au composant.
