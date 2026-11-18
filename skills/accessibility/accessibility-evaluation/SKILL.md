---
name: accessibility-evaluation
description: Use when performing accessibility audits, running automated and manual tests, and creating conformance reports. Follows evaluation methodology for comprehensive testing.
---

# Evaluate Accessibility

Perform systematic accessibility audits using automated tools and manual testing.

## Quick Reference

| Test Type | When to Use | Tools |
|-----------|-------------|-------|
| **Automated** | Initial scan, catching obvious issues | axe, WAVE, Lighthouse, Pa11y |
| **Keyboard** | Verify all interactive elements work | Manual: Tab, Enter, Space, Escape |
| **Screen Reader** | Test announcements and navigation | NVDA, VoiceOver, TalkBack |
| **Visual** | Check zoom, reflow, high contrast | Browser zoom (200%), mobile viewport (320px) |
| **Touch** | Test mobile interactions and target sizes | DevTools device mode, real devices |

## Evaluation Process

### Step 1: Define Scope

- [ ] Identify page types (home, product, form, etc.)
- [ ] Select minimum representative sample (WCAG-EM recommends 10-15%)
- [ ] Document target conformance level (AA)
- [ ] Note any exceptions or known limitations

### Step 2: Run Automated Tests

```bash
# Using axe-core
npx axe-core https://example.com --tags wcag2aa

# Using pa11y
pa11y https://example.com --standard WCAG2AA

# Using Lighthouse
lighthouse https://example.com --only-categories=accessibility
```

Check with browser extensions:
- [ ] **axe DevTools** - Run on all sample pages
- [ ] **WAVE** - Review all error/warning icons
- [ ] **Lighthouse** - Aim for 90+ accessibility score

**Remember:** Automated tests catch only ~30% of issues (contrast, alt text, labels).

### Step 3: Run Manual Tests

#### Keyboard Navigation
```bash
# Manual test procedure:
1. Tab through entire page
2. Verify focus is visible on all interactive elements
3. Test Enter (activate), Space (toggle), Escape (close)
4. Check arrow keys for custom widgets
5. Ensure no keyboard traps
```

- [ ] All clickable elements accessible via Tab
- [ ] Focus indicators clearly visible
- [ ] Logical Tab order (top-to-bottom, left-to-right)
- [ ] Modal dialogs trap focus properly
- [ ] Focus returns to trigger when modal closes

#### Screen Reader Testing
```bash
# Test with at least one screen reader:
# Windows: NVDA (free) - Insert + F7 (elements list)
# macOS/iOS: VoiceOver (built-in) - Cmd + F5
# Android: TalkBack (built-in)
```

- [ ] Navigate by headings (H)
- [ ] Navigate by landmarks (D)
- [ ] Navigate by links (L)
- [ ] Listen for proper button/link announcements
- [ ] Verify dynamic updates announced (aria-live)

#### Visual & Responsive Testing
```bash
# Browser zoom test
1. Zoom to 200% (Ctrl/Cmd + Plus)
2. Verify no horizontal scrolling 
3. Check content remains readable

# Mobile viewport test  
1. DevTools Device Mode: 320px width
2. Verify content reflows vertically
3. Check touch targets are adequate
```

- [ ] 200% zoom: No horizontal scroll, content readable
- [ ] 320px viewport: Single column layout, no overlap
- [ ] High contrast mode (Windows): All content visible
- [ ] CSS disabled: Content makes sense in source order
- [ ] Images disabled: Alt text provides context

#### Touch & Mobile Testing
```bash
# Target size check in DevTools:
1. Inspect element
2. Check computed box model
3. Verify minimum 24×24 CSS pixels

# Alternative interactions check:
1. Identify drag/slide elements
2. Verify up/down arrow buttons exist
3. Or verify single click/tap works
```

- [ ] Touch targets minimum 24×24px (or 44×44px recommended)
- [ ] Drag operations have alternatives (buttons)
- [ ] No required device motions (shake, tilt)
- [ ] Orientation changes work properly

## Testing Checklist

### Perceivable
- [ ] Text alternatives for images
- [ ] Captions/transcripts for media
- [ ] Color not sole means of conveying info
- [ ] Text resizable to 200%
- [ ] Content reflows at 320px viewport

### Operable
- [ ] All functionality via keyboard
- [ ] No keyboard traps
- [ ] Skip links present
- [ ] Page titles descriptive and unique
- [ ] Focus order logical
- [ ] Focus indicators visible
- [ ] **Focus not obscured by sticky content** (NEW in 2.2)
- [ ] **Dragging alternatives available** (NEW in 2.2)
- [ ] **Touch targets adequate size** (NEW in 2.2)

### Understandable
- [ ] Language identified on page
- [ ] Form labels present and associated
- [ ] Error messages clear and helpful
- [ ] **No cognitive tests for authentication** (NEW in 2.2)
- [ ] Consistent navigation across pages
- [ ] Consistent identification of components
- [ ] Consistent help location

### Robust
- [ ] Valid HTML markup
- [ ] ARIA used correctly
- [ ] Name/role/value for custom components
- [ ] Status messages announced

## Severity Levels

When documenting issues:

| Level | Impact | Fix Priority |
|-------|--------|--------------|
| **Critical** | Blocks users completely. No workaround. | Immediate (before release) |
| **High** | Major barrier. Difficult or confusing workaround. | Sprint fix |
| **Medium** | Moderate barrier. Some workaround exists. | Next release |
| **Low** | Minor issue. Easy workaround or cosmetic. | Backlog |

## Report Template

Copy and use for each audit:

```markdown
## Accessibility Audit Report

**Date:** YYYY-MM-DD
**Auditor:** Name
**Scope:** [List pages tested]
**Standard:** Level AA

### Summary
| Severity | Count | Status |
|----------|-------|--------|
| Critical | X | 0 required for release |
| High | X | Fix in sprint |
| Medium | X | Fix next release |
| Low | X | Backlog |
| **Total** | **X** | |

### Automated Test Results
- axe-core: X violations
- Lighthouse: XX/100 score
- WAVE: X errors, X alerts

### Manual Test Results
- Keyboard: [Pass/Partial/Fail]
- Screen Reader: [Pass/Partial/Fail]
- Visual/Zoom: [Pass/Partial/Fail]
- Touch/Mobile: [Pass/Partial/Fail]

### Critical Issues (Must Fix)
1. **Issue Title**
   - **Location:** Specific page/element
   - **Impact:** How it affects users
   - **Criteria:** Success criterion violated
   - **Fix:** Specific remediation steps
   - **Skill to use:** `accessibility-[specific]`

### High Priority Issues
1. **Issue Title**
   ...

### Medium Priority Issues
...

### Low Priority Issues
...

### Recommendations
1. [Improvement suggestion not tied to violation]
2. [Training needs]
3. [Process improvements]

### Next Steps
- [ ] Fix critical issues by [date]
- [ ] Retest with automated tools
- [ ] Verify fixes with screen reader
- [ ] Schedule accessibility training
```

## RGAA Correspondences

French specific requirements:
- **7.1-7.5**: Scripts and dynamic content
- **8.1-8.5**: Mandatory elements (language, title, etc.)
- **12.1-12.11**: Navigation requirements
- **13.1-13.15**: User consultation (zoom up to 400% in France)

Note: RGAA 4.1 requires **level AA** minimum, with stricter zoom requirements (400% vs 200%).

## Common Patterns

| Pattern | Implementation |
|---------|---------------|
| **Automated scan** | Start with axe/WAVE for quick issues |
| **Keyboard testing** | Tab through all interactive elements |
| **Screen reader testing** | NVDA/VoiceOver navigation by headings and landmarks |
| **Visual testing** | 200% zoom, 320px viewport, high contrast |
| **Touch testing** | Mobile device or DevTools emulation |
| **Report generation** | Document issues by severity with remediation steps |

## Related Skills

- Use `accessibility-images` for testing alt text
- Use `accessibility-color-contrast` for contrast checks
- Use `accessibility-keyboard` for keyboard navigation testing
- Use `accessibility-forms` for form validation testing
- Use `accessibility-aria` for ARIA implementation checks
- Use `accessibility-focus` for focus management testing
- Use `accessibility-responsive` for zoom and reflow testing
- Use `accessibility-motion` for animation and timing testing
- Use `accessibility-behavior` for consistent behavior testing

## Resources

- [All WCAG 2.2 Understanding Documents](https://www.w3.org/WAI/WCAG22/Understanding/)
- [How to Meet WCAG](https://www.w3.org/WAI/WCAG22/quickref/) - Quick reference guide
- [WebAIM Accessibility Testing](https://webaim.org/articles/evaluationtools/)
- [WCAG-EM Overview](https://www.w3.org/WAI/test-evaluate/conformance/wcag-em/)
