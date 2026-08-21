# Hackathon requirements — confirmed facts

Sources: GSMA MENA Ignite Inspiration Guide (24pp), GSMA MENA Resource & Tooling Guide
(9pp), HackerEarth challenge page, Nokia NaC public docs, VerifiedCall Project Brief v1.0.
Compiled 2026-08-12.

## Dates — TWO deadlines, not one

| Phase | Window | Deliverable |
|---|---|---|
| **Idea Phase** | 1 Jul – **23 Aug 2026** | A filled-in Inspiration Guide template + architecture diagram link. **Document, not code.** |
| **Prototype Phase** | **26 Aug – 9 Sep 2026** | Working codebase, public repo link mandatory. |
| Shortlist announced | 15 Sep 2026 | |
| Grand finale | week of 21 Sep 2026 | Finalists present live. |
| Final showcase | MWC Doha, 8–10 Nov 2026 | Travel + accommodation covered |

Team size 1–5. Eligibility: residents of Arab League states + Türkiye, 18+.
Prize pool: **GBP 10,000** (confirmed on the official deck).

## Our theme

**Theme 4 — Secure Fintech, Payments & Anti-Fraud Innovation**
GSMA pillar to cite: **Connectivity for Good**

### GSMA's own sample idea for Theme 4: "PayShield AI"

Real-time card-not-present fraud prevention agent. Its published stack:

- Agent orchestration: **Pydantic AI** ("type-safe, production-reliable decisioning agent")
- LLM: **Groq (Llama 3.3 70B)** ("low-latency reasoning suited to checkout-time decisions")
- Backend: n8n · Database: Neon serverless Postgres · Frontend implied Next.js
- APIs: **SIM Swap + Number Verification + Device Status** via Nokia NaC

**This validates our stack choice almost exactly** — we picked Pydantic AI and Groq
independently and GSMA's own exemplar uses both, for the same stated reasons.

**It also warns us:** every lazy Theme 4 entry will be a PayShield clone. Our separation is
the **voice intervention** and **APP fraud** framing — PayShield addresses card-not-present
/ OTP interception, which is *unauthorised* fraud. We do *authorised* push payment fraud,
which its signals cannot catch. Say that explicitly in the submission.

## Idea Phase submission template — exact sections

Every theme in the Inspiration Guide follows this identical structure. Fill it verbatim:

1. **Team Details** — team name, up to 5 members
2. **Integration Context** — the problem, then how the solution uses CAMARA via Nokia NaC
3. **Theme Relevance** — plus two boxed fields: **Project Type** and **GSMA Pillar**, then
   "How it supports this pillar"
4. **Solution Overview** — plus "How it helps solve the problem"
5. **Key Features & Benefits** — bulleted, ~6 items
6. **APIs & Technology** — two columns: "APIs Used & How They Help" | "Tech Stack /
   Frameworks", then "How the tech stack helps"
7. **Innovation Highlights** — ~4–5 bullets
8. **Impact Metrics** — 4–6 boxed metrics
9. **Methodology & Architecture** — "How the agents communicate" as numbered
   Component → Component steps, then "Architecture components" as boxes
10. **Diagram Link** — ⚠️ *"Please insert or attach the links to your architecture diagrams
    in this document for your idea submission."* Lucidchart / Figma / Miro / Excalidraw.

## Confirmed evaluation criteria (Phase 1 — Idea Evaluation)

Judged on the **Idea Capture Template + Pitch Deck** only. Four criteria:

1. **Relevance** — alignment with one of the 7 themes; relevance to regional challenges
2. **Impact** — potential to scale across MENA; clear business model or socio-economic value
3. **Innovation** — originality; addresses meaningful regional pain points
4. **Complexity & Implementation** — technical depth; clear design; effective use of Open
   Gateway/CAMARA APIs; feasible architecture; **AI agent design that intelligently
   orchestrates CAMARA APIs using only the approved Resource & Tooling Guide**

Nokia's own "what makes a strong submission" guidance adds: explain **why each API is
essential** and how they work together; **map the user journey** showing where each API
adds value before/during/after; show **combined API benefits** unachievable with one API
alone; position APIs as building blocks for a **secure, reliable experience**.

## Scoring levers stated in the materials

- Integrate **at least one** Nokia-hosted CAMARA API (mandatory)
- **Multiple** CAMARA APIs → additional points
- APIs spanning **different categories** → extra points
- **Agentic AI orchestrating multiple APIs** into automated decision journeys → bonus points

Judges' explicit tips from the Resource Guide, all of which our design already satisfies:

- "Treat each CAMARA API as a tool the agent decides when to call, not a button the user
  presses. That is what makes a solution 'agentic'."
- "Have a clear fallback when an API or model is rate-limited — agents that gracefully
  degrade demo much better."
- "Cache demo data. Live API calls fail at the worst moment."
- "Show the agent's reasoning trace on screen during the demo — judges love seeing the
  'thinking'."
- "Pick one focus area on day one and resist scope creep."

## Tooling — every vendor we chose is on the approved free-tier list

The Resource Guide names all of these with a Free or Freemium tier and no credit card
required: **Pydantic AI, Groq, Vapi, ElevenLabs, Deepgram, Next.js/Vercel, Nokia Network
as Code, Neon, Supabase, Upstash**. No approved-vendor list constrains us further.

Note Deepgram is listed with **$200 free credits**; ElevenLabs with a monthly character
allowance; Vapi with free credits. Enough for a demo, not for load testing.

## Nokia NaC auth — two layers, plan for it

1. Gateway API key on every request as an **`x-rapidapi-key`** header (platform is a
   white-labelled RapidAPI Enterprise Hub)
2. **OAuth2** on top — client-credentials (two-legged) for non-subscriber-scoped calls
3. **Three-legged OIDC authorisation code** for subscriber-scoped calls needing consent.
   **Number Verification requires this, and the device must be on mobile data, not WiFi.**

CAMARA commonalities version declared: 0.4.0. In-portal spec viewer is disabled — pull
OpenAPI specs from Nokia's public GitHub instead.

## Still unverified

- Official evaluation criteria **weightings** (rules tab is JS-rendered, did not load)
- Exact prize split
- Whether any MENA operator is live on Nokia NaC (none named; e& holds CAMARA certs for
  SIM Swap / Number Verification / Carrier Billing but through its own channel)
- Whether a registration cut-off exists separate from the idea phase close
