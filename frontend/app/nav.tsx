"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Nav() {
  const path = usePathname();
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
