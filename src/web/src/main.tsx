// Buffer polyfill FIRST — Privy's Solana signing paths reference the Node `Buffer` global, which
// Vite does not provide in the browser (the cause of the earlier "Buffer is not defined" on
// delegation). Must run before any Privy import.
import { Buffer } from "buffer";

globalThis.Buffer = globalThis.Buffer ?? Buffer;

import { PrivyProvider } from "@privy-io/react-auth";
import { defaultSolanaRpcsPlugin } from "@privy-io/react-auth/solana";
import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

// Injected at build time by Vite from VITE_* env (see settings.py / projen build:web).
const appId = import.meta.env.VITE_PRIVY_APP_ID as string;

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <PrivyProvider
      appId={appId}
      config={{
        loginMethods: ["email"],
        // Create BOTH embedded wallets on login. The paid tools charge USDC on Solana devnet, so
        // the agent's payment instrument is a Solana wallet — the Solana wallet MUST exist and be
        // delegated. `defaultSolanaRpcsPlugin` wires Privy's Solana RPC support.
        plugins: [defaultSolanaRpcsPlugin()],
        // Do NOT auto-create wallets on login. The wallet the agent pays from is the AgentCore
        // payment instrument (provisioned by the backend and linked to this user); it shows up in
        // user.linkedAccounts. Creating a second wallet here caused the confusing two-wallet split
        // (console showed its own wallet while the agent paid from the instrument wallet).
        embeddedWallets: {
          ethereum: { createOnLogin: "off" },
          solana: { createOnLogin: "off" },
        },
        appearance: { walletChainType: "ethereum-and-solana" },
      }}
    >
      <App />
    </PrivyProvider>
  </React.StrictMode>,
);
