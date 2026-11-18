---
name: accessibility-images
description: Use when checking or creating accessible images, alt text, decorative images, SVG icons, and text alternatives. Ensures images convey information to all users.
---

# Process Accessible Images

Ensure all images have appropriate text alternatives for users who cannot see them.

## Quick Reference

| Image Type | Alt Text Pattern |
|-----------|------------------|
| **Informative** | Descriptive `alt` conveying purpose (1-2 phrases max) |
| **Decorative** | Empty `alt=""` or CSS background |
| **Functional** | Action/destination description (e.g., "Shopping cart") |
| **Complex** | Short `alt` + `aria-describedby` for detailed description |
| **Text as image** | Use real HTML/CSS text instead (exceptions: logos, branding) |
| **SVG** | `<title>` + `role="img"` or `aria-hidden="true"` for decorative |
| **Group** | Each image describes unique view/state |

## Critical Checks

### Informative Images

- [ ] Descriptive `alt` attribute present
- [ ] Alt conveys purpose/function, not just visual description
- [ ] Alt is concise (1-2 sentences maximum)
- [ ] No "image of" or "picture of" prefixes
- [ ] Text visible in image is included in alt

**Examples:**
```html
<!-- Chart with data -->
<img src="chart.png" alt="Sales increased 50% from Q1 to Q2">

<!-- Photo with context -->
<img src="team-photo.png" alt="Development team meeting in conference room, 12 people present">

<!-- Icon with function -->
<img src="alert.png" alt="Warning: System maintenance scheduled">
```

### Decorative Images

- [ ] Empty alt attribute: `alt=""`
- [ ] No ARIA roles when decorative
- [ ] CSS background-image used when appropriate

**Examples:**
```html
<!-- Decorative border/spacer -->
<img src="decorative-border.png" alt="">

<!-- Purely visual element -->
<div style="background-image: url(ornament.png)"></div>
```

### Functional Images (Links/Buttons)

- [ ] Alt describes destination or action
- [ ] Avoids duplicating adjacent visible text
- [ ] Custom icons have descriptive names

**Examples:**
```html
<!-- Link with icon -->
<a href="/cart">
  <img src="cart-icon.png" alt="Shopping cart - 3 items">
</a>

<!-- Button with icon -->
<button>
  <img src="print.png" alt="Print page">
</button>

<!-- Delete action -->
<button aria-label="Delete item">
  <img src="trash.png" alt="">
</button>
```

### Avoid Images of Text

Use real text (HTML/CSS) instead of images containing text:
- [ ] Headings are HTML heading elements, not images
- [ ] Quotes use real text styling
- [ ] Excerpts use HTML text + CSS

**Use HTML/CSS instead:**
```html
<!-- DO - Real text with styling -->
<h1 style="font-family: 'Brand Font', sans-serif; font-size: 2.5rem;">
  Welcome to Our Site
</h1>

<!-- DO - Styled quote -->
<blockquote style="font-style: italic; border-left: 4px solid #333; padding-left: 1rem;">
  "The best way to predict the future is to create it"
</blockquote>
```

**Exceptions allowed (images of text):**
- Logos and branding with custom typography
- Decorative text elements
- User-customizable generated content (email signatures)
- When text presentation is essential and cannot be achieved with CSS

### Complex Images (Charts, Diagrams, Infographics)

- [ ] Short alt summarizing the image purpose
- [ ] Detailed description provided nearby or via `aria-describedby`
- [ ] Data table alternative for charts when possible
- [ ] Text summary of key information

**Examples:**
```html
<!-- Chart with long description -->
<img 
  src="complex-chart.png" 
  alt="Bar chart showing quarterly revenue growth"
  aria-describedby="chart-desc"
>
<p id="chart-desc">
  Detailed data: Q1: $100K, Q2: $150K (+50%), Q3: $175K (+17%), Q4: $210K (+20%).
  Total annual revenue: $635K.
</p>

<!-- Infographic with summary -->
<img src="process-infographic.png" alt="5-step project process flowchart">
<ol>
  <li>Discovery and requirements</li>
  <li>Design and prototyping</li>
  <li>Development</li>
  <li>Testing and QA</li>
  <li>Deployment</li>
</ol>
```

### SVG Graphics

- [ ] `<svg>` has accessible name via `<title>`, `aria-label`, or `aria-labelledby`
- [ ] `role="img"` added unless native semantics apply
- [ ] Complex SVGs use `<desc>` for detailed description
- [ ] Decorative SVGs: `aria-hidden="true"` + `focusable="false"`

**Examples:**
```html
<!-- Informative SVG -->
<svg role="img" aria-labelledby="logo-title">
  <title id="logo-title">Company Name Logo</title>
  <!-- paths -->
</svg>

<!-- Icon with action -->
<svg role="img" aria-label="Close dialog" focusable="false">
  <title>Close</title>
  <!-- X icon paths -->
</svg>

<!-- Decorative SVG -->
<svg aria-hidden="true" focusable="false">
  <title>Decorative background element</title>
  <!-- paths -->
</svg>
```

### Groups of Images

- [ ] Each image in group has appropriate alt
- [ ] Alt describes unique view/state/content
- [ ] Avoid redundant "image 1", "image 2" labels

**Examples:**
```html
<!-- Product gallery showing different angles -->
<img src="product-front.png" alt="Product front view showing touch screen interface">
<img src="product-side.png" alt="Product side profile showing charging port location">
<img src="product-detail.png" alt="Product detail view of camera lens module">
```

### Image Maps

- [ ] Main image has descriptive alt
- [ ] Each `<area>` has descriptive alt describing destination

**Example:**
```html
<img src="floor-plan.png" alt="Office floor plan with selectable rooms" usemap="#map">
<map name="map">
  <area shape="rect" coords="0,0,100,100" href="/room-101" alt="Room 101 - Main reception">
  <area shape="rect" coords="100,0,200,100" href="/room-102" alt="Room 102 - Conference room">
</map>
```

### CAPTCHA Accessibility

CAPTCHA creates accessibility barriers. Provide alternatives:
- [ ] Audio CAPTCHA alternative to visual CAPTCHA
- [ ] Email verification link (magic link)
- [ ] SMS verification code option
- [ ] Simple question/answer alternative (not image-based)
- [ ] Rate limiting and behavioral analysis (invisible)

**Examples:**
```html
<!-- Multiple CAPTCHA options -->
<div role="group" aria-label="Verification method">
  <img src="captcha.png" alt="CAPTCHA challenge, type the characters shown">
  <button>Play audio challenge</button>
  <a href="/send-verification-email">Email me a verification link</a>
</div>

<!-- Alternative: Email verification -->
<p>We've sent a verification link to your email.</p>
```

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Photo with context** | Descriptive alt text (1-2 phrases) | Critical checks above |
| **Icons** | Descriptive functional alt | Critical checks above |
| **Charts** | Short alt + detailed description | `accessibility-aria` for aria-describedby |
| **Logo** | Company name in title/desc | `accessibility-aria` |
| **Product gallery** | Unique description per view | Critical checks above |
| **Image maps** | Main alt + area alts | Critical checks above |

## Testing

For comprehensive image testing procedures, use `accessibility-evaluation`.

## Implementation Checklist

Before deploying:
- [ ] All `<img>` tags have `alt` attribute (empty or descriptive)
- [ ] Informative images have meaningful alt text
- [ ] Decorative images use `alt=""`
- [ ] Functional images describe action, not appearance
- [ ] No text embedded in images (except logos/branding)
- [ ] Complex images have supplementary description
- [ ] SVGs have accessible names
- [ ] Image maps have descriptive area labels
- [ ] CAPTCHA has non-visual alternatives

## RGAA Correspondences

- **1.1-1.10**: Images and alternatives (alt text requirements)
- **2.1-2.2**: Frames and iframes with images
- **3.1**: Information not conveyed by color alone (chart accessibility)

## Related Skills

- Use `accessibility-color-contrast` for checking image contrast ratios
- Use `accessibility-aria` for complex image patterns and descriptions
- Use `accessibility-evaluation` for comprehensive image testing methodology

## Resources

- [Understanding Non-text Content](https://www.w3.org/WAI/WCAG22/Understanding/non-text-content)
- [WebAIM Alternative Text](https://webaim.org/techniques/alttext/)
- [Accessible SVG](https://www.w3.org/TR/graphics-aria-1.0/)
- [WAI-ARIA Graphics Module](https://www.w3.org/TR/graphics-aria-1.0/)
