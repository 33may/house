# Agent-Infrastructure Research — ready-to-run briefs

**Status:** Drafted 2026-06-22 in a tools-limited (Claude Desktop) context. **Run the 4 streams as parallel background agents from Claude Code** (Agent tool + web search available there). Each writes its own file in this folder; then synthesize into `SYNTHESIS.md`.

How to run in Claude Code: open this project, say *"use the house agent"*, then *"run the agent-infrastructure research briefs in docs/research/2026-06-22-agent-infrastructure/RESEARCH-BRIEFS.md as 4 parallel background general-purpose agents."*

Assumptions to confirm: "BMAT" → **BMAD-METHOD**; "Hermes agent" → research identifies it (likely Nous Research Hermes persona/identity lore, or a named personal-agent project).

---

## Stream A — Persistent memory & personality long-running agents
→ writes `A-persistent-memory-personality.md`

Research (2025-2026) best practices for a LONG-LASTING personal agent with persistent personality/identity + durable long-term memory across months.
1. Identify the **"Hermes agent"** the user means (Nous Research Hermes models + persona/identity lore; or a named personal-assistant project; or companion agents) and what makes it notable for personality + long-lasting adoption.
2. Memory infra: **Letta/MemGPT, mem0, Zep/Graphiti, Cognee**, RAG-over-history, summarization/consolidation — model, maturity, pros/cons each.
3. Memory best practices: episodic/semantic/procedural, retrieval, consolidation/forgetting, identity persistence, 24/7 context management.
4. Personality persistence: constitution/system-prompt vs persona-memory vs fine-tuning — what works.
5. Verdict: recommended memory + personality approach for a 24/7 personal house-hunting buddy.

## Stream B — Agentic harness / orchestration stacks
→ writes `B-agentic-harness-stacks.md`

Best tool stacks for a LONG-RUNNING, stateful, event-driven, tool-using personal agent (24/7; reacts to listings + emails; schedules a morning brief; computer-use; long-term memory; Telegram). Solo dev, Python preferred, LLM-extensible codebase.
1. Orchestration: LangGraph, OpenAI Agents SDK, **Claude Agent SDK**, CrewAI, AutoGen/AG2, Pydantic AI, LlamaIndex, Mastra (TS), Letta, Google ADK — good/bad/maturity/fit.
2. Durable execution: Temporal, Inngest, DBOS, Restate — why they matter for weeks-long agents.
3. The 24/7 event-driven architecture: schedulers + webhooks/polling + chat + persistent store.
4. Recommended concrete stack + trade-offs; note overlap with user's stack (Python, Playwright, Telegram, Codex/Claude).

## Stream C — Agent-driven development (the meta-product)
→ writes `C-agent-driven-development.md`

Agent-driven / spec-driven DEVELOPMENT frameworks: human designs features, agents build them, process documented as a reproducible, agent-executable framework — which the user wants to use AND sell as a "textbook"/service.
1. **BMAD-METHOD** — what it is, agents/roles, planning→story→dev cycle, strengths/weaknesses, adoption. Be accurate.
2. Spec-driven dev: GitHub **Spec-Kit**, AWS **Kiro**, the broader movement.
3. **Claude Code as a feature pipeline:** subagents, skills, slash commands, plan mode, hooks.
4. Documenting & productizing a dev process (templates/frameworks/courses/DFY) — real examples.
5. Recommendation: documented, agent-executable feature-creation pipeline a solo dev can use and sell; how to structure the docs so an agent executes them.

## Stream D — Computer-use / web-world interaction infra
→ writes `D-computer-use-web-infra.md`

Best infra + practices (2025-2026) for agents to act on the web; "model the ecosystem, let agents interact through it." User has a Playwright Funda applier (beats DataDome); roadmap Funda→Move.nl→calls.
1. Frameworks: browser-use, Stagehand (Browserbase), Skyvern, OpenAI Operator/computer-use, Claude computer use, Playwright-MCP — DOM vs vision vs hybrid, reliability, cost, anti-bot, maturity.
2. Deterministic (scripted Playwright) vs agentic (LLM-driven); best-practice hybrid (deterministic skills for known forms + LLM for bespoke asks).
3. **MCP (Model Context Protocol)**: wrapping a site/capability as a tool; the "environment agents act in" pattern; enables build-a-capability-on-the-fly.
4. Reliability & safety: anti-bot at scale, sandboxing, retries/verification, human approval gate on irreversible actions.
5. Recommendation: combine the user's Playwright deterministic skills + LLM computer-use + MCP into one "agents act through the web" architecture.

---
*Each stream: clear markdown, headers, inline source URLs, facts vs speculation flagged, 6-line summary returned.*
