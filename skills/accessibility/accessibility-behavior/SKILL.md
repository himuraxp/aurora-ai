---
name: accessibility-behavior
description: Use when checking for predictable behavior, consistent navigation, and avoiding unexpected context changes on focus or input.
---

# Check Predictable Behavior

Ensure interactions are predictable and don't surprise users with unexpected changes.

## Quick Reference

| Scenario | Critical Check |
|----------|---------------|
| Input receives focus | NO context change (no submit, no navigation, no popup) |
| Dropdown/checkbox changed | User must explicitly confirm (button click) |
| Navigation menu | Same order/position on all pages |
| Icons/Buttons | Same function = same label/appearance |
| Help/Contact links | Same position on all pages |

## Critical Checks

### On Focus

When any element receives focus, it MUST NOT:
- [ ] Submit forms automatically
- [ ] Open new windows/popups
- [ ] Navigate to new pages
- [ ] Change content unexpectedly

**Examples:**
```html
<input placeholder="Search products">
<a href="/help">Search help</a>
```

### On Input

Changing a control's value MUST NOT automatically:
- [ ] Submit forms
- [ ] Navigate to new pages
- [ ] Open popups/modals
- [ ] Change context

**Examples:**
```html
<form>
  <select name="sort">
    <option>Price: Low to High</option>
    <option>Price: High to Low</option>
  </select>
  <button type="submit">Apply Sort</button>
</form>
```

### Consistent Navigation

Navigation components must appear in the same relative order and position across all pages in a set.

**Navigation requirements:**
- [ ] Navigation same relative order (DOM sequence) across pages
- [ ] Navigation same visual position on all pages
- [ ] Same components present on all pages
- [ ] Skip links in same relative location
- [ ] Breadcrumb position consistent across pages

**Examples:**
```html
<!-- Consistent header navigation on all pages -->
<header>
  <nav aria-label="Main">
    <a href="/">Home</a>
    <a href="/products">Products</a>
    <a href="/services">Services</a>
    <a href="/about">About</a>
  </nav>
</header>

<!-- Alternative: Breadcrumb in same position -->
<nav aria-label="Breadcrumb" class="breadcrumb">
  <ol>
    <li><a href="/">Home</a></li>
    <li><a href="/products">Products</a></li>
    <li aria-current="page">Current Item</li>
  </ol>
</nav>
```

### Consistent Identification

Components with same functionality MUST:
- [ ] Same icon = same meaning
- [ ] Same text = same action
- [ ] Same visual = same behavior

**Example:**
```html
<!-- All pages -->
<button aria-label="Save document">
  <img src="save.png" alt="">
</button>
```

### Consistent Help

If help mechanisms exist, they MUST appear in same order/position on all pages:

**Help mechanisms include:**
- Human contact info (phone, email, hours)
- Contact methods (chat, form, social)
- Self-help options (FAQ, how-to page)
- Automated help (chatbot)

**Requirements:**
- [ ] Same relative order in DOM
- [ ] Same visual position per viewport
- [ ] Present on all pages of set

**Example:**
```html
<!-- All pages -->
<footer>
  <nav aria-label="Footer">
    <a href="/contact">Contact</a>  <!-- Consistent position -->
    <a href="/about">About</a>
    <a href="/help">Help Center</a>
  </nav>
</footer>

<!-- OR in header -->
<header>
  <nav aria-label="Help">
    <a href="/contact">Contact</a>
    <button>Chat Support</button>
  </nav>
</header>
```

## Testing

For comprehensive testing procedures related to predictable behavior, use `accessibility-evaluation`.

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| Form submission | Explicit submit button | `accessibility-forms` |
| Filter/sort | Apply button required | `accessibility-forms` |
| Help access | Consistent footer/header | `accessibility-navigation` |
| Contact links | Same position all pages | `accessibility-navigation` |
| Navigation menu | Same DOM order | `accessibility-structure` |

## RGAA Correspondences

- **7.3**: Context changes notified → Use `aria-live` for unexpected changes (see `accessibility-aria`)
- **12.x**: Navigation consistency → Same order/position across pages
- **13.x**: Predictable behavior → No auto-submit, explicit user actions

## Related Skills

- Use `accessibility-forms` for form validation and submission patterns
- Use `accessibility-navigation` for navigation structure and skip links
- Use `accessibility-aria` for announcing context changes
- Use `accessibility-evaluation` for audit methodology

## Resources

- [Understanding On Focus](https://www.w3.org/WAI/WCAG22/Understanding/on-focus)
- [Understanding On Input](https://www.w3.org/WAI/WCAG22/Understanding/on-input)
- [Understanding Consistent Help](https://www.w3.org/WAI/WCAG22/Understanding/consistent-help)
