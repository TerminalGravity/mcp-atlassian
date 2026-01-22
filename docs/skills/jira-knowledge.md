---
name: jira-knowledge
description: Query the Jira knowledge base using natural language
---

# Jira Knowledge Query

Use this skill to search the Jira knowledge base using natural language questions. Leverages semantic search to find relevant issues, decisions, and historical context.

## Usage

```
/jira-knowledge <natural language question>
```

Examples:
- `/jira-knowledge How do we handle payment failures?`
- `/jira-knowledge What was decided about the API versioning strategy?`
- `/jira-knowledge Who worked on the authentication system?`

## Workflow

1. **Understand the question type**
   - Technical: How does X work?
   - Historical: What happened with X?
   - Decision: Why did we choose X?
   - People: Who knows about X?

2. **Construct search strategy**
   - Semantic search for conceptual matches
   - JQL for specific filters (project, date range, assignee)
   - Comment search for discussions and decisions

3. **Gather relevant context**
   - Find issues matching the query
   - Extract relevant comments and discussions
   - Identify key people involved

4. **Synthesize answer**
   - Summarize findings
   - Cite specific issues as sources
   - Highlight any conflicting information

## Output Format

```markdown
## Knowledge Query Results

### Question
"[original question]"

### Answer
[Synthesized answer based on Jira history]

### Sources
| Key | Title | Relevance |
|-----|-------|-----------|
| XXX-123 | ... | Main implementation |
| XXX-456 | ... | Design decision |

### Key People
- **[Name]**: [Their involvement]

### Related Topics
- [Link to related query or issue]
```

## Best Practices

- Ask specific questions for better results
- Include project context if known
- Use for learning about existing systems before making changes
