---
name: accessibility-orchestrator
description: Route to specialized accessibility skills for comprehensive audits, quick checks, or component-specific reviews. Use as entry point for all accessibility reviews.
---

# Route Accessibility Reviews

Analyze accessibility needs and route to the most relevant specialized skills for efficient and thorough reviews.

## Quick Start Routes

**For comprehensive audits:**
Tell me what you're auditing (page, component, application) and I'll guide you through the complete workflow.

**For quick checks:**
- "Check [page/component] images"
- "Check contrast on [element]"  
- "Check forms on [page]"
- "Check keyboard navigation"

**For implementation guidance:**
- "How do I make [component] accessible?"
- "How to fix [specific issue]?"

## Decision Engine

When you share what needs review, I determine:

1. **Audit Type**: Quick check, component review, or full page audit
2. **Priority Areas**: Images, colors, forms, keyboard, structure, etc.
3. **Applicable Constraints**: Mobile, touch inputs, motion sensitivity, multilingual
4. **Optimal Skill Sequence**: Which skills to run and in what order

## Audit Workflows

### Complete Audit (14 Areas)

Systematic review covering all accessibility aspects:

1. **Images & Media** → `accessibility-images`
   - Alt text, decorative images, SVG accessibility
   
2. **Color & Contrast** → `accessibility-color-contrast`
   - Text contrast ratios, UI component contrast, color independence
   
3. **Responsive Design** → `accessibility-responsive`
   - 200% zoom, 320px reflow, text spacing
   
4. **Keyboard Navigation** → `accessibility-keyboard`
   - Tab order, keyboard shortcuts, no traps
   
5. **Focus Management** → `accessibility-focus`
   - Visible focus indicators, skip links, focus order
   
6. **Forms** → `accessibility-forms`
   - Labels, error handling, input assistance
   
7. **ARIA Implementation** → `accessibility-aria`
   - Roles, states, accessible names, live regions
   
8. **Page Structure** → `accessibility-structure`
   - Headings, landmarks, semantic HTML
   
9. **Navigation** → `accessibility-navigation`
   - Menus, multiple navigation paths, page titles
   
10. **Touch & Mobile** → `accessibility-touch` (if applicable)
    - Touch targets 24px+, gesture alternatives
    
11. **Motion & Time** → `accessibility-motion` (if applicable)
    - Pause controls, timing limits, motion preferences
    
12. **Tooltips & Popups** → `accessibility-tooltips` (if applicable)
    - Hover/focus content, dismissible elements
    
13. **Consistent Behavior** → `accessibility-behavior`
    - Predictable navigation, error prevention
    
14. **Language** → `accessibility-language` (if applicable)
    - Lang attributes, RTL text, multilingual content

### Quick Check (5 Priorities)

For rapid assessment of critical issues:

1. **Images** → `accessibility-images` (missing alt, decorative marking)
2. **Contrast** → `accessibility-color-contrast` (text readability)
3. **Keyboard** → `accessibility-keyboard` + `accessibility-focus` (basic navigation)
4. **Forms** → `accessibility-forms` (labels and errors)
5. **Structure** → `accessibility-structure` (headings hierarchy)

## Skills Matrix

Route to specialized skills based on what needs checking:

| Skill | Checks | Use When | Priority |
|-------|--------|----------|----------|
| `accessibility-images` | Alt text, SVG, decorative images, complex charts | Any images present | Must |
| `accessibility-color-contrast` | Text contrast, UI contrast, color independence | Visual elements | Must |
| `accessibility-responsive` | Zoom, reflow, text spacing, orientation | Responsive layouts | Must |
| `accessibility-keyboard` | Tab order, keyboard shortcuts, no traps | Interactive elements | Must |
| `accessibility-focus` | Focus indicators, skip links, focus management | Navigation, dialogs | Must |
| `accessibility-forms` | Labels, validation, error messages, input purpose | Any forms | Must |
| `accessibility-aria` | Roles, states, accessible names, live regions | Dynamic content, custom widgets | Should |
| `accessibility-structure` | Headings, landmarks, semantic HTML, tables | Page organization | Should |
| `accessibility-navigation` | Menus, multiple ways, page titles, breadcrumbs | Navigation systems | Should |
| `accessibility-touch` | Touch targets, gestures, motion alternatives | Mobile/touch interfaces | Could |
| `accessibility-motion` | Timing limits, pause controls, reduced motion | Animations, auto-play | Could |
| `accessibility-tooltips` | Hover/focus content, dismissible elements | Tooltips, popups, dropdowns | Could |
| `accessibility-behavior` | Predictable navigation, error prevention | Complex interactions | Could |
| `accessibility-language` | Lang attributes, RTL, multilingual content | Multiple languages | Could |
| `accessibility-evaluation` | Audit methodology, testing procedures | Full audit workflow | Reference |

## Component-Specific Routing

### For Buttons
Check: `accessibility-keyboard`, `accessibility-aria`, `accessibility-focus`

### For Forms
Check: `accessibility-forms`, `accessibility-keyboard`, `accessibility-aria`

### For Images
Check: `accessibility-images`, `accessibility-color-contrast`

### For Modals/Dialogs
Check: `accessibility-focus`, `accessibility-aria`, `accessibility-keyboard`

### For Navigation Menus
Check: `accessibility-navigation`, `accessibility-keyboard`, `accessibility-focus`

### For Tables
Check: `accessibility-structure`, `accessibility-aria`

### For Data Visualizations
Check: `accessibility-images`, `accessibility-color-contrast`, `accessibility-aria`

### For Carousels/Sliders
Check: `accessibility-motion`, `accessibility-keyboard`, `accessibility-focus`

### For Video/Audio Players
Check: `accessibility-media`, `accessibility-keyboard`, `accessibility-motion`

## Accessibility Principles Overview

The four principles that guide accessibility reviews:

**Perceivable**: Information must be presentable in ways users can perceive
- Text alternatives for images and non-text content
- Captions and transcripts for media
- Sufficient color contrast (4.5:1 for text)
- Resizable text without assistive technology

**Operable**: Interface components must be operable by all users
- All functionality available via keyboard
- No keyboard traps
- Sufficient time to read and use content
- No content that causes seizures or physical reactions

**Understandable**: Information and operation must be understandable
- Readable and predictable content
- Consistent navigation and identification
- Input assistance for forms and errors

**Robust**: Content must work with current and future assistive technologies
- Valid HTML and semantic structure
- Appropriate ARIA roles, states, and properties
- Status messages announced to assistive technologies

## Next Steps

**Ready to start a review?**
Share what you want to audit and I'll recommend the optimal skill sequence.

**Example requests:**
- "Audit the homepage for accessibility"
- "Check if the contact form is accessible"
- "Review image alt text on the product page"
- "How do I make this modal dialog accessible?"

**For implementation help:**
Describe the component or issue and I'll guide you through the implementation using the relevant skills.
