---
name: accessibility-aria
description: Use when checking ARIA implementation, roles, states, properties, accessible names, and status messages for screen readers. Critical for custom components and dynamic content.
---

# Check ARIA Implementation

Verify that custom components use correct ARIA markup for assistive technologies.

## Quick Reference

| Scenario | Critical ARIA |
|----------|--------------|
| Custom button | `role="button"` + `tabindex="0"` + keyboard handler |
| Modal/Dialog | `role="dialog" aria-modal="true"` + focus trap |
| Expandable content | `aria-expanded` + `aria-controls` |
| Tab interface | `role="tablist/tab"` + `aria-selected` + `aria-controls` |
| Live updates | `aria-live="polite/assertive"` + `aria-atomic` |
| Form validation | `aria-invalid="true"` + `aria-errormessage` |
| Current location | `aria-current="page/step/date"` |
| Loading state | `aria-busy="true"` |

## Critical Checks

For every custom component:
- [ ] Has `role` attribute matching its behavior
- [ ] Has accessible name via `aria-label`, `aria-labelledby`, or content
- [ ] State changes announced (`aria-expanded`, `aria-selected`, `aria-checked`)
- [ ] Values programmatic (`aria-valuenow`, `aria-valuetext` for sliders)
- [ ] Interactive ARIA widgets ARE keyboard accessible
- [ ] `aria-controls` links control to controlled element
- [ ] `aria-current="page"` marks current nav item

For modals/dialogs:
- [ ] `role="dialog"` present
- [ ] `aria-modal="true"` for blocking modals
- [ ] `aria-labelledby` points to title heading
- [ ] Focus trapped inside modal
- [ ] Focus returns to trigger on close

## Essential Attributes

### Accessible Names (REQUIRED for all interactive elements)

```html
<!-- aria-label for icon-only buttons -->
<button aria-label="Close">×</button>

<!-- aria-labelledby for complex labels -->
<h2 id="modal-title">Confirm Delete</h2>
<div role="dialog" aria-labelledby="modal-title">...</div>

<!-- aria-describedby for helper text -->
<input aria-describedby="password-hint">
<p id="password-hint">Must be 8+ characters</p>
```

### State Attributes (MUST update with JS)

```html
<!-- Toggle buttons -->
<button aria-pressed="false">Mute</button>

<!-- Expandable content -->
<button aria-expanded="false" aria-controls="panel-1">Show More</button>
<div id="panel-1" hidden>...</div>

<!-- Tabs -->
<button role="tab" aria-selected="true" aria-controls="tab-1">Tab 1</button>

<!-- Form validation -->
<input aria-invalid="true" aria-errormessage="email-error">
<span id="email-error">Invalid email format</span>

<!-- Checkboxes -->
<div role="checkbox" aria-checked="true" tabindex="0">Subscribe</div>

<!-- Sliders -->
<div role="slider" aria-valuenow="50" aria-valuemin="0" aria-valuemax="100">Volume</div>
```

### Navigation Attributes

```html
<!-- aria-controls links trigger to content -->
<button aria-controls="search-modal" aria-expanded="false">Search</button>

<!-- aria-current marks active item -->
<a href="/current-page" aria-current="page">Current Page</a>
<ol>
  <li aria-current="step">Step 2 (active)</li>
</ol>

<!-- aria-details for long descriptions -->
<img src="chart.png" aria-details="chart-desc" alt="Sales chart">
<div id="chart-desc">Detailed breakdown...</div>
```

### Live Regions

```html
<!-- Error messages (interruptive) -->
<div role="alert">
  Payment failed: please check your card
</div>

<!-- Success/status (non-interruptive) -->
<div role="status">
  Profile updated successfully
</div>

<!-- Dynamic content updates -->
<ul aria-live="polite" aria-atomic="false">
  <li>Item 1</li>
</ul>

<!-- Loading state -->
<div aria-live="polite" aria-busy="true">Loading results...</div>
```

### Advanced Attributes

```html
<!-- aria-activedescendant for virtual focus (combobox, listbox) -->
<div role="combobox" aria-activedescendant="option-1" tabindex="0">
  <ul role="listbox">
    <li role="option" id="option-1" aria-selected="true">Option 1</li>
  </ul>
</div>

<!-- aria-owns for DOM restructuring -->
<div role="tree" aria-owns="node-1 node-2">
  <div role="treeitem" id="node-1">Item 1</div>
</div>
<div role="treeitem" id="node-2">Item 2 (moved via aria-owns)</div>

<!-- aria-haspopup for popups -->
<button aria-haspopup="dialog" aria-controls="modal">Open Modal</button>
<button aria-haspopup="menu" aria-controls="dropdown">Menu</button>

<!-- aria-orientation -->
<div role="separator" aria-orientation="vertical"></div>
```

## Split Keyboard Focus with Roving Tabindex

For composite widgets (tabs, listbox, treeview):

```html
<div role="tablist">
  <button role="tab" tabindex="0">Tab 1</button>    <!-- Focusable -->
  <button role="tab" tabindex="-1">Tab 2</button>   <!-- Not focusable -->
  <button role="tab" tabindex="-1">Tab 3</button>   <!-- Not focusable -->
</div>
```

```javascript
// Arrow navigation updates tabindex
function moveFocus(current, next) {
  current.setAttribute('tabindex', '-1');
  next.setAttribute('tabindex', '0');
  next.focus();
}
```

## Testing

For comprehensive ARIA testing procedures, use `accessibility-evaluation`.

## Common Patterns

| Pattern | Critical ARIA | See Also |
|---------|--------------|----------|
| **Modal/Dialog** | `role="dialog" aria-modal="true" aria-labelledby` | `accessibility-focus` for traps |
| **Tabs** | `role="tablist/tab" aria-selected aria-controls` | Arrow keys → `accessibility-keyboard` |
| **Accordion** | `aria-expanded aria-controls` | See Disclosure pattern in APG |
| **Combobox** | `role="combobox" aria-activedescendant aria-controls` | Complex - use native when possible |
| **Treeview** | `role="tree" aria-expanded aria-owns` | Arrow nav + expand/collapse |
| **Listbox** | `role="listbox" aria-selected aria-multiselectable` | Roving tabindex required |

## HTML First Rule

**Native HTML elements provide ARIA automatically. Use them:**

| Instead of | Use Native |
|------------|-----------|
| `<div role="button">` | `<button>` |
| `<div role="checkbox">` | `<input type="checkbox">` |
| `<div role="navigation">` | `<nav>` |
| `<div role="tablist">` for simple tabs | Consider `<details>`/`<summary>` |

Always prefer `<button>`, `<nav>`, `<main>`, `<input>`, `<select>` over ARIA equivalents.

## RGAA Correspondences

- **7.1**: Keyboard accessible scripts → Use ARIA with keyboard handlers
- **7.3**: Context changes notified → Use `aria-live` for unexpected changes  
- **7.4**: Modal focus trap → `aria-modal="true"` + JS trap (see `accessibility-focus`)
- **7.5**: Status messages → `role="status"` or `aria-live`

## Related Skills

- Use `accessibility-keyboard` for keyboard interaction patterns (Tab, Enter, Space, Arrows)
- Use `accessibility-focus` for focus management (traps, visibility, skip links)
- Use `accessibility-structure` for semantic HTML alternatives
- Use `accessibility-forms` for form-specific ARIA patterns
- [WAI-ARIA Authoring Practices Guide](https://www.w3.org/WAI/ARIA/apg/patterns/)

## Resources

- [Understanding Name, Role, Value](https://www.w3.org/WAI/WCAG22/Understanding/name-role-value)
- [Understanding Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages)
- [ARIA 1.2 Spec](https://www.w3.org/TR/wai-aria-1.2/)
- [HTML-ARIA Mapping](https://www.w3.org/TR/html-aria/)
- [APG Patterns](https://www.w3.org/WAI/ARIA/apg/patterns/)
