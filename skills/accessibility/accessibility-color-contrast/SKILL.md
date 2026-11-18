---
name: accessibility-color-contrast
description: Use when checking text contrast ratios, avoiding color-only information, and ensuring sufficient contrast for UI components.
---

# Check Color and Contrast

Ensure text and UI elements have sufficient contrast and information isn't conveyed by color alone.

## Quick Reference

| Element | Minimum Ratio | Threshold |
|---------|--------------|-----------|
| Normal text | 4.5:1 | < 18pt regular |
| Large text | 3:1 | ≥ 18pt OR ≥ 14pt bold |
| UI components | 3:1 | Buttons, inputs, focus indicators |
| Icons/graphics | 3:1 | Charts, meaningful images |
| Error states | Color + icon/text required | Never color alone |
| Logos/brand | Exempt | Decorative text exempt |

## Critical Checks

### Sensory Characteristics

Instructions must not rely solely on:
- [ ] Shape ("click the round button")
- [ ] Size ("the big button")
- [ ] Visual location ("button on the right")
- [ ] Color ("the red button")
- [ ] Orientation ("the arrow pointing up")
- [ ] Sound ("wait for the beep")

**Examples:**
```html
<!-- Use accessible names instead -->
<button aria-label="Add to cart">
  <svg aria-hidden="true"><!-- Plus icon --></svg>
  Add
</button>

<p>Click the "Continue" button</p>
```

### Use of Color

Color must not be the only visual means:
- [ ] Error states use icon + text (not just red)
- [ ] Required fields use text/symbol (not just red)
- [ ] Links use underline or other indicator (not just blue)
- [ ] Status uses additional visual cue (not just color)
- [ ] Charts use patterns/labels (not just color)

**Examples:**
```html
<!-- Error: color + icon + text -->
<span style="color: #d32f2f;">
  <svg aria-hidden="true">⚠️</svg>
  Error: Email is required
</span>

<!-- Required: text indicator -->
<label>
  Email <span aria-label="required">*</span>
</label>
<input type="email" required aria-required="true">
```

```css
/* Links: color + underline */
a {
  color: #0056b3;
  text-decoration: underline;
}
```

### Text Contrast

**Normal Text** (< 18pt / < 14pt bold):
- [ ] Contrast ratio ≥ 4.5:1

**Large Text** (≥ 18pt / ≥ 14pt bold):
- [ ] Contrast ratio ≥ 3:1

**Exempt**: Logos, brand names, decorative text

**Common accessible combinations:**
| Background | Text | Ratio |
|------------|------|-------|
| #FFFFFF (white) | #000000 (black) | 21:1 |
| #FFFFFF (white) | #333333 (dark gray) | 12.6:1 |
| #FFFFFF (white) | #767676 (gray) | 4.6:1 |
| #FFFFFF (white) | #999999 (light gray) | 2.8:1 ❌ |

### Non-Text Contrast

**UI Components** (min 3:1 vs adjacent):
- [ ] Form input borders
- [ ] Button backgrounds or borders
- [ ] Focus indicators
- [ ] Selected items
- [ ] Toggle switches

**Graphical Objects** (min 3:1):
- [ ] Icons conveying information
- [ ] Chart elements
- [ ] Status indicators

**Examples:**
```css
/* Input border with sufficient contrast */
input {
  border: 1px solid #767676; /* 4.6:1 on white */
}

/* Focus indicator */
:focus-visible {
  outline: 2px solid #0056b3; /* 7.4:1 contrast */
  outline-offset: 2px;
}

/* Text over images: use overlay */
.overlay {
  background: rgba(0, 0, 0, 0.5); /* Ensures text contrast */
}
```

## Accessible Color Palette

**CSS Custom Properties:**
```css
:root {
  --color-text: #212121;         /* 16.1:1 on white */
  --color-text-secondary: #616161; /* 6.0:1 on white */
  --color-primary: #0056b3;      /* 7.4:1 on white */
  --color-error: #d32f2f;        /* 7.1:1 on white */
  --color-success: #2e7d32;      /* 5.9:1 on white */
  --color-border: #757575;       /* 4.6:1 on white */
}
```

**High contrast mode support:**
```css
@media (prefers-contrast: high) {
  .button {
    border: 2px solid currentColor;
  }
}
```

## Testing

For comprehensive contrast testing procedures, use `accessibility-evaluation`.

**Recommended tools:**
- WAVE (browser extension)
- axe DevTools
- Lighthouse
- WebAIM Contrast Checker

## RGAA Correspondences

- **3.1**: Information not conveyed by color alone
- **3.2**: Contrast ratios (AA required, AAA for enlarged text)
- **10.7**: Text presentation (zoom 200% must be readable)

## Related Skills

- Use `accessibility-images` for image color/contrast
- Use `accessibility-focus` for focus indicator visibility
- Use `accessibility-forms` for form validation colors
- Use `accessibility-evaluation` for audit methodology

## Resources

- [Understanding Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color)
- [Understanding Contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum)
- [Understanding Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast)
- [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)
