"use client";

import { useState, useRef, useEffect } from "react";
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

export default function OnboardPage() {
  const { userId } = useParams<{ userId: string }>();
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [savedCapsules, setSavedCapsules] = useState<SavedCapsule[]>([]);
  const [started, setStarted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const { data: user } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when streaming ends
  useEffect(() => {
    if (!isStreaming) inputRef.current?.focus();
  }, [isStreaming]);

  const sendMessage = async (userMessage: string) => {
    setIsStreaming(true);

    // Build conversation history (exclude the current message)
    const history = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // Add user message to UI (unless it's the init trigger)
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

      // Add placeholder for assistant message
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
                updated[updated.length - 1] = {
                  role: "assistant",
                  content: assistantText,
                };
                return updated;
              });
            } else if (event.type === "actions") {
              for (const action of event.data) {
                if (
                  action.type === "capsule_created" ||
                  action.type === "capsule_updated"
                ) {
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
                updated[updated.length - 1] = {
                  role: "assistant",
                  content: assistantText,
                };
                return updated;
              });
            }
          } catch {}
        }
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev.slice(0, -1).length === prev.length ? prev : prev.slice(0, -1),
        {
          role: "assistant",
          content: "Sorry, something went wrong. You can try again or skip to your dashboard.",
        },
      ]);
    }

    setIsStreaming(false);
    setInput("");
  };

  const startOnboarding = () => {
    setStarted(true);
    sendMessage(""); // Empty triggers the intro
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;
    sendMessage(input.trim());
  };

  const capsuleTypeIcon = (type: string) => {
    const icons: Record<string, string> = {
      memory: "M",
      skill: "S",
      procedure: "P",
      schedule: "C",
      preference: "P",
      contact: "C",
    };
    return icons[type] || "?";
  };

  const capsuleTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      memory: "bg-blue-500/15 text-blue-400",
      skill: "bg-amber-500/15 text-amber-400",
      procedure: "bg-amber-500/15 text-amber-400",
      schedule: "bg-cyan-500/15 text-cyan-400",
      preference: "bg-pink-500/15 text-pink-400",
      contact: "bg-green-500/15 text-green-400",
    };
    return colors[type] || "bg-muted/15 text-muted-foreground";
  };

  // Pre-onboarding welcome screen
  if (!started) {
    return (
      <div className="max-w-2xl mx-auto flex flex-col items-center justify-center min-h-[70vh]">
        <div className="w-20 h-20 rounded-2xl bg-accent flex items-center justify-center mb-6 shadow-lg shadow-accent/20">
          <svg
            width="36"
            height="36"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#09090b"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z" />
            <circle cx="10" cy="16" r="1" />
            <circle cx="14" cy="16" r="1" />
          </svg>
        </div>
        <h1 className="text-2xl font-bold mb-2 text-center">
          Welcome to TrustMesh{user ? `, ${user.display_name}` : ""}!
        </h1>
        <p className="text-muted-foreground text-center max-w-md mb-2">
          Your personal AI agent is ready. Let&apos;s take a minute to get to know you so your agent can help you better.
        </p>
        <p className="text-xs text-muted-foreground text-center max-w-md mb-8">
          Everything you share is encrypted in your personal vault (AES-256-GCM). Only you control who sees what.
        </p>
        <div className="flex gap-3">
          <button
            onClick={startOnboarding}
            className="px-8 py-3 bg-accent hover:bg-accent-hover text-accent-fg font-semibold rounded-xl text-sm transition-all hover:shadow-lg hover:shadow-accent/20"
          >
            Let&apos;s go
          </button>
          <button
            onClick={() => router.push(`/${userId}`)}
            className="px-6 py-3 text-sm text-muted-foreground hover:text-foreground rounded-xl hover:bg-card-hover transition-colors"
          >
            Skip for now
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto flex flex-col h-[calc(100vh-8rem)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-accent flex items-center justify-center">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#09090b"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.27A7 7 0 0 1 14 22h-4a7 7 0 0 1-6.73-3H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z" />
              <circle cx="10" cy="16" r="1" />
              <circle cx="14" cy="16" r="1" />
            </svg>
          </div>
          <div>
            <h2 className="text-sm font-semibold">Getting to know you</h2>
            <p className="text-[11px] text-muted-foreground">
              Your agent is saving info to your encrypted vault
            </p>
          </div>
        </div>
        <button
          onClick={() => router.push(`/${userId}`)}
          className="px-4 py-2 text-xs text-muted-foreground hover:text-foreground bg-card border border-card-border rounded-xl hover:bg-card-hover transition-all"
        >
          Go to Dashboard
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 pb-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-accent text-accent-fg rounded-br-md"
                  : "bg-card border border-card-border rounded-bl-md"
              }`}
            >
              {msg.role === "assistant" ? (
                <Markdown>{msg.content || "..."}</Markdown>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}

        {isStreaming && messages.length > 0 && messages[messages.length - 1].role === "user" && (
          <div className="flex justify-start">
            <div className="bg-card border border-card-border rounded-2xl rounded-bl-md px-4 py-3">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-accent/50 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-2 h-2 bg-accent/50 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-2 h-2 bg-accent/50 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Saved Capsules Ticker */}
      {savedCapsules.length > 0 && (
        <div className="shrink-0 mb-3">
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            <span className="text-[10px] text-muted-foreground shrink-0">Saved:</span>
            {savedCapsules.map((cap, i) => (
              <span
                key={i}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium shrink-0 ${capsuleTypeColor(cap.capsule_type)}`}
              >
                <span className="w-3.5 h-3.5 rounded flex items-center justify-center text-[8px] font-bold bg-black/10">
                  {capsuleTypeIcon(cap.capsule_type)}
                </span>
                {cap.title.length > 30 ? cap.title.slice(0, 30) + "..." : cap.title}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="shrink-0 flex gap-2">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={isStreaming ? "Agent is thinking..." : "Tell your agent about yourself..."}
          disabled={isStreaming}
          className="flex-1 bg-card border border-card-border rounded-xl px-4 py-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!input.trim() || isStreaming}
          className="px-5 py-3 bg-accent hover:bg-accent-hover text-accent-fg font-medium rounded-xl text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          Send
        </button>
      </form>
    </div>
  );
}
