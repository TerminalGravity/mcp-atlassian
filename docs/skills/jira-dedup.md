---
name: jira-dedup
description: Check for duplicate issues before creating a new one
---

# Jira Duplicate Detection

Use this skill before creating a new Jira issue to check for existing duplicates or similar issues that might already address the problem.

## Usage

```
/jira-dedup <description of the issue>
```

Example: `/jira-dedup API rate limiting causing 429 errors in production`

## Workflow

1. **Parse the issue description**
   - Extract key technical terms
   - Identify the problem domain (bug, feature, task)
   - Note any specific components or systems mentioned

2. **Search for similar issues** using multiple strategies:
   - Semantic search with the full description
   - JQL search for key terms in open issues
   - JQL search for recently closed issues (might be fixed)

3. **Score potential duplicates**
   - High: Nearly identical description, same component
   - Medium: Similar problem, different context
   - Low: Related topic, different issue

4. **Present findings** with recommendations:
   - If duplicates found: Link to existing issues
   - If similar found: Suggest referencing or linking
   - If none found: Proceed with creation

## Output Format

```markdown
## Duplicate Check Results

### Search Query
"[original description]"

### Potential Duplicates (High Confidence)
| Key | Summary | Status | Match Reason |
|-----|---------|--------|--------------|
| XXX-123 | ... | Open | Same error message |

### Similar Issues (Medium Confidence)
| Key | Summary | Status | Similarity |
|-----|---------|--------|------------|
| XXX-456 | ... | Closed | Related component |

### Recommendation
[ ] **Duplicate found** - Add comment to [ISSUE-KEY] instead
[ ] **Similar exists** - Create new issue but link to [ISSUE-KEY]
[x] **No duplicates** - Safe to create new issue
```

## Tips

- Be specific in your description for better matching
- Include error messages, component names, and symptoms
- Check both open AND recently closed issues
