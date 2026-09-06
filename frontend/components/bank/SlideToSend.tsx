"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Slide to send.
 *
 * A transfer of this size should take one deliberate physical gesture, not a tap that
 * can happen by accident or under instruction. Banks that handle large transfers on
 * phones (Revolut, Liv, Monzo) confirm them with a hold or a slide for the same reason.
 *
 * It is also the moment this whole project is about. Someone being talked through a
 * scam has a scammer on the line saying "just confirm it". The slide is where a person
 * hesitates, and the pause is visible to them in a way a tap never is.
 *
 * Keyboard and assistive tech get the same action from Enter or Space, because a
 * gesture must never be the only way to do something.
 */
export function SlideToSend({
  label,
  disabled,
  busy,
  onSend,
}: {
  label: string;
  disabled?: boolean;
  busy?: boolean;
  onSend: () => void;
}) {
  const track = useRef<HTMLDivElement | null>(null);
  const thumb = useRef<HTMLButtonElement | null>(null);
  const dragging = useRef(false);
  const startX = useRef(0);
  const [offset, setOffset] = useState(0);
  const [done, setDone] = useState(false);
  const [settling, setSettling] = useState(false);

  const limit = useCallback(() => {
    const t = track.current;
    const h = thumb.current;
    if (!t || !h) return 0;
    return t.clientWidth - h.clientWidth - 8; // 4px inset each side
  }, []);

  const complete = useCallback(() => {
    setSettling(true);
    setOffset(limit());
    setDone(true);
    onSend();
  }, [limit, onSend]);

  const onPointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (disabled || busy || done) return;
    dragging.current = true;
    startX.current = e.clientX - offset;
    setSettling(false);
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (!dragging.current) return;
    const next = Math.min(Math.max(e.clientX - startX.current, 0), limit());
    setOffset(next);
  };

  const onPointerUp = () => {
    if (!dragging.current) return;
    dragging.current = false;
    // Most of the way counts. A slide that stops at 90% and springs back would feel
    // like the phone refusing, which is the wrong message for the person sending.
    if (offset >= limit() * 0.82) {
      complete();
    } else {
      setSettling(true);
      setOffset(0);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (disabled || busy || done) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      complete();
    }
  };

  // A new attempt after an error needs a fresh control.
  useEffect(() => {
    if (!busy && !disabled) {
      setDone(false);
      setOffset(0);
    }
  }, [busy, disabled]);

  const progress = limit() > 0 ? offset / limit() : 0;

  return (
    <div
      ref={track}
      className={`bk-slide${done ? " is-done" : ""}${disabled ? " is-disabled" : ""}`}
      style={{ "--progress": progress } as React.CSSProperties}
    >
      <span className="bk-slide-fill" aria-hidden="true" />
      <span className="bk-slide-label" aria-hidden="true">
        {busy ? "Sending…" : done ? "Sent" : label}
      </span>
      <button
        ref={thumb}
        type="button"
        className="bk-slide-thumb"
        style={{
          transform: `translateX(${offset}px)`,
          transition: settling ? "transform 0.35s cubic-bezier(.2,.9,.3,1.2)" : "none",
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
        disabled={disabled || busy}
        aria-label={`${label}. Slide right, or press Enter.`}
      >
        {busy ? (
          <span className="spinner" />
        ) : (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M5 12h13m0 0-5-5m5 5-5 5"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </button>
    </div>
  );
}
