# SYNTHESIS — Automated House-Hunting as a Business

**Date:** 2026-06-22
**Inputs:** A (tech foundation) · B (market) · C (process & legal) · D (monetization/GTM) — in this folder.
**Question:** Is "Tinder for houses / fully-automated NL house-buying" a real market, will it work, can it be sold as a summer side hustle, and what do we build on top?

---

## 1. The one-paragraph verdict

There is a **real, severe, well-documented pain** (≈350k home deficit, ~11 buyers/listing, ~73% sell over-asking, 77%-want vs 8%-believe starters) and **proven willingness to pay** (€1,495 Rentbird concierge, €2,999 homeup, €2-6k aankoopmakelaars). But it is **not greenfield**: **Walter Living** already owns "AI digital buying agent for expats" (~7,400 users, 264 buys/yr), and **every pure "Tinder for houses" swipe app internationally failed** — the swipe is a hook, never the business. The genuinely unfilled slice is the one thing we already built: **auto-submitted viewing requests + multi-platform discovery + matching, as cheap self-serve automation.** That slice has a **low SaaS price ceiling (€10-40/mo)** — the real margin is in **human-attached fees** (success fee, done-for-you, mortgage/aankoop referrals). **Recommendation: a narrow, expat/starter-focused, "assist — human approves" concierge, sold manual-first this summer, NOT a launched swipe SaaS.**

**Will it work as a summer side hustle?** Yes, modestly — **€500-€1,500 realistic in 3 months**, €2-4k upside if referral fees stack. Not a SaaS, a service.

---

## 2. The three things that decide everything

### 2a. The moat is real but narrow, and it's buy-side
Per Report A, today's Playwright auto-applier is the asset: a **logged-in, DataDome-cleared, deterministic write-path into Funda** that submits genuine viewing-request forms (verified live: Tinelstraat 186 → Kranen Makelaardij). Nobody else automates this on the buy side. **But** it is verified at *one user, low volume, headed Chrome, one manual login*. Multi-tenant / headless / multi-platform is the hard, unbuilt part — and the anti-bot maintenance treadmill never ends.

### 2b. The legal line is the design constraint, not a footnote
Report C's sharpest finding: **Funda's own anti-bot vendor case study explicitly names "scrape lead data → market to those buyers" as a litigation target** — that is precisely this business model's adjacency. Plus NVM database rights + live Akamai/Imperva captcha. **This kills the "centralized scraping SaaS" version.** The only defensible shape:
- Automation runs **client-side / in the user's own authenticated session** (a tool the user runs), not a central scraping service.
- **Human presses send** on every outbound action (neutralizes GDPR Art. 22, liability, "bot pretending to be human" all at once).
- **Notary** (mandatory) and **mortgage advice** (AFM/Wft licence) are owned by licensed partners — we never cross into them, we *refer* into them.

### 2c. The money is not in the automation, it's attached to it
Report B + D agree: pure automation = €10-40/mo, brutal churn (people cancel the day they're housed). The margin is in: **(1) success fee** (€150-400 rent / €500-1,500 buy), **(2) done-for-you setup** (€49-249), **(3) mortgage/aankoop referral fees** (€50-350/lead, ~€500 on conversion — "quietly the best ancillary stream"). Swipe UI and freemium are *later growth levers*, not summer money.

---

## 3. The strategy on a page

**Wedge:** "We hunt your home for you. Our bot watches the portals 24/7 and gets you viewings within minutes of a listing going live, with a tailored Dutch application — you approve, we send. Pay when you get the keys."

**Beachhead:** Expats relocating to **Eindhoven (ASML/Brainport/TU/e)** + Amsterdam — highest pain, time-pressured, relocation budgets, weak Dutch, will gladly pay. Found free via r/Netherlands, r/Eindhoven, expat Facebook groups, Holland Expat Center South.

**Model stack (summer):** done-for-you setup fee → pay-on-success → referral fees on top. SaaS is the *destination*, not the start.

**Differentiator vs Walter Living:** automation depth (true auto-apply, which they don't do) + price + speed. Don't fight them on human buying-agent judgment.

---

## 4. The buy-vs-rent fork (the main open decision)

This is the central tension across the reports, and it's the user's call:

| | **Buy side** (where the tool already works) | **Rent side** (where the summer cash is) |
|---|---|---|
| Our existing moat | ✅ Funda for-sale auto-applier is live | ❌ would need Pararius/Kamernet/Huurwoningen rebuilds |
| Urgency / speed-to-apply | Lower (weeks) | **Extreme** (minutes) — speed is THE feature |
| Willingness to pay | High (€500-1,500 success fee plausible) | Lower per-deal (€150-400) but **far more volume + faster cycle** |
| Competition | Walter Living, aankoopmakelaars | Rentbird/RentSlam/Uprent (crowded, cheap, scam-stigma) |
| Summer revenue speed | Slow (long cycle, few clients) | **Fast** (Sept student/expat intake = peak demand now) |

**The friction:** our *technical moat* is buy-side, but the *fastest money + sharpest urgency* is rent-side — and rent-side means rebuilding the applier for new portals (new anti-bot each).

---

## 5. What to build on top (ranked value ÷ effort)

1. **AI Dutch application/cover letter** (LLM, expat-aware) — low effort, proven seller, directly lifts win-rate. *Build first.*
2. **Multi-platform aggregation** (Pararius + Kamernet + Huurwoningen alongside Funda) — "coverage is the job"; each portal = its own ingestion + anti-bot.
3. **Document/deadline assistant** (payslips, employer statement, ID, deposit; bedenktijd & contingency reminders) — removes #1 expat friction, mostly templating.
4. **Heuristic match-scoring** (rules+weights, framed as "AI matching") — curated shortlist justifies premium; real ML comes later once swipes generate signal.
5. *Defer:* swipe UI (retention polish, not value), bid-strategy advisor (buy-side, needs data + legal care).
6. *Not a feature — a partnership:* mortgage/notary coordination = sign 1-2 referral partners, don't build software.

---

## 6. Risks, ranked

1. **Funda ToS / database-right / litigation (HIGH)** → never centralize scraping; user-session only; stay assistive.
2. **Anti-bot breakage at scale (HIGH, operational)** → client-side automation; no single server signature; expect maintenance forever.
3. **Trust / scam-stigma + commoditization (HIGH, GTM)** → narrow + human-faced + pay-on-success + visible proof fast.
4. **Wft unlicensed mortgage advice (MED-HIGH)** → hard boundary "budget estimate + logistics only"; licensed partner for advice.
5. **GDPR/AVG + tenant-side fee rules (MED)** → consent, data minimisation, no BSN, structure fees as tooling/concierge not brokerage. **[verify before charging]**

---

## 7. Recommended next step (for the architect to approve)

Run a **2-4 week manual concierge pilot** with 2-3 real expat clients in Eindhoven, using the existing buy-side tool by hand + a quick AI-letter add-on, pay-on-success. Goal: validate price and willingness to pay before building anything. Decide the buy-vs-rent fork (§4) based on which clients you can actually source first.

> Everything above is strategy synthesis from the four research reports; the buy-vs-rent fork and the pilot go/no-go are decisions for May.
