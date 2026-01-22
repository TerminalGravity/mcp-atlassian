---
name: jira-investigate
description: Deep investigation of a Jira issue using semantic search to find related context
---

# Jira Issue Investigation

Use this skill to perform a deep investigation of a Jira issue by finding semantically related issues, similar past work, and potential duplicates.

## Usage

```
/jira-investigate <issue-key>
```

Example: `/jira-investigate DS-1234`

## Workflow

1. **Fetch the target issue** using `mcp__adr-jira__jira_get_issue`
   - Get full details including description, comments, and links

2. **Search for semantically similar issues** using `jira_semantic_search` (if available) or construct a search query
   - Use the issue summary and key description terms as the search query
   - Look for issues with similar problem descriptions

3. **Check for linked issues**
   - Review parent/child relationships
   - Check epic associations
   - Review issue links (blocks, relates to, duplicates)

4. **Search for related keywords**
   - Extract key technical terms from the description
   - Search for those terms across the project

5. **Compile investigation report** with:
   - Issue summary and current status
   - Related issues found (with similarity reasoning)
   - Potential duplicates or prior art
   - Linked issues and their status
   - Recommended actions based on findings

## Output Format

```markdown
## Investigation: [ISSUE-KEY]

### Summary
[Brief description of the issue]

### Status
- **Current**: [status]
- **Assignee**: [name]
- **Priority**: [priority]

### Related Issues Found
| Key | Summary | Relevance |
|-----|---------|-----------|
| XXX-123 | ... | Similar problem |
| XXX-456 | ... | Same component |

### Potential Duplicates
[List any issues that appear to be duplicates with reasoning]

### Linked Issues
[Parent, child, and related issues with their status]

### Recommendations
[Actionable next steps based on the investigation]
```
