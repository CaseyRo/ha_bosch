# Open Loops Register

> Auto-loaded every session.
> Contains active follow-ups, commitments, deadlines, and unresolved items.

<!-- Format:
## [Item Title]
- **Type**: follow-up | deadline | commitment | question
- **Due**: YYYY-MM-DD or "when X happens"
- **Context**:
- **Status**: open | in-progress | blocked
- *Added: YYYY-MM-DD*
-->

## PoinTTAPI Playwright automation — blocked by Bosch?
- **Type**: question
- **Due**: when revisiting automated OAuth token capture
- **Context**: Full Playwright automation of Bosch SingleKey ID login kept failing silently (password fill didn't register, login rejected). Switched to semi-automated mode (user logs in manually, script captures callback). Regional instance theory ruled out — user confirmed they can log in manually using the same `en-us` URL that HA generates. Root cause is almost certainly Playwright bot detection by Bosch SingleKey ID. Semi-automated script (user logs in manually, Playwright captures callback) is current approach — still needs to be confirmed working end-to-end.
- **Status**: open
- *Added: 2026-02-25* ^tr4a9c2e81b7
