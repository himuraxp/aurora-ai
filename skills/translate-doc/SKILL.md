---
name: translate-doc
description: Translate documentation between languages while preserving meaning and structure.
---

# Skill: Translate Documentation Between Languages

## Goal

Translate documentation files from a **source language to a target language** while preserving the original meaning, tone, and structure of the source material.

The translation must remain faithful to the intent of the original text and maintain consistent terminology throughout the entire document.

---

## Core Principles

1. **Stay faithful to the original meaning**
   - Translate the content as closely as possible to the meaning of the source text.
   - Do not add, remove, or reinterpret information.
   - Avoid paraphrasing unless necessary for clarity in the target language.

2. **Maintain documentation style**
   - Preserve the structure of the document (headings, lists, code blocks, tables).
   - Do not modify formatting unless required for correctness.
   - Keep technical terminology accurate and appropriate for developer documentation.

3. **Ensure terminology consistency**
   - Use consistent wording for repeated terms across the entire file.
   - If a specific term appears multiple times, translate it the same way unless context clearly requires otherwise.
   - Prefer standard technical vocabulary used in software documentation in the target language.

---

## Translation Process

### 1. Process the document in chunks if it's too large

To avoid context overload and maintain translation quality:

- Split the file into **chunks of reasonable size** when the whole document is too large.
- Each chunk should contain a coherent section of the document (e.g., paragraphs or subsections).
- Translate each chunk independently while keeping awareness of previously translated terminology.

### 2. Track terminology

During translation:

- Maintain a **mental glossary** of important terms.
- Reuse the same translations for key concepts throughout the document.
- Avoid translating the same term differently across sections.

### 3. Preserve technical elements

Do **not translate or modify**:

- Code blocks
- CLI commands
- File paths
- Variable names
- Configuration keys
- URLs

Translate **only surrounding explanatory text**.

---

## Post-Translation Verification

After translating the entire document:

1. **Meaning validation**
   - Verify that the translation accurately reflects the original meaning.
   - Ensure no information was lost or introduced.
   - If possible, perform a **back-translation spot check**: select a few key paragraphs, translate them back into the source language, and compare with the original to detect meaning drift.

2. **Consistency check**
   - Confirm that key terminology is translated consistently across the whole file.

3. **Fluency review**
   - Ensure the text reads naturally in the target language.
   - Adjust phrasing only when necessary to improve clarity without altering meaning.

4. **Formatting check**
   - Confirm that:
     - Markdown structure is preserved
     - Headings remain correct
     - Lists and tables render properly
     - Code blocks are unchanged
     - Language-specific typographic conventions are appropriate for the target language

---

## Expected Output

- The final output must be a **fully translated version of the original file in the target language**.
- Formatting and structure must match the original document.
- The translation should be **accurate, consistent, and natural for readers of the target language**.
