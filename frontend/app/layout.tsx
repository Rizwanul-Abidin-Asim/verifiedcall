import type { Metadata } from "next";
import "./globals.css";
import Nav from "./nav";

export const metadata: Metadata = {
  title: "VerifiedCall",
  description:
    "Intercepting authorised push payment fraud with CAMARA network signals and a multilingual voice call.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <Nav />
        {children}
      </body>
    </html>
  );
}
