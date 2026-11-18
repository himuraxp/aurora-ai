---
name: accessibility-structure
description: Use when checking semantic HTML structure, headings hierarchy, page regions, lists, and data tables.
---

# Structure Content Semantically

Ensure content is properly structured with semantic HTML so assistive technologies can navigate and understand page organization.

## Quick Reference

| Scenario | Requirement | Implementation |
|----------|-------------|----------------|
| **Page sections** | Landmarks present | header, nav, main, aside, footer elements |
| **Headings** | Logical hierarchy | One h1, sequential levels without skips |
| **Interactive elements** | Native semantics | button for actions, a for navigation |
| **Data tables** | Structured markup | th headers with scope, caption, thead/tbody |
| **Content order** | Meaningful sequence | DOM order matches visual reading order |
| **Lists** | Proper structure | ul/ol/li for list items, dl for definition lists |

## Critical Checks

### Semantic HTML Elements

Use appropriate HTML elements to convey structure and purpose:

- [ ] Use `<header>` for page banner (logo, site title)
- [ ] Use `<nav>` for navigation blocks
- [ ] Use `<main>` for primary content (must be unique per page)
- [ ] Use `<aside>` for complementary content (sidebars)
- [ ] Use `<footer>` for footer content
- [ ] Use `<search>` for search regions (HTML5)
- [ ] Use `<article>` for self-contained content
- [ ] Use `<section>` for thematic grouping when no more specific element applies
- [ ] Use `<button>` for clickable actions (submit, toggle)
- [ ] Use `<a>` for navigation links (page changes)

```html
<!-- Page structure with landmarks -->
<header>
  <a href="/">Company Logo</a>
  <search>
    <input type="search" aria-label="Search site">
    <button>Search</button>
  </search>
</header>

<nav aria-label="Main navigation">
  <ul>
    <li><a href="/">Home</a></li>
    <li><a href="/about">About</a></li>
  </ul>
</nav>

<main>
  <h1>Page Title</h1>
  <article>
    <h2>Article Heading</h2>
    <p>Content...</p>
  </article>
</main>

<aside>
  <h2>Related Links</h2>
  <ul>
    <li><a href="/related">Related article</a></li>
  </ul>
</aside>

<footer>
  <p>&copy; 2024 Company Name</p>
</footer>
```

### Interactive Element Semantics

Distinguish between buttons and links based on behavior:

- [ ] `<button>` for actions within the page (submit form, toggle, open modal)
- [ ] `<a>` for navigation to new pages or locations
- [ ] Use `type="button"` on buttons not in forms to prevent accidental submission
- [ ] Links that behave like buttons need role="button" AND keyboard handlers

```html
<!-- Button for actions -->
<button type="submit">Save Changes</button>
<button type="button" onclick="toggleMenu()">Toggle Menu</button>
<button type="button" onclick="openModal()">Open Dialog</button>

<!-- Link for navigation -->
<a href="/about">Learn more about us</a>
<a href="#section-2">Jump to Section 2</a>
```

### Heading Hierarchy

Headings create an outline of the page content:

- [ ] One `<h1>` per page as the main topic
- [ ] Headings follow logical hierarchy without skipping levels
- [ ] Heading levels reflect visual hierarchy
- [ ] Headings are descriptive of the content they introduce
- [ ] No empty headings

```html
<h1>Product Guide</h1>
  <h2>Getting Started</h2>
    <h3>Installation</h3>
    <h3>Configuration</h3>
  <h2>Advanced Features</h2>
    <h3>API Integration</h3>
    <h3>Customization Options</h3>
  <h2>Troubleshooting</h2>
```

**Avoid heading hierarchy issues:**
- Don't skip levels (h1 → h3)
- Don't use multiple h1 elements
- Don't choose heading level based on visual size (use CSS for styling)
- Don't use heading elements purely for styling

### Data Tables

Structure tables so screen readers can associate headers with data:

- [ ] Use `<th>` for column and row headers
- [ ] Use `scope="col"` for column headers
- [ ] Use `scope="row"` for row headers
- [ ] Use `<caption>` to describe the table
- [ ] Use `<thead>` and `<tbody>` to group header and data rows
- [ ] Avoid using tables for layout

```html
<table>
  <caption>Sales Performance by Quarter</caption>
  <thead>
    <tr>
      <th scope="col">Product</th>
      <th scope="col">Q1</th>
      <th scope="col">Q2</th>
      <th scope="col">Q3</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th scope="row">Widget A</th>
      <td>$10,000</td>
      <td>$12,000</td>
      <td>$15,000</td>
    </tr>
    <tr>
      <th scope="row">Widget B</th>
      <td>$8,000</td>
      <td>$9,000</td>
      <td>$11,000</td>
    </tr>
  </tbody>
</table>
```

### Lists

Use list elements for grouped items:

- [ ] Use `<ul>` for unordered lists
- [ ] Use `<ol>` for ordered/sequential lists
- [ ] Use `<li>` for list items
- [ ] Use `<dl>`, `<dt>`, `<dd>` for definition/description lists
- [ ] Nested lists for hierarchical content

```html
<!-- Unordered list -->
<ul>
  <li>Apples</li>
  <li>Oranges</li>
  <li>Bananas</li>
</ul>

<!-- Ordered list with nested list -->
<ol>
  <li>First step</li>
  <li>Second step
    <ul>
      <li>Sub-step A</li>
      <li>Sub-step B</li>
    </ul>
  </li>
  <li>Third step</li>
</ol>

<!-- Definition list -->
<dl>
  <dt>HTML</dt>
  <dd>HyperText Markup Language</dd>
  <dt>CSS</dt>
  <dd>Cascading Style Sheets</dd>
</dl>
```

### Meaningful Sequence

Ensure content reading order is logical:

- [ ] DOM order matches visual reading order
- [ ] CSS doesn't reposition content in ways that change meaning
- [ ] Multi-column layouts read top-to-bottom, then left-to-right
- [ ] Screen reader announces content in logical sequence
- [ ] Tab order follows visual order

**CSS considerations:**
```css
/* Be cautious with order property - it changes visual order but not DOM order */
.flex-container {
  display: flex;
}

/* This affects ALL users - visual order differs from DOM/screen reader order */
.sidebar {
  order: 2;
}
.main-content {
  order: 1;
}

/* Better: structure DOM in the intended reading order */
```

**CSS Grid reading order:**
```css
/* Grid with logical DOM order */
.grid-layout {
  display: grid;
  grid-template-areas:
    "header header"
    "nav main"
    "footer footer";
}

/* DOM structure should match grid areas visually */
```

### HTML5 Landmarks

Landmark regions help users navigate to major page sections:

- [ ] `<header>` - Banner region (not nested in landmarks)
- [ ] `<nav>` - Navigation regions
- [ ] `<main>` - Main content (one per page, not nested)
- [ ] `<aside>` - Complementary content
- [ ] `<footer>` - Contentinfo region
- [ ] `<search>` - Search landmark (HTML5, for search functionality)

```html
<header>
  <!-- Site logo, name, utility nav -->
</header>

<nav aria-label="Main">
  <!-- Primary navigation -->
</nav>

<nav aria-label="Secondary">
  <!-- Secondary navigation -->
</nav>

<main>
  <!-- Primary page content -->
</main>

<aside>
  <!-- Related content, ads, sidebars -->
</aside>

<footer>
  <!-- Copyright, legal links -->
</footer>
```

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Page landmarks** | header, nav, main, aside, footer structure | Critical checks above |
| **Navigation list** | nav > ul > li > a hierarchy | `accessibility-navigation` |
| **Form sections** | section + h2 to group related fields | `accessibility-forms` |
| **Article cards** | article > h2 + content preview | Critical checks above |
| **Data table** | table with caption, thead, scoped th | Critical checks above |
| **Definition list** | dl > (dt + dd) pairs | Critical checks above |

## Testing

For comprehensive semantic structure testing procedures, use `accessibility-evaluation`.

## RGAA Correspondences

- **8.1-8.2**: Unique h1 per page
- **8.3-8.6**: Language declaration and page structure
- **8.7-8.9**: Title and headings hierarchy
- **5.1-5.8**: Table structure and headers
- **9.1-9.4**: Page structure and landmarks
- **10.x**: Presentation of information (semantics vs presentation)

## Related Skills

- Use `accessibility-navigation` for navigation structure and skip links
- Use `accessibility-headings` (if available) for detailed heading patterns
- Use `accessibility-aria` for complex structures requiring ARIA roles
- Use `accessibility-language` for language declarations on sections
- Use `accessibility-evaluation` for testing with screen readers

## Resources

- [HTML Living Standard - Semantics](https://html.spec.whatwg.org/multipage/semantics.html)
- [ARIA Landmarks](https://www.w3.org/WAI/WCAG22/Understanding/info-and-relationships)
- [Understanding Meaningful Sequence](https://www.w3.org/WAI/WCAG22/Understanding/meaningful-sequence)
- [Understanding Headings and Labels](https://www.w3.org/WAI/WCAG22/Understanding/headings-and-labels)
