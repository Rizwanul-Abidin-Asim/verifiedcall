"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Nav() {
  const path = usePathname();
  // The bank app is the customer's screen. A customer does not see a link to the
  // fraud desk, so the bar stays off that route; the demo drawer links across instead.
  if (path === "/checkout") return null;
  return (
    <header className="topbar">
      <div className="brand">
        Verified<span>Call</span>
      </div>
      <nav>
        <Link href="/checkout" data-active={path === "/checkout"}>
          Checkout
        </Link>
        <Link href="/dashboard" data-active={path === "/dashboard"}>
          Fraud ops
        </Link>
      </nav>
      <div className="spacer" />
    </header>
  );
}
