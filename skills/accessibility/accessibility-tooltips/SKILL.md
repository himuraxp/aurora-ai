---
name: accessibility-tooltips
description: Use when checking tooltips, popups, hover content, and dismissible content that appears on hover or focus.
---

# Manage Hover and Focus Content

Ensure additional content that appears on hover or focus is dismissible, hoverable, persistent, and accessible to screen readers.

## Quick Reference

| Scenario | Requirement | Implementation |
|----------|-------------|----------------|
| **Dismissible** | Close without moving pointer/focus | Escape key or click outside |
| **Hoverable** | Move to content without disappearing | Sufficient gap or delay |
| **Persistent** | Remains visible until dismissed | Until explicit user action |
| **Screen reader** | Content announced | role="tooltip" + aria-describedby |
| **Keyboard** | Accessible via focus | Show on focus, hide on blur |

## Critical Checks

### Dismissible Content

Users must be able to dismiss tooltip content without moving their pointer or focus:

- [ ] Press Escape key dismisses the tooltip
- [ ] Click outside the tooltip dismisses it
- [ ] Tooltip doesn't block access to other content
- [ ] Dismissal doesn't move focus unexpectedly

```javascript
// Dismiss on Escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    hideAllTooltips();
  }
});

// Dismiss on click outside
document.addEventListener('click', (e) => {
  if (!e.target.closest('[data-tooltip]') && !e.target.closest('.tooltip')) {
    hideAllTooltips();
  }
});
```

### Hoverable Content

Users must be able to move their pointer from the trigger to the tooltip content without it disappearing:

- [ ] Gap between trigger and tooltip is hoverable
- [ ] Tooltip stays visible when moving mouse over it
- [ ] Sufficient time to reach content (delay or persistent trigger area)
- [ ] Tooltip remains open during interaction with content

```css
/* Create hoverable gap with pseudo-element or padding */
.tooltip-trigger:hover .tooltip,
.tooltip-trigger:focus .tooltip,
.tooltip:hover {
  opacity: 1;
  visibility: visible;
}

/* Ensure tooltip is reachable */
.tooltip {
  margin-top: 8px; /* Creates hoverable gap */
  pointer-events: auto; /* Allows interaction with tooltip */
}
```

### Persistent Content

Tooltip content must remain visible until:

- [ ] User explicitly dismisses it (Escape or click outside)
- [ ] User moves focus or hover away from both trigger and content
- [ ] The information is no longer valid (e.g., validation success message)
- [ ] User activates another control

```javascript
// Persistent tooltip behavior
class AccessibleTooltip {
  constructor(trigger) {
    this.trigger = trigger;
    this.tooltip = document.getElementById(trigger.getAttribute('aria-describedby'));
    this.isVisible = false;
    
    // Show on hover/focus
    trigger.addEventListener('mouseenter', () => this.show());
    trigger.addEventListener('focus', () => this.show());
    
    // Hide only when leaving both trigger and tooltip
    trigger.addEventListener('mouseleave', (e) => this.handleMouseLeave(e));
    this.tooltip.addEventListener('mouseleave', () => this.hide());
    trigger.addEventListener('blur', () => this.hide());
    
    // Keep visible when hovering tooltip
    this.tooltip.addEventListener('mouseenter', () => this.show());
  }
  
  show() {
    this.tooltip.style.display = 'block';
    this.isVisible = true;
  }
  
  hide() {
    this.tooltip.style.display = 'none';
    this.isVisible = false;
  }
  
  handleMouseLeave(e) {
    // Wait to see if entering tooltip
    setTimeout(() => {
      if (!this.tooltip.matches(':hover')) {
        this.hide();
      }
    }, 100);
  }
}
```

### Screen Reader Support

Tooltips must be accessible to assistive technologies:

- [ ] Tooltip container has `role="tooltip"`
- [ ] Trigger element uses `aria-describedby` pointing to tooltip
- [ ] Complex tooltips use `aria-labelledby` for primary content
- [ ] Tooltip content is in the DOM before becoming visible

```html
<!-- Simple tooltip with aria-describedby -->
<button aria-describedby="tooltip-help" class="tooltip-trigger">
  Help
</button>
<div 
  id="tooltip-help" 
  role="tooltip"
  class="tooltip"
  hidden
>
  This action will save your changes
</div>

<!-- Complex tooltip with aria-labelledby -->
<button aria-labelledby="tooltip-label" aria-describedby="tooltip-desc" class="tooltip-trigger">
  Info
</button>
<div 
  id="tooltip-label" 
  role="tooltip"
  class="tooltip"
  hidden
>
  <strong>Save Document</strong>
  <span id="tooltip-desc">Stores your current progress to the server</span>
</div>
```

## Implementation Patterns

### CSS-Only Tooltip (Simple)

For simple tooltips without complex interactions:

```html
<button class="tooltip-trigger" aria-label="More information about this feature" aria-describedby="tooltip-1">
  <span aria-hidden="true">?</span>
</button>
<span id="tooltip-1" role="tooltip" class="tooltip">
  This feature allows advanced configuration of user preferences
</span>
```

```css
.tooltip {
  position: absolute;
  display: none;
  background: #333;
  color: #fff;
  padding: 0.5rem;
  border-radius: 4px;
  max-width: 250px;
  z-index: 1000;
}

/* Show on hover and focus */
.tooltip-trigger:hover + .tooltip,
.tooltip-trigger:focus + .tooltip {
  display: block;
}
```

### JavaScript-Controlled Tooltip (Complete)

For accessible tooltips with full keyboard support:

```html
<button 
  class="tooltip-trigger" 
  data-tooltip="tooltip-1"
  aria-describedby="tooltip-1"
>
  Save
</button>
<div 
  id="tooltip-1" 
  role="tooltip"
  class="tooltip"
  hidden
>
  Save your changes to the server
</div>
```

```css
.tooltip {
  position: absolute;
  background: #333;
  color: #fff;
  padding: 0.5rem;
  border-radius: 4px;
  max-width: 250px;
  z-index: 1000;
  pointer-events: auto; /* Allow interaction with tooltip */
}

.tooltip[hidden] {
  display: none;
}

.tooltip-trigger {
  position: relative;
}
```

```javascript
// Complete accessible tooltip implementation
class AccessibleTooltip {
  constructor(trigger) {
    this.trigger = trigger;
    this.tooltipId = trigger.getAttribute('data-tooltip') || 
                     trigger.getAttribute('aria-describedby');
    this.tooltip = document.getElementById(this.tooltipId);
    
    if (!this.tooltip) return;
    
    this.initialize();
  }
  
  initialize() {
    // Position tooltip relative to trigger
    this.positionTooltip();
    
    // Event listeners
    this.trigger.addEventListener('mouseenter', () => this.show());
    this.trigger.addEventListener('mouseleave', (e) => this.handleTriggerLeave(e));
    this.trigger.addEventListener('focus', () => this.show());
    this.trigger.addEventListener('blur', () => this.hide());
    
    // Allow hovering tooltip content
    this.tooltip.addEventListener('mouseenter', () => this.show());
    this.tooltip.addEventListener('mouseleave', () => this.hide());
    
    // Dismiss on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.isVisible) {
        this.hide();
        this.trigger.focus();
      }
    });
    
    // Dismiss on click outside
    document.addEventListener('click', (e) => {
      if (!this.trigger.contains(e.target) && !this.tooltip.contains(e.target)) {
        this.hide();
      }
    });
  }
  
  show() {
    this.tooltip.hidden = false;
    this.isVisible = true;
    this.positionTooltip();
  }
  
  hide() {
    this.tooltip.hidden = true;
    this.isVisible = false;
  }
  
  positionTooltip() {
    const rect = this.trigger.getBoundingClientRect();
    this.tooltip.style.position = 'fixed';
    this.tooltip.style.top = `${rect.bottom + 8}px`;
    this.tooltip.style.left = `${rect.left}px`;
  }
  
  handleTriggerLeave(e) {
    // Small delay to allow moving to tooltip
    setTimeout(() => {
      if (!this.tooltip.matches(':hover') && !this.trigger.matches(':hover')) {
        this.hide();
      }
    }, 50);
  }
}

// Initialize all tooltips
document.querySelectorAll('[data-tooltip], [aria-describedby][role="tooltip"]').forEach(trigger => {
  new AccessibleTooltip(trigger);
});
```

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Simple tooltip** | CSS hover/focus + aria-describedby | Implementation patterns above |
| **Dismissible tooltip** | JavaScript with Escape handler | Critical checks - Dismissible |
| **Hoverable tooltip** | Mouse event handlers with delay | Critical checks - Hoverable |
| **Complex content tooltip** | Use modal dialog instead | `accessibility-aria` for dialog pattern |
| **Form validation tooltip** | Associated with input via aria-describedby | `accessibility-forms` for validation |
| **Icon button tooltip** | aria-label on button + visual tooltip | `accessibility-aria` for accessible names |

## When to Use Tooltips

Use tooltips appropriately by following these guidelines:

**Appropriate uses:**
- Supplementary information that repeats visible text (icon meanings)
- Additional context for abbreviations or technical terms
- Non-critical help text for form controls
- Keyboard shortcut hints

**Avoid using tooltips for:**
- Critical information users must see (use inline text)
- Complex content requiring interaction (use modal/popover)
- Form error messages (use inline error text with aria-invalid)
- Content that doesn't fit in a small container (use expandable sections)
- Content that requires scrolling (use modal or page)

**Better alternatives:**
```html
<!-- Use inline text for critical info -->
<label for="password">
  Password
  <small>Must be at least 8 characters with one number</small>
</label>

<!-- Use modal for complex content -->
<button aria-haspopup="dialog" aria-controls="help-modal">
  Detailed Help
</button>
<dialog id="help-modal">
  <!-- Complex help content with rich formatting -->
</dialog>
```

## Testing

For comprehensive tooltip testing procedures, use `accessibility-evaluation`.

## RGAA Correspondences

- **7.1-7.5**: Scripts and dynamic content control
- **10.1-10.7**: Information presentation via CSS
- **7.3**: Context changes notified (announcements via aria-live)

## Related Skills

- Use `accessibility-focus` for focus management in tooltips
- Use `accessibility-aria` for tooltip roles and complex patterns
- Use `accessibility-forms` for form validation patterns (avoid error tooltips)
- Use `accessibility-evaluation` for testing hover/focus behavior
- Use `accessibility-keyboard` for keyboard interaction patterns

## Resources

- [ARIA Tooltip Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/tooltip/)
- [Understanding Content on Hover or Focus](https://www.w3.org/WAI/WCAG22/Understanding/content-on-hover-or-focus)
- [Tooltips and Toggle Tips Tutorial](https://www.w3.org/WAI/tutorials/forms/tooltips/)
