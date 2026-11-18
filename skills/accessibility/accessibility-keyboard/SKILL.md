---
name: accessibility-keyboard
description: Use when ensuring all functionality is available via keyboard, implementing keyboard navigation patterns, and managing focus order. Essential for keyboard-only and assistive technology users.
---

# Navigate with Keyboard

Ensure all functionality can be accessed and operated using only a keyboard.

## Quick Reference

| Key | Action |
|-----|--------|
| **Tab** | Move focus forward |
| **Shift + Tab** | Move focus backward |
| **Enter** | Activate buttons, links, submit forms |
| **Space** | Activate buttons, toggle checkboxes |
| **Arrow Keys** | Navigate within groups (menus, lists) |
| **Escape** | Close menus, dialogs, popups |
| **Home / End** | Move to start/end of list |

## Critical Checks

### Keyboard Operations by Element

| Element | Tab | Activation | Navigation |
|---------|-----|------------|------------|
| **Button** | Focus with Tab | Enter or Space | — |
| **Link** | Focus with Tab | Enter | — |
| **Checkbox** | Focus with Tab | Space to toggle | — |
| **Radio group** | Focus group with Tab | Space to select | Arrow keys change selection |
| **Select dropdown** | Focus with Tab | Enter or Space to open | Arrow keys navigate options |
| **Menu/Navigation** | Focus with Tab | Enter or Space | Arrow keys navigate items |
| **Slider** | Focus with Tab | Arrow keys change value | Home/End for min/max |

### Focus Order

- [ ] Tab follows visual top-to-bottom, left-to-right
- [ ] No positive tabindex values (use 0 or natural DOM order)
- [ ] Focus doesn't jump unexpectedly
- [ ] Custom widgets maintain logical sequence

### No Keyboard Traps

- [ ] Can Tab or Shift+Tab out of all components
- [ ] Dialogs close with Escape key
- [ ] Focus returns to trigger when modal closes
- [ ] No infinite loops in custom navigation

**Escape Key Implementation:**
```javascript
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && modalIsOpen) {
    closeModal();
    triggerButton.focus(); // Restore focus
  }
});
```

### Character Key Shortcuts

- [ ] Single-character shortcuts can be turned off or remapped
- [ ] Shortcuts use modifiers (Ctrl, Alt) or require component focus
- [ ] Global shortcuts documented and configurable

**Implementation:**
```javascript
// With modifier - acceptable
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    saveDocument();
  }
});

// Component-specific - acceptable
textEditor.addEventListener('keydown', (e) => {
  if (e.key === '/' && document.activeElement === textEditor) {
    showCommandPalette();
  }
});
```

## Focus Management Patterns

### Skip Links

Provide bypass links at page start:

```html
<a href="#main-content" class="skip-link">Skip to main content</a>

<main id="main-content" tabindex="-1">
  <!-- Content -->
</main>
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

### Focus Trap in Modals

When modal is open, Tab cycles within modal only:

```javascript
function trapFocus(containerElement) {
  const focusableElements = containerElement.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  const firstElement = focusableElements[0];
  const lastElement = focusableElements[focusableElements.length - 1];

  containerElement.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
      if (e.shiftKey && document.activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
      } else if (!e.shiftKey && document.activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
      }
    }
  });
}
```

### Keyboard Event Handling

Use `e.key` instead of deprecated `keyCode`:

```javascript
element.addEventListener('keydown', (e) => {
  switch(e.key) {
    case 'Enter':
      // Activate
      break;
    case ' ':
      e.preventDefault(); // Prevent scroll
      // Toggle
      break;
    case 'Escape':
      // Close/dismiss
      break;
    case 'ArrowUp':
    case 'ArrowDown':
      // Navigate vertically
      break;
  }
});
```

### Custom Dropdown Menu

```javascript
button.addEventListener('keydown', (e) => {
  switch(e.key) {
    case 'ArrowDown':
      e.preventDefault();
      openMenu();
      menu.querySelector('[role="menuitem"]').focus();
      break;
    case 'Escape':
      closeMenu();
      button.focus();
      break;
  }
});

// Menu item navigation
menu.addEventListener('keydown', (e) => {
  const items = menu.querySelectorAll('[role="menuitem"]');
  const currentIndex = Array.from(items).indexOf(document.activeElement);
  
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    const nextIndex = (currentIndex + 1) % items.length;
    items[nextIndex].focus();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    const prevIndex = (currentIndex - 1 + items.length) % items.length;
    items[prevIndex].focus();
  }
});
```

### Drag and Drop Alternative

Provide buttons for keyboard users:

```javascript
// Instead of only drag-and-drop
<button onclick="moveItemUp(index)">Move up</button>
<button onclick="moveItemDown(index)">Move down</button>

function moveItemUp(index) {
  if (index > 0) {
    swapItems(index, index - 1);
    announceToScreenReader(`Item moved to position ${index}`);
  }
}
```

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Button activation** | Enter or Space to activate | Critical checks above |
| **Link navigation** | Enter to follow link | Critical checks above |
| **Menu navigation** | Arrow keys to navigate items, Enter to select | `accessibility-aria` for menu roles |
| **Modal dialog** | Tab traps focus, Esc to close | `accessibility-focus` for focus trap |
| **Slider control** | Arrow keys adjust value | Critical checks above |
| **Drag and drop** | Up/down buttons for reordering | Critical checks above |

## Testing

For comprehensive keyboard navigation testing procedures, use `accessibility-evaluation`.

### Quick Verification
- [ ] All interactive elements reachable via Tab
- [ ] Tab order follows visual layout
- [ ] Enter/Space activate controls appropriately
- [ ] Arrow keys navigate within widgets
- [ ] Escape closes dialogs and menus
- [ ] No keyboard traps present

## RGAA Correspondences

- **7.1**: Scripts must be keyboard accessible
- **7.2**: Drag-and-drop alternatives provided
- **10.12**: Focus visible with sufficient contrast
- **12.6**: Skip links to bypass navigation blocks

## Related Skills

- Use `accessibility-focus` for focus visibility and skip links
- Use `accessibility-aria` for custom widget implementation
- Use `accessibility-forms` for form-specific keyboard patterns
- Use `accessibility-evaluation` for comprehensive keyboard testing methodology

## Resources

- [Understanding Keyboard](https://www.w3.org/WAI/WCAG22/Understanding/keyboard)
- [Understanding No Keyboard Trap](https://www.w3.org/WAI/WCAG22/Understanding/no-keyboard-trap)
- [Understanding Character Key Shortcuts](https://www.w3.org/WAI/WCAG22/Understanding/character-key-shortcuts)
- [WebAIM Keyboard Accessibility](https://webaim.org/techniques/keyboard/)
- [ARIA Authoring Practices - Keyboard Interface](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/)
