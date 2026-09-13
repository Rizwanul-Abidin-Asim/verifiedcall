"use client";

import Vapi from "@vapi-ai/web";
import { useCallback, useEffect, useRef, useState } from "react";

import { getWebSession, reportWebCallStarted } from "@/lib/api";

/**
 * The security check, as the customer experiences it: a call inside the banking app.
 *
 * Two reasons it is in-app rather than on the phone network, and the second matters
 * more than the first.
 *
 * A UAE mobile cannot be reached by any AI voice platform, because Etisalat and du are
 * required to block VoIP-originated termination. We confirmed that from call records,
 * not documentation. `docs/telephony-findings.md` has them.
 *
 * More importantly, a phone call claiming to be your bank is exactly what the scammer
 * is already doing. Ringing the customer on the same channel as the attacker gives them
 * no way to tell us apart. A call inside the authenticated app cannot be spoofed, which
 * is why Android now verifies bank calls against the bank's own app and hangs up when
 * it cannot.
 *
 * This deliberately looks like a bank app, not like the phone's own dialler. Imitating
 * the system call screen would imply carrier integration we do not have.
 */

type Stage = "ringing" | "connecting" | "live" | "ended" | "error";

interface Line {
  role: string;
  text: string;
}

export function IncomingCall({
  transactionId,
  amountLabel,
  beneficiary,
  onFinished,
}: {
  transactionId: string;
  /** Already formatted for display, e.g. "42,000.00 AED". */
  amountLabel: string;
  beneficiary: string;
  onFinished?: () => void;
}) {
  const [stage, setStage] = useState<Stage>("ringing");
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [seconds, setSeconds] = useState(0);
  const [muted, setMuted] = useState(false);
  const [speaking, setSpeaking] = useState(false);

  const vapi = useRef<Vapi | null>(null);
  const ringtone = useRef<Ringtone | null>(null);
  const lastLine = useRef<HTMLDivElement | null>(null);

  // The assistant config, fetched while the phone is still ringing.
  //
  // Answering used to do three things in sequence: ask for the microphone, fetch this,
  // then open the WebRTC connection. The fetch is the only one that does not need the
  // customer's tap, so it happens up front and the tap is left with the two that do.
  const session = useRef<Awaited<ReturnType<typeof getWebSession>> | null>(null);
  const sessionError = useRef<unknown>(null);

  // Whether the call has finished, readable from inside the SDK's event handlers.
  // State would be stale in those closures, and this decides whether an incoming error
  // is a real failure or the noise of a finished call closing down.
  const finished = useRef(false);
  // Did the CUSTOMER ever say anything? Set only on a user transcript, never on the
  // assistant's own.
  //
  // This used to flip on any final transcript, including the assistant's greeting —
  // which meant every call was "far enough along" within two seconds, and a genuine
  // failure after that was silently relabelled as a normal hangup. That is how three
  // broken calls in a row showed the customer a tidy "ended" screen and told us
  // nothing. A call where only the assistant ever spoke did not go fine.
  const spoke = useRef(false);

  // Ring until answered. Generated rather than an audio file so there is no asset to
  // fetch and nothing to fail on a slow connection during a demo.
  useEffect(() => {
    if (stage !== "ringing") {
      ringtone.current?.stop();
      return;
    }
    const tone = new Ringtone();
    ringtone.current = tone;
    return () => tone.stop();
  }, [stage]);

  // Warm the session while it rings. A failure here is not surfaced yet — the customer
  // has not asked for anything — so it is stored and re-raised if they do answer.
  useEffect(() => {
    let cancelled = false;
    getWebSession(transactionId)
      .then((s) => { if (!cancelled) session.current = s; })
      .catch((err) => { if (!cancelled) sessionError.current = err; });
    return () => { cancelled = true; };
  }, [transactionId]);

  // A call takes over the screen, so the page behind it must not scroll underneath.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  // Call timer.
  useEffect(() => {
    if (stage !== "live") return;
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [stage]);

  // A live call must not outlive the screen, or the microphone stays open.
  useEffect(() => {
    return () => {
      vapi.current?.stop();
      vapi.current = null;
      ringtone.current?.stop();
    };
  }, []);

  useEffect(() => {
    lastLine.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [lines]);

  const answer = useCallback(async () => {
    ringtone.current?.stop();
    setStage("connecting");
    setError(null);

    try {
      // Claim the microphone first, before anything that awaits.
      //
      // A browser only grants the microphone while a user gesture is still active, and
      // on mobile that activation does not survive an await. Fetching the session first
      // spent it, so by the time the SDK asked for audio the tap had expired: the call
      // connected with no microphone track, the assistant heard silence, and Vapi ended
      // it with error-assistant-did-not-receive-customer-audio. It looked like a crash
      // and was really an ordering bug.
      //
      // Asking here, synchronously in the tap, grants permission for the origin. The
      // track is released immediately because the SDK opens its own; two handles on one
      // microphone is a good way to get silence on Android.
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error(
          "This browser will not share a microphone on an insecure page. Open the " +
          "https link rather than an IP address."
        );
      }
      // Echo cancellation asked for explicitly rather than left to the browser.
      //
      // On a laptop with no headphones the assistant's own voice comes out of the
      // speakers and straight back into the microphone. Deepgram then transcribes the
      // assistant as if it were the customer, which is how a call ends up with the
      // assistant answering itself, repeating a question it already asked, and
      // "uh"-flecked fragments of its own script appearing in the transcript.
      const permission = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      permission.getTracks().forEach((track) => track.stop());

      // Already fetched while ringing, in the common case.
      if (session.current === null && sessionError.current !== null) {
        throw sessionError.current;
      }
      const ready = session.current ?? (await getWebSession(transactionId));
      session.current = ready;

      const client = new Vapi(ready.public_key);
      vapi.current = client;

      client.on("call-start", () => setStage("live"));
      client.on("call-end", () => {
        finished.current = true;
        setStage("ended");
        onFinished?.();
      });
      client.on("speech-start", () => setSpeaking(true));
      client.on("speech-end", () => setSpeaking(false));
      client.on("error", (err: unknown) => {
        // A Vapi web call runs on Daily, and Daily reports the teardown of a call that
        // ENDED NORMALLY as "Meeting ended due to ejection: Meeting has ended". The
        // assistant asking its three questions and then hanging up, exactly as
        // instructed, produced that error — so a successful check was showing the
        // customer a failure screen and inviting them to call back.
        //
        // So an ejection only counts as a failure if it arrives before the call ever
        // got going. Once we have heard a transcript, or Vapi has already told us the
        // call ended, it is the room closing and nothing more.
        const raw = err instanceof Error ? err.message : String(err ?? "");
        const teardown = /ejection|meeting has ended|meeting ended/i.test(raw);

        // Only a call that actually got somewhere may treat an ejection as a normal
        // close. Anything earlier is a real failure and the customer should be told.
        if (teardown && (finished.current || spoke.current)) {
          finished.current = true;
          setStage((current) => (current === "error" ? current : "ended"));
          onFinished?.();
          return;
        }

        setError(explain(err));
        setStage("error");
      });
      client.on("message", (message: Record<string, unknown>) => {
        if (
          message.type === "transcript" &&
          message.transcriptType === "final" &&
          typeof message.transcript === "string"
        ) {
          if (String(message.role ?? "") === "user") spoke.current = true;
          setLines((prev) => [
            ...prev,
            { role: String(message.role ?? "user"), text: message.transcript as string },
          ]);
        }
      });

      const call = await client.start(
        ready.assistant as Parameters<Vapi["start"]>[0]
      );
      if (!call?.id) {
        // start() resolves without a call when the room never really opened — almost
        // always because something else already holds the microphone, so the browser
        // handed us a track with no audio on it. The old wording here said the call had
        // connected, which sent you looking in the wrong place entirely.
        throw new Error("no-call-id");
      }
      await reportWebCallStarted(transactionId, call.id);
    } catch (err) {
      setError(explain(err));
      setStage("error");
      vapi.current?.stop();
      vapi.current = null;
    }
  }, [transactionId, onFinished]);

  const hangUp = useCallback(() => {
    // Set before stop(), because stopping is what triggers the ejection error above.
    finished.current = true;
    vapi.current?.stop();
    vapi.current = null;
    setStage("ended");
    onFinished?.();
  }, [onFinished]);

  // The keypad the script promises. On a phone line these are real DTMF presses; in
  // the browser there is no dial pad, so a tap injects the word as the customer's own
  // turn. The assistant hears it exactly as a spoken answer and moves on, and the
  // transcript the extractor reads carries it. This is also the fallback the
  // multilingual story depends on: if the transcriber struggles with an accent, the
  // customer taps.
  const answerWith = useCallback((word: "yes" | "no") => {
    const client = vapi.current;
    if (!client) return;
    client.send({
      type: "add-message",
      message: { role: "user", content: word },
      triggerResponseEnabled: true,
    } as Parameters<Vapi["send"]>[0]);
    setLines((prev) => [...prev, { role: "user", text: word === "yes" ? "1 · Yes" : "2 · No" }]);
  }, []);

  const toggleMute = useCallback(() => {
    const client = vapi.current;
    if (!client) return;
    const next = !client.isMuted();
    client.setMuted(next);
    setMuted(next);
  }, []);

  return (
    <div className="callscreen">
      <div className="callscreen-inner">
        <p className="callscreen-app">
          <ShieldIcon /> VerifiedCall Bank
        </p>

        <div className="callscreen-who">
          <div className={`callscreen-avatar${stage === "ringing" ? " is-ringing" : ""}`}>
            <ShieldIcon large />
          </div>
          <h2>Security check</h2>
          <p className="callscreen-status">
            {stage === "ringing" && "Incoming call…"}
            {stage === "connecting" && "Connecting…"}
            {stage === "live" && formatClock(seconds)}
            {stage === "ended" && "Call ended"}
            {stage === "error" && "Call failed"}
          </p>
          {stage === "ringing" && (
            <p className="callscreen-about">
              About your payment of {amountLabel} to {beneficiary}
            </p>
          )}
        </div>

        {stage === "live" && (
          <div className={`callscreen-wave${speaking ? " is-speaking" : ""}`}>
            {[0, 1, 2, 3, 4].map((i) => (
              <span key={i} style={{ animationDelay: `${i * 0.12}s` }} />
            ))}
          </div>
        )}

        {(stage === "live" || stage === "ended") && lines.length > 0 && (
          <div className="callscreen-lines">
            {lines.map((line, i) => (
              <div
                key={i}
                ref={i === lines.length - 1 ? lastLine : null}
                className={`callscreen-line${line.role === "user" ? " is-you" : ""}`}
              >
                {line.text}
              </div>
            ))}
          </div>
        )}

        {stage === "error" && <p className="callscreen-error">{error}</p>}

        <div className="callscreen-actions">
          {stage === "ringing" && (
            <>
              <button className="callbtn is-answer" onClick={answer}>
                <PhoneIcon />
                <span>Answer</span>
              </button>
              <p className="callscreen-note">
                Your bank is calling inside the app, so this call cannot be faked.
              </p>
            </>
          )}

          {stage === "connecting" && <p className="callscreen-note">Allow the microphone…</p>}

          {stage === "live" && (
            <>
              <div className="callscreen-keys" role="group" aria-label="Answer with a key">
                <button className="callkey is-yes" onClick={() => answerWith("yes")}>
                  <span className="callkey-digit">1</span>
                  <span>Yes</span>
                </button>
                <button className="callkey is-no" onClick={() => answerWith("no")}>
                  <span className="callkey-digit">2</span>
                  <span>No</span>
                </button>
              </div>
              <div className="callscreen-row">
                <button className="callbtn is-mute" onClick={toggleMute}>
                  <span>{muted ? "Unmute" : "Mute"}</span>
                </button>
                <button className="callbtn is-end" onClick={hangUp}>
                  <PhoneIcon down />
                  <span>End</span>
                </button>
              </div>
            </>
          )}

          {stage === "error" && (
            <button className="callbtn is-answer" onClick={answer}>
              <PhoneIcon />
              <span>Try again</span>
            </button>
          )}

          {stage === "ended" && (
            <p className="callscreen-note">Checking what you told us…</p>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Turn a provider error into something the person holding the phone can act on.
 *
 * The raw messages are written for whoever wrote the SDK. "Meeting ended due to
 * ejection: Meeting has ended" is what the customer saw when the real problem was that
 * their microphone never opened, which is both fixable and their decision to make.
 */
function explain(err: unknown): string {
  if (err instanceof DOMException) {
    if (err.name === "NotAllowedError" || err.name === "SecurityError") {
      return "We need your microphone to hear your answers. Allow it in your browser, "
        + "then tap Answer again.";
    }
    if (err.name === "NotFoundError" || err.name === "OverconstrainedError") {
      return "No microphone was found on this device.";
    }
    if (err.name === "NotReadableError" || err.name === "AbortError") {
      return "Another app is using your microphone. Close it and tap Answer again.";
    }
  }

  const raw = err instanceof Error ? err.message : String(err ?? "");

  // Vapi ends a call it cannot hear. The wording below is the provider's; the
  // explanation is ours, because theirs does not say what to do about it.
  if (/no-call-id|did-not-receive-customer-audio|no audio/i.test(raw)) {
    return "We could not hear you, so the call stopped. Another browser tab or app is "
      + "probably holding your microphone — close it, check the mic is not muted, then "
      + "tap Answer again.";
  }
  if (/ejection|meeting has ended/i.test(raw)) {
    return "The call ended before we could finish. Tap Answer to try again.";
  }
  if (/network|failed to fetch|load failed/i.test(raw)) {
    return "We lost the connection. Check your internet and tap Answer again.";
  }
  return raw || "We could not connect the call.";
}


function formatClock(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function ShieldIcon({ large }: { large?: boolean }) {
  const size = large ? 34 : 15;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2 4 5.5v6c0 5 3.4 9.3 8 10.5 4.6-1.2 8-5.5 8-10.5v-6L12 2Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path
        d="m8.6 12.2 2.3 2.3 4.5-4.6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PhoneIcon({ down }: { down?: boolean }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      style={down ? { transform: "rotate(135deg)" } : undefined}
    >
      <path
        d="M6.6 3h3l1.5 3.8-2 1.4a12 12 0 0 0 5.7 5.7l1.4-2L20 13.4v3a2 2 0 0 1-2.2 2A16.5 16.5 0 0 1 4.6 5.2 2 2 0 0 1 6.6 3Z"
        fill="currentColor"
      />
    </svg>
  );
}

/**
 * A two-tone ring, built with the Web Audio API.
 *
 * No audio file to host, nothing to 404 on a slow connection, and it starts from the
 * user's tap so mobile autoplay rules are satisfied.
 */
class Ringtone {
  private ctx: AudioContext | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private stopped = false;

  constructor() {
    try {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      this.ctx = new Ctor();
      this.burst();
      this.timer = setInterval(() => this.burst(), 3000);
    } catch {
      // No audio is survivable. The screen still says "Incoming call".
      this.ctx = null;
    }
  }

  private burst() {
    const ctx = this.ctx;
    if (!ctx || this.stopped) return;
    // iOS suspends the context until a gesture; resuming is harmless elsewhere.
    void ctx.resume?.();
    [0, 0.42].forEach((offset) => {
      const at = ctx.currentTime + offset;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(480, at);
      gain.gain.setValueAtTime(0, at);
      gain.gain.linearRampToValueAtTime(0.12, at + 0.04);
      gain.gain.setValueAtTime(0.12, at + 0.3);
      gain.gain.linearRampToValueAtTime(0, at + 0.36);
      osc.connect(gain).connect(ctx.destination);
      osc.start(at);
      osc.stop(at + 0.4);
    });
  }

  stop() {
    this.stopped = true;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    void this.ctx?.close?.();
    this.ctx = null;
  }
}
