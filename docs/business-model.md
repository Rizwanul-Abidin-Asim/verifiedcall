# Who pays for this, and what it costs to run

Written because our mentor pointed out the submission never said. Every figure below is
either measured from our own system, taken from a named public source, or flagged as an
assumption. Nothing here is a round number we liked the look of.

---

## What one payment costs us

### The agent — measured

Groq `openai/gpt-oss-120b`, two turns, `reasoning_effort=low`.

| | Tokens | Rate | Cost |
|---|---|---|---|
| Input (system prompt + 7 tool schemas + context, 2 turns) | ~4,200 | $0.15 / M | $0.00063 |
| Output (tool calls + written opinion) | ~350 | $0.60 / M | $0.00021 |
| | | **Total** | **~$0.0008** |

About **eight cents per thousand payments assessed**. Prompt caching roughly halves the
input half of that; we have not switched it on yet.

### The network APIs — honestly, we do not know yet

**CAMARA per-call pricing is not published.** Operators negotiate it per partner, and no
MENA operator has a public rate card. We asked; it is commercial.

So rather than invent a number, the model below treats the per-call price as `p` and shows
what happens across the plausible range. That is also the more useful thing to hand a bank,
because `p` is what *they* will negotiate.

What is public is that these APIs are already a real business: Telefónica has served 2.3
billion Number Verification calls, and SIM Swap passed 340 million calls in 2025, mostly
to banks doing exactly this kind of fraud work.

### The intervention

| Channel | Cost | When |
|---|---|---|
| In-app prompt | ~$0 | Preferred when the voice line is compromised |
| Voice call (Vapi all-in, 60–90s) | $0.10–$0.25 | Preferred when the line is clean |
| SMS | ~$0.01 | Last resort, carries no code |

---

## Why being selective is the whole business case

The agent decides which checks a payment deserves, and pulls nothing on a routine one.
That is usually presented as an elegance argument. It is really a cost argument.

For a bank running **10 million payments a year**, assuming 5% get network checks
(averaging 3 of the 7 APIs) and 0.2% end in an intervention:

| | Checks every payment, all 7 APIs | Our agent |
|---|---|---|
| CAMARA calls / year | 70,000,000 | 1,500,000 |
| At `p` = $0.03 | $2,100,000 | $45,000 |
| Agent (LLM) | — | $8,000 |
| Interventions (60% in-app, 40% voice) | — | $1,440 |
| **Total** | **$2,100,000** | **~$54,000** |

**About 40× cheaper**, and the difference is entirely "the agent decided this payment did
not need the network's opinion."

Across the range of `p`:

| `p` per CAMARA call | Our annual cost | Cost per payment |
|---|---|---|
| $0.01 | ~$24,000 | $0.0024 |
| $0.03 | ~$54,000 | $0.0054 |
| $0.10 | ~$159,000 | $0.016 |

### Break-even

The demo transaction is AED 42,000 (~$11,400), which is a realistic APP fraud amount.

| `p` | Scams we must stop per year to pay for ourselves |
|---|---|
| $0.01 | 3 |
| $0.03 | 5 |
| $0.10 | 14 |

**Out of ten million payments, stopping fewer than fifteen scams a year covers the entire
system** — at the most pessimistic API pricing we can imagine. That is the number to put
in front of a bank.

---

## Who buys it

**1. Retail banks — the primary buyer.** They carry the loss and, increasingly, the
regulatory duty to reimburse. 74 licensed financial institutions are connected to Aani,
the UAE's instant payments platform.

**2. Payment service providers and gateways.** They are the ones actually holding the
transaction at the moment we need to act, which makes integration natural. They sell
fraud prevention to banks as a differentiator rather than carrying the loss themselves.

**3. Mobile operators — the most interesting channel.** e&, du, STC and Ooredoo already
sell CAMARA APIs. We are a finished use case that consumes them: bundling us drives their
API volume and gives them a banking product to sell rather than a raw endpoint. This is
the fastest route to distribution in MENA, and it is why our redesign deliberately moved
toward the APIs operators have actually deployed.

**4. The scheme itself.** Al Etihad Payments could run this at the Aani level so every
participating bank inherits it. Longest sale, largest prize.

### Pricing

Usage-based, per payment assessed, with the CAMARA cost passed through at cost. A bank can
model it on one line, and it scales with the thing that creates the risk. A success fee on
prevented fraud is the obvious upsell once there is enough history to agree a baseline.

---

## Market size

Built bottom-up, and deliberately not flattering.

### Beachhead — UAE

APP scam losses in the UAE were **$8.3M in 2023**, grew **43% year on year in 2024**, and
are forecast to reach **$30.3M by 2028** (29.6% CAGR). By 2028 APP fraud is expected to be
roughly **90% of all UAE scam losses**.

Banks typically spend a fraction of prevented losses on the tooling that prevents them. At
10–15%, UAE alone is a **$3–5M annual market by 2028**.

That is small, and we should say so. The UAE is where we prove it, not where the business
is.

### The actual market

ACI Worldwide tracks APP scam losses across six real-time payment markets — the US, UK,
India, Brazil, Australia and the UAE — reaching **$7.6 billion by 2028**. At the same
10–15% of prevented losses, that is a **$380–760M annual market**, and it is growing at
roughly 30% a year because real-time payments are what make this fraud work.

### Why we can actually reach it

We are not building a network. The rails already exist, and we pulled the numbers from
GSMA's own deployment feed on 2026-09-12:

| API | Live deployments | Markets |
|---|---|---|
| SIM Swap | 213 | 45 |
| Number Verification | 157 | 37 |
| Device Swap | 21 | 11 |
| Call Forwarding Signal | 17 | 9 |
| Device Reachability Status | 6 | 6 |

SIM Swap is commercially live in **45 markets**. Anywhere it is deployed, we are an
integration rather than a build.

**The honest caveat:** Call Forwarding Signal — historically our highest-weighted
signal — is live in only 9 markets and **none of them are in MENA**. That is a real
limitation and it drove a real design change: the system now degrades to the APIs
operators have actually shipped, and says which ones it is missing rather than assuming
them. In the UAE today that means SIM Swap (du, e&) and Device Status (e&); in Qatar,
Number Verification and SIM Swap on both Ooredoo and Vodafone.

---

## Sources

- ACI Worldwide Scamscope, via [ffnews](https://ffnews.com/newsarticle/paytech/aci-worldwide-scamscope-estimates-43-yoy-growth-in-uae-app-scam-losses-for-2024-projects-us30-million-in-losses-by-2028/)
  and [ACI investor relations](https://investor.aciworldwide.com/news-releases/news-release-details/aci-worldwide-scamscope-projects-app-scam-losses-hit-76-billion)
- UAE APP scam growth — [TahawulTech](https://www.tahawultech.com/news/authorised-push-payment-app-scam-losses-in-uae-to-grow-43-yoy/)
- Aani adoption and institution count — [Al Etihad Payments](https://aep.ae/en/news-media/press-releasesarticles/aani-delivers-a-transformational-leap-in-the-uae-s-digital-payments-landscape-125-million-users-and-instant-transfers-in-3-seconds/)
- Groq pricing — [AI Pricing Guru](https://www.aipricing.guru/groq-pricing/)
- Vapi all-in per-minute cost — [CloudTalk](https://www.cloudtalk.io/blog/vapi-ai-pricing/)
- CAMARA API adoption volumes — [5G/6G Academy](https://www.5g6gacademy.com/learn/network-apis-camara)
- API deployment counts — GSMA Open Gateway map data feed, retrieved 2026-09-12
