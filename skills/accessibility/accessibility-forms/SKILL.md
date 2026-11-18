---
name: accessibility-forms
description: Use when checking form accessibility including labels, error handling, input assistance, and submission patterns.
---

# Create Accessible Forms

Ensure all users can understand, complete, and submit forms with proper labeling and error handling.

## Quick Reference

| Pattern | Implementation |
|---------|---------------|
| **Labels** | `<label for="id">` or implicit `<label>` wrapping |
| **Required fields** | Visible indicator + `required` + `aria-required` |
| **Errors** | `aria-invalid` + `aria-describedby` error message |
| **Error messages** | Specific suggestions (format, length, examples) |
| **Radio/Checkbox groups** | `<fieldset>` + `<legend>` |
| **Redundant entry** | Auto-fill or copy from previous input |
| **Authentication** | Alternatives to captcha/puzzles |

## Critical Checks

### Labels and Accessible Names

- [ ] Every input has associated label
- [ ] Labels are visible (not just placeholders)
- [ ] Visible label text matches accessible name (voice control compatibility)
- [ ] Labels are descriptive and clear
- [ ] Clicking label focuses associated input

**Implementation:**
```html
<!-- Explicit association (recommended) -->
<label for="email">Email address</label>
<input type="email" id="email" name="email">

<!-- Implicit association -->
<label>
  Email address
  <input type="email" name="email">
</label>

<!-- ARIA labeling -->
<input type="search" aria-label="Search products">

<!-- Accessible name includes visible label text -->
<button aria-label="Send message">Send</button>
```

### Input Purpose and Autocomplete

- [ ] Use `autocomplete` attributes for user data fields
- [ ] Common values: email, tel, name, address-line1, postal-code, country
- [ ] Password fields: current-password, new-password

```html
<input type="email" autocomplete="email">
<input type="tel" autocomplete="tel">
<input name="password" autocomplete="current-password">
<input name="new-password" autocomplete="new-password">
```

### Error Identification and Handling

- [ ] Errors clearly identified visually
- [ ] Error message associated with field (aria-describedby)
- [ ] Error announced to screen readers (role="alert" or aria-live)
- [ ] Form doesn't submit with errors
- [ ] Focus moves to first error on submit attempt

**Error State Pattern:**
```html
<label for="email">Email address</label>
<input 
  type="email" 
  id="email" 
  aria-invalid="true"
  aria-describedby="email-error"
>
<span id="email-error" role="alert">
  Please enter a valid email address (e.g., user@example.com)
</span>
```

### Error Suggestions

Provide specific correction guidance:
- [ ] Format examples: "Date format: MM/DD/YYYY"
- [ ] Length requirements: "Password must be at least 8 characters"
- [ ] Format validation: "Email must contain @ symbol"
- [ ] Available options: "Username must be unique. Try: johnsmith123"

### Form Structure

**Radio and Checkbox Groups:**
```html
<fieldset>
  <legend>How did you hear about us?</legend>
  <label><input type="radio" name="source" value="web"> Website</label>
  <label><input type="radio" name="source" value="friend"> Friend</label>
  <label><input type="radio" name="source" value="ad"> Advertisement</label>
</fieldset>
```

**Required Field Indicators:**
```html
<label for="email">
  Email address <span aria-label="required">*</span>
</label>
<input 
  type="email" 
  id="email" 
  required 
  aria-required="true"
>
```

### Error Prevention (Sensitive Data)

For legal, financial, or data-modifying submissions:
- [ ] Submission is reversible (delete/undo)
- [ ] OR data is checked for errors before final submission
- [ ] OR user explicitly confirms action

**Review and Confirm Pattern:**
```html
<!-- Step 1: Review screen -->
<h2>Review your transfer</h2>
<p>Amount: $500</p>
<p>To: Account #1234</p>
<button>Edit details</button>
<button>Confirm transfer</button>

<!-- Step 2: Success with undo option -->
<p>Transfer completed</p>
<button>Undo within 24 hours</button>
```

### Redundant Entry (Forms)

- [ ] Don't ask for same information twice in same session
- [ ] Auto-fill shipping address from billing address with "Same as" checkbox
- [ ] Copy previously entered email instead of re-asking
- [ ] Allow editing of pre-filled data

**Auto-fill Pattern:**
```html
<label>
  <input type="checkbox" id="same-as-billing" checked>
  Shipping address same as billing address
</label>

<script>
document.getElementById('same-as-billing').addEventListener('change', (e) => {
  if (e.target.checked) {
    // Copy billing to shipping fields
    copyBillingToShipping();
  }
});
</script>
```

### Accessible Authentication

Authentication must not rely solely on cognitive function tests:

- [ ] Alternatives to CAPTCHA provided
- [ ] Accept password managers
- [ ] "Magic link" email authentication available
- [ ] SMS or authenticator app codes (not sole method)
- [ ] Biometric authentication as option
- [ ] No mandatory memorization of passwords beyond login

**CAPTCHA Alternatives:**
```html
<!-- Instead of image CAPTCHA -->
<p>Email verification sent. Check your inbox.</p>
<input type="text" placeholder="Enter 6-digit code" autocomplete="one-time-code">

<!-- Or magic link -->
<a href="/auth-link?token=abc123">Click to log in</a>
```

## Common Patterns

| Pattern | Implementation | See Also |
|---------|---------------|----------|
| **Text input** | Label + input with autocomplete | Critical checks above |
| **Error display** | aria-invalid + aria-describedby | `accessibility-aria` |
| **Required fields** | Visible indicator (e.g., *) + aria-required | Critical checks above |
| **Radio group** | Fieldset + Legend | Critical checks above |
| **Multi-step form** | Progress indicator + clear steps | `accessibility-navigation` |
| **Form submission** | Submit button + error summary | `accessibility-behavior` for confirmation |

## Testing

For comprehensive form testing procedures, use `accessibility-evaluation`.

## RGAA Correspondences

- **11.1-11.3**: Form labels required (`label` or `aria-label`)
- **11.4-11.6**: Fieldsets for radio/checkbox groups
- **11.7-11.9**: Required field indicators
- **11.10-11.11**: Error identification and suggestions
- **11.12-11.13**: Error prevention for sensitive data

## Related Skills

- Use `accessibility-keyboard` for form navigation and focus management
- Use `accessibility-color-contrast` for error message visibility
- Use `accessibility-aria` for complex form validation patterns
- Use `accessibility-evaluation` for comprehensive form testing methodology

## Resources

- [HTML Autocomplete Values](https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#autofilling-form-controls)
- [Label in Name Pattern](https://www.w3.org/WAI/WCAG22/Understanding/label-in-name)
- [Accessible Authentication](https://www.w3.org/WAI/WCAG22/Understanding/accessible-authentication-minimum)
