---
name: accessibility-responsive
description: Use when checking responsive design accessibility including text resize, reflow at 320px, text spacing, and orientation support.
---

# Make Content Adaptable

Ensure content remains accessible, readable, and functional when users zoom, adjust text spacing, or change device orientation.

## Quick Reference

| Scenario | Requirement | Implementation |
|----------|-------------|----------------|
| **200% zoom** | No horizontal scroll | Fluid layouts with max-width: 100% |
| **Mobile viewport (320px)** | Single column layout | Responsive grids with min-width constraints |
| **Text spacing** | No overlap or clipping | Flexible containers that expand vertically |
| **Orientation change** | Works in portrait and landscape | Layout adapts to viewport dimensions |
| **Text resize** | No truncated content | Min-heights instead of fixed heights |

## Critical Checks

### Zoom and Text Scaling

Content must remain readable and functional at 200% browser zoom:

- [ ] Browser zoom to 200% works without horizontal scrolling (unless table/chart)
- [ ] Text containers expand vertically to accommodate larger text
- [ ] No text is clipped, truncated, or overlapping
- [ ] Interactive elements remain functional and clickable
- [ ] Layout maintains logical reading order

```css
/* Flexible containers that adapt */
.container {
  max-width: 100%;
  padding: 1rem;
}

/* Responsive typography */
h1 {
  font-size: clamp(1.5rem, 5vw, 3rem);
}

/* Flexible grids */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 1rem;
}
```

### Mobile Viewport Reflow

At 320px width (equivalent to mobile devices):

- [ ] No horizontal scrolling required (exceptions: data tables, charts, video)
- [ ] Content reflows in a single column
- [ ] Navigation remains accessible (hamburger menu or wrapped)
- [ ] Forms are usable with adequate touch targets
- [ ] Text remains readable without zooming

```css
/* Responsive layout patterns */
.main-content {
  display: flex;
  flex-direction: column;
}

@media (min-width: 600px) {
  .main-content {
    flex-direction: row;
  }
}

/* Tables with horizontal scroll container */
.table-wrapper {
  overflow-x: auto;
  max-width: 100%;
}
```

**Exceptions where horizontal scroll is permitted:**
- Data tables with many columns
- Complex graphics or charts
- Video players
- Game canvases
- Maps or diagrams requiring detail

### Text Spacing Support

Content must remain accessible when users apply specific text spacing:

- [ ] Line height: 1.5 (150%)
- [ ] Paragraph spacing: 2 times font size
- [ ] Letter spacing: 0.12em ( increase by 0.12 times font size)
- [ ] Word spacing: 0.16em (1.16 times font size)

When these values are applied:
- [ ] Text containers expand vertically
- [ ] No text is clipped or overlapping
- [ ] Buttons and links remain clickable
- [ ] Forms and inputs remain usable

```css
/* Flexible spacing implementation */
.text-content {
  line-height: 1.5;
  margin-bottom: 2em;
}

/* Containers that expand */
.card {
  min-height: 200px;
  height: auto;
  overflow: visible;
}

/* Avoid clipped text */
.sidebar {
  min-height: 100px;
  max-height: none;
}
```

**Testing bookmarklet for text spacing:**
```javascript
javascript:(function(){var d=document,s=d.createElement('style');s.textContent='*{line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important;margin-bottom:2em!important}';d.head.appendChild(s)})();
```

### Device Orientation

Content must work in both portrait and landscape orientations:

- [ ] Content is accessible in portrait mode
- [ ] Content is accessible in landscape mode
- [ ] No mandatory "please rotate your device" messages
- [ ] Layout adapts to orientation changes
- [ ] All functionality available in both orientations

**Allowed exceptions:**
- Piano keyboard applications
- Check deposit applications
- Games requiring specific orientation
- Virtual reality content

```css
/* Orientation-adaptive layouts */
@media (orientation: portrait) {
  .gallery {
    grid-template-columns: 1fr;
  }
}

@media (orientation: landscape) {
  .gallery {
    grid-template-columns: repeat(3, 1fr);
  }
}
```

## Testing

For comprehensive responsive design testing procedures, use `accessibility-evaluation`.

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Flexible typography** | `clamp()` for fluid font sizes | Critical checks above |
| **Responsive grids** | `auto-fit` and `minmax()` | CSS grid patterns |
| **Mobile navigation** | Hamburger menu or wrapped items | `accessibility-focus` |
| **Overflow tables** | Wrapper with `overflow-x: auto` | Critical checks above |
| **Flexible cards** | `min-height` with `height: auto` | Critical checks above |
| **Sticky headers** | `position: sticky` with scroll padding | `accessibility-focus` |

## CSS Implementation Examples

### Fluid Layouts

```css
/* Container with maximum width but fluid */
.wrapper {
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  padding: 0 1rem;
}

/* Flexible sidebar */
.sidebar {
  width: 25%;
  min-width: 250px;
}

@media (max-width: 768px) {
  .sidebar {
    width: 100%;
  }
}
```

### Responsive Images

```css
/* Images that scale with container */
img {
  max-width: 100%;
  height: auto;
}

/* Aspect ratio preservation */
.video-container {
  aspect-ratio: 16/9;
  max-height: 80vh;
}

.video-container iframe {
  width: 100%;
  height: 100%;
}
```

### Flexible Navigation

```css
/* Navigation that wraps on small screens */
.nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

/* Or mobile-first with media query */
.nav-desktop {
  display: none;
}

.nav-mobile {
  display: block;
}

@media (min-width: 768px) {
  .nav-desktop {
    display: flex;
  }
  .nav-mobile {
    display: none;
  }
}
```

### Framework Implementations

**React responsive hook:**
```jsx
import { useState, useEffect } from 'react';

function useWindowSize() {
  const [size, setSize] = useState([window.innerWidth, window.innerHeight]);
  
  useEffect(() => {
    const handleResize = () => {
      setSize([window.innerWidth, window.innerHeight]);
    };
    
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);
  
  return size;
}
```

**Tailwind CSS responsive utilities:**
```html
<!-- Responsive text -->
<h1 class="text-base md:text-lg lg:text-xl">
  Responsive Heading
</h1>

<!-- Flexible container -->
<div class="max-w-full px-4 md:px-8">
  Content adapts to viewport
</div>

<!-- Responsive grid -->
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
  <div>Item 1</div>
  <div>Item 2</div>
  <div>Item 3</div>
</div>
```

## RGAA Correspondences

- **10.1-10.4**: Styled text presentation (zoom, font size)
- **10.5-10.7**: Information presented by color and CSS
- **10.8-10.10**: Mandatory element presentation (orientation)
- **10.11**: Content presentation control
- **13.x**: Vérification requirements for responsive testing

## Related Skills

- Use `accessibility-touch` for mobile-specific interactions and touch targets
- Use `accessibility-color-contrast` for high contrast mode support
- Use `accessibility-images` for responsive image techniques
- Use `accessibility-evaluation` for testing responsive behavior at 200% zoom and 320px viewport
- Use `accessibility-focus` for focus management in responsive layouts

## Resources

- [Understanding Resize Text](https://www.w3.org/WAI/WCAG22/Understanding/resize-text)
- [Understanding Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow)
- [Understanding Text Spacing](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing)
- [Understanding Orientation](https://www.w3.org/WAI/WCAG22/Understanding/orientation)
