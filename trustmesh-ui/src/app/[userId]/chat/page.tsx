"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type User, type QueryResult, type AgentAction, type Connection } from "@/lib/api";
import { useParams } from "next/navigation";
import { TrustBadge, DecisionBadge } from "@/components/TrustBadge";
import { Markdown } from "@/components/Markdown";

interface StreamingResult {
  id?: string;
  from_user_id: string;
  to_user_id: string;
  question: string;
  trust_level: string;
  shared_networks: string[];
  response: string;
  decision: string;
  agent_actions?: AgentAction[];
  latency_ms: number;
  created_at: string;
  isStreaming?: boolean;
  tools?: { name: string; input: Record<string, unknown> }[];
}

export default function ChatPage() {
  const { userId } = useParams<{ userId: string }>();
  const queryClient = useQueryClient();
  const [targetId, setTargetId] = useState("");
  const [question, setQuestion] = useState("");
  const [results, setResults] = useState<StreamingResult[]>([]);
  const [isListening, setIsListening] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);

  const { data: users } = useQuery({
    queryKey: ["users"],
    queryFn: api.listUsers,
  });
  const { data: history } = useQuery({
    queryKey: ["queries", userId],
    queryFn: () => api.listQueries(userId),
  });
  const { data: connections } = useQuery({
    queryKey: ["connections", userId],
    queryFn: () => api.listConnections(userId),
  });
  const { data: networks } = useQuery({
    queryKey: ["networks", userId],
    queryFn: () => api.listNetworks(userId),
  });

  const [queryMode, setQueryMode] = useState<"self" | "other">("self");
  const [sessionHistory, setSessionHistory] = useState<{ role: string; content: string }[]>([]);

  // Build combined reachable users: discoverable + connected + network members
  const allReachableUsers = (() => {
    const byId = new Map<string, User>();
    // 1. Discoverable users from listUsers API
    for (const u of users ?? []) {
      if (u.id !== userId) byId.set(u.id, u);
    }
    // 2. Connected peers (may not be discoverable)
    for (const c of connections ?? []) {
      if (c.peer && c.peer.id !== userId && !byId.has(c.peer.id)) {
        byId.set(c.peer.id, c.peer as User);
      }
    }
    // 3. Network members (may not be discoverable)
    for (const net of networks ?? []) {
      for (const m of net.members ?? []) {
        if (m.id !== userId && !byId.has(m.id)) {
          byId.set(m.id, m as User);
        }
      }
    }
    return Array.from(byId.values());
  })();
  const otherUsers = allReachableUsers;

  // Build a set of connected user IDs and a map of user -> shared network names
  const connectedIds = new Set(
    (connections ?? []).map((c: Connection) =>
      c.from_user_id === userId ? c.to_user_id : c.from_user_id
    )
  );
  const userNetworkMap = new Map<string, string[]>();
  for (const net of networks ?? []) {
    for (const member of net.members ?? []) {
      if (member.id !== userId) {
        const existing = userNetworkMap.get(member.id) ?? [];
        existing.push(net.name);
        userNetworkMap.set(member.id, existing);
      }
    }
  }

  const handleStreamQuery = useCallback(async () => {
    const target = queryMode === "self" ? userId : targetId;
    const q = question.trim();
    if (!q || (queryMode === "other" && !target)) return;

    setIsStreaming(true);
    const placeholderResult: StreamingResult = {
      from_user_id: userId,
      to_user_id: target,
      question: q,
      trust_level: "",
      shared_networks: [],
      response: "",
      decision: "allowed",
      latency_ms: 0,
      created_at: new Date().toISOString(),
      isStreaming: true,
      tools: [],
    };
    setResults((prev) => [placeholderResult, ...prev]);
    setQuestion("");

    // Add user message to session history for future context
    const historySnapshot = [...sessionHistory];
    setSessionHistory((prev) => [...prev, { role: "user", content: q }]);

    try {
      const res = await api.queryStream(userId, target, q, historySnapshot.length > 0 ? historySnapshot : undefined);
      if (!res.ok || !res.body) {
        throw new Error("Stream failed");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === "text") {
              setResults((prev) => {
                const updated = [...prev];
                if (updated[0]?.isStreaming) {
                  updated[0] = { ...updated[0], response: updated[0].response + event.data };
                }
                return updated;
              });
            } else if (event.type === "meta") {
              setResults((prev) => {
                const updated = [...prev];
                if (updated[0]?.isStreaming) {
                  updated[0] = {
                    ...updated[0],
                    trust_level: event.trust_level,
                    shared_networks: event.shared_networks,
                  };
                }
                return updated;
              });
            } else if (event.type === "tool") {
              setResults((prev) => {
                const updated = [...prev];
                if (updated[0]?.isStreaming) {
                  updated[0] = {
                    ...updated[0],
                    tools: [...(updated[0].tools || []), event.data],
                  };
                }
                return updated;
              });
            } else if (event.type === "done") {
              setResults((prev) => {
                const updated = [...prev];
                if (updated[0]?.isStreaming) {
                  // Add assistant response to session history for continuity
                  const responseText = updated[0].response;
                  if (responseText) {
                    setSessionHistory((h) => [...h, { role: "assistant", content: responseText }]);
                  }
                  updated[0] = {
                    ...updated[0],
                    id: event.id,
                    decision: event.decision,
                    latency_ms: event.latency_ms,
                    trust_level: event.trust_level,
                    shared_networks: event.shared_networks,
                    agent_actions: event.agent_actions,
                    isStreaming: false,
                  };
                }
                return updated;
              });
            } else if (event.type === "error") {
              setResults((prev) => {
                const updated = [...prev];
                if (updated[0]?.isStreaming) {
                  updated[0] = {
                    ...updated[0],
                    response: `Error: ${event.data}`,
                    decision: "denied",
                    isStreaming: false,
                  };
                }
                return updated;
              });
            }
          } catch {
            // Skip malformed events
          }
        }
      }
    } catch (err) {
      setResults((prev) => {
        const updated = [...prev];
        if (updated[0]?.isStreaming) {
          updated[0] = {
            ...updated[0],
            response: `Error: ${err instanceof Error ? err.message : "Connection failed"}`,
            decision: "denied",
            isStreaming: false,
          };
        }
        return updated;
      });
    } finally {
      setIsStreaming(false);
      queryClient.invalidateQueries({ queryKey: ["queries", userId] });
    }
  }, [queryMode, userId, targetId, question, queryClient, sessionHistory]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (queryMode === "other" && !targetId) return;
    if (!question.trim()) return;
    handleStreamQuery();
  };

  const [hasSpeechRecognition, setHasSpeechRecognition] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const win = window as any;
    setHasSpeechRecognition(!!(win.SpeechRecognition ?? win.webkitSpeechRecognition));
  }, []);

  // Auto-dismiss voice error after 5 seconds
  useEffect(() => {
    if (!voiceError) return;
    const t = setTimeout(() => setVoiceError(""), 5000);
    return () => clearTimeout(t);
  }, [voiceError]);

  const toggleVoice = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const win = window as any;
    const SpeechRecognition = win.SpeechRecognition ?? win.webkitSpeechRecognition;
    if (!SpeechRecognition) return;
    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognitionRef.current = recognition;
    setVoiceError("");

    let finalTranscript = "";
    let gotResults = false;
    // Auto-stop after 15 seconds of listening
    const autoStopTimer = setTimeout(() => {
      recognition.stop();
    }, 15000);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (event: any) => {
      gotResults = true;
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript;
        } else {
          interim += event.results[i][0].transcript;
        }
      }
      setQuestion(finalTranscript + interim);
    };
    recognition.onend = () => {
      clearTimeout(autoStopTimer);
      setIsListening(false);
      if (finalTranscript.trim()) {
        setQuestion(finalTranscript.trim());
      } else if (!gotResults) {
        setVoiceError("No speech detected — check your mic is unmuted and try again");
      }
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onerror = (e: any) => {
      clearTimeout(autoStopTimer);
      // no-speech is expected when user hasn't spoken yet in continuous mode — just restart
      if (e.error === "no-speech") return;
      console.warn("Speech recognition error:", e.error, e.message);
      setIsListening(false);
      const messages: Record<string, string> = {
        "not-allowed": "Microphone access denied — check browser permissions",
        "network": "Speech service unavailable — check your internet connection",
        "audio-capture": "No microphone found — check your audio settings",
        "aborted": "Voice input cancelled",
      };
      setVoiceError(messages[e.error] || `Voice input error: ${e.error}`);
    };
    try {
      recognition.start();
      setIsListening(true);
    } catch (err) {
      clearTimeout(autoStopTimer);
      console.warn("Failed to start speech recognition:", err);
      setIsListening(false);
      setVoiceError("Failed to start voice input — try refreshing the page");
    }
  }, [isListening]);

  const targetUser = otherUsers.find((u: User) => u.id === targetId);

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold mb-1">Agent Chat</h1>
          <p className="text-muted-foreground text-sm">
            Talk to your own agent or query another person&apos;s agent. Trust level determines what knowledge gets shared.
          </p>
        </div>
        {results.length > 0 && (
          <button
            onClick={() => {
              setResults([]);
              setSessionHistory([]);
            }}
            className="shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium text-muted-foreground hover:text-foreground bg-card-hover hover:bg-card border border-card-border transition-all"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
            </svg>
            New Chat
          </button>
        )}
      </div>

      {/* Query Form */}
      <form onSubmit={handleSubmit} className="bg-card border border-card-border rounded-2xl p-5 mb-8">
        {/* Mode Toggle */}
        <div className="flex gap-2 mb-5">
          <button
            type="button"
            onClick={() => setQueryMode("self")}
            className={`flex-1 py-2.5 px-4 rounded-xl text-sm font-medium transition-all ${
              queryMode === "self"
                ? "bg-accent/15 border-2 border-accent text-accent"
                : "bg-card-hover border-2 border-transparent text-muted-foreground hover:border-card-border"
            }`}
          >
            <span className="flex items-center justify-center gap-2">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
              </svg>
              Ask My Agent
            </span>
          </button>
          <button
            type="button"
            onClick={() => setQueryMode("other")}
            className={`flex-1 py-2.5 px-4 rounded-xl text-sm font-medium transition-all ${
              queryMode === "other"
                ? "bg-accent/15 border-2 border-accent text-accent"
                : "bg-card-hover border-2 border-transparent text-muted-foreground hover:border-card-border"
            }`}
          >
            <span className="flex items-center justify-center gap-2">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
                <path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
              </svg>
              Ask Another Agent
            </span>
          </button>
        </div>

        {/* Target Selection (only for "other" mode) */}
        {queryMode === "other" && (
          <div className="mb-5">
            <label className="block text-sm font-medium text-muted-foreground mb-2">Whose agent do you want to ask?</label>
            <select
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              className="w-full bg-background border border-card-border rounded-xl px-4 py-3 text-sm appearance-none cursor-pointer"
            >
              <option value="">Select an agent to query...</option>
              {(() => {
                const connected = otherUsers.filter((u: User) => connectedIds.has(u.id) && u.user_type === "person");
                const orgs = otherUsers.filter((u: User) => u.user_type === "organization" || u.user_type === "government");
                const others = otherUsers.filter((u: User) => !connectedIds.has(u.id) && u.user_type === "person");
                return (
                  <>
                    {connected.length > 0 && (
                      <optgroup label="Connected">
                        {connected.map((u: User) => (
                          <option key={u.id} value={u.id}>
                            {u.display_name} (@{u.username})
                            {userNetworkMap.get(u.id)?.length ? ` — ${userNetworkMap.get(u.id)!.join(", ")}` : ""}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    {orgs.length > 0 && (
                      <optgroup label="Organizations">
                        {orgs.map((u: User) => (
                          <option key={u.id} value={u.id}>
                            {u.display_name} (@{u.username})
                            {userNetworkMap.get(u.id)?.length ? ` — ${userNetworkMap.get(u.id)!.join(", ")}` : ""}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    {others.length > 0 && (
                      <optgroup label="Other People">
                        {others.map((u: User) => (
                          <option key={u.id} value={u.id}>{u.display_name} (@{u.username})</option>
                        ))}
                      </optgroup>
                    )}
                  </>
                );
              })()}
            </select>
          </div>
        )}

        {/* Self query info banner */}
        {queryMode === "self" && (
          <div className="mb-5 p-3 bg-accent/5 border border-accent/15 rounded-xl">
            <p className="text-xs text-muted-foreground">
              <span className="font-medium text-accent">Private access</span> — your agent sees all your capsules and can <span className="font-medium text-accent">save new knowledge</span> to your vault. Try: &ldquo;Remember that Peter is allergic to shellfish&rdquo; or &ldquo;Save that my dentist appointment is March 5th&rdquo;
            </p>
          </div>
        )}

        {/* Question Input with @-mention */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-muted-foreground mb-2">Your question</label>
          <div className="relative">
            <MentionInput
              value={question}
              onChange={setQuestion}
              onSubmit={() => {
                if (queryMode === "other" && !targetId) return;
                if (!question.trim()) return;
                handleStreamQuery();
              }}
              users={users ?? []}
              connectedIds={connectedIds}
              userNetworkMap={userNetworkMap}
              currentUserId={userId}
              placeholder={
                queryMode === "self"
                  ? `Ask your agent about your knowledge...`
                  : targetUser
                    ? `Ask ${targetUser.display_name}'s agent...`
                    : "Select a person above..."
              }
              disabled={(queryMode === "other" && !targetId)}
            />
            <div className="absolute right-1.5 top-1.5 flex items-center gap-1">
              <button
                type="button"
                onClick={toggleVoice}
                disabled={!hasSpeechRecognition}
                className={`p-2 rounded-lg transition-all ${
                  !hasSpeechRecognition
                    ? "opacity-30 cursor-not-allowed text-muted-foreground"
                    : isListening
                      ? "bg-red-500/20 text-red-400 animate-pulse"
                      : "bg-card-hover text-muted-foreground hover:text-foreground"
                }`}
                title={!hasSpeechRecognition ? "Voice input not supported in this browser (try Chrome)" : isListening ? "Stop listening" : "Voice input"}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                  <line x1="12" y1="19" x2="12" y2="23"/>
                  <line x1="8" y1="23" x2="16" y2="23"/>
                </svg>
              </button>
              <button
                type="submit"
                disabled={(queryMode === "other" && !targetId) || !question.trim() || isStreaming}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-accent-fg text-sm font-medium rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                {isStreaming ? (
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                ) : "Send"}
              </button>
            </div>
          </div>
        </div>

        {/* Voice status/error */}
        {isListening && (
          <p className="text-xs text-red-400 flex items-center gap-1.5 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-red-400 inline-block" />
            Listening... speak now
          </p>
        )}
        {voiceError && !isListening && (
          <p className="text-xs text-amber-400 flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            {voiceError}
          </p>
        )}

        {/* Trust Context Hint */}
        {(queryMode === "self" || targetUser) && (
          <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>
            {queryMode === "self"
              ? "Your agent has full access to all your capsules including private ones."
              : `Your trust level with ${targetUser?.display_name} determines which capsules their agent can access.`
            }
          </p>
        )}
      </form>

      {/* Results */}
      {results.length > 0 && (
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-muted-foreground mb-3">This Session</h2>
          <div className="space-y-3">
            {results.map((r, idx) => (
              <QueryResultCard key={r.id || `streaming-${idx}`} result={r} users={users ?? []} currentUserId={userId} />
            ))}
          </div>
        </div>
      )}

      {/* History */}
      {history && history.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-muted-foreground mb-3">Query History</h2>
          <div className="space-y-3">
            {history.map((r: QueryResult) => (
              <QueryResultCard key={r.id} result={r} users={users ?? []} currentUserId={userId} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// @-Mention Input Component
// ═══════════════════════════════════════════════════════════════

function MentionInput({
  value,
  onChange,
  onSubmit,
  users,
  connectedIds,
  userNetworkMap,
  currentUserId,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (val: string) => void;
  onSubmit: () => void;
  users: User[];
  connectedIds: Set<string>;
  userNetworkMap: Map<string, string[]>;
  currentUserId: string;
  placeholder: string;
  disabled: boolean;
}) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [showMentions, setShowMentions] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionStart, setMentionStart] = useState(-1);
  const [selectedIdx, setSelectedIdx] = useState(0);

  const filteredUsers = users
    .filter((u) => {
      if (u.id === currentUserId) return false; // Don't show yourself
      if (u.username?.startsWith("remote:")) return false; // Exclude ghost users
      if (!mentionQuery) return true;
      const q = mentionQuery.toLowerCase();
      return (
        u.username.toLowerCase().includes(q) ||
        u.display_name.toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      // Connected users first, then network members, then others
      const aConnected = connectedIds.has(a.id) ? 0 : 1;
      const bConnected = connectedIds.has(b.id) ? 0 : 1;
      if (aConnected !== bConnected) return aConnected - bConnected;
      // People before orgs
      const aIsOrg = a.user_type !== "person" ? 1 : 0;
      const bIsOrg = b.user_type !== "person" ? 1 : 0;
      if (aIsOrg !== bIsOrg) return aIsOrg - bIsOrg;
      return a.display_name.localeCompare(b.display_name);
    });

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const val = e.target.value;
      const cursor = e.target.selectionStart ?? val.length;
      onChange(val);

      // Auto-resize textarea
      const textarea = e.target;
      textarea.style.height = "auto";
      textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";

      // Find the @ trigger: look backwards from cursor for @
      const textBeforeCursor = val.slice(0, cursor);
      const atIdx = textBeforeCursor.lastIndexOf("@");

      if (atIdx >= 0) {
        // Make sure @ is at start or preceded by a space
        const charBefore = atIdx > 0 ? val[atIdx - 1] : " ";
        const textAfterAt = textBeforeCursor.slice(atIdx + 1);
        // No spaces in the mention query (means they've moved on)
        if (charBefore === " " || atIdx === 0) {
          if (!textAfterAt.includes(" ")) {
            setShowMentions(true);
            setMentionQuery(textAfterAt);
            setMentionStart(atIdx);
            setSelectedIdx(0);
            return;
          }
        }
      }
      setShowMentions(false);
    },
    [onChange]
  );

  const insertMention = useCallback(
    (user: User) => {
      const before = value.slice(0, mentionStart);
      const afterCursor = value.slice(
        mentionStart + 1 + mentionQuery.length
      );
      const newVal = `${before}@${user.display_name} ${afterCursor}`;
      onChange(newVal);
      setShowMentions(false);
      setMentionQuery("");
      // Re-focus input
      setTimeout(() => inputRef.current?.focus(), 0);
    },
    [value, mentionStart, mentionQuery, onChange]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (showMentions && filteredUsers.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSelectedIdx((i) => Math.min(i + 1, filteredUsers.length - 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSelectedIdx((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === "Tab" || e.key === "Enter") {
          e.preventDefault();
          insertMention(filteredUsers[selectedIdx]);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setShowMentions(false);
          return;
        }
      }
      // Enter → submit, Shift+Enter → newline
      if (e.key === "Enter" && !e.shiftKey && !showMentions) {
        e.preventDefault();
        onSubmit();
      }
    },
    [showMentions, filteredUsers, selectedIdx, insertMention, onSubmit]
  );

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setShowMentions(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div className="relative">
      <textarea
        ref={inputRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={1}
        className="w-full bg-background border border-card-border rounded-xl px-4 py-3 text-sm pr-32 placeholder:text-muted-foreground resize-none overflow-y-auto"
        style={{ maxHeight: 160 }}
        disabled={disabled}
      />

      {/* @-mention autocomplete dropdown */}
      {showMentions && filteredUsers.length > 0 && (
        <div
          ref={dropdownRef}
          className="absolute left-0 right-24 bottom-full mb-1 bg-card border border-card-border rounded-xl shadow-lg overflow-hidden z-50"
        >
          <div className="px-3 py-1.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wider border-b border-card-border bg-card-hover/50">
            Mention someone
          </div>
          {filteredUsers.slice(0, 6).map((u, i) => {
            const isConnected = connectedIds.has(u.id);
            const sharedNets = userNetworkMap.get(u.id) ?? [];
            return (
              <button
                key={u.id}
                type="button"
                onClick={() => insertMention(u)}
                className={`w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors ${
                  i === selectedIdx
                    ? "bg-accent/10 text-accent"
                    : "hover:bg-card-hover text-foreground"
                }`}
              >
                <div className="relative">
                  <div
                    className={`w-6 h-6 rounded-md flex items-center justify-center text-white font-bold text-[10px] ${
                      isConnected ? "bg-accent" : "bg-muted-foreground/60"
                    }`}
                  >
                    {u.display_name[0]}
                  </div>
                  {isConnected && (
                    <div className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 bg-green-500 rounded-full border border-card" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className={`text-sm font-medium ${!isConnected ? "text-muted-foreground" : ""}`}>
                      {u.display_name}
                    </span>
                    <span className="text-xs text-muted-foreground">@{u.username}</span>
                    {u.user_type === "organization" && (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 font-semibold uppercase">Org</span>
                    )}
                    {u.user_type === "government" && (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-semibold uppercase">Gov</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1 mt-0.5">
                    {isConnected ? (
                      sharedNets.length > 0 ? (
                        sharedNets.map((net) => (
                          <span key={net} className="text-[10px] px-1.5 py-0.5 rounded bg-accent/10 text-accent/80">
                            {net}
                          </span>
                        ))
                      ) : (
                        <span className="text-[10px] text-green-400">Connected</span>
                      )
                    ) : (
                      <span className="text-[10px] text-muted-foreground/60">Not connected</span>
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}


function QueryResultCard({
  result,
  users,
  currentUserId,
}: {
  result: StreamingResult | QueryResult;
  users: User[];
  currentUserId: string;
}) {
  const fromUser = users.find((u) => u.id === result.from_user_id);
  const toUser = users.find((u) => u.id === result.to_user_id);
  const isSent = result.from_user_id === currentUserId;
  const streaming = "isStreaming" in result && result.isStreaming;
  const tools = "tools" in result ? result.tools : undefined;

  // TTS state
  const [isSpeaking, setIsSpeaking] = useState(false);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => {
    return () => {
      if (utteranceRef.current) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  const toggleTTS = useCallback(() => {
    if (isSpeaking) {
      window.speechSynthesis.cancel();
      setIsSpeaking(false);
      return;
    }
    const text = result.response;
    if (!text) return;
    // Strip markdown formatting for clean speech
    const clean = text
      .replace(/#{1,6}\s/g, "")
      .replace(/\*\*(.*?)\*\*/g, "$1")
      .replace(/\*(.*?)\*/g, "$1")
      .replace(/```[\s\S]*?```/g, "")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/[-*+]\s/g, "")
      .replace(/\n{2,}/g, ". ")
      .replace(/\n/g, " ")
      .trim();
    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.rate = 1.05;
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    utteranceRef.current = utterance;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    setIsSpeaking(true);
  }, [isSpeaking, result.response]);

  return (
    <div className={`bg-card border rounded-2xl overflow-hidden ${streaming ? "border-accent/30" : "border-card-border"}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-card-border bg-card-hover/30">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">
            {isSent ? "You" : fromUser?.display_name}
          </span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
          </svg>
          <span className="font-semibold text-foreground">
            {isSent ? toUser?.display_name : "your"}&apos;s agent
          </span>
          {streaming && (
            <span className="flex items-center gap-1.5 text-accent">
              <span className="flex gap-0.5">
                <span className="w-1 h-1 bg-accent rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1 h-1 bg-accent rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1 h-1 bg-accent rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </span>
              <span className="text-[10px] font-medium">Thinking...</span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {!streaming && result.response && (
            <button
              onClick={toggleTTS}
              className={`p-1.5 rounded-lg transition-all ${
                isSpeaking
                  ? "bg-accent/20 text-accent animate-pulse"
                  : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
              }`}
              title={isSpeaking ? "Stop reading" : "Read aloud"}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                {isSpeaking ? (
                  <><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></>
                ) : (
                  <><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></>
                )}
              </svg>
            </button>
          )}
          {result.trust_level && <TrustBadge tier={result.trust_level} />}
          {!streaming && <DecisionBadge decision={result.decision} />}
        </div>
      </div>

      {/* Body */}
      <div className="px-5 py-4">
        <p className="text-sm font-medium mb-3">&ldquo;{result.question}&rdquo;</p>

        {/* Tool activity (streaming) */}
        {tools && tools.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {tools.map((tool, i) => (
              <div key={i} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-500/10 border border-amber-500/20 text-amber-400">
                <svg className={`w-3 h-3 ${streaming ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                </svg>
                {tool.name.replace(/_/g, " ")}
              </div>
            ))}
          </div>
        )}

        {/* Agent Actions (non-streaming) */}
        {result.agent_actions && result.agent_actions.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {result.agent_actions.map((action: AgentAction, i: number) => (
              <AgentActionCard key={i} action={action} />
            ))}
          </div>
        )}

        {(result.response || streaming) && (
          <div
            className={`text-sm p-4 rounded-xl leading-relaxed prose prose-sm prose-invert max-w-none ${
              streaming
                ? "bg-accent/5 border border-accent/15"
                : result.decision === "allowed"
                  ? "bg-success-dim border border-success/15"
                  : result.decision === "denied"
                    ? "bg-danger-dim border border-danger/15"
                    : "bg-warning-dim border border-warning/15"
            }`}
          >
            {result.response ? (
              <Markdown>{result.response}</Markdown>
            ) : (
              <span className="text-muted-foreground animate-pulse">Agent is processing...</span>
            )}
            {streaming && result.response && (
              <span className="inline-block w-0.5 h-4 bg-accent ml-0.5 animate-pulse" />
            )}
          </div>
        )}

        {/* Metadata */}
        {!streaming && (
          <div className="flex items-center gap-4 mt-3 text-[11px] text-muted-foreground">
            {result.shared_networks.length > 0 && (
              <span className="flex items-center gap-1">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>
                  <line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/>
                </svg>
                {result.shared_networks.join(", ")}
              </span>
            )}
            {result.latency_ms > 0 && <span>{result.latency_ms}ms</span>}
            {"citadel_input" in result && result.citadel_input?.decision && (
              <span className={`flex items-center gap-1 ${result.citadel_input.decision === "BLOCK" ? "text-danger" : "text-success"}`}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
                Citadel: {result.citadel_input.decision}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// Agent Action Inline Cards
// ═══════════════════════════════════════════════════════════════

function AgentActionCard({ action }: { action: AgentAction }) {
  if (action.type === "capsule_created" || action.type === "capsule_updated") {
    return (
      <div
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
          action.type === "capsule_created"
            ? "bg-green-500/10 border border-green-500/20 text-green-400"
            : "bg-blue-500/10 border border-blue-500/20 text-blue-400"
        }`}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          {action.type === "capsule_created" ? (
            <><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></>
          ) : (
            <><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></>
          )}
        </svg>
        <span>{action.type === "capsule_created" ? "Saved" : "Updated"}: {action.title}</span>
        <span className="text-[10px] opacity-60">{action.capsule_type} / {action.tier}</span>
        {action.networks && action.networks.length > 0 && (
          <span className="text-[10px] opacity-60">
            &rarr; {action.networks.join(", ")}
          </span>
        )}
      </div>
    );
  }

  if (action.type === "task_created") {
    return (
      <div className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium bg-amber-500/10 border border-amber-500/20 text-amber-400">
        {/* Clipboard icon */}
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
          <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>
          <rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>
        </svg>
        <span className="truncate max-w-[200px]">{action.title}</span>
        {action.category && (
          <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 text-[10px] font-semibold uppercase tracking-wide">
            {action.category}
          </span>
        )}
        <span className="text-amber-300/60 text-[10px] hover:text-amber-300 cursor-pointer transition-colors">
          View in Dashboard
        </span>
      </div>
    );
  }

  if (action.type === "peer_queried") {
    return (
      <div className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium bg-sky-500/10 border border-sky-500/15 text-sky-400">
        {/* Chat bubble icon */}
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <span className="truncate max-w-[280px]">
          Asked{" "}
          <span className="font-semibold text-sky-300">@{action.target_username}</span>
          {action.question && (
            <span className="text-sky-400/70">: {action.question}</span>
          )}
        </span>
      </div>
    );
  }

  if (action.type === "quotes_requested") {
    return (
      <div className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium bg-amber-500/10 border border-amber-500/20 text-amber-400">
        {/* Receipt/dollar icon */}
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
          <line x1="12" y1="1" x2="12" y2="23"/>
          <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
        </svg>
        <span className="truncate max-w-[220px]">
          Requested quotes for{" "}
          <span className="font-semibold text-amber-300">{action.service_type}</span>
        </span>
        {action.providers_queried != null && action.providers_queried > 0 && (
          <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 text-[10px] font-semibold">
            {action.providers_queried} provider{action.providers_queried !== 1 ? "s" : ""} contacted
          </span>
        )}
      </div>
    );
  }

  // Fallback for any unknown action type
  return null;
}
