---
name: accessibility-touch
description: Use when checking touch accessibility, pointer gestures, dragging movements, motion actuation, and target sizes for mobile interactions.
---

# Enable Touch Interactions

Ensure touchscreen users can interact with all functionality, with sufficient target sizes and alternatives to complex gestures.

## Quick Reference

| Scenario | Requirement | Implementation |
|----------|-------------|----------------|
| **Complex gestures** | Single pointer alternative | Buttons instead of swipe/pinch/rotate |
| **Dragging** | Non-drag alternative | Up/down arrows to reorder items |
| **Motion control** | Button alternative | UI controls for shake/tilt actions |
| **Target size** | Minimum 24×24 CSS pixels | 44×44px recommended for touch |
| **Pointer actions** | Cancelable before completion | Action on up-event, not down-event |
| **Touch spacing** | Adequate target separation | 8px gap between touch targets |

## Critical Checks

### Single Pointer Alternatives

Provide single-pointer alternatives for complex multi-point or path-based gestures:

- [ ] Swipe gestures have button alternatives (previous/next arrows)
- [ ] Pinch-to-zoom has plus/minus buttons
- [ ] Rotation gestures have rotation controls
- [ ] Multi-finger gestures have single-pointer alternatives

```html
<!-- Carousel with swipe AND button alternatives -->
<div class="carousel" role="region" aria-label="Product images">
  <button aria-label="Previous image" class="nav-button">
    ←
  </button>
  <div class="slides">
    <img src="product-1.jpg" alt="Product front view">
  </div>
  <button aria-label="Next image" class="nav-button">
    →
  </button>
</div>

<!-- Map with zoom buttons and gestures -->
<div class="map-container">
  <div class="map" role="application" aria-label="Interactive map"></div>
  <div class="map-controls">
    <button aria-label="Zoom in">+</button>
    <button aria-label="Zoom out">−</button>
    <button aria-label="Rotate clockwise">↻</button>
    <button aria-label="Rotate counterclockwise">↺</button>
  </div>
</div>
```

```javascript
// Support both swipe and button navigation
class AccessibleCarousel {
  constructor(element) {
    this.element = element;
    this.currentSlide = 0;
    
    // Button controls
    this.prevButton = element.querySelector('[aria-label*="Previous"]');
    this.nextButton = element.querySelector('[aria-label*="Next"]');
    
    this.prevButton.addEventListener('click', () => this.prev());
    this.nextButton.addEventListener('click', () => this.next());
    
    // Swipe gesture support (optional enhancement)
    this.addSwipeSupport();
  }
  
  prev() {
    this.currentSlide = Math.max(0, this.currentSlide - 1);
    this.updateSlide();
  }
  
  next() {
    this.currentSlide = Math.min(this.totalSlides - 1, this.currentSlide + 1);
    this.updateSlide();
  }
  
  addSwipeSupport() {
    // Swipe is supplementary, buttons remain primary
    let startX = 0;
    
    this.element.addEventListener('touchstart', (e) => {
      startX = e.touches[0].clientX;
    });
    
    this.element.addEventListener('touchend', (e) => {
      const diff = startX - e.changedTouches[0].clientX;
      if (Math.abs(diff) > 50) {
        diff > 0 ? this.next() : this.prev();
      }
    });
  }
}
```

### Pointer Cancellation

Ensure users can cancel or abort actions before completion:

- [ ] Actions trigger on pointer up (mouseup/touchend), not pointer down
- [ ] Users can abort by moving pointer away before releasing
- [ ] No irreversible actions on down-event

**Exceptions allowed:**
- Piano keyboard applications (musical performance)
- Painting or drawing applications
- Games where down-event timing is essential

```javascript
// Correct: Action on click (mouseup event)
button.addEventListener('click', (event) => {
  // User can move away before releasing to cancel
  submitForm();
});

// Keyboard click also fires on keyup
button.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    // action handled by click event for consistency
  }
});
```

### Dragging Alternatives

Provide alternatives for functionality that uses dragging movements:

- [ ] Drag operations have button alternatives
- [ ] Items can be reordered without dragging
- [ ] Keyboard support for drag-like actions

```html
<!-- Sortable list with drag and button alternatives -->
<ul class="sortable-list" role="list" aria-label="Priority order">
  <li class="sortable-item">
    <span>Task Priority 1</span>
    <div class="reorder-controls">
      <button aria-label="Move up" class="reorder-up">↑</button>
      <button aria-label="Move down" class="reorder-down">↓</button>
    </div>
    <div class="drag-handle" aria-label="Drag to reorder" role="button" tabindex="0">
      ⋮⋮
    </div>
  </li>
  <li class="sortable-item">
    <span>Task Priority 2</span>
    <div class="reorder-controls">
      <button aria-label="Move up" class="reorder-up">↑</button>
      <button aria-label="Move down" class="reorder-down">↓</button>
    </div>
    <div class="drag-handle" aria-label="Drag to reorder" role="button" tabindex="0">
      ⋮⋮
    </div>
  </li>
</ul>
```

```javascript
// Reorder functionality with multiple input methods
class AccessibleSortableList {
  constructor(listElement) {
    this.list = listElement;
    this.items = listElement.querySelectorAll('.sortable-item');
    
    // Button controls
    this.items.forEach((item, index) => {
      const upBtn = item.querySelector('.reorder-up');
      const downBtn = item.querySelector('.reorder-down');
      const dragHandle = item.querySelector('.drag-handle');
      
      upBtn.addEventListener('click', () => this.moveItem(index, index - 1));
      downBtn.addEventListener('click', () => this.moveItem(index, index + 1));
      
      // Drag support (optional)
      if (dragHandle) {
        this.addDragSupport(dragHandle, index);
      }
    });
  }
  
  moveItem(fromIndex, toIndex) {
    if (toIndex < 0 || toIndex >= this.items.length) return;
    
    const item = this.items[fromIndex];
    const targetItem = this.items[toIndex];
    
    // Animate and reorder
    this.list.insertBefore(item, toIndex > fromIndex ? targetItem.nextSibling : targetItem);
    
    // Announce to screen readers
    this.announce(`Item moved to position ${toIndex + 1}`);
  }
  
  addDragSupport(handle, index) {
    // Touch/mouse drag implementation
    // Keyboard drag with arrow keys
    handle.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.moveItem(index, index - 1);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.moveItem(index, index + 1);
      }
    });
  }
  
  announce(message) {
    const announcement = document.createElement('div');
    announcement.setAttribute('role', 'status');
    announcement.setAttribute('aria-live', 'polite');
    announcement.className = 'sr-only';
    announcement.textContent = message;
    document.body.appendChild(announcement);
    setTimeout(() => announcement.remove(), 1000);
  }
}
```

### Motion Actuation Alternatives

Provide alternatives for functionality operated by device or user motion:

- [ ] Motion-operated functions have UI component alternatives
- [ ] Motion can be disabled to prevent accidental activation
- [ ] Users can control the feature through standard UI controls

```javascript
// Motion feature with UI alternative and disable option
class MotionController {
  constructor() {
    this.motionEnabled = true;
    this.init();
  }
  
  init() {
    // UI alternative buttons
    document.getElementById('undo-btn').addEventListener('click', () => this.undo());
    document.getElementById('scroll-up-btn').addEventListener('click', () => this.scrollUp());
    
    // Settings toggle
    document.getElementById('motion-toggle').addEventListener('change', (e) => {
      this.motionEnabled = e.target.checked;
      this.updateMotionListener();
    });
    
    // Initialize motion if enabled
    this.updateMotionListener();
  }
  
  updateMotionListener() {
    if (this.motionEnabled) {
      window.addEventListener('devicemotion', this.handleMotion);
    } else {
      window.removeEventListener('devicemotion', this.handleMotion);
    }
  }
  
  handleMotion(event) {
    // Detect shake gesture
    const acceleration = event.accelerationIncludingGravity;
    if (this.detectShake(acceleration)) {
      this.undo();
    }
  }
  
  undo() {
    // Undo functionality accessible via both button and motion
    console.log('Undo action triggered');
  }
  
  scrollUp() {
    window.scrollBy({ top: -200, behavior: 'smooth' });
  }
}
```

### Touch Target Size

Ensure touch targets are large enough to activate easily:

- [ ] Minimum target size: 24×24 CSS pixels (required for AA)
- [ ] Recommended target size: 44×44 CSS pixels (iOS/Android guidelines)
- [ ] Adequate spacing between targets (minimum 8px)
- [ ] Inline links can be smaller if sentence context provides spacing

```css
/* Minimum touch target size */
.touch-target {
  min-width: 24px;
  min-height: 24px;
}

/* Recommended size for better usability */
button,
[role="button"],
a,
input,
select,
textarea {
  min-width: 44px;
  min-height: 44px;
  padding: 12px;
}

/* Button with visible padding */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 44px;
  padding: 12px 24px;
}

/* Icon button sizing */
.icon-btn {
  width: 44px;
  height: 44px;
  padding: 10px;
}

/* Ensure adequate spacing between targets */
.nav-list {
  display: flex;
  gap: 8px; /* Minimum spacing */
}

/* Inline links within text context */
p a {
  /* Can be smaller as they're in sentence context */
  text-decoration: underline;
}
```

### Touch Target Spacing

Ensure targets are not too close together:

```css
/* Touch target groups */
.touch-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px; /* Minimum 8px spacing */
}

/* Form controls spacing */
.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 4px;
}

.form-group input,
.form-group button {
  margin-top: 4px;
}

/* Checkbox and radio groups */
.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 8px 0;
}

.checkbox-group input[type="checkbox"] {
  width: 24px;
  height: 24px;
  min-width: 24px; /* Ensure minimum target */
}
```

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Swipe with buttons** | Carousel with arrow buttons + optional swipe | Critical checks - Single Pointer |
| **Sortable list** | Drag handle + up/down buttons | Critical checks - Dragging |
| **Zoom controls** | Plus/minus buttons + pinch gesture | Critical checks - Single Pointer |
| **Undo action** | Undo button + optional shake | Critical checks - Motion |
| **Touch buttons** | 44×44px minimum with 8px spacing | Critical checks - Target Size |
| **Checkbox groups** | Adequate spacing between options | Critical checks - Spacing |

## Testing

For comprehensive touch and mobile testing procedures, use `accessibility-evaluation`.

## RGAA Correspondences

- **5.1-5.8**: Alternatives to web features (gestures, drag, motion)
- **7.1-7.5**: Keyboard accessibility of scripts and dynamic content
- **12.1-12.11**: Navigation consistency (touch navigation patterns)

## Related Skills

- Use `accessibility-keyboard` for keyboard alternatives to touch interactions
- Use `accessibility-responsive` for orientation support and mobile layouts
- Use `accessibility-aria` for accessible names on touch targets
- Use `accessibility-evaluation` for testing touch target sizes and mobile behavior
- Use `accessibility-motion` for motion preferences and timeout handling

## Resources

- [Understanding Pointer Gestures](https://www.w3.org/WAI/WCAG22/Understanding/pointer-gestures)
- [Understanding Pointer Cancellation](https://www.w3.org/WAI/WCAG22/Understanding/pointer-cancellation)
- [Understanding Dragging Movements](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements)
- [Understanding Motion Actuation](https://www.w3.org/WAI/WCAG22/Understanding/motion-actuation)
- [Understanding Target Size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum)
- [Mobile Accessibility Practices](https://www.w3.org/WAI/standards-guidelines/mobile/)
