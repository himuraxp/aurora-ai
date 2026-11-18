---
name: accessibility-motion
description: Use when checking time limits, auto-playing content, animations, and flashing content that could cause seizures or physical reactions.
---

# Control Time and Motion

Ensure users have sufficient time to interact, can control moving content, and are protected from seizure-inducing flashes.

## Quick Reference

| Scenario | Action Required | Implementation |
|----------|----------------|----------------|
| **Time limits** | User control options | Turn off, adjust, or extend with warning |
| **Moving/blinking content** | Pause mechanism | Stop auto-play after 5 seconds |
| **Auto-updating content** | User controls | Pause, stop, or adjust frequency |
| **Session timeouts** | Warning and recovery | Warn before 20h inactivity, allow data recovery |
| **Flashing content** | Flash prevention | Maximum 3 flashes per second |
| **Animations** | Motion preference | Respect prefers-reduced-motion |

## Critical Checks

### Time Limits

For any time-limited content or interactions:

- [ ] Users can turn off time limits before encountering them
- [ ] Users can adjust time limits to at least 10x the default
- [ ] Warning displayed at least 20 seconds before expiration
- [ ] Simple action to extend time (e.g., press Space bar)
- [ ] Allow extension at least 10 times

**Exceptions allowed:**
- Real-time events (auctions, live trading)
- Essential time limits (tests, security)
- Limits longer than 20 hours

```html
<!-- Timer with extend option -->
<div role="timer" aria-live="polite" aria-atomic="true">
  Time remaining: <span id="time-left">5:00</span>
</div>
<button onclick="extendTime()">Extend time (+5 minutes)</button>

<!-- Warning before timeout -->
<div role="alert" id="timeout-warning" hidden>
  Your session will expire in 20 seconds. Press Space to continue.
</div>
```

### Pause, Stop, Hide

For auto-starting moving, blinking, or scrolling content:

- [ ] Mechanism to pause, stop, or hide content
- [ ] Applies to content starting automatically
- [ ] Applies to content lasting more than 5 seconds
- [ ] Applies to content presented in parallel with other content

**For auto-updating content:**
- [ ] Mechanism to pause, stop, hide, or control frequency
- [ ] Applies to any auto-updating content (no 5-second exception)

```html
<!-- Carousel with controls -->
<div class="carousel" role="region" aria-label="News carousel">
  <button aria-label="Pause carousel" onclick="pauseCarousel()">⏸</button>
  <button aria-label="Previous slide" onclick="prevSlide()">←</button>
  <button aria-label="Next slide" onclick="nextSlide()">→</button>
  <div class="slides">
    <!-- Carousel content -->
  </div>
</div>

<!-- Scrolling ticker with pause -->
<div class="ticker">
  <div class="ticker-content" id="ticker">
    Latest news: Breaking developments in accessibility standards...
  </div>
  <button aria-label="Pause news ticker" onclick="pauseTicker()">Pause</button>
</div>
```

### Session Timeouts

For sessions with inactivity timeouts (Level AA):

- [ ] Warning provided before data loss
- [ ] At least 20 seconds to extend session
- [ ] Simple action to extend (e.g., press Space)
- [ ] Data preserved for at least 20 hours of user inactivity
- [ ] User can continue activity without loss of data

```javascript
// Timeout warning pattern
let inactivityTimer;
const TIMEOUT_WARNING = 20 * 60 * 60 * 1000; // 20 hours
const WARNING_DURATION = 20000; // 20 seconds

function resetTimer() {
  clearTimeout(inactivityTimer);
  inactivityTimer = setTimeout(showTimeoutWarning, TIMEOUT_WARNING);
}

function showTimeoutWarning() {
  const warning = document.getElementById('timeout-warning');
  warning.hidden = false;
  
  setTimeout(() => {
    if (!warning.hidden) {
      saveDataAndLogout();
    }
  }, WARNING_DURATION);
}

// Reset on user activity
document.addEventListener('keydown', resetTimer);
document.addEventListener('mousedown', resetTimer);
```

### Flashing Content

To prevent seizures and physical reactions:

- [ ] No content flashes more than 3 times per second
- [ ] Combined flashing area does not exceed 341×256 CSS pixels (25% of screen)
- [ ] Special caution with saturated red colors (red flashes)
- [ ] Test all animated content including GIFs and videos

**Flash thresholds:**
- General flash: Opposing luminance change >10% where darker state <0.80 
- Red flash: Opposing transitions involving saturated red
- Safe: ≤3 flashes per second OR small area (<25% screen)

**Testing tools:**
- Harding Flash and Pattern Analyzer (FPA)
- PEAT (Photosensitive Epilepsy Analysis Tool) - Trace Center

```css
/* Safe animation - limited duration and speed */
@keyframes safe-flash {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.safe-indicator {
  animation: safe-flash 2s ease-in-out 3; /* Runs 3 times over 6 seconds */
}
```

### Motion and Animation Preferences

Respect user preferences for reduced motion:

```css
/* Honor user preference for reduced motion */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
  
  /* Stop auto-playing carousels */
  .carousel {
    animation: none !important;
  }
  
  /* Disable parallax */
  .parallax {
    transform: none !important;
  }
}

/* Alternative: Provide toggle for animations */
.reduce-motion .animated-element {
  animation: none;
  transition: none;
}
```

### Auto-playing Audio Control

Audio auto-playing for more than 3 seconds is covered in detail in `accessibility-media`.

Brief requirements:
- [ ] Mechanism to pause or stop audio
- [ ] Or: Mechanism to control volume independently from system
- [ ] Must be available within first 3 seconds

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Session timeout** | Warning at 20h, extend option, data preservation | `accessibility-forms` for form data |
| **Carousel** | Pause button, manual navigation, reduced motion support | `accessibility-keyboard` for navigation |
| **Auto-updating dashboard** | Frequency control, pause/resume, timestamps | `accessibility-aria` for live regions |
| **Animated notifications** | Dismissible, non-blocking, respect reduced motion | `accessibility-tooltips` |
| **Video backgrounds** | Pause control, no auto-play with sound | `accessibility-media` |

## Testing

For comprehensive motion and timing testing procedures, use `accessibility-evaluation`.

## RGAA Correspondences

- **5.x**: Time limits and timeouts (session management)
- **13.x**: User consultation restrictions (flashing content)
- **7.x**: Scripts and dynamic content control

## Related Skills

- Use `accessibility-media` for audio control and media player accessibility
- Use `accessibility-tooltips` for dismissible notifications and popups
- Use `accessibility-evaluation` for testing animation and motion
- Use `accessibility-keyboard` for accessible controls
- Use `accessibility-forms` for form session management

## Resources

- [Understanding Timing Adjustable](https://www.w3.org/WAI/WCAG22/Understanding/timing-adjustable)
- [Understanding Pause, Stop, Hide](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide)
- [Understanding Timeouts](https://www.w3.org/WAI/WCAG22/Understanding/timeouts)
- [Understanding Three Flashes](https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold)
- [PEAT Tool - Photosensitive Epilepsy Analysis](https://trace.umd.edu/peat/)
