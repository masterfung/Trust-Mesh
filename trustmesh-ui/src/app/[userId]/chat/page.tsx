"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type User, type QueryResult, type AgentAction, type Connection, type RegistryAgent, getPodUrl } from "@/lib/api";
import { SIBLING_PORTS, fetchSiblingPodUsers } from "@/lib/pods";
import { ResearchFeed } from "@/components/ResearchFeed";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { TrustBadge, DecisionBadge } from "@/components/TrustBadge";
import { Markdown } from "@/components/Markdown";
import { LiveAgent } from "@/components/LiveAgent";
import QRCode from "react-qr-code";

// Demo scenario suggestions per pod username (shown when chat is empty)
const DEMO_SCENARIOS: Record<string, { label: string; question: string; icon: string }[]> = {
  molly: [
    { label: "Check on Grandma Rose", question: "What medications does Grandma Rose take? Are there any health updates I should know about?", icon: "💊" },
    { label: "Find a cleaning service", question: "Can you find me a house cleaning service? Ask SparkleClean about their rates.", icon: "🧹" },
    { label: "SAT prep for the kids", question: "Look into SAT prep tutoring options. Check what AceTutor offers.", icon: "📚" },
  ],
  peter: [
    { label: "Grandma's health update", question: "Check in on Grandma Rose's health. Any recent changes to her care plan?", icon: "❤️" },
    { label: "Home repair help", question: "I need a handyman for some repairs. Can you check what HandyPro offers?", icon: "🔧" },
    { label: "Family plans this week", question: "What does our family have planned this week? Check with Molly and Jane.", icon: "📅" },
  ],
  grandmarose: [
    { label: "Find a cleaning service", question: "Can you help me find a home cleaning service nearby? I need someone reliable.", icon: "🏠" },
    { label: "Check on the family", question: "How is everyone in the family doing? Check in with Peter and Molly.", icon: "👨‍👩‍👧" },
    { label: "Medical appointment", question: "When is my next medical appointment? Check with Riverside Hospital.", icon: "🏥" },
  ],
  dr_lee: [
    { label: "Patient health update", question: "Check Grandma Rose's recent health updates and medication list.", icon: "📋" },
    { label: "Hospital resources", question: "What resources does Riverside Hospital have available for elderly care?", icon: "🏥" },
    { label: "Emergency protocols", question: "What are the current emergency protocols? Check with the ambulance service.", icon: "🚑" },
  ],
  jane: [
    { label: "Check on Grandma", question: "How is Grandma Rose doing? Any health updates I should know about?", icon: "💕" },
    { label: "Find a tutor", question: "Can you look into tutoring services? What does AceTutor offer for SAT prep?", icon: "📖" },
    { label: "Family schedule", question: "What's the family schedule looking like this week?", icon: "🗓️" },
  ],
  sparkleclean: [
    { label: "View service requests", question: "Do we have any new service inquiries or quote requests?", icon: "📬" },
    { label: "Check our listings", question: "What services do we currently have listed? Are our descriptions up to date?", icon: "📋" },
  ],
  riverside_hospital: [
    { label: "Patient referrals", question: "Are there any incoming patient referrals or queries from the community?", icon: "🏥" },
    { label: "Service availability", question: "What services are we currently offering? Any capacity updates?", icon: "📊" },
  ],
  riverside_gov: [
    { label: "Community inquiries", question: "Are there any community service requests or inquiries pending?", icon: "🏛️" },
    { label: "Emergency services", question: "What emergency services are currently available in our network?", icon: "🚨" },
  ],
};

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
  routing?: { provider: string; model?: string };
  latency_ms: number;
  created_at: string;
  isStreaming?: boolean;
  tools?: { name: string; input: Record<string, unknown> }[];
}

export default function ChatPage() {
  const { userId } = useParams<{ userId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [results, setResults] = useState<StreamingResult[]>([]);
  const [isListening, setIsListening] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamElapsed, setStreamElapsed] = useState(0);
  const [voiceError, setVoiceError] = useState("");
  const [formVisible, setFormVisible] = useState(true);
  // Pod users from sibling pods (for cross-pod @mentions)
  const [podUsers, setPodUsers] = useState<User[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

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

  const { data: capsules, isSuccess: capsulesLoaded } = useQuery({
    queryKey: ["capsules", userId],
    queryFn: () => api.listCapsules(userId),
  });

  // Redirect new users to onboarding — agent can't help without any vault context
  useEffect(() => {
    if (capsulesLoaded && capsules?.length === 0) {
      router.replace(`/${userId}/onboard`);
    }
  }, [capsulesLoaded, capsules, userId, router]);

  const [sessionHistory, setSessionHistory] = useState<{ role: string; content: string }[]>([]);
  const [showLive, setShowLive] = useState(false);
  const [showResearchFeed, setShowResearchFeed] = useState(false);

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

  // Merge local users + connection peers + sibling pod owners for @mention
  const allMentionableUsers = useMemo(() => {
    const local = users ?? [];
    const localIds = new Set(local.map((u) => u.id));
    const remotePeers: User[] = (connections ?? [])
      .map((c: Connection) => c.peer)
      .filter((p): p is User => !!p && !localIds.has(p.id));
    // Dedup pod owners against local + peers by username (ghost IDs differ from home-pod IDs)
    const knownUsernames = new Set([
      ...local.map(u => u.username),
      ...remotePeers.map(u => u.username?.replace(/^remote:/, "")),
    ]);
    const podOwners = podUsers.filter(
      p => !localIds.has(p.id) && !knownUsernames.has(p.username)
    );
    return [...local, ...remotePeers, ...podOwners];
  }, [users, connections, podUsers]);

  const handleStreamQuery = useCallback(async (overrideQ?: string) => {
    const q = (overrideQ ?? question).trim();
    if (!q) return;

    // Parse @username or @"Full Name" to route to another user's agent
    let toUserId = userId;
    let questionText = q;
    // Support @handle, @"Full Name", @Full_Name (underscores as spaces)
    const mentionMatch = q.match(/^@(?:"([^"]+)"|(\S+))(?:\s+([\s\S]*))?$/);
    if (mentionMatch) {
      const handle = (mentionMatch[1] ?? mentionMatch[2] ?? "").toLowerCase().replace(/_/g, " ");
      const rest = mentionMatch[3]?.trim() ?? "";
      const target = allMentionableUsers.find(
        (u) =>
          u.username?.toLowerCase() === handle ||
          u.display_name?.toLowerCase() === handle ||
          u.display_name?.toLowerCase().startsWith(handle)
      );
      if (target && target.id !== userId) {
        const podUrl = target.pod_url;
        if (podUrl) {
          // Cross-pod user: register peer in background, then route through own agent
          // The agent will use query_peer tool to reach them
          api.addPeer(podUrl).catch(() => {});
          toUserId = userId; // stay on own agent
          questionText = q;  // keep full message including @mention
        } else {
          // Same-pod user: route directly
          toUserId = target.id;
          questionText = rest || q;
        }
      }
    }
    const isOwnAgent = toUserId === userId;

    const abortCtrl = new AbortController();
    streamAbortRef.current = abortCtrl;
    setIsStreaming(true);
    const placeholderResult: StreamingResult = {
      from_user_id: userId,
      to_user_id: toUserId,
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

    // Add user message to session history (only for own-agent conversations)
    const historySnapshot = [...sessionHistory];
    if (isOwnAgent) setSessionHistory((prev) => [...prev, { role: "user", content: q }]);

    try {
      const res = await api.queryStream(
        userId,
        toUserId,
        questionText,
        isOwnAgent && historySnapshot.length > 0 ? historySnapshot : undefined,
      );
      if (!res.ok || !res.body) {
        throw new Error("Stream failed");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      // Cancel reader when abort is triggered
      abortCtrl.signal.addEventListener("abort", () => { reader.cancel().catch(() => {}); });

      while (true) {
        if (abortCtrl.signal.aborted) break;
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
              // Show research feed when browsing tools are active
              const toolName = event.data?.name;
              if (toolName === "browse_web" || toolName === "research_parallel") {
                setShowResearchFeed(true);
              }
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
                  // Add assistant response to session history (own agent only)
                  const responseText = updated[0].response;
                  if (responseText && isOwnAgent) {
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
  }, [userId, question, queryClient, sessionHistory, allMentionableUsers]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    handleStreamQuery();
  };

  const sendMessage = useCallback((msg: string) => {
    setQuestion(msg);
    handleStreamQuery(msg);
  }, [handleStreamQuery]);

  const stopStream = useCallback(() => {
    streamAbortRef.current?.abort();
    setIsStreaming(false);
    setResults((prev) => {
      const updated = [...prev];
      if (updated[0]?.isStreaming) {
        updated[0] = { ...updated[0], isStreaming: false, response: (updated[0].response || "") + "\n\n*(Stopped)*" };
      }
      return updated;
    });
  }, []);

  // Elapsed timer while streaming
  useEffect(() => {
    if (!isStreaming) { setStreamElapsed(0); return; }
    setStreamElapsed(0);
    const t = setInterval(() => setStreamElapsed(s => s + 1), 1000);
    return () => clearInterval(t);
  }, [isStreaming]);

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

  // Auto-scroll input into view and focus it after streaming completes
  useEffect(() => {
    if (!isStreaming && results.length > 0 && results[0] && !results[0].isStreaming) {
      // Small delay so DOM has settled
      const t = setTimeout(() => {
        formRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        inputRef.current?.focus();
      }, 300);
      return () => clearTimeout(t);
    }
  }, [isStreaming, results]);

  // Track whether the form is in the viewport to show sticky reply bar
  useEffect(() => {
    const el = formRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => setFormVisible(entry.isIntersecting),
      { threshold: 0.2 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

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

    // Preserve any text already in the input — voice appends, not replaces
    const priorText = question.trimEnd();
    const prefix = priorText ? priorText + " " : "";
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
      setQuestion(prefix + finalTranscript + interim);
    };
    recognition.onend = () => {
      clearTimeout(autoStopTimer);
      setIsListening(false);
      if (finalTranscript.trim()) {
        setQuestion((prefix + finalTranscript).trim());
      } else if (!gotResults) {
        setVoiceError("No speech detected — check your mic is unmuted and try again");
      }
      // If stopped before any speech, leave prior text untouched
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
  }, [isListening, question]);

  // Research feed pod URLs: current pod + demo sibling pods (if in multi-pod mode)
  const currentPodUrl = typeof window !== "undefined" ? getPodUrl() : "";
  const currentPort = currentPodUrl.match(/:(\d+)/)?.[1] ?? "";
  const researchPodUrls = SIBLING_PORTS.includes(currentPort)
    ? SIBLING_PORTS.map((p) => currentPodUrl.replace(/:(\d+)/, `:${p}`))
    : currentPodUrl
      ? [currentPodUrl]
      : [];

  // Fetch owners of sibling pods for cross-pod @mention
  useEffect(() => {
    if (!currentPodUrl) return;
    fetchSiblingPodUsers(currentPodUrl).then(setPodUsers);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPodUrl]);

  return (
    <div className="max-w-3xl mx-auto">
      {/* Live Agent modal */}
      {showLive && <LiveAgent userId={userId} onClose={() => setShowLive(false)} />}

      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold mb-1">Agent Chat</h1>
          <p className="text-muted-foreground text-sm">
            Ask your agent anything. Type <span className="text-accent font-medium">@name</span> to reach another person&apos;s agent — trust determines what they share back.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowLive(true)}
            className="shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium text-blue-400 hover:text-blue-300 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 transition-all"
            title="Start a live voice conversation with your agent"
          >
            <span>🎙️</span> Live
          </button>
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
      </div>

      {/* Live Research Feed */}
      <ResearchFeed podUrls={researchPodUrls} visible={showResearchFeed || isStreaming} onSend={sendMessage} />

      {/* Sticky reply bar — shown when form is scrolled out of view and agent has asked a question */}
      {!formVisible && !isStreaming && results.length > 0 && (() => {
        const lastResponse = results.find(r => r.response && !r.isStreaming)?.response ?? "";
        // Extract last sentence ending in ? as a hint
        const lastQ = lastResponse.match(/[^.!?]*\?(?:\s|$)/g)?.at(-1)?.trim();
        return (
          <div className="fixed bottom-0 left-0 right-0 z-40 bg-background/95 backdrop-blur border-t border-card-border px-4 py-3 flex items-center gap-3 max-w-3xl mx-auto shadow-2xl">
            {lastQ && (
              <p className="text-xs text-muted-foreground truncate flex-1 hidden sm:block">
                <span className="text-accent font-medium">Agent asked:</span> {lastQ}
              </p>
            )}
            <input
              type="text"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(question); } }}
              placeholder="Reply to agent…"
              className="flex-1 sm:max-w-xs px-3 py-2 text-sm bg-card border border-card-border rounded-xl focus:outline-none focus:border-accent"
            />
            <button
              onClick={() => { if (question.trim()) sendMessage(question); else formRef.current?.scrollIntoView({ behavior: "smooth" }); }}
              className="px-4 py-2 text-xs font-semibold rounded-xl bg-accent hover:bg-accent-hover text-accent-fg transition-all"
            >
              {question.trim() ? "Send" : "Scroll to input ↓"}
            </button>
          </div>
        );
      })()}

      {/* Query Form */}
      <form ref={formRef} onSubmit={handleSubmit} className="bg-card border border-card-border rounded-2xl p-5 mb-8">
        {/* Info banner */}
        <div className="mb-4 p-3 bg-accent/5 border border-accent/15 rounded-xl">
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-accent">Your private agent</span> — sees all your memories and can save new knowledge to your vault. Type <span className="font-medium text-accent">@name</span> to ask another person&apos;s agent directly.
          </p>
        </div>

        {/* Question Input with @-mention */}
        <div className="mb-4 relative overflow-visible">
          <div className="flex items-end gap-2 bg-background border border-card-border rounded-xl px-3 py-2 focus-within:border-accent/60 transition-colors">
            <MentionInput
              value={question}
              onChange={setQuestion}
              onSubmit={() => {
                if (!question.trim()) return;
                handleStreamQuery();
              }}
              users={allMentionableUsers}
              connectedIds={connectedIds}
              userNetworkMap={userNetworkMap}
              currentUserId={userId}
              placeholder="Ask your agent anything... (type @ to ask another agent)"
              disabled={false}
            />
            <div className="flex items-center gap-1 shrink-0 pb-0.5">
              <button
                type="button"
                onClick={toggleVoice}
                disabled={!hasSpeechRecognition}
                className={`p-1.5 rounded-lg transition-all ${
                  !hasSpeechRecognition
                    ? "opacity-30 cursor-not-allowed text-muted-foreground"
                    : isListening
                      ? "bg-red-500/20 text-red-400 animate-pulse"
                      : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
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
                disabled={!question.trim() || isStreaming}
                className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-accent-fg text-xs font-medium rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-all"
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
        <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
          </svg>
          Your agent has full access to all your memories. Your relationship determines what others share back.
        </p>
      </form>

      {/* Demo Scenario Suggestions (only when empty) */}
      {results.length === 0 && !isStreaming && (() => {
        const currentUser = (users ?? []).find(u => u.id === userId);
        const scenarios = currentUser?.username ? DEMO_SCENARIOS[currentUser.username] : undefined;
        const podPort = getPodUrl().match(/:(\d+)/)?.[1];
        const isMultiPod = podPort && podPort !== "8000";
        if (!scenarios || !isMultiPod) return null;
        return (
          <div className="mb-8">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-sm font-semibold text-muted-foreground">Try a demo scenario</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400 font-medium border border-violet-500/20">Federation</span>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {scenarios.map((s, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setQuestion(s.question);
                  }}
                  className="group p-3 rounded-xl bg-card border border-card-border hover:border-accent/40 transition-all hover:bg-card-hover text-left"
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-base">{s.icon}</span>
                    <span className="text-sm font-medium text-foreground group-hover:text-accent transition-colors">{s.label}</span>
                  </div>
                  <p className="text-[11px] text-muted-foreground line-clamp-2 leading-relaxed">{s.question}</p>
                </button>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Results */}
      {results.length > 0 && (
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-muted-foreground mb-3">This Session</h2>
          <div className="space-y-3">
            {results.map((r, idx) => (
              <QueryResultCard key={r.id || `streaming-${idx}`} result={r} users={users ?? []} currentUserId={userId} onSend={sendMessage} onStop={r.isStreaming ? stopStream : undefined} streamElapsed={r.isStreaming ? streamElapsed : undefined} />
            ))}
          </div>
        </div>
      )}

      {/* History (collapsed by default) */}
      {history && history.length > 0 && (
        <HistorySection history={history} users={users ?? []} userId={userId} />
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// History Section (collapsed by default)
// ═══════════════════════════════════════════════════════════════

function HistorySection({ history, users, userId }: { history: QueryResult[]; users: User[]; userId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors mb-2 group"
      >
        <svg
          width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          className={`transition-transform ${open ? "rotate-90" : ""}`}
        >
          <path d="M9 18l6-6-6-6" />
        </svg>
        <span className="group-hover:underline">Chat History</span>
        <span className="px-1.5 py-0.5 rounded bg-card-hover text-[10px] font-medium">{history.length}</span>
      </button>
      {open && (
        <div className="space-y-3">
          {history.map((r: QueryResult) => (
            <QueryResultCard key={r.id} result={r} users={users} currentUserId={userId} />
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// @-Mention Input Component
// ═══════════════════════════════════════════════════════════════

// A registry result adapted to look like a local user for mention insertion
interface RegistryMentionItem {
  id: string; // use DID as id
  username: string; // public handle
  display_name: string;
  user_type: string;
  isRegistry: true;
  pod_url: string;
}

type MentionItem = (User & { isRegistry?: false }) | RegistryMentionItem;

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
  const [registryResults, setRegistryResults] = useState<RegistryMentionItem[]>([]);
  const registryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Local user IDs and usernames for deduplication
  const localUsernames = useMemo(() => new Set(users.map(u => u.username).filter(Boolean)), [users]);

  // Debounced registry search
  useEffect(() => {
    if (!showMentions || mentionQuery.length < 2) {
      const timeoutId = setTimeout(() => setRegistryResults([]), 0);
      return () => clearTimeout(timeoutId);
    }
    if (registryTimerRef.current) clearTimeout(registryTimerRef.current);
    registryTimerRef.current = setTimeout(async () => {
      try {
        const res = await api.registrySearch(mentionQuery);
        const items: RegistryMentionItem[] = (res.results || [])
          .filter((r: RegistryAgent) => !localUsernames.has(r.username) && r.did !== currentUserId)
          .map((r: RegistryAgent) => ({
            id: r.did,
            username: r.username,
            display_name: r.display_name,
            user_type: r.user_type || "person",
            isRegistry: true as const,
            pod_url: "",
          }));
        setRegistryResults(items);
      } catch {
        setRegistryResults([]);
      }
    }, 300);
    return () => { if (registryTimerRef.current) clearTimeout(registryTimerRef.current); };
  }, [showMentions, mentionQuery, localUsernames, currentUserId]);

  const filteredUsers: User[] = users
    .filter((u) => {
      if (u.id === currentUserId) return false;
      if (!mentionQuery) return true;
      const q = mentionQuery.toLowerCase();
      // For remote users, only match on display_name (their username is a DID hash)
      if (u.username?.startsWith("remote:")) {
        return u.display_name.toLowerCase().includes(q);
      }
      return (
        (u.username && u.username.toLowerCase().includes(q)) ||
        u.display_name.toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      // Connected first (0), then local non-connected (1), then remote pod users (2), then orgs
      const aScore = connectedIds.has(a.id) ? 0 : a.is_remote ? 2 : 1;
      const bScore = connectedIds.has(b.id) ? 0 : b.is_remote ? 2 : 1;
      if (aScore !== bScore) return aScore - bScore;
      const aIsOrg = a.user_type !== "person" ? 1 : 0;
      const bIsOrg = b.user_type !== "person" ? 1 : 0;
      if (aIsOrg !== bIsOrg) return aIsOrg - bIsOrg;
      return a.display_name.localeCompare(b.display_name);
    });

  // Auto-resize textarea whenever value changes (covers voice input, demo clicks, etc.)
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [value]);

  // Combine local + registry results (deduped)
  const allMentionItems: MentionItem[] = useMemo(() => {
    const combined: MentionItem[] = [...filteredUsers];
    for (const r of registryResults) {
      if (!combined.some(c => c.username === r.username)) {
        combined.push(r);
      }
    }
    return combined;
  }, [filteredUsers, registryResults]);

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
    (item: MentionItem) => {
      const before = value.slice(0, mentionStart);
      const afterCursor = value.slice(
        mentionStart + 1 + mentionQuery.length
      );
      // Local users get @handle, remote/ghost users get @"Full Name" (quoted if has spaces)
      let mention: string;
      if (item.username && !item.username.startsWith("remote:")) {
        mention = `@${item.username}`;
      } else {
        const name = item.display_name;
        mention = name.includes(" ") ? `@"${name}"` : `@${name}`;
      }
      const newVal = `${before}${mention} ${afterCursor}`;
      onChange(newVal);
      setShowMentions(false);
      setMentionQuery("");
      setRegistryResults([]);
      setTimeout(() => inputRef.current?.focus(), 0);
    },
    [value, mentionStart, mentionQuery, onChange]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (showMentions && allMentionItems.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSelectedIdx((i) => Math.min(i + 1, allMentionItems.length - 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSelectedIdx((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === "Tab" || e.key === "Enter") {
          e.preventDefault();
          insertMention(allMentionItems[selectedIdx]);
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
    [showMentions, allMentionItems, selectedIdx, insertMention, onSubmit]
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
    <div className="relative flex-1 min-w-0 overflow-visible">
      <textarea
        ref={inputRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={1}
        className="w-full bg-transparent text-sm placeholder:text-muted-foreground resize-none overflow-y-auto focus:outline-none"
        style={{ maxHeight: 160, minHeight: "1.5rem" }}
        disabled={disabled}
      />

      {/* @-mention empty state */}
      {showMentions && allMentionItems.length === 0 && mentionQuery.length > 0 && (
        <div className="absolute left-0 right-0 top-full mt-1 bg-card border border-card-border rounded-xl shadow-2xl z-[100] px-3 py-2 text-xs text-muted-foreground">
          {mentionQuery.length < 2 ? "Type 2+ chars to search…" : `No agents found for "${mentionQuery}"`}
        </div>
      )}

      {/* @-mention autocomplete dropdown */}
      {showMentions && allMentionItems.length > 0 && (
        <div
          ref={dropdownRef}
          className="absolute left-0 right-0 top-full mt-1 bg-card border border-card-border rounded-xl shadow-2xl overflow-hidden z-[100] max-h-72 overflow-y-auto"
        >
          {/* Local results */}
          {filteredUsers.length > 0 && (
            <>
              <div className="px-3 py-1.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wider border-b border-card-border bg-card-hover/50">
                People You Know
              </div>
              {filteredUsers.slice(0, 5).map((u, i) => {
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
                          isConnected ? "bg-accent" : u.is_remote ? "bg-muted-foreground/40" : "bg-muted-foreground/25"
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
                        <span className={`text-sm font-medium ${!isConnected && !u.is_remote ? "text-muted-foreground" : ""}`}>
                          {u.username && !u.username.startsWith("remote:")
                            ? <><span className="text-accent">@{u.username}</span> <span className="text-muted-foreground text-xs">({u.display_name})</span></>
                            : u.display_name
                          }
                        </span>
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
                        ) : u.is_remote && u.pod_url ? (
                          <span className="text-[10px] font-mono text-muted-foreground/50">
                            :{u.pod_url.match(/:(\d+)/)?.[1]}
                          </span>
                        ) : !u.is_remote ? (
                          <span className="text-[10px] text-muted-foreground/60">Not connected</span>
                        ) : null}
                      </div>
                    </div>
                  </button>
                );
              })}
            </>
          )}

          {/* Registry results */}
          {registryResults.length > 0 && (
            <>
              <div className="px-3 py-1.5 text-[10px] font-medium text-violet-400 uppercase tracking-wider border-b border-card-border bg-violet-500/5 flex items-center gap-1.5">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
                </svg>
                Public Directory
              </div>
              {registryResults.slice(0, 4).map((r) => {
                const globalIdx = filteredUsers.length + registryResults.indexOf(r);
                const podPort = r.pod_url.match(/:(\d+)/)?.[1];
                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => insertMention(r)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors ${
                      globalIdx === selectedIdx
                        ? "bg-accent/10 text-accent"
                        : "hover:bg-card-hover text-foreground"
                    }`}
                  >
                    <div className="w-6 h-6 rounded-md flex items-center justify-center text-white font-bold text-[10px] bg-violet-500/60">
                      {r.display_name[0]}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium">
                          <span className="text-violet-400">@{r.username}</span>{" "}
                          <span className="text-muted-foreground text-xs">({r.display_name})</span>
                        </span>
                        {r.user_type === "organization" && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 font-semibold uppercase">Org</span>
                        )}
                        {r.user_type === "government" && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-semibold uppercase">Gov</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1 mt-0.5">
                        <span className="text-[10px] text-violet-400/70">Public agent</span>
                        {podPort && <span className="text-[10px] text-muted-foreground/50">Pod :{podPort}</span>}
                      </div>
                    </div>
                  </button>
                );
              })}
            </>
          )}

          {/* Search hint when no registry results yet */}
          {mentionQuery.length >= 2 && registryResults.length === 0 && filteredUsers.length > 0 && (
            <div className="px-3 py-1.5 text-[10px] text-muted-foreground/50 border-t border-card-border">
              Searching public directory...
            </div>
          )}
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// Inline Emergency QR Card
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════
// Vault Context Authorization Manifest + Pipeline Card
// ═══════════════════════════════════════════════════════════════

interface VaultContextItem {
  title: string;
  content: string;
  capsule_type: string;
  freshness: string;
  confidence: string;
  authority_weight: number;
  capsule_id: string;
}

function VaultContextCard({ tools }: { tools: { name: string; input: Record<string, unknown> }[] }) {
  const [open, setOpen] = useState(false);

  // Extract vault_context_used from tool results (stored in input for display)
  const browseTools = tools.filter(t => t.name === "browse_web" || t.name === "research_parallel");
  if (browseTools.length === 0) return null;

  // Check if any browse tool ran (we show the pipeline card regardless of context items)
  const hasParallel = tools.some(t => t.name === "research_parallel");
  const taskCount = hasParallel
    ? (tools.find(t => t.name === "research_parallel")?.input?.tasks as unknown[])?.length ?? 1
    : browseTools.length;

  return (
    <div className="mb-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen(v => !v)}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-cyan-400 shrink-0" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
        </svg>
        <span className="text-[11px] font-semibold text-cyan-400">How this search was protected</span>
        {hasParallel && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/20 font-medium">
            {taskCount} sites parallel
          </span>
        )}
        <svg
          width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          className={`ml-auto text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
          strokeLinecap="round" strokeLinejoin="round"
        >
          <path d="M9 18l6-6-6-6"/>
        </svg>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-1.5">
          {/* Pipeline visualization */}
          <div className="text-[10px] font-mono space-y-1 text-muted-foreground border-t border-cyan-500/10 pt-2 mt-1">
            {[
              { icon: "🔓", label: "Vault", desc: "Zig-decrypted preferences (keys never leave native memory)" },
              { icon: "🎯", label: "Goal", desc: "Personalized with your context — nothing raw sent" },
              { icon: "🌐", label: "Browse", desc: hasParallel ? `TinyFish — ${taskCount} sites simultaneously` : "TinyFish AI browser session" },
              { icon: "🛡️", label: "Scan", desc: "Citadel ML — injection + leak detection" },
              { icon: "🔒", label: "Store", desc: "Zig re-encrypts into vault (AES-256-GCM)" },
              { icon: "🤝", label: "Share", desc: "Trust-scoped to your network" },
            ].map(({ icon, label, desc }) => (
              <div key={label} className="flex items-start gap-2">
                <span className="shrink-0 w-4 text-center">{icon}</span>
                <span className="text-cyan-400 font-semibold w-12 shrink-0">{label}</span>
                <span>{desc}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const SCAN_URL_RE = /https?:\/\/\S+\/emergency\/scan\?\S+/g;

function EmergencyQRCards({ response }: { response: string }) {
  const urls = response.match(SCAN_URL_RE);
  if (!urls || urls.length === 0) return null;

  // Deduplicate
  const unique = [...new Set(urls)];

  return (
    <div className="mt-3 flex flex-wrap gap-3 not-prose">
      {unique.map((url, i) => {
        let parsed: URL | null = null;
        try { parsed = new URL(url); } catch { return null; }
        const patient = parsed.searchParams.get("p") ?? "patient";
        const tokenRoleHint = url.includes("paramedic")
          ? "Paramedic"
          : url.includes("attending")
            ? "Physician"
            : url.includes("er_nurse")
              ? "ER Nurse"
              : "Emergency";
        return (
          <div
            key={i}
            className="flex flex-col items-center gap-3 p-4 bg-red-950/30 border border-red-700/40 rounded-xl w-full sm:w-auto"
          >
            <span className="text-red-400 font-semibold text-xs uppercase tracking-wider text-center">
              🚑 {tokenRoleHint} — {patient}
            </span>
            <div className="bg-white p-2.5 rounded-lg">
              <QRCode value={url} size={150} />
            </div>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-red-300 hover:text-red-200 underline transition-colors text-center break-all"
            >
              Open emergency scan →
            </a>
          </div>
        );
      })}
    </div>
  );
}

// ── Inline reply ─────────────────────────────────────────────────────────────

function InlineReply({ question, onSend }: { question: string; onSend: (msg: string) => void }) {
  const [text, setText] = useState("");
  const [sent, setSent] = useState(false);

  if (sent) return null;

  return (
    <div className="mt-3 rounded-xl bg-accent/5 border border-accent/15 p-3">
      <p className="text-[11px] text-accent font-medium mb-2 flex items-center gap-1.5">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>
        </svg>
        Reply
      </p>
      <div className="flex gap-2">
        <input
          autoFocus
          type="text"
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" && !e.shiftKey && text.trim()) {
              e.preventDefault();
              onSend(text.trim());
              setSent(true);
            }
          }}
          placeholder={`Answer: "${question.length > 60 ? question.slice(0, 60) + "…" : question}"`}
          className="flex-1 px-3 py-2 text-sm bg-background border border-card-border rounded-xl focus:outline-none focus:border-accent"
        />
        <button
          onClick={() => { if (text.trim()) { onSend(text.trim()); setSent(true); } }}
          disabled={!text.trim()}
          className="px-4 py-2 text-xs font-semibold rounded-xl bg-accent hover:bg-accent-hover text-accent-fg transition-all disabled:opacity-40"
        >
          Send
        </button>
      </div>
    </div>
  );
}

function QueryResultCard({
  result,
  users,
  currentUserId,
  onSend,
  onStop,
  streamElapsed,
}: {
  result: StreamingResult | QueryResult;
  users: User[];
  currentUserId: string;
  onSend?: (msg: string) => void;
  onStop?: () => void;
  streamElapsed?: number;
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
            {result.from_user_id === result.to_user_id
              ? "Your agent"
              : isSent
                ? `${toUser?.display_name || "Unknown"}'s agent`
                : "your agent"}
          </span>
          {streaming && (
            <span className="flex items-center gap-2 text-accent">
              <span className="flex gap-0.5">
                <span className="w-1 h-1 bg-accent rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1 h-1 bg-accent rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1 h-1 bg-accent rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </span>
              <span className="text-[10px] font-medium">Thinking…</span>
              {streamElapsed !== undefined && streamElapsed > 0 && (
                <span className="text-[10px] text-muted-foreground tabular-nums">{streamElapsed}s</span>
              )}
              {onStop && (
                <button
                  onClick={onStop}
                  className="ml-1 text-[10px] px-2 py-0.5 rounded bg-destructive/15 text-destructive border border-destructive/30 hover:bg-destructive/25 transition-colors font-medium"
                  title="Stop generating"
                >
                  Stop
                </button>
              )}
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

        {/* Authorization manifest + pipeline card (shown when browse_web / research_parallel ran) */}
        {!streaming && tools && tools.some(t => t.name === "browse_web" || t.name === "research_parallel") && (
          <VaultContextCard tools={tools} />
        )}

        {/* Agent Actions (non-streaming) */}
        {result.agent_actions && result.agent_actions.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {result.agent_actions.map((action: AgentAction, i: number) => (
              <AgentActionCard key={i} action={action} onSend={onSend} userId={currentUserId} />
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
              <span className="text-muted-foreground animate-pulse text-xs">
                {tools && tools.length > 0
                  ? `Running ${tools[tools.length - 1].name.replace(/_/g, " ")}…`
                  : "Agent is thinking…"}
              </span>
            )}
            {streaming && result.response && (
              <span className="inline-block w-0.5 h-4 bg-accent ml-0.5 animate-pulse" />
            )}
          </div>
        )}
        {/* Inline QR cards for emergency scan URLs */}
        {result.response && <EmergencyQRCards response={result.response} />}

        {/* Follow-up chips: parse "Want me to:" numbered options from agent response */}
        {!streaming && result.response && onSend && (() => {
          const match = result.response.match(/want me to[:\s*]*([\s\S]*?)(?:\n\n|$)/i);
          if (!match) return null;
          const options = [...match[1].matchAll(/\d+\.\s+\*?\*?([^*\n]+)\*?\*?/g)].map(m => m[1].trim()).filter(Boolean);
          if (options.length < 2) return null;
          return (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {options.map((opt, i) => (
                <button
                  key={i}
                  onClick={() => onSend(opt)}
                  className="text-xs px-3 py-1.5 rounded-full bg-accent/10 border border-accent/25 text-accent hover:bg-accent/20 transition-all"
                >
                  {opt}
                </button>
              ))}
            </div>
          );
        })()}

        {/* Inline reply — shown when agent ended with a question */}
        {!streaming && result.response && onSend && (() => {
          // Find last question in the response
          const questions = result.response.match(/[^.!?\n]{10,}[?]/g);
          const lastQ = questions?.at(-1)?.trim();
          if (!lastQ) return null;
          return (
            <InlineReply question={lastQ} onSend={onSend} />
          );
        })()}

        {/* Metadata */}
        {!streaming && (
          <div className="flex items-center gap-4 mt-3 text-[11px] text-muted-foreground flex-wrap">
            {/* Federation indicator */}
            {result.agent_actions?.some((a: AgentAction) => a.federated) && (
              <span className="flex items-center gap-1 text-violet-400">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
                </svg>
                Remote query
              </span>
            )}
            {result.shared_networks.length > 0 && (
              <span className="flex items-center gap-1 text-green-400">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>
                  <line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/>
                </svg>
                via {result.shared_networks.join(", ")}
              </span>
            )}
            {result.trust_level && result.trust_level !== "private" && (
              <span className={`flex items-center gap-1 ${
                result.trust_level === "network" ? "text-green-400" :
                result.trust_level === "connected" ? "text-blue-400" :
                "text-zinc-400"
              }`}>
                {result.trust_level === "network" ? "group member" :
                 result.trust_level === "connected" ? "connected" :
                 result.trust_level === "private" ? "private" :
                 result.trust_level}
              </span>
            )}
            {result.latency_ms > 0 && <span>{result.latency_ms}ms</span>}
            {onSend && !streaming && result.question && (
              <button
                onClick={() => onSend(result.question)}
                className="flex items-center gap-1 text-[11px] text-muted-foreground/60 hover:text-accent transition-colors"
                title="Retry this question"
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.51"/>
                </svg>
                Retry
              </button>
            )}
            {result.routing?.provider && (
              <span className={`flex items-center gap-1 ${
                result.routing.provider === "gemini" ? "text-blue-400" :
                result.routing.provider === "tee" ? "text-violet-400" :
                "text-zinc-400"
              }`}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                </svg>
                {result.routing.provider === "gemini" ? "Gemini Flash" :
                 result.routing.provider === "tee" ? "TEE Enclave (private)" :
                 "Claude Sonnet"}
              </span>
            )}
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

function AgentActionCard({ action, onSend, userId }: { action: AgentAction; onSend?: (msg: string) => void; userId: string }) {
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
        {onSend && (
          <button
            onClick={() => onSend(`Create a task to track and continue working on: "${action.title}"`)}
            className="ml-1 text-[10px] opacity-50 hover:opacity-100 hover:text-accent border border-current/20 rounded px-1.5 py-0.5 transition-all"
            title="Follow up on this"
          >
            Follow up
          </button>
        )}
      </div>
    );
  }

  if (action.type === "task_created") {
    return (
      <Link href={`/${userId}/timeline`} className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium bg-amber-500/10 border border-amber-500/20 text-amber-400 hover:bg-amber-500/15 transition-colors">
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
        <span className="text-amber-300/60 text-[10px]">View →</span>
      </Link>
    );
  }

  if (action.type === "peer_queried") {
    // Clean display name: prefer target_display_name, fall back to cleaned username
    const displayName = action.target_display_name || (() => {
      const un = action.target_username || "unknown";
      if (un.startsWith("remote:")) {
        const name = un.slice(7).split("@")[0];
        return name.charAt(0).toUpperCase() + name.slice(1);
      }
      return un;
    })();
    const podLabel = action.remote_pod ? (() => {
      const match = action.remote_pod.match(/:(\d+)/);
      return match ? `Pod :${match[1]}` : "Remote Pod";
    })() : null;

    return (
      <div className={`inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium ${
        action.federated
          ? "bg-violet-500/10 border border-violet-500/15 text-violet-400"
          : "bg-sky-500/10 border border-sky-500/15 text-sky-400"
      }`}>
        {action.federated ? (
          /* Globe/federation icon */
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
            <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
        ) : (
          /* Chat bubble icon */
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        )}
        <span className="truncate max-w-[280px]">
          {action.federated ? "Queried" : "Asked"}{" "}
          <span className={`font-semibold ${action.federated ? "text-violet-300" : "text-sky-300"}`}>
            {displayName}
          </span>
          {podLabel && (
            <span className="opacity-60 ml-1">({podLabel})</span>
          )}
        </span>
        {action.trust_level && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${
            action.trust_level === "network" ? "bg-green-500/15 text-green-400" :
            action.trust_level === "private" ? "bg-blue-500/15 text-blue-400" :
            "bg-zinc-500/15 text-zinc-400"
          }`}>
            {action.trust_level}
          </span>
        )}
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
