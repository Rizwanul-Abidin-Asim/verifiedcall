# Telephony findings

What we learned trying to place a real automated call to a UAE mobile. Written the same
way as `camara-findings.md`: observed behaviour, with the evidence, not documentation
summaries. Every result here came from a live API.

**The headline: a UAE mobile cannot be reached by any AI voice platform.** That is a
regulatory boundary, not a configuration mistake, and we only established it by testing
each layer separately.

## The target

`+971504229551`, confirmed by Twilio's Lookup API rather than assumed:

```
valid       : true
country     : AE
parsed as   : +971504229551
line type   : mobile
carrier     : Etisalat
```

## What each platform did

| Platform | Result | Their words |
|---|---|---|
| **Vapi**, free number | Refused before dialling | `400 Couldn't start call. Free Vapi numbers do not support international calls.` |
| **Retell**, managed number | Refused before dialling | `Call country not supported: AE` |
| **ElevenLabs Agents** | Cannot be tried | Issues no numbers of its own; only Twilio, Exotel or a SIP trunk |
| **Twilio**, our own number | Accepted, never delivered | `no-answer` after 55s, twice, no error, never billed |

Three different failures, one underlying cause.

### Vapi

Free Vapi numbers are US national only. Their documentation states it in four places and
directs you to import your own number for international use, which we did. The imported
number was accepted and went `active`, so the restriction really is scoped to their free
numbers.

### Retell

Retell-managed numbers reach sixteen countries: US, India, Australia, Germany, Spain,
UK, Mexico, France, Japan, Canada, Italy, Indonesia, Philippines, Malaysia, Thailand,
plus US toll-free. The UAE is not among them, and the account's number reported
`phone_number_type: retell-twilio`, so their platform list governs and there is no
`allowed_outbound_country_list` to widen.

### ElevenLabs

Worth recording because it looks like the obvious alternative when ElevenLabs already
supplies the voice. It issues no phone numbers at all. `POST /v1/convai/phone-numbers`
accepts only `CreateTwilioPhoneNumberRequest`, `CreateExotelPhoneNumberRequest` or
`CreateSIPTrunkPhoneNumberRequestV2`. It does not avoid the Twilio step; it requires it.

Separately, its transcript timing is `time_in_call_secs`, an **integer**. Our hesitation
threshold is 3,500 ms and could not be expressed. `conversation_turn_metrics` holds
system latency, not the customer's pause. For most voice agents that is irrelevant; for
this one it removes the signal that distinguishes scenario 3 from a clean call.

### Twilio

Twilio got furthest and its behaviour is the interesting part.

- Twilio publishes an outbound rate to UAE mobiles of **$0.2995/min**, so it sells the
  call we wanted to make.
- Its UAE restriction runs the other way: you may not place outbound calls **from** a
  UAE Geographic Number. Calling **to** the UAE is a different case and is offered.
- Geo Permissions had the UAE already enabled under **Low Risk**. The High-Risk entry
  for the UAE covers only special-service and premium ranges, not ordinary mobile. The
  Low-Risk row showed `$0.299–$0.364`, matching the published mobile and landline rates
  exactly, which is what confirms it is the row covering a normal handset.
- The destination was a Verified Caller ID, so the trial restriction was satisfied.

Two calls were placed. Both behaved identically:

```
call 1   start 15:54:19Z   end 15:55:14Z   status no-answer   duration 0   price none
call 2   start 16:01:07Z   end 16:02:02Z   status no-answer   duration 0   price none
notifications: 0 on both
```

Exactly 55 seconds each, no error notifications, never billed. **The recipient's call
log showed nothing at all**, checked once retrospectively and once while watching the
screen during the call.

## Why

Etisalat and du are required to block VoIP-originated termination. Twilio, Vapi, Retell
and ElevenLabs are all VoIP-originated, so all of them are blocked at the same point.

That explains the 55 seconds. The terminating carrier returned ringback and dropped the
call, so from Twilio's side it genuinely looked like a ringing phone that nobody
answered. `no-answer` and "blocked after ringback" are indistinguishable from the API.

## The mistake worth recording

Our own `twilio_reach_test.py` originally reported `no-answer` as success, printing
"Twilio can reach this number". It does not prove that. Twilio reports `no-answer`
whenever it saw ringback and timed out, and a blocking carrier returns ringback for a
call it never delivers.

The script now reports `no-answer` as **inconclusive** and points at the recipient's
call log, which is the only place the difference is visible. Had we trusted the first
result we would have concluded the phone path worked and found out on stage.

## What this means for the project

Two things, and the second matters more.

**Operationally**, the live demo runs over the browser. `VOICE_CHANNEL=web` hands the
customer the same conversation through the page: same script, same voice, same
transcription, same answer extraction, same hesitation timing, same resolution. Only the
audio path differs, and both the database and the dashboard record which channel was
used rather than implying a phone rang.

**For the argument**, this is direct evidence for the premise. A bank cannot reliably
reach a UAE customer over internet telephony. Reaching customers on a mobile network,
and knowing anything about the state of that connection, requires the operator. That is
the case for CAMARA, and we did not have to argue it from principle.

## Reproducing

```bash
uv run python scripts/twilio_reach_test.py +971504229551   # carrier only, no AI layer
uv run python scripts/live_call_test.py   +971504229551    # the full path
```

The first isolates the carrier. Run it before blaming anything else.
