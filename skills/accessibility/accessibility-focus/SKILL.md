---
name: accessibility-focus
description: Use when checking focus visibility, skip links, focus order, and focus indicators. Ensures users can see where they are on the page and navigate efficiently.
---

# Manage Focus Visibility

Ensure keyboard users can always see which element has focus and navigate efficiently.

## Quick Reference

| Scenario | Solution |
|----------|----------|
| Skip navigation | `href="#main"` link + `tabindex="-1"` on target |
| Focus indicator | Outline 2px solid + 3:1 contrast ratio |
| Focus obscured | Check element not hidden 100% by sticky headers |
| Focus order | Tab follows visual order (top→bottom, left→right) |
| Modal dialogs | Trap focus inside, return focus on close |

## Critical Checks

### Skip Links

- [ ] Skip to main content link provided
- [ ] Skip to navigation link (optional)
- [ ] Link visible on Tab (not hover)
- [ ] Target element has `tabindex="-1"`
- [ ] Focus moves to target content (not just viewport)

**Implementation:**
```html
<a href="#main" class="skip-link">Skip to main content</a>
<nav>...</nav>
<main id="main" tabindex="-1">...</main>
```

```css
.skip-link {
  position: absolute;
  top: -40px;
  left: 0;
  background: #000;
  color: #fff;
  padding: 8px;
  z-index: 100;
}
.skip-link:focus {
  top: 0;
}
```

### Focus Visibility

- [ ] All interactive elements show visible focus
- [ ] Focus indicator has minimum 3:1 contrast
- [ ] Focus indicator is at least 2px thick
- [ ] Focus visible on keyboard navigation (`:focus-visible`)

**Focus Indicator Options:**
```css
/* Option 1: Outline */
:focus-visible {
  outline: 2px solid #0056b3;
  outline-offset: 2px;
}

/* Option 2: Background + border */
:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px white, 0 0 0 4px #0056b3;
}

/* Option 3: Inverted colors */
:focus-visible {
  background-color: #0056b3;
  color: #fff;
  outline: 2px solid #0056b3;
}
```

### Focus Not Obscured (Focus Not Hidden by Sticky Content)

When scrollable content has sticky headers/footers, the focused element must not be completely hidden:

- [ ] Tab through page with sticky header present
- [ ] Verify focused element is not 100% obscured
- [ ] Check dialog/modal doesn't hide focused trigger
- [ ] Test mobile viewports with fixed navigation

**Implementation Approaches:**
```css
/* Solution 1: Scroll padding for sticky header */
html {
  scroll-padding-top: 80px; /* Height of sticky header */
}

/* Solution 2: Element margin when focused */
:focus-visible {
  scroll-margin-top: 80px;
}
```

### Focus Order and Traps

- [ ] Tab follows visual top-to-bottom order
- [ ] No unexpected focus jumps
- [ ] Modal dialogs trap focus within modal
- [ ] Focus returns to trigger when modal closes

**Modal Focus Trap Example:**
```javascript
// When opening modal
modal.showModal();
const firstFocusable = modal.querySelector('button, [href], input, select');
firstFocusable.focus();

// When closing modal
modal.close();
triggerButton.focus(); // Return focus to trigger
```

**Trap Navigation:**
```javascript
// Tab cycles within modal only
modal.addEventListener('keydown', (e) => {
  if (e.key === 'Tab') {
    const focusables = modal.querySelectorAll('button, [href], input');
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
});
```

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Skip links** | First focusable element, visible on Tab | Critical checks above |
| **Focus indicator** | Outline 2px+ solid with 3:1 contrast | `accessibility-color-contrast` |
| **Focus not obscured** | scroll-padding-top or scroll-margin-top | Critical checks above |
| **Modal focus trap** | Tab cycles within dialog, Esc to close | `accessibility-aria` for dialogs |
| **Focus return** | Restore focus to trigger on close | JavaScript focus() call |

## Testing

For comprehensive focus testing procedures, use `accessibility-evaluation`.

## RGAA Correspondences

- **12.6**: Skip links to bypass navigation blocks
- **12.7**: Skip links visible and functional
- **10.12**: Focus visible with sufficient contrast
- **10.13**: Focus not obscured by other elements
- **7.4**: Modal windows trap focus properly

## Related Skills

- Use `accessibility-evaluation` for comprehensive testing methodology
- Use `accessibility-keyboard` for keyboard navigation patterns
- Use `accessibility-color-contrast` for checking focus indicator contrast
- Use `accessibility-navigation` for landmark structure
- Use `accessibility-aria` for focus management in custom components

## Resources

- [Understanding Focus Visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible)
- [Understanding Focus Not Obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum)
- [Focus Appearance Understanding](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance)
- [ARIA Focus Management](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/)
