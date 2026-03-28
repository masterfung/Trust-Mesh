"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Shield, Wifi, Globe, ArrowRight, Check, Copy } from "lucide-react";

type ConnectivityMode = "relay_primary" | "direct_with_fallback" | "invite_only";

const MODES: {
  id: ConnectivityMode;
  label: string;
  sublabel: string;
  description: string;
  Icon: React.ElementType;
  recommended?: boolean;
}[] = [
  {
    id: "relay_primary",
    label: "Always available",
    sublabel: "Best for staying connected",
    description:
      "Anyone with your invite link can reach your agent, even when your device is off. Your messages queue until you're back online.",
    Icon: Globe,
  },
  {
    id: "direct_with_fallback",
    label: "Only when online",
    sublabel: "Good for home labs & VPS",
    description:
      "People can query your agent while your device is running. When you're offline, they'll see you as unavailable.",
    Icon: Wifi,
  },
  {
    id: "invite_only",
    label: "Invite only",
    sublabel: "Recommended to start",
    description:
      "You control who can connect. Share a link when you're ready. Nothing is public until you choose to share it.",
    Icon: Shield,
    recommended: true,
  },
];

export default function DiscoverySetupPage() {
  const params = useParams();
  const userId = params.userId as string;
  const router = useRouter();
  const queryClient = useQueryClient();

  const [selected, setSelected] = useState<ConnectivityMode>("invite_only");
  const [copied, setCopied] = useState(false);

  const { data: capsules } = useQuery({
    queryKey: ["capsules", userId],
    queryFn: () => api.listCapsules(userId),
  });

  const { data: user } = useQuery({
    queryKey: ["user", userId],
    queryFn: () => api.getUser(userId),
  });

  const updateMutation = useMutation({
    mutationFn: () => api.updateConnectivityMode(userId, selected),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user", userId] });
      router.push(`/${userId}`);
    },
  });

  const capsuleCount = capsules?.length ?? 0;

  // Placeholder invite link — real invite link generation is Phase 2
  const inviteLink = `${window?.location?.origin ?? "https://trustmesh.net"}/invite?did=pending`;

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(inviteLink);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-4">
      <div className="w-full max-w-xl">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="w-12 h-12 rounded-xl bg-accent/20 flex items-center justify-center mx-auto mb-4">
            <Shield className="w-6 h-6 text-accent" />
          </div>
          {capsuleCount > 0 ? (
            <h1 className="text-2xl font-bold text-fg mb-2">Your vault is ready</h1>
          ) : (
            <h1 className="text-2xl font-bold text-fg mb-2">Almost there</h1>
          )}
          {capsuleCount > 0 && (
            <p className="text-fg-muted text-sm">
              You saved{" "}
              <span className="font-semibold text-accent">{capsuleCount} capsule{capsuleCount !== 1 ? "s" : ""}</span>{" "}
              during setup.
            </p>
          )}
          <p className="text-fg-muted text-sm mt-1">
            How do you want{user?.display_name ? ` ${user.display_name.split(" ")[0]}` : " your agent"} to be reachable?
          </p>
        </div>

        {/* Mode selector */}
        <div className="space-y-3 mb-8">
          {MODES.map(({ id, label, sublabel, description, Icon, recommended }) => {
            const isSelected = selected === id;
            return (
              <button
                key={id}
                onClick={() => setSelected(id)}
                className={[
                  "w-full text-left p-4 rounded-xl border-2 transition-all",
                  isSelected
                    ? "border-accent bg-accent/5"
                    : "border-border bg-surface-2 hover:border-accent/40",
                ].join(" ")}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={[
                      "w-10 h-10 rounded-lg flex items-center justify-center shrink-0 mt-0.5",
                      isSelected ? "bg-accent/20" : "bg-surface-3",
                    ].join(" ")}
                  >
                    <Icon
                      className={["w-5 h-5", isSelected ? "text-accent" : "text-fg-muted"].join(" ")}
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-fg">{label}</span>
                      {recommended && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent font-medium">
                          recommended
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-fg-muted mt-0.5">{sublabel}</p>
                    {isSelected && (
                      <p className="text-sm text-fg-muted mt-2 leading-relaxed">{description}</p>
                    )}
                  </div>
                  <div
                    className={[
                      "w-5 h-5 rounded-full border-2 shrink-0 mt-0.5 flex items-center justify-center",
                      isSelected ? "border-accent bg-accent" : "border-border",
                    ].join(" ")}
                  >
                    {isSelected && <Check className="w-3 h-3 text-white" strokeWidth={3} />}
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-3">
          <button
            onClick={handleCopyLink}
            className="flex items-center justify-center gap-2 w-full py-2.5 px-4 rounded-lg border border-border text-fg-muted text-sm hover:bg-surface-2 transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-4 h-4 text-success" />
                <span>Copied!</span>
              </>
            ) : (
              <>
                <Copy className="w-4 h-4" />
                <span>Get my invite link</span>
              </>
            )}
          </button>

          <button
            onClick={() => updateMutation.mutate()}
            disabled={updateMutation.isPending}
            className="flex items-center justify-center gap-2 w-full py-3 px-4 rounded-xl bg-accent text-white font-semibold text-sm hover:bg-accent/90 transition-colors disabled:opacity-60"
          >
            {updateMutation.isPending ? (
              <span>Saving...</span>
            ) : (
              <>
                <span>Go to my dashboard</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>

        {/* Skip */}
        <p className="text-center text-xs text-fg-muted mt-4">
          You can change this anytime in{" "}
          <button
            className="underline hover:text-fg transition-colors"
            onClick={() => router.push(`/${userId}`)}
          >
            pod settings
          </button>
          .
        </p>
      </div>
    </div>
  );
}
