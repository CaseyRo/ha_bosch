# Total Recall Memory Schema

> Protocol documentation for the Total Recall memory system.
> Loaded every session to guide memory operations.

## Four-Tier Architecture

```
CLAUDE.local.md          ← Working memory (auto-loaded, ~1500 words)
memory/registers/        ← Domain registers (load on demand)
memory/daily/            ← Daily logs (append-only, date-named)
memory/archive/          ← Completed/superseded items (cold storage)
```

### Tier 1: Working Memory (CLAUDE.local.md)
- Auto-loaded every session
- Only behavior-changing facts
- ~1500 word limit — prune aggressively
- Updated via /recall-write or manual edits

### Tier 2: Registers (memory/registers/)
- Loaded on demand when topic is relevant
- Domain-specific: people, projects, decisions, preferences, tech-stack, open-loops
- More detailed than working memory
- open-loops.md loaded every session (auto)

### Tier 3: Daily Logs (memory/daily/)
- Append-only, one file per day (YYYY-MM-DD.md)
- First write destination for all new information
- Raw capture — promote important items to registers later
- Never delete, archive after 90 days

### Tier 4: Archive (memory/archive/)
- Completed projects, superseded decisions, old daily logs
- Cold storage — rarely read
- Organized by type: projects/, daily/

## Write Gate Rules

Before writing anything, ask: **"Does this change future behavior?"**

Write if YES:
- User corrects something I got wrong
- New preference stated explicitly
- Decision made with rationale
- Commitment or deadline given
- Person introduced with context
- Project state changes significantly

Skip if NO:
- Casual conversation
- Information already in memory
- One-off facts with no future relevance
- Transient debug output

## Read Rules

**Auto-loaded every session:**
- CLAUDE.local.md (working memory)
- memory/registers/open-loops.md

**Load on demand:**
- people.md — when a person is mentioned
- projects.md — when a project is discussed
- decisions.md — when past choices are questioned
- preferences.md — when task involves user style
- tech-stack.md — when technical choices come up

**Load explicitly (user request or /recall-search):**
- Daily logs
- Archive files

## Routing Table

| Trigger | Destination |
|---------|-------------|
| New preference stated | preferences.md + working memory |
| Person introduced | people.md |
| Project status update | projects.md |
| Decision made | decisions.md |
| Deadline/commitment | open-loops.md + working memory |
| Tech choice confirmed | tech-stack.md |
| General note | daily log |

## Contradiction Protocol

**Never silently overwrite.** When new info contradicts existing memory:

1. Note the contradiction explicitly
2. Mark old entry as `[SUPERSEDED: YYYY-MM-DD]`
3. Write new entry with date and source
4. If uncertain which is correct, flag both and ask user

## Correction Handling

Corrections are highest-priority writes:
1. Immediately update working memory
2. Propagate to relevant register
3. Add note to daily log: `CORRECTION: [what changed]`
4. If archived, update archive too

## Maintenance Cadences

**Immediate** (during session):
- Write to daily log first
- Update working memory if behavior-changing

**End of session**:
- Promote important daily log entries to registers
- Prune working memory if over limit
- Close open loops that were resolved

**Periodic** (every ~2 weeks):
- Review open-loops.md for stale items
- Promote patterns from daily logs to registers
- Archive completed project entries

**Quarterly**:
- Archive daily logs older than 90 days
- Review and prune registers for relevance
- Update SCHEMA.md if protocols have evolved

## Notes

- Working memory lives in CLAUDE.local.md (auto-loaded)
- Protocol lives in .claude/rules/total-recall.md (auto-loaded if configured)
- Use /recall-write, /recall-search, /recall-status, /recall-promote skills
