---
name: user-stories
description: Write well-structured user stories from requirements using template-based approach.
---

# User Story Generation

Create well-structured user stories that capture requirements clearly and concisely.

## When to Use

- Translating stakeholder requirements into actionable stories
- Breaking down epics into smaller stories
- Clarifying vague or incomplete requirements
- Documenting feature requests

## Quick Reference

| Element | Question to Answer |
|---------|-------------------|
| **Role** | Who is this for? |
| **Action** | What do they want to do? |
| **Benefit** | Why does it matter? |
| **Context** | Why now? What problem? |
| **Acceptance Criteria** | What defines done? |
| **Deadline** | When must it be delivered? |
| **Priority** | High / Medium / Low |
| **Value** | What does the team gain? |

## Process

### Step 1: Identify the User Role

**Who is this for?** Determine the primary user:

**Common roles:**
- End users (by persona: admin, customer, viewer, editor)
- Developers (internal team, API consumers)
- Operations (devops, sysadmin, SRE)
- Business users (analysts, managers, executives)

**Clarifying questions:**
- "Who will use this feature?"
- "What role do they have in the system?"
- "Is this for internal or external users?"

### Step 2: Define the Action

**What do they want to do?** Be specific about the capability:

**Guidelines:**
- Use action verbs (create, view, edit, delete, export, filter)
- Focus on one capability per story
- Avoid bundling unrelated actions
- Think from the user's perspective, not technical implementation

**Clarifying questions:**
- "What exactly should the user be able to do?"
- "Can this be broken into smaller actions?"
- "What triggers this action?"

### Step 3: Articulate the Benefit

**Why does it matter?** Connect to user value:

**Focus on:**
- Problem solved or pain point addressed
- Time or effort saved
- Risk reduced or compliance enabled
- Revenue or efficiency gained

**Clarifying questions:**
- "What problem does this solve for them?"
- "What can they do with this that they couldn't before?"
- "What happens if we don't build this?"

### Step 4: Gather Context

**Why now? What problem does this solve?**

**Information to capture:**
- Current workaround or manual process
- Business driver (regulatory, competitive, strategic)
- Related issues, bugs, or technical debt
- Dependencies on other features

**Clarifying questions:**
- "How are users working around this today?"
- "What's driving this request?"
- "Are there related issues or features?"

### Step 5: Determine Deadline

**When must this be delivered?**

**Types of deadlines:**
- Hard date (regulatory compliance, contract requirement)
- Milestone (release version, sprint goal)
- Relative ("before Q3", "by next iteration")
- TBD (not yet determined - still valid)

**Clarifying questions:**
- "Is there a specific date this is needed by?"
- "Is this tied to a release or milestone?"
- "What happens if delivery is delayed?"

### Step 6: Assess Priority

**High / Medium / Low - why now?**

**Consider:**
- **High**: Blocking other work, time-sensitive, critical bug
- **Medium**: Important but not urgent, can wait a sprint or two
- **Low**: Nice to have, backlog item, future consideration

**Clarifying questions:**
- "What's the impact of not doing this soon?"
- "Does this block other work?"
- "Compared to other open stories, where does this rank?"

### Step 7: Define Value Delivered

**What does the client or team gain?**

**Types of value:**
- Quantitative (time saved, error reduction %, revenue increase)
- Qualitative (user satisfaction, team velocity, reduced complexity)
- Strategic (competitive advantage, market positioning)

**Clarifying questions:**
- "How will we measure success?"
- "What metric might improve?"
- "Who benefits and how?"

### Step 8: Define Acceptance Criteria

**What conditions must be met for this story to be complete?**

Acceptance criteria are measurable conditions that define done:

**Types of acceptance criteria:**
- Functional requirements (what the system must do)
- Validation rules (input/output constraints)
- Performance requirements (response time, throughput)
- Security requirements (permissions, encryption)
- Edge cases (error handling, empty states)

**Guidelines:**
- Use "Given/When/Then" format or simple checklist
- Make them testable and unambiguous
- Cover happy path and common edge cases
- Keep criteria concise but complete

**Clarifying questions:**
- "What does done look like for this story?"
- "How will we test this works?"
- "What edge cases should we handle?"
- "Are there any validation rules?"

### Step 9: Apply the Template

Use the template below as your base structure. Fill in placeholder content with actual story information.

---

## User Story Template

```markdown
# User Story

As a [role], I want [action] so that [benefit].

## Context

[Why are we doing this? What problem does it solve?]

## Acceptance Criteria

- [Criterion 1 - measurable condition]
- [Criterion 2 - testable requirement]
- [Criterion 3 - edge case or validation]

## Deadline

[When must this be delivered?]

## Priority

[High / Medium / Low - why now?]

## Value Delivered

[What does the client or team gain?]
```

---

### Step 10: Review and Refine

Check that the story:
- Has a single focus (one action, one reason)
- Uses clear, non-technical language for the main statement
- Contains actionable information (role can be identified, benefit is concrete)
- Would be understood by someone unfamiliar with the project

## Key Principles

- **One story, one value** - Each story delivers one piece of value
- **User-focused** - Write from the user's perspective, not technical implementation
- **Concise** - Be brief but complete; avoid unnecessary detail
- **Actionable** - Stories should enable estimation and implementation
- **Flexible** - Stories are conversations, not contracts; refine as needed
