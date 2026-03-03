"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Markdown } from "@/components/Markdown";
import { CAPSULE_TYPE_EMOJIS, CAPSULE_TYPE_COLORS } from "@/lib/constants";

const PERSONALITY_MODES = [
  { key: "simple", emoji: "🌱", label: "Simple", desc: "Plain language, clear analogies" },
  { key: "step-by-step", emoji: "📖", label: "Step-by-Step", desc: "Walk me through everything" },
  { key: "concise", emoji: "⚡", label: "Concise", desc: "Bullet points, get to the point" },
  { key: "technical", emoji: "🔧", label: "Technical", desc: "Precise, domain-expert level" },
  { key: "friendly", emoji: "🤝", label: "Friendly", desc: "Warm, encouraging, casual" },
] as const;

interface Message {
  role: "assistant" | "user";
  content: string;
}

interface SavedCapsule {
  title: string;
  capsule_type: string;
  tier: string;
  category?: string;
}

const ONBOARD_STEPS = [
  { key: "work", label: "Work & Life", icon: "💼", description: "Job, location, daily life" },
  { key: "health", label: "Health & Body", icon: "❤️", description: "Allergies, diet, conditions" },
  { key: "family", label: "Family & Home", icon: "🏠", description: "Household, pets, key people" },
  { key: "goals", label: "Goals & Interests", icon: "⭐", description: "Hobbies, what you want help with" },
];

const QUICK_RESPONSES: Record<string, string[]> = {
  start: [
    "I work in software engineering",
    "I'm a student",
    "I'm a parent and homemaker",
    "I'm retired",
  ],
  health: [
    "I have food allergies",
    "No restrictions, I'm easy",
    "I'm vegetarian",
    "Skip this for now",
  ],
  family: [
    "I live with my partner and kids",
    "I live alone",
    "I have a large extended family",
    "Skip this for now",
  ],
  goals: [
    "Share health info with family",
    "Keep my life organized",
    "Help me find local services",
    "All of the above!",
  ],
  general: [
    "Tell me more about that",
    "What else should I share?",
    "That's all for now",
  ],
};

function inferPhase(messageCount: number, capsuleCount: number): string {
  if (messageCount <= 2) return "start";
  if (capsuleCount >= 3) return "goals";
  if (capsuleCount >= 2) return "family";
  if (capsuleCount >= 1) return "health";
  return "general";
}

function capsuleToStepKey(cap: SavedCapsule): string | null {
  const cat = (cap.category || "").toLowerCase();
  const type = (cap.capsule_type || "").toLowerCase();
  if (type === "skill" || cat === "work") return "work";
  if (cat === "health" || (type === "preference" && /allerg|diet|medic|health|exercise|condition/i.test(cap.title))) return "health";
  if (type === "contact" || cat === "family" || cat === "social") return "family";
  if (cat === "personal" || cat === "goals" || /hobby|hobbies|goal|interest|help/i.test(cap.title)) return "goals";
  if (type === "preference") return "goals";
  return null;
}


export default function OnboardPage() {
  const { userId } = useParams<{ userId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [newCapsules, setNewCapsules] = useState<SavedCapsule[]>([]);
  const [started, setStarted] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [selectedPersonality, setSelectedPersonality] = useState<string>("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data: user } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });

  const { data: agent } = useQuery({
    queryKey: ["agent", userId],
    queryFn: () => api.getAgent(userId),
  });

  const { data: existingCapsules } = useQuery({
    queryKey: ["capsules", userId],
    queryFn: () => api.listCapsules(userId),
  });

  // Sync agent personality to local state once loaded
  useEffect(() => {
    if (agent?.personality && !selectedPersonality) {
      const known = PERSONALITY_MODES.map(m => m.key);
      const agentMode = known.find(k => agent.personality.startsWith(k) || agent.personality === k);
      if (agentMode) setSelectedPersonality(agentMode);
    }
  }, [agent, selectedPersonality]);

  const updateAgentMutation = useMutation({
    mutationFn: (personality: string) => api.updateAgent(userId, { personality }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent", userId] }),
  });

  const handleSelectPersonality = (key: string) => {
    setSelectedPersonality(key);
    updateAgentMutation.mutate(key);
  };

  const hasExistingData = (existingCapsules?.length ?? 0) > 0;
  const existingCount = existingCapsules?.length ?? 0;

  // Detect profile completeness: ≥3 distinct capsule types = "complete"
  const distinctTypes = new Set(existingCapsules?.map(c => c.capsule_type) ?? []);
  const isCompleteProfile = distinctTypes.size >= 3;
  const isSeededUser = hasExistingData && !isCompleteProfile;

  const goToDashboard = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["capsules", userId] });
    queryClient.invalidateQueries({ queryKey: ["user", userId] });
    router.push(`/${userId}`);
  }, [queryClient, router, userId]);

  const hasSpeech = typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

  const toggleVoice = useCallback(() => {
    if (isListening && recognitionRef.current) {
      if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
      recognitionRef.current.stop();
      setIsListening(false);
      return;
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const W = window as any;
    const SR = W.SpeechRecognition || W.webkitSpeechRecognition;
    if (!SR) return;

    const recognition = new SR();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognitionRef.current = recognition;

    let finalTranscript = "";

    const resetSilenceTimer = () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = setTimeout(() => { recognition.stop(); }, 4000);
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (event: any) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) { finalTranscript += transcript; }
        else { interim = transcript; }
      }
      setInput(finalTranscript + interim);
      resetSilenceTimer();
    };

    recognition.onend = () => {
      if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
      setIsListening(false);
    };

    recognition.onerror = () => {
      if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
      setIsListening(false);
    };

    recognition.start();
    setIsListening(true);
    resetSilenceTimer();
  }, [isListening]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!isStreaming) inputRef.current?.focus();
  }, [isStreaming]);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 200) + "px";
    }
  }, [input]);

  const handleTextareaInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
  }, []);

  const sendMessage = async (userMessage: string) => {
    setIsStreaming(true);

    const history = messages.map((m) => ({ role: m.role, content: m.content }));

    if (userMessage.trim()) {
      setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    }

    try {
      const res = await api.intakeStep(userId, userMessage, history);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No reader");

      const decoder = new TextDecoder();
      let assistantText = "";
      let buffer = "";

      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

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
              assistantText += event.data;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = { role: "assistant", content: assistantText };
                return updated;
              });
            } else if (event.type === "actions") {
              for (const action of event.data) {
                if (action.type === "capsule_created" || action.type === "capsule_updated") {
                  setNewCapsules((prev) => [
                    ...prev,
                    { title: action.title || "Untitled", capsule_type: action.capsule_type || "memory", tier: action.tier || "private", category: action.category },
                  ]);
                }
              }
            } else if (event.type === "error") {
              assistantText += `\n\n*Error: ${event.data}*`;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = { role: "assistant", content: assistantText };
                return updated;
              });
            }
          } catch {}
        }
      }
    } catch {
      setMessages((prev) => {
        const withoutPlaceholder = prev[prev.length - 1]?.content === "" ? prev.slice(0, -1) : prev;
        return [...withoutPlaceholder, { role: "assistant" as const, content: "Sorry, something went wrong. You can try again or skip to your dashboard." }];
      });
    }

    setIsStreaming(false);
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
  };

  const startOnboarding = () => {
    setStarted(true);
    sendMessage("");
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;
    sendMessage(input.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (input.trim() && !isStreaming) sendMessage(input.trim());
    }
  };

  const phase = inferPhase(messages.length, newCapsules.length);
  const suggestions = QUICK_RESPONSES[phase] || QUICK_RESPONSES.general;
  const completedStepKeys = new Set(
    newCapsules.map(capsuleToStepKey).filter((k): k is string => k !== null)
  );

  // Group existing capsules by type for the summary display
  const capsulesByType = existingCapsules?.reduce((acc, c) => {
    acc[c.capsule_type] = (acc[c.capsule_type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>) ?? {};

  // ── Shared personality selector ──
  const PersonalitySelector = ({ required }: { required?: boolean }) => (
    <div className="w-full max-w-md mb-6">
      <p className={`text-xs font-semibold uppercase tracking-wider mb-2.5 flex items-center gap-1.5 ${required && !selectedPersonality ? "text-accent" : "text-muted-foreground"}`}>
        How should your agent talk to you?
        {required && !selectedPersonality && (
          <span className="text-[9px] font-bold bg-accent/15 text-accent px-1.5 py-0.5 rounded-full">Required</span>
        )}
      </p>
      <div className={`grid grid-cols-5 gap-1.5 ${required && !selectedPersonality ? "ring-1 ring-accent/20 rounded-2xl p-1" : ""}`}>
        {PERSONALITY_MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => handleSelectPersonality(m.key)}
            title={m.desc}
            className={`flex flex-col items-center gap-1 p-2 rounded-xl border text-center transition-all ${
              selectedPersonality === m.key
                ? "border-accent bg-accent/10 text-accent"
                : "border-card-border bg-card hover:border-accent/40 hover:bg-accent/5 text-muted-foreground hover:text-foreground"
            }`}
          >
            <span className="text-base leading-none">{m.emoji}</span>
            <span className="text-[10px] font-medium leading-tight">{m.label}</span>
          </button>
        ))}
      </div>
      {selectedPersonality && (
        <p className="text-[11px] text-muted-foreground mt-1.5 text-center">
          {PERSONALITY_MODES.find(m => m.key === selectedPersonality)?.desc}
        </p>
      )}
    </div>
  );

  // ── Pre-start screen ──
  if (!started) {
    const firstName = user?.display_name?.split(" ")[0] || "";

    return (
      <div className="max-w-2xl mx-auto flex flex-col items-center justify-center min-h-[80vh] px-4">
        {/* Agent avatar */}
        <div className="relative mb-6">
          <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-accent to-accent-dim flex items-center justify-center shadow-2xl shadow-accent/30">
            <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z" />
              <circle cx="10" cy="16" r="1" /><circle cx="14" cy="16" r="1" />
            </svg>
          </div>
          <div className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-green-500 border-2 border-background flex items-center justify-center">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
        </div>

        {/* ── State: New user ── */}
        {!hasExistingData && (
          <>
            <h1 className="text-2xl font-bold mb-2 text-center">Let&apos;s get to know you, {firstName}!</h1>
            <p className="text-muted-foreground text-center max-w-md mb-6 text-sm leading-relaxed">
              Your AI agent needs to learn about you to be helpful. This takes about 2 minutes — just a quick conversation.
            </p>

            <PersonalitySelector required />

            <div className="w-full max-w-md mb-6">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">What we&apos;ll cover</p>
              <div className="grid grid-cols-2 gap-2">
                {ONBOARD_STEPS.map((step) => (
                  <div key={step.key} className="flex items-start gap-2.5 p-3 rounded-xl bg-card border border-card-border">
                    <span className="text-base mt-0.5">{step.icon}</span>
                    <div>
                      <p className="text-xs font-medium">{step.label}</p>
                      <p className="text-[10px] text-muted-foreground">{step.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {/* ── State: Seeded / partial data user (like Molly) ── */}
        {isSeededUser && (
          <>
            <h1 className="text-2xl font-bold mb-2 text-center">Your agent already knows you</h1>
            <p className="text-muted-foreground text-center max-w-md mb-4 text-sm leading-relaxed">
              There&apos;s already some info in your vault. Let&apos;s fill in the gaps — takes about 2 minutes.
            </p>

            {Object.keys(capsulesByType).length > 0 && (
              <div className="w-full max-w-md mb-5">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">What&apos;s already saved</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(capsulesByType).map(([type, count]) => (
                    <div key={type} className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium ${CAPSULE_TYPE_COLORS[type] || "bg-muted/15 text-muted-foreground border-card-border"}`}>
                      <span>{CAPSULE_TYPE_EMOJIS[type] || "📝"}</span>
                      <span>{count} {type}{count !== 1 ? "s" : ""}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <PersonalitySelector />
          </>
        )}

        {/* ── State: Complete profile — returning user ── */}
        {isCompleteProfile && (
          <>
            <h1 className="text-2xl font-bold mb-2 text-center">{existingCount} things in your vault</h1>
            <p className="text-muted-foreground text-center max-w-md mb-4 text-sm leading-relaxed">
              Here&apos;s what your agent knows. Continue to add more or update what it has.
            </p>

            {Object.keys(capsulesByType).length > 0 && (
              <div className="w-full max-w-md mb-5">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Latest in vault</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(capsulesByType).slice(0, 4).map(([type, count]) => (
                    <div key={type} className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium ${CAPSULE_TYPE_COLORS[type] || "bg-muted/15 text-muted-foreground border-card-border"}`}>
                      <span>{CAPSULE_TYPE_EMOJIS[type] || "📝"}</span>
                      <span>{count} {type}{count !== 1 ? "s" : ""}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <PersonalitySelector />
          </>
        )}

        {/* Security note */}
        <div className="flex items-center gap-2 mb-6 px-4 py-2 rounded-xl bg-green-500/5 border border-green-500/15">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-green-400 shrink-0">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          <p className="text-[11px] text-green-400/80">Everything is encrypted. You control who sees what.</p>
        </div>

        {/* CTA */}
        {/* New users must pick a personality before starting */}
        {(() => {
          const needsPersonality = !hasExistingData && !selectedPersonality;
          return (
            <div className="flex flex-col items-center gap-3">
              <button
                onClick={startOnboarding}
                disabled={needsPersonality}
                className="px-8 py-3.5 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-2xl text-sm transition-all hover:shadow-xl hover:shadow-accent/25 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100 disabled:hover:shadow-none"
              >
                {isCompleteProfile ? "Update My Agent" : isSeededUser ? "Continue with Agent" : "Start Conversation"}
              </button>
              {needsPersonality && (
                <p className="text-[11px] text-muted-foreground animate-pulse">
                  ↑ Pick a conversation style first
                </p>
              )}
              <button
                onClick={() => goToDashboard()}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                {hasExistingData ? "Go to Dashboard" : "I\u2019ll do this later"}
              </button>
            </div>
          );
        })()}
      </div>
    );
  }

  // ── Chat phase ──
  return (
    <div className="max-w-4xl mx-auto flex gap-5 h-[calc(100vh-6rem)]">
      {/* Sidebar */}
      <div className="w-52 shrink-0 hidden lg:flex flex-col gap-3">
        {/* Progress steps */}
        <div className="bg-card border border-card-border rounded-2xl p-4">
          <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-3">This Session</p>
          <div className="space-y-2">
            {ONBOARD_STEPS.map((step) => {
              const done = completedStepKeys.has(step.key);
              return (
                <div key={step.key} className="flex items-center gap-2">
                  <span className={`text-sm ${done ? "" : "opacity-30"}`}>{step.icon}</span>
                  <span className={`text-xs ${done ? "text-green-400" : "text-muted-foreground/50"}`}>
                    {step.label}
                  </span>
                  {done && (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" className="text-green-400 ml-auto shrink-0"><polyline points="20 6 9 17 4 12"/></svg>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Previously known */}
        {hasExistingData && (
          <div className="bg-card border border-card-border rounded-2xl p-4">
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Already Known</p>
            <p className="text-xs text-muted-foreground">{existingCount} memories in vault</p>
            <div className="flex flex-wrap gap-1 mt-2">
              {Object.entries(capsulesByType).map(([type, count]) => (
                <span key={type} className="text-[10px] px-1.5 py-0.5 rounded bg-card-hover text-muted-foreground">
                  {CAPSULE_TYPE_EMOJIS[type]} {count}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* New capsules saved this session */}
        {newCapsules.length > 0 && (
          <div className="bg-card border border-card-border rounded-2xl p-4 flex-1 overflow-y-auto">
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Added Today ({newCapsules.length})
            </p>
            <div className="space-y-1.5">
              {newCapsules.map((cap, i) => (
                <div key={i} className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border text-[10px] ${CAPSULE_TYPE_COLORS[cap.capsule_type] || "bg-muted/15 text-muted-foreground border-card-border"}`}>
                  <span>{CAPSULE_TYPE_EMOJIS[cap.capsule_type] || "📝"}</span>
                  <span className="truncate">{cap.title}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <button
          onClick={() => goToDashboard()}
          className="w-full py-2 text-xs font-medium text-muted-foreground hover:text-foreground bg-card border border-card-border rounded-xl hover:bg-card-hover transition-all"
        >
          Go to Dashboard
        </button>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between mb-4 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-accent to-accent-dim flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z" />
                <circle cx="10" cy="16" r="1" /><circle cx="14" cy="16" r="1" />
              </svg>
            </div>
            <div>
              <h2 className="text-sm font-semibold">Your Agent</h2>
              <p className="text-[10px] text-muted-foreground">
                {isStreaming ? "Thinking..." : newCapsules.length > 0 ? `${newCapsules.length} new items saved` : "Ready to help"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {newCapsules.length > 0 && (
              <span className="lg:hidden inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-500/10 text-green-400 border border-green-500/20">
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                {newCapsules.length} saved
              </span>
            )}
            <button
              onClick={() => goToDashboard()}
              className="lg:hidden px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground bg-card border border-card-border rounded-lg hover:bg-card-hover transition-all"
            >
              Dashboard
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-4 pb-4">
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} gap-2`}>
              {msg.role === "assistant" && (
                <div className="w-6 h-6 rounded-lg bg-accent/15 flex items-center justify-center shrink-0 mt-1">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
                    <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z" />
                    <circle cx="10" cy="16" r="1" /><circle cx="14" cy="16" r="1" />
                  </svg>
                </div>
              )}
              <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-accent text-accent-fg rounded-br-md"
                  : "bg-card border border-card-border rounded-bl-md"
              }`}>
                {msg.role === "assistant" ? (
                  <Markdown>{msg.content || "..."}</Markdown>
                ) : msg.content}
              </div>
            </div>
          ))}

          {isStreaming && messages.length > 0 && messages[messages.length - 1].role === "user" && (
            <div className="flex justify-start gap-2">
              <div className="w-6 h-6 rounded-lg bg-accent/15 flex items-center justify-center shrink-0 mt-1">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
                  <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z" />
                  <circle cx="10" cy="16" r="1" /><circle cx="14" cy="16" r="1" />
                </svg>
              </div>
              <div className="bg-card border border-card-border rounded-2xl rounded-bl-md px-4 py-3">
                <div className="flex gap-1.5">
                  <span className="w-1.5 h-1.5 bg-accent/40 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="w-1.5 h-1.5 bg-accent/40 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="w-1.5 h-1.5 bg-accent/40 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Suggestion chips */}
        {!isStreaming && messages.length > 0 && messages[messages.length - 1].role === "assistant" && (
          <div className="shrink-0 mb-2">
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className="px-2.5 py-1 text-xs font-medium bg-card border border-card-border rounded-full hover:border-accent/40 hover:text-accent hover:bg-accent/5 transition-all"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Input */}
        <form onSubmit={handleSubmit} className="shrink-0 relative">
          <div className={`flex items-end gap-2 bg-card border rounded-2xl p-2 transition-all ${
            isListening ? "border-red-500/50 ring-2 ring-red-500/20" : "border-card-border focus-within:ring-2 focus-within:ring-accent/30 focus-within:border-accent/30"
          }`}>
            {hasSpeech && (
              <button
                type="button"
                onClick={toggleVoice}
                disabled={isStreaming}
                className={`p-2 rounded-xl transition-all shrink-0 ${
                  isListening ? "bg-red-500/15 text-red-400 animate-pulse" : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
                } disabled:opacity-30`}
                title={isListening ? "Stop recording" : "Voice input"}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                  <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
                </svg>
              </button>
            )}
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={handleTextareaInput}
              onKeyDown={handleKeyDown}
              placeholder={isListening ? "Listening..." : isStreaming ? "Agent is thinking..." : "Type or tap the mic..."}
              disabled={isStreaming}
              className="flex-1 bg-transparent border-none px-2 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none disabled:opacity-50 resize-none min-h-[34px] max-h-[200px] overflow-y-auto"
            />
            <button
              type="submit"
              disabled={!input.trim() || isStreaming}
              className="px-3 py-2 bg-accent hover:bg-accent-hover text-accent-fg font-medium rounded-xl text-sm disabled:opacity-30 disabled:cursor-not-allowed transition-all shrink-0"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
              </svg>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
