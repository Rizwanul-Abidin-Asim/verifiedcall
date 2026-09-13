# 3-minute demo, five speakers

Rizwan drives the laptop throughout. Everyone else talks to what is on screen.
Spoken total: 2 minutes 59 at a normal pace.

## Before you go on
Rizwan: both servers up, checkout tab left, dashboard tab right. Headphones in, close
anything else using the mic. Answer the location prompt once so the slider is unlocked.
Run one throwaway payment to reset the rate limit. Leave it on the home screen.

---

## 0:00 AHMAD · 20s
*Title slide.*

> Someone calls you. They say they are from your bank, your account is compromised, move
> your money to a safe account now. And don't tell anyone, staff might be involved.
>
> So you do it. Your phone. Your login. Your money.
>
> Nothing was hacked. In the UAE this grew forty-three percent last year.

---

## 0:20 KHADER · 32s
*Checkout home screen.*
**Covers: all seven CAMARA APIs and what each is for.**

> Every check a bank runs asks the same thing. Is this really you. The answer is genuinely
> yes, so the payment goes through.
>
> We ask something different. Is somebody standing over you.
>
> Seven CAMARA APIs on Nokia Network as Code answer that. Call Forwarding and SIM Swap tell
> us whether her calls and her texts still reach her. Device Swap and Device Reachability
> tell us whether the app does. Location Verification tells us whether she is where the
> payment claims. Roaming Status and Location Retrieval fill in the rest.

---

## 0:52 RIZWAN · 31s
*Do it while you talk. Demo controls, "Phone is right here, line is clean", fill in headline
payment, Send, Review, slide.*
**Covers: where the AI is, where the deterministic engine is.**

> Forty-two thousand dirhams, to an account she has never paid, at two in the morning.
>
> The payment is held. Nothing has moved.
>
> The AI agent picks which of those seven checks are worth making. It chose three. On a
> routine payment to a regular payee it picks none.
>
> The AI never sets the score. A fixed weights table does that, and a fixed rule decides
> which door we reach her on. A bank has to reproduce both of those for a regulator.

*Phone rings. Stop talking.*

---

## 1:23 THE CALL · 22s
*Ryhan taps Answer. Greeting and question one play. He answers 1 · Yes.*

**Nobody speaks.** Let the room hear it.

---

## 1:45 RYHAN · 37s
*Rizwan silently stages the second scenario: Demo controls, "Her calls are diverted", fill
in headline payment, Send, Review, slide.*
**Covers: VoIP in production.**

> Those questions are about the scam's story, not the payment. He can coach her to deny
> being asked to pay. He cannot coach her to deny being told her money is at risk.
>
> One note on the number. Etisalat and du block VoIP calls from landing on a UAE handset,
> so this call runs inside the bank's own app. In production the bank dials from an
> operator-issued number, and the operator is already the one selling us these APIs.

*In-app sheet appears. No ringing.*

> Now the same payment, but her calls are forwarded. We do not call her. That call reaches
> the fraudster. So we use the app, and it arrives silently.

---

## 2:22 FADIL · 27s
*Dashboard, newest case, Reach tab, then Your call.*

> Every decision, explained. Three routes to her. The call is barred by call forwarding.
> The app is open, and that is the one we used. Text is barred by the SIM swap. A route
> nobody checked shows grey, never red.
>
> When all three are barred we contact nobody and page a human.
>
> And a person can overrule it, with a reason, recorded next to the agent's decision.

---

## 2:49 AHMAD · 10s

> Seven CAMARA APIs, all live. Under a cent a payment. Others ask if it is really you. We
> ask which door he does not control yet.

---

## The line each of you must not drop

- **Ahmad:** "Nothing was hacked."
- **Khader:** name all seven APIs and what they do.
- **Rizwan:** "The AI never sets the score."
- **Ryhan:** "That call reaches the fraudster."
- **Fadil:** "A route nobody checked shows grey, never red."

## If it breaks

**Says "deterministic fallback":** Rizwan, "the model was rate limited, the deterministic
engine finished it, still the right answer." Carry on.

**Call fails:** Ryhan says "mic conflict". Rizwan goes straight to the diverted scenario,
Ryhan gives his lines over that. Needs no microphone.

**Sandbox down:** Rizwan, "every network call is failing and we are still deciding from
cache, every cached answer labelled cached. We never show cached data as live."

**Running slow:** cut the call. Rizwan straight to the diverted scenario. Saves 30 seconds,
keeps the differentiator.
