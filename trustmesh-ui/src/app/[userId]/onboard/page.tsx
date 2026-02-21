"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Markdown } from "@/components/Markdown";

interface Message {
  role: "assistant" | "user";
  content: string;
}

interface SavedCapsule {
  title: string;
  capsule_type: string;
  tier: string;
}

// Topics the agent gathers — progress tracker
const ONBOARD_STEPS = [
  { key: "about", label: "About You", icon: "U", description: "Job, skills, interests" },
  { key: "people", label: "Your People", icon: "P", description: "Family, household, contacts" },
  { key: "prefs", label: "Preferences", icon: "H", description: "Allergies, diet, likes" },
  { key: "goals", label: "Goals", icon: "G", description: "What you want from TrustMesh" },
];

// Suggestion chips shown after each agent response to guide the user
const QUICK_RESPONSES: Record<string, string[]> = {
  start: [
    "I work in software engineering",
    "I'm a student",
    "I'm a parent and homemaker",
    "I'm retired",
  ],
  people: [
    "I live with my partner and kids",
    "I live alone",
    "I have a large extended family",
    "Skip this for now",
  ],
  prefs: [
    "I have food allergies",
    "No restrictions, I'm easy",
    "I'm vegetarian",
    "Skip this for now",
  ],
  goals: [
    "Share health info with family",
    "Find local services",
    "Keep my life organized",
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
  if (capsuleCount >= 2) return "prefs";
  if (capsuleCount >= 1) return "people";
  return "general";
}

const CAPSULE_ICONS: Record<string, string> = {
  memory: "M", skill: "S", procedure: "P",
  schedule: "C", preference: "H", contact: "P",
};

const CAPSULE_COLORS: Record<string, string> = {
  memory: "bg-blue-500/15 text-blue-400 border-blue-500/20",
  skill: "bg-amber-500/15 text-amber-400 border-amber-500/20",
  procedure: "bg-amber-500/15 text-amber-400 border-amber-500/20",
  schedule: "bg-cyan-500/15 text-cyan-400 border-cyan-500/20",
  preference: "bg-pink-500/15 text-pink-400 border-pink-500/20",
  contact: "bg-green-500/15 text-green-400 border-green-500/20",
};

export default function OnboardPage() {
  const { userId } = useParams<{ userId: string }>();
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [savedCapsules, setSavedCapsules] = useState<SavedCapsule[]>([]);
  const [started, setStarted] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);

  const { data: user } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });

  // Web Speech API — voice input
  const hasSpeech = typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

  const toggleVoice = useCallback(() => {
    if (isListening && recognitionRef.current) {
      recognitionRef.current.stop();
      setIsListening(false);
      return;
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const W = window as any;
    const SR = W.SpeechRecognition || W.webkitSpeechRecognition;
    if (!SR) return;

    const recognition = new SR();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognitionRef.current = recognition;

    let finalTranscript = "";

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (event: any) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interim = transcript;
        }
      }
      setInput(finalTranscript + interim);
      if (inputRef.current) {
        inputRef.current.style.height = "auto";
        inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 120) + "px";
      }
    };

    recognition.onend = () => {
      setIsListening(false);
      if (finalTranscript.trim()) {
        sendMessage(finalTranscript.trim());
        finalTranscript = "";
      }
    };

    recognition.onerror = () => {
      setIsListening(false);
    };

    recognition.start();
    setIsListening(true);
  }, [isListening]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when streaming ends
  useEffect(() => {
    if (!isStreaming) inputRef.current?.focus();
  }, [isStreaming]);

  // Auto-resize textarea
  const handleTextareaInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, []);

  const sendMessage = async (userMessage: string) => {
    setIsStreaming(true);

    const history = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

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
                  setSavedCapsules((prev) => [
                    ...prev,
                    {
                      title: action.title || "Untitled",
                      capsule_type: action.capsule_type || "memory",
                      tier: action.tier || "private",
                    },
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
        return [
          ...withoutPlaceholder,
          {
            role: "assistant" as const,
            content: "Sorry, something went wrong. You can try again or skip to your dashboard.",
          },
        ];
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

  const phase = inferPhase(messages.length, savedCapsules.length);
  const suggestions = QUICK_RESPONSES[phase] || QUICK_RESPONSES.general;
  const completedSteps = Math.min(savedCapsules.length, ONBOARD_STEPS.length);

  // ── Pre-start welcome ──
  if (!started) {
    return (
      <div className="max-w-2xl mx-auto flex flex-col items-center justify-center min-h-[80vh] px-4">
        {/* Agent avatar */}
        <div className="relative mb-8">
          <div className="w-24 h-24 rounded-3xl bg-gradient-to-br from-accent to-accent-dim flex items-center justify-center shadow-2xl shadow-accent/30">
            <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z" />
              <circle cx="10" cy="16" r="1" /><circle cx="14" cy="16" r="1" />
            </svg>
          </div>
          <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-green-500 border-2 border-background flex items-center justify-center">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
        </div>

        <h1 className="text-3xl font-bold mb-3 text-center">
          {user ? `Hey ${user.display_name.split(" ")[0]}!` : "Welcome!"}
        </h1>
        <p className="text-muted-foreground text-center max-w-md mb-8 text-base leading-relaxed">
          Your AI agent needs to get to know you to be helpful. This takes about 2 minutes — just a quick conversation.
        </p>

        {/* What we'll cover */}
        <div className="w-full max-w-md mb-8">
          <div className="grid grid-cols-2 gap-3">
            {ONBOARD_STEPS.map((step) => (
              <div
                key={step.key}
                className="flex items-start gap-3 p-3 rounded-xl bg-card border border-card-border"
              >
                <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center text-accent font-bold text-xs shrink-0">
                  {step.icon}
                </div>
                <div>
                  <p className="text-sm font-medium">{step.label}</p>
                  <p className="text-[11px] text-muted-foreground">{step.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Security note */}
        <div className="flex items-center gap-2 mb-8 px-4 py-2.5 rounded-xl bg-green-500/5 border border-green-500/15">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-green-400 shrink-0">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          <p className="text-xs text-green-400/80">
            Everything is encrypted and secure. You control who sees what.
          </p>
        </div>

        {/* CTA */}
        <div className="flex flex-col items-center gap-3">
          <button
            onClick={startOnboarding}
            className="px-10 py-4 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-2xl text-base transition-all hover:shadow-xl hover:shadow-accent/25 hover:scale-[1.02] active:scale-[0.98]"
          >
            Start Conversation
          </button>
          <button
            onClick={() => router.push(`/${userId}`)}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            I&apos;ll do this later
          </button>
        </div>
      </div>
    );
  }

  // ── Chat phase ──
  return (
    <div className="max-w-4xl mx-auto flex gap-6 h-[calc(100vh-6rem)]">
      {/* Sidebar: progress + saved capsules */}
      <div className="w-56 shrink-0 hidden lg:flex flex-col">
        {/* Progress steps */}
        <div className="bg-card border border-card-border rounded-2xl p-4 mb-4">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Progress</p>
          <div className="space-y-2.5">
            {ONBOARD_STEPS.map((step, i) => {
              const done = i < completedSteps;
              const active = i === completedSteps;
              return (
                <div key={step.key} className="flex items-center gap-2.5">
                  <div className={`w-6 h-6 rounded-lg flex items-center justify-center text-[10px] font-bold transition-all ${
                    done ? "bg-green-500/15 text-green-400" :
                    active ? "bg-accent/15 text-accent ring-1 ring-accent/30" :
                    "bg-card-hover text-muted-foreground/50"
                  }`}>
                    {done ? (
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                    ) : step.icon}
                  </div>
                  <span className={`text-xs ${done ? "text-green-400" : active ? "text-foreground font-medium" : "text-muted-foreground/50"}`}>
                    {step.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Saved capsules */}
        {savedCapsules.length > 0 && (
          <div className="bg-card border border-card-border rounded-2xl p-4 flex-1 overflow-y-auto">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              Saved ({savedCapsules.length})
            </p>
            <div className="space-y-2">
              {savedCapsules.map((cap, i) => (
                <div
                  key={i}
                  className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-xs ${
                    CAPSULE_COLORS[cap.capsule_type] || "bg-muted/15 text-muted-foreground border-card-border"
                  }`}
                >
                  <span className="w-5 h-5 rounded flex items-center justify-center text-[9px] font-bold bg-black/10 shrink-0">
                    {CAPSULE_ICONS[cap.capsule_type] || "?"}
                  </span>
                  <span className="truncate">{cap.title}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Done button */}
        <button
          onClick={() => router.push(`/${userId}`)}
          className="mt-4 w-full py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground bg-card border border-card-border rounded-xl hover:bg-card-hover transition-all"
        >
          Go to Dashboard
        </button>
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between mb-4 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent to-accent-dim flex items-center justify-center">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#09090b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z" />
                <circle cx="10" cy="16" r="1" /><circle cx="14" cy="16" r="1" />
              </svg>
            </div>
            <div>
              <h2 className="text-sm font-semibold">Your Agent</h2>
              <p className="text-[11px] text-muted-foreground">
                {isStreaming ? "Typing..." : `${savedCapsules.length} items saved`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Mobile: show capsule count */}
            {savedCapsules.length > 0 && (
              <span className="lg:hidden inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-medium bg-green-500/10 text-green-400 border border-green-500/20">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                {savedCapsules.length} saved
              </span>
            )}
            <button
              onClick={() => router.push(`/${userId}`)}
              className="lg:hidden px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground bg-card border border-card-border rounded-lg hover:bg-card-hover transition-all"
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
                <div className="w-7 h-7 rounded-lg bg-accent/15 flex items-center justify-center shrink-0 mt-1">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
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
                ) : (
                  msg.content
                )}
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {isStreaming && messages.length > 0 && messages[messages.length - 1].role === "user" && (
            <div className="flex justify-start gap-2">
              <div className="w-7 h-7 rounded-lg bg-accent/15 flex items-center justify-center shrink-0 mt-1">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
                  <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z" />
                  <circle cx="10" cy="16" r="1" /><circle cx="14" cy="16" r="1" />
                </svg>
              </div>
              <div className="bg-card border border-card-border rounded-2xl rounded-bl-md px-4 py-3">
                <div className="flex gap-1.5">
                  <span className="w-2 h-2 bg-accent/40 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="w-2 h-2 bg-accent/40 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="w-2 h-2 bg-accent/40 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Suggestion chips */}
        {!isStreaming && messages.length > 0 && messages[messages.length - 1].role === "assistant" && (
          <div className="shrink-0 mb-3">
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className="px-3 py-1.5 text-xs font-medium bg-card border border-card-border rounded-full hover:border-accent/40 hover:text-accent hover:bg-accent/5 transition-all"
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
            {/* Mic button */}
            {hasSpeech && (
              <button
                type="button"
                onClick={toggleVoice}
                disabled={isStreaming}
                className={`p-2 rounded-xl transition-all shrink-0 ${
                  isListening
                    ? "bg-red-500/15 text-red-400 animate-pulse"
                    : "text-muted-foreground hover:text-foreground hover:bg-card-hover"
                } disabled:opacity-30`}
                title={isListening ? "Stop recording" : "Voice input"}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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
              placeholder={isListening ? "Listening..." : isStreaming ? "Agent is thinking..." : "Type or tap the mic to talk..."}
              disabled={isStreaming}
              className="flex-1 bg-transparent border-none px-2 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none disabled:opacity-50 resize-none min-h-[36px] max-h-[120px]"
            />
            <button
              type="submit"
              disabled={!input.trim() || isStreaming}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-accent-fg font-medium rounded-xl text-sm disabled:opacity-30 disabled:cursor-not-allowed transition-all shrink-0"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
              </svg>
            </button>
          </div>
          <p className="text-[10px] text-muted-foreground/50 mt-1.5 text-center">
            Press Enter to send, Shift+Enter for new line
          </p>
        </form>
      </div>
    </div>
  );
}
