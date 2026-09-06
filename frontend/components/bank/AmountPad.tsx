"use client";

import { useEffect, useState } from "react";

/**
 * The amount, entered on a keypad that belongs to the app.
 *
 * The phone's own keyboard would cover half the screen and bring its own styling with
 * it. Banking apps draw their own pad for that reason, and it lets the amount sit
 * where the eye lands: large, in gold, and growing as you type.
 *
 * The value is kept as a plain digit string ("42000.5") so formatting is a display
 * concern and the backend receives an exact decimal.
 */

export function formatAmount(raw: string): string {
  if (!raw) return "0";
  const [whole, frac] = raw.split(".");
  const grouped = (whole || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac !== undefined ? `${grouped}.${frac}` : grouped;
}

export function AmountPad({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  const [pulse, setPulse] = useState(false);

  useEffect(() => {
    if (!pulse) return;
    const id = setTimeout(() => setPulse(false), 140);
    return () => clearTimeout(id);
  }, [pulse]);

  const press = (key: string) => {
    if (disabled) return;
    let next = value;
    if (key === "⌫") {
      next = value.slice(0, -1);
    } else if (key === ".") {
      if (!value.includes(".")) next = (value || "0") + ".";
    } else {
      const [, frac] = value.split(".");
      if (frac !== undefined && frac.length >= 2) return;      // fils, not thirds
      if (frac === undefined && value.replace(".", "").length >= 9) return;
      next = value === "0" ? key : value + key;
    }
    onChange(next);
    setPulse(true);
  };

  const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"];

  return (
    <div className="bk-amount">
      <div className={`bk-amount-display${pulse ? " is-pulse" : ""}`}>
        <span className="bk-amount-currency">AED</span>
        <span className="bk-amount-value">{formatAmount(value)}</span>
      </div>

      <div className="bk-pad" role="group" aria-label="Amount keypad">
        {keys.map((k) => (
          <button
            key={k}
            type="button"
            className={`bk-key${k === "⌫" ? " is-delete" : ""}`}
            onClick={() => press(k)}
            disabled={disabled}
            aria-label={k === "⌫" ? "Delete" : k}
          >
            {k}
          </button>
        ))}
      </div>
    </div>
  );
}
