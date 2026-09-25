import {
  usePrivy,
  useSessionSigners,
  type WalletWithMetadata,
} from "@privy-io/react-auth";
import { useEffect, useRef, useState } from "react";

// The agent's authorization key id (Privy dashboard → Wallet infrastructure → Authorization).
const SIGNER_ID = import.meta.env.VITE_PRIVY_SIGNER_ID as string;

// Central English catalog: JSX consumes message keys instead of embedding copy, so adding another
// locale does not require finding prose throughout the component tree.
const COPY = {
  loading: "Loading…",
  brand: "AGENTCORE · X402",
  loginTitle: "Agentic payments demo",
  loginDescription:
    "Sign in with email, delegate your Solana devnet wallet, then chat with an agent that pays for x402 tools on your behalf.",
  signIn: "Sign in with email",
  appTitle: "Agentic x402 payments",
  signOut: "Sign out",
  emptyChat: "Ask the agent to call a paid tool. It handles the x402 payment automatically.",
  paidPrefix: "paid",
  transactionLink: "tx ↗",
  reasoning: "reasoning",
  reasoningLive: "reasoning…",
  send: "Send",
  setup: "Setup",
  agentWallet: "Agent wallet · Solana devnet",
  fundPrefix: "Fund with devnet USDC at ",
  faucetHost: "faucet.circle.com",
  fundSuffix: " — gas is sponsored, no SOL needed.",
  delegationTitle: "Let the agent sign for you",
  delegated: "✓ Wallet delegated",
  delegate: "Delegate signing to the agent",
  copyToken: "Copy access token",
  newConversation: "New conversation",
  traceTitle: "x402 call trace",
  traceEmpty:
    "Send a prompt — every step the agent takes (tool call, 402 challenge, ProcessPayment, settlement) is recorded and listed here.",
  headerPrefix: "header: ",
} as const;

const QUICK_PROMPTS = [
  "What's the current price of bitcoin?",
  "What's the USD to Hong Kong dollar rate?",
  "How much is one ETH in Indonesian rupiah?",
];

// One recorded step from the agent (src/agentcore/runtime/demo_agent/trace.py). These are OBSERVED
// facts — the tool the model chose, the quoted price, the payment id, the settlement tx.
type AgentEvent = {
  kind: string;
  label: string;
  at: number;
  tool?: string;
  arguments?: Record<string, unknown>;
  result?: unknown;
  paid?: boolean;
  price?: string;
  network?: string;
  pay_to?: string;
  x402_version?: number;
  instrument_id?: string;
  payment_id?: string;
  header?: string;
  tx?: string;
};

const KIND_ICON: Record<string, string> = {
  prompt: "▸",
  discover: "☰",
  tool_call: "⚙",
  request: "↗",
  challenge: "402",
  wallet: "◈",
  payment: "✎",
  retry: "↻",
  settled: "⛓",
  tool_result: "↙",
  answer: "✓",
  result: "↙",
  error: "✕",
};

/** One compact chat line per turn: which tool ran, what it cost, and the settlement tx.
 *
 * The chat deliberately does NOT list every step — that belongs in the trace pane. Here we want
 * what a normal chat UI shows for a tool call: name, arguments, and the outcome.
 */
function summarize(events: AgentEvent[]) {
  const call = events.find((e) => e.kind === "tool_call");
  const paid = events.find((e) => e.kind === "challenge");
  const settled = events.find((e) => e.kind === "settled");
  const failed = events.find((e) => e.kind === "error");
  if (!call && !failed) return null;
  return {
    tool: call?.tool ?? "paid tool",
    args: call?.arguments,
    price: paid?.price,
    tx: settled?.tx,
    error: failed?.label,
  };
}

type Msg = { role: "user" | "agent"; text: string; events?: AgentEvent[]; thinking?: string };

export function App() {
  const { ready, authenticated, login, logout, getAccessToken, user } = usePrivy();
  const { addSessionSigners } = useSessionSigners();

  const [wallet, setWallet] = useState<string | null>(null);
  const [delegated, setDelegated] = useState<boolean | null>(null); // null = unknown/loading
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // Steps received so far on the live SSE stream, plus the label of the newest one (shown as the
  // single in-progress line in the chat).
  const [liveEvents, setLiveEvents] = useState<AgentEvent[]>([]);
  const [waitLabel, setWaitLabel] = useState("");
  // Answer text as it streams in, rendered in a live bubble before the turn is committed.
  const [liveText, setLiveText] = useState("");
  // Reasoning for the turn in flight, shown dimmed and separate from the answer.
  const [liveThinking, setLiveThinking] = useState("");
  // One conversation per browser session, so follow-up questions keep their context. The backend
  // re-derives the real session key from the verified token, so this value alone grants nothing.
  const [convId, setConvId] = useState<string>(() => {
    const k = "acp-conv";
    let v = sessionStorage.getItem(k);
    if (!v) {
      v = crypto.randomUUID();
      sessionStorage.setItem(k, v);
    }
    return v;
  });
  const [note, setNote] = useState("");
  const [statusError, setStatusError] = useState("");
  const chatEnd = useRef<HTMLDivElement>(null);

  const privyWallets = (user?.linkedAccounts ?? []).filter(
    (a): a is WalletWithMetadata =>
      a.type === "wallet" && (a as WalletWithMetadata).walletClientType === "privy",
  );

  // Real delegation state + the wallet the agent actually pays from, from the backend.
  async function refreshStatus() {
    try {
      const token = await getAccessToken();
      if (!token) {
        setStatusError("no Privy access token yet — try signing in again");
        return;
      }
      const r = await fetch("/api/status", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ privy_token: token }),
      });
      const j = await r.json();
      if (typeof j.delegated !== "boolean") {
        // Surface it: silently swallowing this left the badge stuck on "checking…" forever.
        setStatusError(j.error ? `status: ${j.error}` : `status HTTP ${r.status}`);
        return;
      }
      setStatusError("");
      if (j.wallet) setWallet(j.wallet);
      // Only mark delegated when the backend confirms it; never flip a known-true badge to a false
      // negative from a transient /status hiccup.
      if (j.delegated === true) setDelegated(true);
      else if (delegated !== true) setDelegated(false);
    } catch (e) {
      setStatusError(`status unreachable: ${String(e)}`);
    }
  }

  useEffect(() => {
    if (authenticated) refreshStatus();
  }, [authenticated]);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, liveEvents, liveText, liveThinking]);

  async function delegate() {
    if (privyWallets.length === 0) {
      setNote("Wallets still provisioning — try again in a moment.");
      return;
    }
    setNote("Delegating…");
    for (const w of privyWallets) {
      try {
        await addSessionSigners({ address: w.address, signers: [{ signerId: SIGNER_ID }] });
      } catch (e) {
        if (!String(e).includes("Duplicate signer")) {
          setNote(`Delegation failed on ${w.chainType}: ${String(e)}`);
          return;
        }
      }
    }
    setDelegated(true);
    setNote("Delegated — the agent can now pay from your wallet.");
    refreshStatus();
  }

  /** Stream one run: read the SSE body and render each frame the moment it arrives.
   *
   * `EventSource` cannot POST, so this reads the `fetch` body itself. Frames are `data: {json}\n\n`
   * exactly as the agent yielded them — a step (`type: "event"`) or the final answer.
   */
  async function send(prompt: string) {
    const text = prompt.trim();
    if (!text || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setBusy(true);
    setLiveEvents([]);
    setLiveText("");
    setLiveThinking("");
    setWaitLabel("Connecting to the agent…");
    const collected: AgentEvent[] = [];
    let answer = "";
    let thinking = "";
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("no access token");
      const r = await fetch("/api/invoke", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify({ prompt: text, privy_token: token, session_id: convId }),
      });
      if (!r.body) throw new Error(`no response body (HTTP ${r.status})`);
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are separated by a blank line; keep the trailing partial frame in the buffer.
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const line = frame.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue; // `: open` heartbeat
          let msg: { type?: string; text?: string } & AgentEvent;
          try {
            msg = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }
          if (msg.type === "event") {
            collected.push(msg);
            setLiveEvents([...collected]);
            setWaitLabel(msg.label);
          } else if (msg.type === "thinking") {
            thinking += msg.text ?? "";
            setLiveThinking(thinking);
          } else if (msg.type === "text") {
            // Partial prose: show it immediately instead of holding the whole answer back.
            answer += msg.text ?? "";
            setLiveText(answer);
          } else if (msg.type === "answer") {
            answer = msg.text || answer;
          } else if (msg.type === "error") {
            answer = `Error: ${msg.text ?? "unknown"}`;
          }
        }
      }
      setMessages((m) => [
        ...m,
        { role: "agent", text: answer || "(no answer)", events: collected, thinking },
      ]);
    } catch (e) {
      setMessages((m) => [...m, { role: "agent", text: `Error: ${String(e)}` }]);
    } finally {
      setBusy(false);
      setWaitLabel("");
      setLiveText("");
      setLiveThinking("");
    }
  }

  async function copyToken() {
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("no token");
      await navigator.clipboard.writeText(token);
      setNote("Access token copied to clipboard.");
    } catch (e) {
      setNote(`Could not copy token: ${String(e)}`);
    }
  }

  if (!ready) return <div style={S.center}>{COPY.loading}</div>;

  if (!authenticated) {
    return (
      <div style={S.center}>
        <div style={S.loginCard}>
          <div style={S.brand}>{COPY.brand}</div>
          <h1 style={S.h1}>{COPY.loginTitle}</h1>
          <p style={S.sub}>{COPY.loginDescription}</p>
          <button style={S.primary} onClick={login}>
            {COPY.signIn}
          </button>
        </div>
      </div>
    );
  }

  // The trace pane shows the run being revealed, else the newest completed turn's full trace.
  const lastTrace = [...messages].reverse().find((m) => m.events && m.events.length > 0)?.events;
  const traceEvents = liveEvents.length > 0 ? liveEvents : (lastTrace ?? []);

  const badge =
    delegated === true ? { t: "● Delegated", c: "#087443", b: "#d6f5e3" }
    : statusError ? { t: "! status unavailable", c: "#8a2020", b: "#f7d6d6" }
    : delegated === null ? { t: "checking…", c: "#8a6d00", b: "#fff4d6" }
    : { t: "○ Not delegated", c: "#8a6d00", b: "#fff4d6" };

  return (
    <div style={S.shell}>
      <header style={S.header}>
        <div>
          <span style={S.brand}>{COPY.brand}</span>
          <span style={S.headerTitle}>{COPY.appTitle}</span>
        </div>
        <div style={S.headerRight}>
          <span style={{ ...S.pill, color: badge.c, background: badge.b }}>{badge.t}</span>
          <button style={S.smallGhost} onClick={logout}>
            {COPY.signOut}
          </button>
        </div>
      </header>

      <div style={S.panes}>
        {/* LEFT: chat, full height */}
        <section style={S.chatPane}>
          <div style={S.chatLog}>
            {messages.length === 0 && (
              <div style={S.empty}>{COPY.emptyChat}</div>
            )}
            {messages.map((m, i) => {
              const call = m.events ? summarize(m.events) : null;
              return (
                <div key={i} style={S.turn}>
                  {call && (
                    <div style={S.toolCard}>
                      <span style={S.stepIcon}>{call.error ? "✕" : "⚙"}</span>
                      <div style={S.stepText}>
                        <span style={S.toolName}>{call.tool}</span>
                        {call.args && <code style={S.stepCode}>{JSON.stringify(call.args)}</code>}
                        {call.price && (
                          <span style={S.stepMeta}>{`${COPY.paidPrefix} ${call.price}`}</span>
                        )}
                        {call.tx && (
                          <a
                            style={S.stepTx}
                            href={`https://explorer.solana.com/tx/${call.tx}?cluster=devnet`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {COPY.transactionLink}
                          </a>
                        )}
                        {call.error && <span style={S.stepMeta}>{call.error}</span>}
                      </div>
                    </div>
                  )}
                  {m.thinking && (
                    <details style={S.think}>
                      <summary style={S.thinkHead}>{COPY.reasoning}</summary>
                      <div style={S.thinkBody}>{m.thinking}</div>
                    </details>
                  )}
                  <div style={m.role === "user" ? S.bubbleUser : S.bubbleAgent}>{m.text}</div>
                </div>
              );
            })}
            {busy && (
              <div style={S.turn}>
                {liveThinking && (
                  <div style={{ ...S.think, ...S.thinkLive }}>
                    <div style={S.thinkHead}>{COPY.reasoningLive}</div>
                    <div style={S.thinkBody}>{liveThinking}</div>
                  </div>
                )}
                {liveText ? (
                  <div style={S.bubbleAgent}>{liveText}</div>
                ) : (
                  <div style={S.toolCard}>
                    <span style={S.stepIcon}>◌</span>
                    <div style={S.stepText}>
                      <span style={S.stepMain}>{waitLabel || "Working…"}</span>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div ref={chatEnd} />
          </div>
          <div style={S.quickRow}>
            {QUICK_PROMPTS.map((p) => (
              <button key={p} style={S.quick} disabled={busy} onClick={() => send(p)}>
                {p.replace("Call the ", "").replace(" tool", "")}
              </button>
            ))}
          </div>
          <form
            style={S.inputRow}
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <input
              style={S.input}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Message the agent…"
              disabled={busy}
            />
            <button style={S.primary} type="submit" disabled={busy || !input.trim()}>
              {COPY.send}
            </button>
          </form>
        </section>

        {/* RIGHT: setup, then the x402 call flow */}
        <aside style={S.sidebar}>
          <section style={S.card}>
            <div style={S.cardTitle}>{COPY.setup}</div>
            <div style={S.setupStep}>
              <div style={S.stepNum}>1</div>
              <div style={S.stepBody}>
                <div style={S.stepLabel}>{COPY.agentWallet}</div>
                <code style={S.walletCode}>{wallet ?? "provisioning…"}</code>
                <div style={S.setupHint}>
                  {COPY.fundPrefix}
                  <a
                    href="https://faucet.circle.com"
                    target="_blank"
                    rel="noreferrer"
                    style={S.link}
                  >
                    {COPY.faucetHost}
                  </a>
                  {COPY.fundSuffix}
                </div>
              </div>
            </div>
            <div style={S.setupStep}>
              <div style={S.stepNum}>2</div>
              <div style={S.stepBody}>
                <div style={S.stepLabel}>{COPY.delegationTitle}</div>
                {delegated ? (
                  <div style={S.delegatedBig}>{COPY.delegated}</div>
                ) : (
                  <button style={S.cta} onClick={delegate}>
                    {COPY.delegate}
                  </button>
                )}
                <button style={S.ghostBtn} onClick={copyToken}>
                  {COPY.copyToken}
                </button>
                <button
                  style={S.ghostBtn}
                  onClick={() => {
                    const v = crypto.randomUUID();
                    sessionStorage.setItem("acp-conv", v);
                    setConvId(v);
                    setMessages([]);
                    setNote("Started a new conversation — the agent no longer remembers the old one.");
                  }}
                >
                  {COPY.newConversation}
                </button>
              </div>
            </div>
            {note && <div style={S.note}>{note}</div>}
            {statusError && <div style={S.errNote}>{statusError}</div>}
          </section>

          <section style={S.card}>
            <div style={S.cardTitle}>{COPY.traceTitle}</div>
            {traceEvents.length === 0 ? (
              <div style={S.setupHint}>{COPY.traceEmpty}</div>
            ) : (
              <ol style={S.flowList}>
                {traceEvents.map((ev, i) => (
                  <li key={i} style={S.flowItem}>
                    <span style={S.flowDot(ev.kind === "error" ? "error" : "done")}>
                      {KIND_ICON[ev.kind] ?? "•"}
                    </span>
                    <div style={{ minWidth: 0 }}>
                      <div style={S.flowLabel}>{ev.label}</div>
                      {ev.price && (
                        <div style={S.flowMeta}>
                          {ev.price} → {(ev.pay_to ?? "").slice(0, 8)}… (x402 v{ev.x402_version})
                        </div>
                      )}
                      {ev.arguments && (
                        <div style={S.flowMeta}>{JSON.stringify(ev.arguments)}</div>
                      )}
                      {ev.payment_id && <div style={S.flowMeta}>{ev.payment_id}</div>}
                      {ev.header && (
                        <div style={S.flowMeta}>{`${COPY.headerPrefix}${ev.header}`}</div>
                      )}
                      {ev.tx && (
                        <a
                          style={S.flowTx}
                          href={`https://explorer.solana.com/tx/${ev.tx}?cluster=devnet`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {ev.tx} ↗
                        </a>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

const ACCENT = "#5b5bd6";
const S = {
  center: {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "linear-gradient(160deg,#0f1020,#1b1c3a)",
    fontFamily: "system-ui,-apple-system,Segoe UI,sans-serif",
    color: "#666",
  },
  loginCard: {
    background: "#fff",
    borderRadius: 16,
    padding: 32,
    maxWidth: 420,
    boxShadow: "0 20px 60px rgba(0,0,0,.35)",
    color: "#1a1a2e",
  },
  shell: {
    height: "100vh",
    overflow: "hidden",
    background: "#0f1020",
    fontFamily: "system-ui,-apple-system,Segoe UI,sans-serif",
    color: "#e8e8f0",
    display: "flex",
    flexDirection: "column" as const,
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "14px 22px",
    borderBottom: "1px solid #23244a",
  },
  headerTitle: { fontSize: 22, fontWeight: 700, marginLeft: 12 },
  headerRight: { display: "flex", alignItems: "center", gap: 10 },
  brand: { fontSize: 12, letterSpacing: 2.5, color: "#8f8fe0", fontWeight: 700 },
  pill: { fontSize: 13, fontWeight: 600, padding: "4px 10px", borderRadius: 999 },
  sidebar: {
    flex: "0 0 380px",
    minWidth: 320,
    padding: 18,
    background: "#0c0d22",
    overflow: "auto",
    display: "flex",
    flexDirection: "column" as const,
    gap: 16,
  },
  card: {
    background: "#141530",
    border: "1px solid #23244a",
    borderRadius: 14,
    padding: 18,
  },
  cardTitle: {
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: 1.6,
    textTransform: "uppercase" as const,
    color: "#8f8fe0",
    marginBottom: 16,
  },
  setupStep: { display: "flex", gap: 12, marginBottom: 16 },
  stepNum: {
    flexShrink: 0,
    width: 24,
    height: 24,
    borderRadius: 999,
    background: "#1e1f42",
    color: "#a9a9e8",
    fontSize: 12,
    fontWeight: 700,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  stepBody: { display: "flex", flexDirection: "column" as const, gap: 7, minWidth: 0, flex: 1 },
  stepLabel: { fontSize: 14, fontWeight: 600, color: "#d8d8ee" },
  setupHint: { fontSize: 12.5, color: "#8e8eb0", lineHeight: 1.5 },
  cta: {
    width: "100%",
    padding: "12px 16px",
    fontSize: 14.5,
    fontWeight: 700,
    color: "#fff",
    background: ACCENT,
    border: "none",
    borderRadius: 10,
    cursor: "pointer",
    boxShadow: "0 6px 18px rgba(91,91,214,.4)",
  },
  ghostBtn: {
    width: "100%",
    padding: "10px 14px",
    fontSize: 13,
    fontWeight: 600,
    color: "#c8c8f0",
    background: "#1e1f42",
    border: "1px solid #2e2f5a",
    borderRadius: 10,
    cursor: "pointer",
  },
  delegatedBig: {
    fontSize: 14,
    fontWeight: 700,
    color: "#7fe0a0",
    background: "#12241a",
    border: "1px solid #1d4a30",
    borderRadius: 10,
    padding: "11px 16px",
    textAlign: "center" as const,
  },
  walletCode: {
    fontFamily: "ui-monospace,Menlo,monospace",
    color: "#c8c8f0",
    fontSize: 12.5,
    wordBreak: "break-all" as const,
    background: "#0f1020",
    border: "1px solid #23244a",
    borderRadius: 8,
    padding: "7px 9px",
  },
  note: {
    fontSize: 12.5,
    lineHeight: 1.5,
    color: "#c8f7d4",
    background: "#12241a",
    border: "1px solid #1d4a30",
    borderRadius: 8,
    padding: "8px 10px",
  },
  errNote: {
    fontSize: 12.5,
    lineHeight: 1.5,
    color: "#ffc9c9",
    background: "#2a1414",
    border: "1px solid #5a2020",
    borderRadius: 8,
    padding: "8px 10px",
    wordBreak: "break-word" as const,
  },
  link: { color: "#9a9af0" },
  panes: { display: "flex", flex: 1, minHeight: 0 },
  chatPane: {
    flex: 1,
    display: "flex",
    flexDirection: "column" as const,
    borderRight: "1px solid #23244a",
    minWidth: 0,
  },
  chatLog: { flex: 1, overflow: "auto", padding: 20, display: "flex", flexDirection: "column" as const, gap: 10 },
  empty: { color: "#6c6c90", fontSize: 15, margin: "auto", textAlign: "center" as const, maxWidth: 340 },
  bubbleUser: {
    alignSelf: "flex-end" as const,
    background: ACCENT,
    color: "#fff",
    padding: "10px 14px",
    borderRadius: "14px 14px 4px 14px",
    maxWidth: "80%",
    fontSize: 15,
    lineHeight: 1.55,
    whiteSpace: "pre-wrap" as const,
  },
  bubbleAgent: {
    alignSelf: "flex-start" as const,
    background: "#1e1f42",
    color: "#e0e0f5",
    padding: "10px 14px",
    borderRadius: "14px 14px 14px 4px",
    maxWidth: "85%",
    fontSize: 15,
    lineHeight: 1.6,
    whiteSpace: "pre-wrap" as const,
  },
  turn: { display: "flex", flexDirection: "column" as const, gap: 8 },
  think: {
    alignSelf: "flex-start" as const,
    maxWidth: "85%",
    background: "#101126",
    border: "1px dashed #2e2f5a",
    borderRadius: 10,
    padding: "8px 12px",
  },
  thinkLive: { opacity: 0.9 },
  thinkHead: {
    fontFamily: "ui-monospace,Menlo,monospace",
    fontSize: 11.5,
    letterSpacing: 1,
    textTransform: "uppercase" as const,
    color: "#8f8fe0",
    cursor: "pointer",
  },
  thinkBody: {
    fontSize: 13,
    lineHeight: 1.6,
    color: "#8e8eb0",
    fontStyle: "italic" as const,
    whiteSpace: "pre-wrap" as const,
    marginTop: 6,
  },
  toolCard: {
    alignSelf: "flex-start" as const,
    maxWidth: "85%",
    display: "flex",
    gap: 9,
    alignItems: "flex-start",
    padding: "9px 12px",
    background: "#12132b",
    border: "1px solid #23244a",
    borderRadius: 10,
  },
  toolName: { fontSize: 13.5, fontWeight: 600, color: "#c8c8f0" },
  stepRow: { display: "flex", gap: 9, alignItems: "flex-start" },
  stepIcon: {
    flexShrink: 0,
    width: 20,
    fontSize: 11,
    fontWeight: 700,
    color: "#8f8fe0",
    textAlign: "center" as const,
    lineHeight: "20px",
  },
  stepText: { display: "flex", flexWrap: "wrap" as const, gap: 8, alignItems: "baseline", minWidth: 0 },
  stepMain: { fontSize: 13.5, color: "#c4c4e4" },
  stepCode: {
    fontFamily: "ui-monospace,Menlo,monospace",
    fontSize: 12,
    color: "#9ad7b4",
    background: "#0f1020",
    borderRadius: 6,
    padding: "1px 6px",
    wordBreak: "break-all" as const,
  },
  stepMeta: { fontSize: 12, color: "#7f7fa8" },
  stepTx: {
    fontFamily: "ui-monospace,Menlo,monospace",
    fontSize: 12,
    color: "#7fe0a0",
    textDecoration: "none",
  },
  quickRow: { display: "flex", gap: 8, padding: "0 20px 10px", flexWrap: "wrap" as const },
  quick: {
    fontSize: 13,
    color: "#c8c8f0",
    background: "#1e1f42",
    border: "1px solid #2e2f5a",
    borderRadius: 999,
    padding: "6px 12px",
    cursor: "pointer",
  },
  inputRow: { display: "flex", gap: 8, padding: 16, borderTop: "1px solid #23244a" },
  input: {
    flex: 1,
    padding: "13px 16px",
    fontSize: 15,
    borderRadius: 10,
    border: "1px solid #2e2f5a",
    background: "#15162e",
    color: "#e8e8f0",
  },
  primary: {
    padding: "11px 18px",
    fontSize: 14,
    fontWeight: 600,
    color: "#fff",
    background: ACCENT,
    border: "none",
    borderRadius: 10,
    cursor: "pointer",
  },
  smallPrimary: {
    padding: "6px 12px",
    fontSize: 12,
    fontWeight: 600,
    color: "#fff",
    background: ACCENT,
    border: "none",
    borderRadius: 8,
    cursor: "pointer",
  },
  smallGhost: {
    padding: "6px 12px",
    fontSize: 12,
    color: "#a9a9c8",
    background: "transparent",
    border: "1px solid #2e2f5a",
    borderRadius: 8,
    cursor: "pointer",
  },
  h1: { fontSize: 24, margin: "8px 0 6px" },
  sub: { color: "#555", fontSize: 14, marginBottom: 22 },
  flowList: {
    listStyle: "none",
    padding: 0,
    margin: 0,
    display: "flex",
    flexDirection: "column" as const,
    gap: 14,
  },
  flowItem: { display: "flex", gap: 12, alignItems: "flex-start" },
  flowDot: (state: string) => ({
    flexShrink: 0,
    width: 26,
    height: 26,
    borderRadius: 999,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 11,
    fontWeight: 700,
    color: state === "idle" ? "#6c6c90" : "#fff",
    background:
      state === "error" ? "#7a2020"
      : state === "done" ? "#087443"
      : state === "run" ? ACCENT
      : "#1e1f42",
  }),
  flowLabel: { fontSize: 14, color: "#d0d0ea", lineHeight: 1.35 },
  flowMeta: {
    fontSize: 12,
    color: "#8383ad",
    marginTop: 3,
    wordBreak: "break-all" as const,
    fontFamily: "ui-monospace,Menlo,monospace",
  },
  flowTx: {
    display: "block",
    fontFamily: "ui-monospace,Menlo,monospace",
    fontSize: 11.5,
    color: "#7fe0a0",
    marginTop: 4,
    wordBreak: "break-all" as const,
    textDecoration: "none",
  },
} as const;
