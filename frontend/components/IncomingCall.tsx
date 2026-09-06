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
      const permission = await navigator.mediaDevices.getUserMedia({ audio: true });
      permission.getTracks().forEach((track) => track.stop());

      const session = await getWebSession(transactionId);
      const client = new Vapi(session.public_key);
      vapi.current = client;

      client.on("call-start", () => setStage("live"));
      client.on("call-end", () => {
        setStage("ended");
        onFinished?.();
      });
      client.on("speech-start", () => setSpeaking(true));
      client.on("speech-end", () => setSpeaking(false));
      client.on("error", (err: unknown) => {
        setError(explain(err));
        setStage("error");
      });
      client.on("message", (message: Record<string, unknown>) => {
        if (
          message.type === "transcript" &&
          message.transcriptType === "final" &&
          typeof message.transcript === "string"
        ) {
          setLines((prev) => [
            ...prev,
            { role: String(message.role ?? "user"), text: message.transcript as string },
          ]);
        }
      });

      const call = await client.start(
        session.assistant as Parameters<Vapi["start"]>[0]
      );
      if (!call?.id) {
        throw new Error("The call connected but returned no id, so we cannot track it.");
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
  if (/did-not-receive-customer-audio|no audio/i.test(raw)) {
    return "We could not hear you, so the call ended. Check your microphone is not "
      + "muted, then tap Answer again.";
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
