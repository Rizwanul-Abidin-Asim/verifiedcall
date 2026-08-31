"use client";

import Vapi from "@vapi-ai/web";
import { useCallback, useEffect, useRef, useState } from "react";

import { getWebSession, reportWebCallStarted } from "@/lib/api";

/**
 * The intervention, taken in the browser instead of over the phone.
 *
 * This exists because a UAE mobile cannot be reached by any AI voice platform. Etisalat
 * and du are required to block VoIP-originated termination, and we confirmed it from
 * call records rather than assuming it: two calls, each ringing for exactly 55 seconds,
 * never billed, never delivered.
 *
 * The conversation itself is unchanged. Same script, same voice, same transcription,
 * same answer extraction, same hesitation timing, same resolution. Only the path the
 * audio takes is different, and the page says so rather than implying a phone rang.
 *
 * The assistant definition comes from the server, so the interrogation script stays in
 * version control next to its tests. The browser plays it; it does not compose it.
 */

type Stage = "offer" | "connecting" | "live" | "ended" | "error";

interface Line {
  role: string;
  text: string;
}

export function WebCall({
  transactionId,
  language,
}: {
  transactionId: string;
  language: string;
}) {
  const [stage, setStage] = useState<Stage>("offer");
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const vapi = useRef<Vapi | null>(null);

  // A live call must not outlive the page. Without this, navigating away leaves the
  // microphone open and the assistant talking to nobody.
  useEffect(() => {
    return () => {
      vapi.current?.stop();
      vapi.current = null;
    };
  }, []);

  const answer = useCallback(async () => {
    setStage("connecting");
    setError(null);
    setLines([]);

    try {
      const session = await getWebSession(transactionId);
      const client = new Vapi(session.public_key);
      vapi.current = client;

      client.on("call-start", () => setStage("live"));
      client.on("call-end", () => setStage("ended"));
      client.on("error", (err: unknown) => {
        setError(
          err instanceof Error ? err.message : "The call ended unexpectedly."
        );
        setStage("error");
      });
      client.on("message", (message: Record<string, unknown>) => {
        // Only final transcripts. Partial ones rewrite themselves mid-sentence and
        // make the panel flicker.
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
        throw new Error("The call started but returned no id, so we cannot track it.");
      }
      await reportWebCallStarted(transactionId, call.id);
    } catch (err) {
      // A refused microphone is the common case and deserves its own wording rather
      // than a stack trace the customer cannot act on.
      const message =
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "We need microphone access to speak with you. Allow it in your browser and try again."
          : err instanceof Error
            ? err.message
            : "We could not start the call.";
      setError(message);
      setStage("error");
      vapi.current?.stop();
      vapi.current = null;
    }
  }, [transactionId]);

  const hangUp = useCallback(() => {
    vapi.current?.stop();
    vapi.current = null;
    setStage("ended");
  }, []);

  return (
    <div className="card card-pad" style={{ marginTop: "1rem" }}>
      <p className="eyebrow">Security check</p>

      {stage === "offer" && (
        <>
          <h2 style={{ marginTop: ".25rem" }}>We need to speak with you</h2>
          <p>
            Before this payment goes through, we have three short questions. Answer
            them out loud and this takes about thirty seconds.
          </p>
          <button className="pay" onClick={answer}>
            Answer the call
          </button>
          <p className="hint">
            This runs in your browser rather than over the phone network. UAE mobile
            operators block internet-originated calls, so a phone would never ring.
            Everything else is the same call.
          </p>
        </>
      )}

      {stage === "connecting" && (
        <>
          <h2 style={{ marginTop: ".25rem" }}>
            <span className="spinner" /> Connecting…
          </h2>
          <p className="hint">
            Your browser will ask for the microphone. Allow it so we can hear your
            answers.
          </p>
        </>
      )}

      {stage === "live" && (
        <>
          <h2 style={{ marginTop: ".25rem" }}>Call in progress</h2>
          <p className="hint">
            Speaking {LANGUAGE_LABEL[language] ?? language}. You can answer out loud,
            or press 1 for yes and 2 for no.
          </p>
          <Transcript lines={lines} />
          <button className="pay" onClick={hangUp} style={{ marginTop: ".75rem" }}>
            End the call
          </button>
        </>
      )}

      {stage === "ended" && (
        <>
          <h2 style={{ marginTop: ".25rem" }}>Call finished</h2>
          <p className="hint">Working out what you told us…</p>
          <Transcript lines={lines} />
        </>
      )}

      {stage === "error" && (
        <>
          <h2 style={{ marginTop: ".25rem" }}>We could not complete the call</h2>
          <p>{error}</p>
          <p className="hint">
            Your payment stays held either way. Nothing has been charged.
          </p>
          <button className="pay" onClick={answer}>
            Try again
          </button>
        </>
      )}
    </div>
  );
}

const LANGUAGE_LABEL: Record<string, string> = {
  en: "English",
  ar: "Arabic",
  hi: "Hindi",
  ur: "Urdu",
};

function Transcript({ lines }: { lines: Line[] }) {
  if (lines.length === 0) return null;
  return (
    <div
      style={{
        marginTop: ".75rem",
        maxHeight: "12rem",
        overflowY: "auto",
        display: "grid",
        gap: ".35rem",
      }}
    >
      {lines.map((line, index) => (
        <p
          key={index}
          className="hint"
          style={{ margin: 0, fontWeight: line.role === "user" ? 600 : 400 }}
        >
          <strong>{line.role === "user" ? "You" : "VerifiedCall"}:</strong> {line.text}
        </p>
      ))}
    </div>
  );
}
