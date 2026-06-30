# House Copilot — Project Plan

> pmflow plan doc. Notes/dev workspace for the House Copilot project — **separate from the `houses/` database**.
> Living memory for the agent lives in `.agent-memory/MEMORY.md`; this plan is the human-facing roadmap.

## What this is
Building, first for May's own house hunt, a **24/7 personal AI realtor assistant** on top of the Funda tracker — it monitors listings, notifies, chats, learns taste, and acts (with approval: auto-submits Funda viewing requests). Product/business is emergent; solve May's own problem first.

## Current state (2026-06-22)
- Funda tracker live: poll → per-city caps (Eindhoven ≤450k; Tilburg/Best/Boxtel ≤350k) → Obsidian page per house → status workflow → Telegram + Gmail + Calendar sync.
- **Auto-applier live** (`funda_tracker/applier.py`): deterministic Playwright, DataDome-cleared, submits real Funda viewing requests. First live: Tinelstraat 186 → Kranen Makelaardij.
- ~150 tracked houses, 43 tests.

## Near-term roadmap
1. **Learned-preference filter** — talk to the bot about a viewing → it builds/refines an automated taste filter; continuously validate against May (garden / area / centrality + more).
2. **Move.nl automation** — next platform after Funda.
3. AI Dutch application letter; doc/deadline assistant.
4. (Later) broker call automation (voice, aspirational).

## Open decisions
- v1 scope: "find + get viewings" vs "full companion to offer/keys".
- Buy vs rent focus.
- Move repo `Documents/may/house` → `projects/house` (deferred — do next time).

## Infra / setup
- pmflow project: `house-copilot` (this config). Notes vault = `Documents/may/house/{daily,tasks,docs,meetings,sessions}`.
- OpenSpec initialized (`openspec/`, spec-driven) — use `/opsx:propose` for changes.
- Linear: team May33, project "House Copilot" (prefix HC) — **project still to be created**.
- House agent: `~/.claude/agents/funda-assistant.md` (Claude Code) + `HOUSE_AGENT.md` activation (Claude Desktop) + `.agent-memory/MEMORY.md`.
