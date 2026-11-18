---
name: laravel-cruddy-by-design
description: Use when generating or refactoring Laravel controllers and routes. Enforces strict RESTful controllers (max 7 default methods or invokable) and favours resource-based routing over custom verbs.
---

# Check Laravel Controller Implementation

Verify that the application uses "Cruddy by Design" RESTful controllers.

## Quick Reference

| Scenario | Critical Implementation |
|----------|--------------|
| Standard Resource | `Route::resource()` + max 7 default methods (`index`, `show`, `create`, `store`, `edit`, `update`, `destroy`) |
| Custom Verb (e.g., Publish) | Extract to new `Invokable Controller` or use `store/destroy` on a State Resource |
| Nested Resource (Child items) | Dedicated Controller (e.g., `PodcastEpisodeController@index`) |
| Pivot Table Interaction | Dedicated Controller treating pivot as a resource (e.g., `SubscriptionController@store`) |
| Controller Responsibility | HTTP Layer only (Request validation, Model interaction, HTTP Response) |

## Critical Checks

For every controller and route:
- [ ] Controller contains ONLY standard CRUD methods or `__invoke`
- [ ] No custom method names (e.g., NO `publish()`, `subscribe()`, `updateCoverImage()`)
- [ ] Route uses `Route::resource()`, `Route::apiResource()`, or standard explicit mapping
- [ ] FormRequests are used for validation before reaching the controller logic

## Essential Patterns

### Route Definitions (REQUIRED for clean architecture)

```php
// ❌ BAD: Custom verbs leading to fat controllers
Route::post('/podcasts/{podcast}/publish', [PodcastController::class, 'publish']);

// ✅ GOOD: State represented as a resource using a Single Action Controller
Route::post('/podcasts/{podcast}/publish', PublishPodcastController::class);

// ✅ GOOD: Nested resource mapped cleanly
Route::get('/podcasts/{podcast}/episodes', [PodcastEpisodeController::class, 'index']);
```

### The Dumb Controller (MUST be thin)

```php
// ❌ BAD: Mixed HTTP and Business Logic
public function store(Request $request)
{
    $validated = $request->validate([...]);
    $user = User::create($validated);
    $user->assignRole('author');
    Mail::to($user)->send(new WelcomeEmail());
    return redirect()->route('home');
}

// ✅ GOOD: HTTP concerns only, delegate logic elsewhere
public function store(RegisterUserRequest $request)
{
    $user = User::create($request->validated());
    // Business logic (roles, emails) should be handled outside the controller
    return redirect()->route('home')->with('success', 'User created');
}
```

## Refactoring Custom Actions

When encountering a custom action requirement, split it into a specific resource:

| Instead of (Fat Controller) | Use Dedicated Controller (Cruddy) |
| --- | --- |
| `PodcastController@listEpisodes` | `PodcastEpisodeController@index` |
| `PodcastController@updateCover` | `PodcastCoverImageController@update` |
| `PodcastController@subscribe` | `SubscriptionController@store` |
| `PodcastController@publish` | `PublishPodcastController@__invoke` |

## State Transitions

For concepts that toggle a state, treat the state itself as a resource:

```php
// Creating a "Published" state
class PublishedPodcastController extends Controller
{
    // 'store' means "create a published state"
    public function store(Podcast $podcast)
    {
        $podcast->publish();
        return back();
    }

    // 'destroy' means "remove the published state"
    public function destroy(Podcast $podcast)
    {
        $podcast->unpublish();
        return back();
    }
}
```

