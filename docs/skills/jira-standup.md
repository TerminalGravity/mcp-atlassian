---
name: jira-standup
description: Generate a standup report from recent Jira activity
---

# Jira Standup Report Generator

Use this skill to generate a standup report based on your recent Jira activity. Automatically summarizes what you worked on, what's in progress, and identifies blockers.

## Usage

```
/jira-standup [options]
```

Options:
- No args: Your activity from the last 24 hours
- `--week`: Your activity from the last week
- `--team`: Include team activity (requires team context)
- `--project <KEY>`: Filter to specific project

Examples:
- `/jira-standup`
- `/jira-standup --week`
- `/jira-standup --project DS`

## Workflow

1. **Fetch recent activity**
   - Issues updated by you in the time period
   - Issues transitioned by you
   - Comments you added

2. **Categorize by status**
   - **Done**: Issues moved to Done/Closed
   - **In Progress**: Active work
   - **Blocked**: Issues with blocker flags or stalled

3. **Extract key updates**
   - Status changes
   - Important comments
   - Time logged

4. **Generate standup format**

## Output Format

```markdown
## Standup Report - [Date]

### Yesterday / Recently Completed
- [ISSUE-KEY]: [Summary] - [Brief what was done]
- [ISSUE-KEY]: [Summary] - [Brief what was done]

### Today / In Progress
- [ISSUE-KEY]: [Summary] - [Current status/next steps]
- [ISSUE-KEY]: [Summary] - [Current status/next steps]

### Blockers
- [ISSUE-KEY]: [Summary] - [What's blocking]

### Notes
[Any additional context or FYIs]
```

## Example Output

```markdown
## Standup Report - January 22, 2026

### Recently Completed
- DS-2461: Wrap APIs for ezeprepaid - API integration complete, PR merged
- DS-2438: Galileo instant issue cards - Testing complete

### In Progress
- DS-2617: Chase integration - Working on auth flow, 60% complete

### Blockers
- DS-2550: Payment gateway timeout - Waiting on vendor response

### Notes
- Will need code review on DS-2617 by EOD
```

## Tips

- Run at the start of your day to prepare for standup
- Use `--week` for weekly summaries or 1:1s
- Combine with `/jira-my-work` for full context
