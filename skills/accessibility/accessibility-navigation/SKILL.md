---
name: accessibility-navigation
description: Use when checking navigation accessibility including page titles, link purpose, multiple ways to navigate, and location indicators.
---

# Enable Effective Navigation

Ensure users can navigate efficiently, understand their location, and find content through multiple methods.

## Quick Reference

| Scenario | Requirement | Implementation |
|----------|-------------|----------------|
| **Page titles** | Unique and descriptive | Each page has specific title describing content |
| **Link text** | Descriptive purpose | Link destination clear from text or context |
| **Multiple paths** | Alternative navigation | At least 2 ways to find each page |
| **Current location** | Location indication | Visual and programmatic current page marking |
| **SPA navigation** | Dynamic title updates | Document title updates on route changes |

## Critical Checks

### Page Titles

Every page must have a unique, descriptive title:

- [ ] Each page has a unique `<title>` element
- [ ] Title describes the page topic or purpose
- [ ] Title follows a consistent pattern (e.g., "Page Name - Site Name")
- [ ] Single Page Applications update title on navigation

```html
<!-- Descriptive page titles -->
<title>Contact Us - Acme Corporation</title>
<title>Service Dashboard - User Portal</title>
<title>Shopping Cart (3 items) - Acme Store</title>

<!-- SPA title updates -->
<script>
// React/Vue/Angular route guard
router.afterEach((to) => {
  document.title = `${to.meta.title} - Site Name`;
});
</script>
```

### Link Purpose

The purpose of each link must be clear from the link text or its context:

- [ ] Link text describes the destination or action
- [ ] Ambiguous links have programmatic context (sentence, list item, aria-label)
- [ ] Same link text consistently leads to same destination across site
- [ ] Links to different destinations have distinguishing text

**Descriptive link text:**
```html
<a href="/services">View our services and pricing</a>
<a href="/contact">Contact customer support</a>
<button type="submit">Complete purchase</button>
```

**Context for ambiguous links:**
```html
<!-- Context in list item -->
<ul>
  <li>
    <h3>Accessibility Guidelines</h3>
    <p>Best practices for inclusive design...</p>
    <a href="/article-1" aria-label="Read full article: Accessibility Guidelines">Read more</a>
  </li>
  <li>
    <h3>Color Contrast Standards</h3>
    <p>Understanding WCAG contrast requirements...</p>
    <a href="/article-2" aria-label="Read full article: Color Contrast Standards">Read more</a>
  </li>
</ul>

<!-- Context via aria-labelledby -->
<article id="article-1">
  <h2 id="article-title">Accessibility Best Practices</h2>
  <p>Summary of key accessibility guidelines...</p>
  <a href="/article-1" aria-labelledby="article-title">Read full article</a>
</article>

<!-- Context in sentence -->
<p>Learn about our <a href="/services">comprehensive consulting services</a>.</p>
```

### Multiple Ways to Navigate

Provide at least two methods to locate pages within a site:

**Navigation method options:**
- [ ] Site navigation menu
- [ ] Site search functionality
- [ ] Site map or index page
- [ ] Table of contents (for larger sections)
- [ ] Breadcrumb navigation
- [ ] Links between related pages

**Exceptions:**
- Single-page processes or step-by-step forms
- Pages that are part of a linear sequence

### Location Indicators

Help users understand where they are within the site:

**Current page marking:**
```html
<nav aria-label="Main navigation">
  <ul>
    <li><a href="/" aria-current="page">Home</a></li>
    <li><a href="/about">About</a></li>
    <li><a href="/services">Services</a></li>
  </ul>
</nav>
```

**Breadcrumb navigation:**
```html
<nav aria-label="Breadcrumb">
  <ol>
    <li><a href="/">Home</a></li>
    <li><a href="/products">Products</a></li>
    <li aria-current="page">Super Widget</li>
  </ol>
</nav>
```

**URL and heading structure:**
```html
<!-- Clear URL structure -->
https://example.com/services/web-development
https://example.com/products/widgets/premium

<!-- Matching page heading -->
<h1>Web Development Services</h1>
<h1>Premium Widget Specifications</h1>
```

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Skip links** | Bypass blocks to main content | `accessibility-focus` |
| **Breadcrumbs** | Hierarchical location indicator | Navigation structure above |
| **Mega menu** | Expandable navigation with sections | `accessibility-aria` for toggles |
| **Pagination** | Page numbers with current state | `accessibility-aria` for states |
| **Site search** | Search input with submit button | `accessibility-forms` |
| **SPA routing** | Dynamic title updates in router | Page titles section above |

## Testing

For comprehensive navigation testing procedures, use `accessibility-evaluation`.

## RGAA Correspondences

- **8.5**: Page title relevance and uniqueness
- **12.1-12.11**: Navigation consistency and skip links
- **6.1-6.2**: Links and link context

## Related Skills

- Use `accessibility-focus` for skip links to bypass blocks
- Use `accessibility-structure` for landmarks and page regions
- Use `accessibility-behavior` for consistent navigation across pages
- Use `accessibility-aria` for complex navigation patterns
- Use `accessibility-evaluation` for comprehensive navigation testing

## Resources

- [Accessible Navigation Design](https://www.w3.org/WAI/tutorials/menus/)
- [Page Title Best Practices](https://www.w3.org/WAI/WCAG22/Understanding/page-titled)
- [Link Purpose Understanding](https://www.w3.org/WAI/WCAG22/Understanding/link-purpose-in-context)
- [Multiple Ways to Navigate](https://www.w3.org/WAI/WCAG22/Understanding/multiple-ways)
