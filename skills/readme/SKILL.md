---
name: readme
description: Generate comprehensive README.md documentation for projects using template-based approach.
---

# README Generation

Generate consistent, comprehensive README.md files using a structured template.

## When to Use

- Creating new project documentation
- Updating outdated or incomplete READMEs
- Standardizing documentation across multiple projects

## Quick Reference

| Task | What to Look For |
|------|------------------|
| **Project type** | Programming language, framework, file extensions |
| **Package managers** | Dependency configuration files |
| **Build configs** | Build automation files |
| **Entry points** | Main application files |
| **Existing docs** | `.md` files, `docs/`, `documentation/` directories |
| **License** | `LICENSE*` files |

## Process

### Step 1: Explore the Project

Understand what you're documenting before writing:

**Check for existing documentation:**
- Read existing `README.md` if present
- Look for documentation files and directories (`.md` files, `docs/`, `documentation/`)

**Identify project type:**
- Programming language/framework (check file extensions, configs)
- Package managers
- Build configs
- Entry points

**Extract key information:**
- Project name and description (from package files, comments)
- Version numbers
- Dependencies and their versions
- License information

### Step 2: Ask Clarifying Questions

When information is unclear, ask about:
- **Target audience** - developers, end users, data scientists?
- **Tone** - formal, friendly, minimal?
- **Key features** - what should be highlighted?
- **Platform support** - Windows, Mac, Linux? Browser support?

### Step 3: Apply the Template

Use the template below as your base structure. Fill in placeholder content with actual project information.

---

## README Template

```markdown
# [Project Name]

[Brief one-sentence description of what this project does.]

## Description

[Detailed description of the project, its purpose, and key benefits.]

## Features

- [Feature 1 - brief description if needed]
- [Feature 2]
- [Feature 3]

## Prerequisites

- [List required dependencies, version numbers, etc.]
- [Example: Node.js >= 18.0]
- [Example: Docker & Docker Compose]

## Installation

[Step-by-step installation instructions.]

```bash
[Command 1]
[Command 2]
[Command 3]
```

## Usage

[How to use the project after installation.]

```bash
[Example commands]
```

## Configuration

[Environment variables, config files, and how to customize the project.]

| Variable | Description | Default |
| -------- | ----------- | ------- |
| VAR_NAME | Description | value   |

## Testing

[How to run tests.]

```bash
[test command]
```

## Contributing

[Guidelines for contributing to the project.]
```

---

### Step 4: Fill Each Section

Use these guidelines when filling template sections:

**Description:**
- What problem does this project solve?
- What are the key benefits?
- Who is the target audience?

**Features:**
- Main capabilities (bullet list)
- What makes it unique?

**Prerequisites:**
- Runtime requirements with versions (Node.js, Python, Java)
- Build tools needed
- System dependencies

**Installation:**
- How users get the code (npm, pip, git clone, download)
- Commands to install dependencies
- Build steps (compile, transpile, bundle)

**Usage:**
- Basic command-line usage
- Import statements for libraries
- Common operations
- Configuration requirements

**Configuration:**
- Environment variables (use table format)
- Config file formats
- Default values
- Optional settings

**Testing:**
- Test framework used
- How to run the test suite
- Coverage requirements
- Common test commands

**Contributing:**
- How to submit pull requests
- Code style requirements
- Branch naming conventions
- Commit message format

## Key Principles

- **Be complete** - Include all sections from the template
- **Be precise** - Use exact commands, correct paths, accurate versions
- **Be concise** - Clear instructions without unnecessary verbosity
- **Be consistent** - Follow markdown formatting conventions
- **Verify** - Ensure commands are runnable as written
