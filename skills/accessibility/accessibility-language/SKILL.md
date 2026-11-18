---
name: accessibility-language
description: Use when checking language declarations, multilingual content, and text direction for proper screen reader pronunciation and international accessibility.
---

# Declare Page Language

Ensure content is properly marked for language to support screen reader pronunciation and international users.

## Quick Reference

| Declaration | Usage |
|-------------|-------|
| **Page language** | `<html lang="fr">` on root element |
| **Inline change** | `<span lang="en">foreign text</span>` |
| **RTL language** | `<html lang="ar" dir="rtl">` |
| **BCP 47 format** | `language-region` (e.g., `fr-FR`, `en-US`) |

## Critical Checks

### Page Language Declaration

- [ ] Default language declared on `<html>` element
- [ ] Valid BCP 47 language code used
- [ ] Code matches actual page content language

**Common BCP 47 Language Codes:**

| Language | Code | Example |
|----------|------|---------|
| French | `fr` or `fr-FR` | `<html lang="fr">` |
| English | `en` or `en-US` | `<html lang="en">` |
| German | `de` or `de-DE` | `<html lang="de">` |
| Spanish | `es` or `es-ES` | `<html lang="es">` |
| Italian | `it` | `<html lang="it">` |
| Portuguese | `pt` or `pt-BR` | `<html lang="pt">` |
| Dutch | `nl` | `<html lang="nl">` |
| Chinese (Simplified) | `zh-Hans` or `zh-CN` | `<html lang="zh-Hans">` |
| Chinese (Traditional) | `zh-Hant` | `<html lang="zh-Hant">` |
| Japanese | `ja` | `<html lang="ja">` |
| Korean | `ko` | `<html lang="ko">` |
| Arabic | `ar` | `<html lang="ar" dir="rtl">` |
| Hebrew | `he` | `<html lang="he" dir="rtl">` |
| Russian | `ru` | `<html lang="ru">` |

**Implementation:**
```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Ma page en français</title>
</head>
<body>
  <!-- Content in French -->
</body>
</html>
```

### Inline Language Changes

- [ ] Foreign words/phrases marked with `lang` attribute
- [ ] Short quotations in other languages identified
- [ ] Exceptions handled properly (proper names, technical terms)

**Examples:**
```html
<p>Welcome to our <span lang="fr">café</span> and bakery.</p>

<p>The concept of <span lang="de">Schadenfreude</span> has no direct English translation.</p>

<p>Visit us at <span lang="ja">東京</span> (Tokyo) station.</p>

<p>Email us at <span lang="en">contact@example.com</span></p>
```

**Exceptions** (no language markup needed):
- Proper names: Paris, Tokyo, Mercedes
- Technical terms: HTML, CSS, API
- Common loanwords: café, kindergarten, spaghetti
- Words adopted into vernacular

### Right-to-Left (RTL) Languages

For Arabic, Hebrew, Persian, and other RTL scripts:

- [ ] `dir="rtl"` on `<html>` or container
- [ ] Content flows right-to-left
- [ ] CSS logical properties used for margins/padding

**Implementation:**
```html
<!-- RTL page -->
<html lang="ar" dir="rtl">
  <body>
    <h1>مرحبا بالعالم</h1>
    <p>محتوى الصفحة...</p>
  </body>
</html>

<!-- Inline RTL in LTR page -->
<p>The Arabic phrase <span lang="ar" dir="rtl">مرحبا</span> means hello.</p>
```

**CSS Logical Properties:**
```css
/* Instead of fixed directions, use logical properties */
.content {
  /* Instead of margin-left: 1rem; */
  margin-inline-start: 1rem;
  
  /* Instead of padding-right: 2rem; */
  padding-inline-end: 2rem;
  
  /* Instead of border-left: 1px solid; */
  border-inline-start: 1px solid;
}

/* Text alignment */
.text-start {
  text-align: start; /* Respects direction */
}
```

### Bidirectional Text

For mixed LTR and RTL content:

```html
<!-- Phone number in Arabic text -->
<p lang="ar" dir="rtl">
  للاتصال: <span dir="ltr">+33 1 23 45 67 89</span>
</p>

<!-- Email in RTL context -->
<p lang="he" dir="rtl">
  צרו קשר: <span dir="ltr">contact@example.com</span>
</p>
```

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Monolingual page** | `<html lang="fr">` on root | Critical checks above |
| **Multilingual content** | `<span lang="en">` for inline foreign text | Critical checks above |
| **RTL page** | `<html lang="ar" dir="rtl">` | `accessibility-responsive` for RTL layouts |
| **Mixed text** | `<span dir="ltr">` in RTL context for numbers/URLs | Critical checks above |
| **CSS logical properties** | `margin-inline-start` instead of `margin-left` | Critical checks above |

## Testing

For comprehensive language testing procedures and screen reader validation, use `accessibility-evaluation`.

### Quick Verification
- [ ] `<html lang="...">` present in page source
- [ ] Language code matches actual content
- [ ] Inline foreign text marked with `lang` attribute
- [ ] RTL pages use `dir="rtl"` appropriately

## RGAA Correspondences

- **8.3**: Default language present on page (`<html lang="...">`)
- **8.4**: Language code valid and relevant (BCP 47 format)
- **8.7**: Language changes indicated in source code (`<span lang="...">`)
- **8.8**: Language code for changes valid and relevant

## Related Skills

- Use `accessibility-structure` for document structure and headings
- Use `accessibility-evaluation` for comprehensive testing methodology
- Use `accessibility-aria` for complex multilingual patterns

## Resources

- [Understanding Language of Page](https://www.w3.org/WAI/WCAG22/Understanding/language-of-page)
- [Understanding Language of Parts](https://www.w3.org/WAI/WCAG22/Understanding/language-of-parts)
- [BCP 47 Language Codes](https://tools.ietf.org/html/bcp47)
- [W3C Internationalization](https://www.w3.org/International/)
- [RTL Styling Best Practices](https://rtlstyling.com/)
