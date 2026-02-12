# TrustMesh: Agent Escalation & Delegation Patterns

A comprehensive guide to implementing multi-agent orchestration, human escalation, and async request handling for trust-aware knowledge sharing.

---

## Table of Contents

1. [Agent-to-Agent Delegation](#1-agent-to-agent-delegation)
2. [Agent-to-Human Escalation](#2-agent-to-human-escalation)
3. [Async Request Queues](#3-async-request-queues)
4. [Multi-Agent Orchestration Frameworks](#4-multi-agent-orchestration-frameworks)
5. [Human-in-the-Loop Patterns](#5-human-in-the-loop-patterns)

---

## 1. Agent-to-Agent Delegation

### 1.1 Protocol Design

Agent-to-agent communication requires a standardized protocol for:
- Query forwarding with context preservation
- Trust score propagation
- Multi-hop chain tracking
- Response aggregation

#### Core Protocol Specification

```typescript
// types/agent-protocol.ts

/**
 * Agent Query Protocol (AQP)
 * Defines how agents communicate across the TrustMesh network
 */

export interface AgentQueryRequest {
  id: string; // Unique request ID for tracking
  from_agent_id: string;
  original_requester_id: string; // Preserve original questioner
  question: string;
  context: {
    trust_chain: TrustHop[];
    shared_networks: string[];
    urgency: "low" | "medium" | "high";
    timeout_ms: number;
  };
  metadata: {
    created_at: string;
    hops_remaining: number; // Prevent infinite loops
    max_hops: number;
  };
}

export interface TrustHop {
  agent_id: string;
  user_id: string;
  trust_level: number; // 0-1, cumulative trust
  timestamp: string;
}

export interface AgentQueryResponse {
  request_id: string;
  from_agent_id: string;
  status: "answered" | "delegated" | "escalated" | "failed";
  answer?: string;
  confidence: number; // 0-1, how confident is this answer
  delegated_to?: {
    agent_id: string;
    reason: string;
  };
  escalated_to?: {
    user_id: string;
    reason: string;
  };
  metadata: {
    processing_time_ms: number;
    hops_taken: number;
  };
}

/**
 * Agent Delegation Decision Engine
 * Determines if a query should be answered, delegated, or escalated
 */
export interface DelegationDecision {
  action: "answer" | "delegate" | "escalate";
  confidence: number;
  reasoning: string;
  target_agent_id?: string;
  target_user_id?: string;
}
```

### 1.2 Multi-Hop Query Resolution

How agents handle queries when they don't have answers:

```typescript
// services/agent-delegation.ts

import { Database } from "@supabase/supabase-js";

export class AgentDelegationService {
  constructor(
    private supabase: Database,
    private trustCalculator: TrustCalculator
  ) {}

  /**
   * Process incoming agent query with delegation logic
   */
  async processAgentQuery(
    request: AgentQueryRequest
  ): Promise<AgentQueryResponse> {
    const startTime = Date.now();

    // Step 1: Check if this agent has the answer
    const answer = await this.findLocalAnswer(request.question);

    if (answer && answer.confidence > 0.7) {
      return this.createResponse(request, "answered", answer.content, answer.confidence);
    }

    // Step 2: Check if we should delegate further
    if (request.metadata.hops_remaining <= 0) {
      return this.createResponse(request, "escalated", undefined, 0, request.original_requester_id);
    }

    // Step 3: Find the best agent to delegate to
    const delegationTargets = await this.findBestDelegates(
      request.question,
      request.context.shared_networks,
      request.context.trust_chain
    );

    if (delegationTargets.length > 0) {
      const bestTarget = delegationTargets[0];
      const delegatedResponse = await this.forwardQuery(
        request,
        bestTarget,
        startTime
      );
      return delegatedResponse;
    }

    // Step 4: If no suitable agent found, escalate to human owner
    return this.createResponse(
      request,
      "escalated",
      undefined,
      0,
      request.original_requester_id
    );
  }

  /**
   * Find agents capable of answering a question
   */
  private async findBestDelegates(
    question: string,
    sharedNetworks: string[],
    trustChain: TrustHop[]
  ): Promise<AgentCandidate[]> {
    // Query agents who:
    // 1. Have expertise in the topic (via capsule categories)
    // 2. Are in shared networks
    // 3. Have sufficient trust scores

    const { data: agents } = await this.supabase
      .from("agents")
      .select(
        `
        id,
        owner_id,
        expertise_categories,
        users!inner(id, connections(to_user_id))
      `
      )
      .in("expertise_categories", this.extractTopics(question));

    if (!agents) return [];

    // Score agents by trust and expertise relevance
    const scored = agents.map((agent) => ({
      agent_id: agent.id,
      owner_id: agent.owner_id,
      expertise_match: this.calculateExpertiseMatch(question, agent),
      trust_score: this.calculateTrustScore(agent.owner_id, trustChain),
      is_in_shared_network: sharedNetworks.some(
        (nid) =>
          agent.users?.networks?.some((n: any) => n.id === nid)
      ),
    }));

    // Sort by combined score (expertise + trust + network proximity)
    return scored
      .filter((s) => s.trust_score > 0.3) // Minimum trust threshold
      .sort((a, b) => {
        const aScore = a.expertise_match * 0.4 + a.trust_score * 0.4 +
          (a.is_in_shared_network ? 0.2 : 0);
        const bScore = b.expertise_match * 0.4 + b.trust_score * 0.4 +
          (b.is_in_shared_network ? 0.2 : 0);
        return bScore - aScore;
      });
  }

  /**
   * Forward query to another agent with reduced hop count
   */
  private async forwardQuery(
    originalRequest: AgentQueryRequest,
    target: AgentCandidate,
    startTime: number
  ): Promise<AgentQueryResponse> {
    const forwardedRequest: AgentQueryRequest = {
      ...originalRequest,
      from_agent_id: originalRequest.from_agent_id,
      metadata: {
        ...originalRequest.metadata,
        hops_remaining: originalRequest.metadata.hops_remaining - 1,
      },
      context: {
        ...originalRequest.context,
        trust_chain: [
          ...originalRequest.context.trust_chain,
          {
            agent_id: originalRequest.from_agent_id,
            user_id: (await this.getAgentOwner(originalRequest.from_agent_id)).id,
            trust_level: target.trust_score,
            timestamp: new Date().toISOString(),
          },
        ],
      },
    };

    try {
      // Call target agent's API endpoint
      const response = await fetch(
        `${process.env.AGENT_MESH_BASE_URL}/agents/${target.agent_id}/query`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(forwardedRequest),
          timeout: originalRequest.context.timeout_ms,
        }
      );

      const delegatedResponse: AgentQueryResponse = await response.json();

      // Log delegation chain
      await this.logDelegationChain(
        originalRequest.id,
        originalRequest.from_agent_id,
        target.agent_id,
        delegatedResponse.status
      );

      return delegatedResponse;
    } catch (error) {
      // If delegation fails, escalate
      return this.createResponse(
        originalRequest,
        "escalated",
        undefined,
        0,
        originalRequest.original_requester_id
      );
    }
  }

  private createResponse(
    request: AgentQueryRequest,
    status: "answered" | "delegated" | "escalated" | "failed",
    answer?: string,
    confidence: number = 0,
    escalateToUserId?: string
  ): AgentQueryResponse {
    return {
      request_id: request.id,
      from_agent_id: request.from_agent_id,
      status,
      answer,
      confidence,
      escalated_to: escalateToUserId
        ? { user_id: escalateToUserId, reason: "No suitable agent found" }
        : undefined,
      metadata: {
        processing_time_ms: Date.now(),
        hops_taken: request.metadata.max_hops - request.metadata.hops_remaining,
      },
    };
  }

  private async findLocalAnswer(question: string): Promise<any> {
    // Search through owned capsules for relevant answers
    // Implementation depends on your knowledge base structure
    return null;
  }

  private calculateExpertiseMatch(question: string, agent: any): number {
    // Implement semantic similarity between question and agent expertise
    return 0;
  }

  private calculateTrustScore(userId: string, trustChain: TrustHop[]): number {
    // Calculate cumulative trust using the chain
    return 0;
  }

  private extractTopics(question: string): string[] {
    // NLP-based topic extraction
    return [];
  }

  private async getAgentOwner(agentId: string) {
    return { id: "user-id" };
  }

  private async logDelegationChain(
    requestId: string,
    fromAgentId: string,
    toAgentId: string,
    status: string
  ) {
    // Log for auditing and learning
  }
}

interface AgentCandidate {
  agent_id: string;
  owner_id: string;
  expertise_match: number;
  trust_score: number;
  is_in_shared_network: boolean;
}
```

### 1.3 Google A2A (Agent-to-Agent) Pattern

Google's A2A framework (from their enterprise AI research) follows these principles:

```typescript
// patterns/google-a2a-pattern.ts

/**
 * Google A2A Pattern for TrustMesh
 * Adapted from: "Agent-to-Agent Communication for Enterprise AI"
 * Key principles:
 * 1. Agents are autonomous but coordinated
 * 2. Trust is explicit and measured
 * 3. Delegation includes capability assertion
 * 4. Responses include provenance tracking
 */

export interface A2ACapabilityAssertion {
  // What can this agent do?
  agent_id: string;
  capabilities: string[]; // e.g., ["financial-analysis", "risk-assessment"]
  confidence_levels: Record<string, number>; // capability -> confidence
  verified_by: string[]; // Other agents that have verified this
  updated_at: string;
}

export interface A2ARequest {
  // Standard A2A message format
  id: string;
  requester: {
    agent_id: string;
    user_id: string;
    timestamp: string;
  };
  task: {
    description: string;
    required_capability: string;
    priority: "low" | "normal" | "high" | "urgent";
    deadline_ms: number;
  };
  context_requirements: {
    networks: string[];
    trust_minimum: number;
    sensitivity_level: "public" | "internal" | "sensitive" | "confidential";
  };
  callback: {
    webhook_url: string;
    timeout_ms: number;
  };
}

export interface A2AResponse {
  request_id: string;
  responder: {
    agent_id: string;
    user_id: string;
    timestamp: string;
  };
  result: {
    status: "success" | "partial" | "delegated" | "escalated";
    data?: any;
    confidence: number;
    metadata: {
      processing_time_ms: number;
      delegation_chain: string[]; // [agent-1, agent-2, agent-3]
      capsules_consulted: string[];
    };
  };
  provenance: {
    // Track source of information
    sources: Array<{
      capsule_id: string;
      capsule_owner: string;
      trust_level: number;
      relevance_score: number;
    }>;
    reasoning_trail: string; // Explanation of why/how answer was derived
  };
}

/**
 * A2A Agent Implementation
 */
export class A2AAgent {
  private capabilities: A2ACapabilityAssertion;
  private delegationRules: DelegationRule[];

  async handleA2ARequest(request: A2ARequest): Promise<A2AResponse> {
    // 1. Verify request authenticity and permissions
    const isAuthorized = await this.verifyRequestAuthorization(request);
    if (!isAuthorized) {
      return this.deniedResponse(request, "Unauthorized request");
    }

    // 2. Check if we have the capability
    const hasCapability =
      this.capabilities.capabilities.includes(request.task.required_capability);
    const capabilityConfidence = hasCapability
      ? this.capabilities.confidence_levels[request.task.required_capability] ?? 0
      : 0;

    // 3. Decide: answer, delegate, or escalate
    if (capabilityConfidence > 0.8) {
      // We can answer with high confidence
      return this.answerRequest(request);
    } else if (capabilityConfidence > 0.3) {
      // We can partially answer
      return this.partialAnswer(request, capabilityConfidence);
    } else {
      // Find best delegate
      const delegates = await this.findBestDelegates(request);
      if (delegates.length > 0) {
        return this.delegateRequest(request, delegates[0]);
      } else {
        return this.escalateToHuman(request);
      }
    }
  }

  private async verifyRequestAuthorization(request: A2ARequest): Promise<boolean> {
    // Check: Is requester in shared network? Does requester have trust?
    return true;
  }

  private async answerRequest(request: A2ARequest): Promise<A2AResponse> {
    // Find relevant capsules and synthesize answer
    const relevantCapsules = await this.findRelevantCapsules(
      request.task.description
    );

    const answer = await this.synthesizeAnswer(
      request.task.description,
      relevantCapsules
    );

    return {
      request_id: request.id,
      responder: {
        agent_id: this.id,
        user_id: this.ownerId,
        timestamp: new Date().toISOString(),
      },
      result: {
        status: "success",
        data: answer,
        confidence: 0.9,
        metadata: {
          processing_time_ms: 250,
          delegation_chain: [this.id],
          capsules_consulted: relevantCapsules.map((c) => c.id),
        },
      },
      provenance: {
        sources: relevantCapsules.map((c) => ({
          capsule_id: c.id,
          capsule_owner: c.owner_id,
          trust_level: 0.85,
          relevance_score: 0.92,
        })),
        reasoning_trail:
          "Answer derived from capsules X, Y, Z using semantic search and synthesis",
      },
    };
  }

  private async delegateRequest(
    request: A2ARequest,
    delegate: AgentDelegate
  ): Promise<A2AResponse> {
    // Forward to delegate with callback
    const delegationId = `del-${request.id}`;

    // Store delegation promise to track response
    const response = await this.forwardToAgent(delegate.agent_id, {
      ...request,
      requester: {
        agent_id: this.id, // Now we're the requester
        user_id: this.ownerId,
        timestamp: new Date().toISOString(),
      },
      callback: {
        webhook_url: `${process.env.SELF_URL}/webhooks/delegation/${delegationId}`,
        timeout_ms: 5000,
      },
    });

    return {
      request_id: request.id,
      responder: {
        agent_id: this.id,
        user_id: this.ownerId,
        timestamp: new Date().toISOString(),
      },
      result: {
        status: "delegated",
        confidence: delegate.confidence,
        metadata: {
          processing_time_ms: 100,
          delegation_chain: [this.id, delegate.agent_id],
          capsules_consulted: [],
        },
      },
      provenance: {
        sources: [],
        reasoning_trail: `Request delegated to agent ${delegate.agent_id} due to higher expertise confidence`,
      },
    };
  }

  private async escalateToHuman(request: A2ARequest): Promise<A2AResponse> {
    // Notify human owner and queue request
    await this.notifyOwner({
      type: "escalation",
      request_id: request.id,
      reason: "No agent with sufficient capability found",
      originated_by: request.requester.agent_id,
    });

    return {
      request_id: request.id,
      responder: {
        agent_id: this.id,
        user_id: this.ownerId,
        timestamp: new Date().toISOString(),
      },
      result: {
        status: "escalated",
        confidence: 0,
        metadata: {
          processing_time_ms: 150,
          delegation_chain: [this.id],
          capsules_consulted: [],
        },
      },
      provenance: {
        sources: [],
        reasoning_trail:
          "Escalated to human owner for decision; no AI agent capable of handling this request",
      },
    };
  }

  private async findBestDelegates(request: A2ARequest): Promise<AgentDelegate[]> {
    // Use agent registry to find best match
    return [];
  }

  private async findRelevantCapsules(query: string) {
    return [];
  }

  private async synthesizeAnswer(query: string, capsules: any[]) {
    return "answer";
  }

  private async forwardToAgent(agentId: string, request: A2ARequest) {
    return {};
  }

  private async notifyOwner(notification: any) {}

  private deniedResponse(request: A2ARequest, reason: string): A2AResponse {
    return {
      request_id: request.id,
      responder: {
        agent_id: this.id,
        user_id: this.ownerId,
        timestamp: new Date().toISOString(),
      },
      result: {
        status: "escalated",
        confidence: 0,
        metadata: {
          processing_time_ms: 0,
          delegation_chain: [this.id],
          capsules_consulted: [],
        },
      },
      provenance: {
        sources: [],
        reasoning_trail: reason,
      },
    };
  }

  private id = "agent-123";
  private ownerId = "user-456";
}

interface AgentDelegate {
  agent_id: string;
  user_id: string;
  confidence: number;
  reason: string;
}

interface DelegationRule {
  condition: string;
  target_agent: string;
}
```

---

## 2. Agent-to-Human Escalation

### 2.1 Multi-Channel Notification Strategy

When agents can't resolve a query, they escalate to the human owner through multiple channels:

```typescript
// services/notification-service.ts

import * as Sentry from "@sentry/node";

export type NotificationChannel =
  | "push"
  | "email"
  | "sms"
  | "in_app"
  | "webhook";

export interface NotificationPayload {
  id: string;
  user_id: string;
  type: "escalation" | "approval" | "update" | "alert";
  priority: "low" | "medium" | "high" | "urgent";
  title: string;
  message: string;
  action_url?: string;
  context: {
    request_id: string;
    from_agent_id: string;
    from_user_id?: string;
    original_question?: string;
    suggested_action?: string;
  };
  expires_at: string;
}

/**
 * Smart Notification Router
 * Selects appropriate channels based on user preferences and priority
 */
export class NotificationService {
  constructor(
    private supabase: any,
    private webPushService: WebPushService,
    private emailService: EmailService,
    private smsService: SmsService,
    private webhookService: WebhookService
  ) {}

  /**
   * Send escalation notification through optimal channels
   */
  async notifyEscalation(payload: NotificationPayload): Promise<void> {
    // Step 1: Get user notification preferences
    const preferences = await this.getUserNotificationPrefs(payload.user_id);

    // Step 2: Select channels based on priority and preferences
    const channels = this.selectOptimalChannels(
      payload.priority,
      preferences
    );

    // Step 3: Send through all selected channels in parallel
    const results = await Promise.allSettled(
      channels.map((channel) => this.sendViaChannel(channel, payload))
    );

    // Step 4: Log results and retry failed attempts
    await this.logNotificationResults(payload.id, results);
    await this.scheduleRetries(payload.id, results);

    // Step 5: Create in-app notification record
    await this.createInAppNotification(payload);
  }

  private selectOptimalChannels(
    priority: string,
    preferences: UserNotificationPreferences
  ): NotificationChannel[] {
    const channels: NotificationChannel[] = [];

    // Urgent: Use all available channels
    if (priority === "urgent") {
      if (preferences.push_enabled) channels.push("push");
      if (preferences.email_enabled) channels.push("email");
      if (preferences.sms_enabled) channels.push("sms");
      channels.push("in_app");
      if (preferences.webhook_url) channels.push("webhook");
      return channels;
    }

    // High: Push + Email + In-app
    if (priority === "high") {
      if (preferences.push_enabled) channels.push("push");
      if (preferences.email_enabled) channels.push("email");
      channels.push("in_app");
      return channels;
    }

    // Medium/Low: Email + In-app
    channels.push("in_app");
    if (preferences.email_enabled) channels.push("email");
    return channels;
  }

  private async sendViaChannel(
    channel: NotificationChannel,
    payload: NotificationPayload
  ): Promise<void> {
    try {
      switch (channel) {
        case "push":
          await this.webPushService.send(payload);
          break;
        case "email":
          await this.emailService.send(payload);
          break;
        case "sms":
          await this.smsService.send(payload);
          break;
        case "webhook":
          await this.webhookService.send(payload);
          break;
        case "in_app":
          // Handled separately
          break;
      }
    } catch (error) {
      Sentry.captureException(error, {
        contexts: { notification: { channel, payload_id: payload.id } },
      });
      throw error;
    }
  }

  private async logNotificationResults(
    notificationId: string,
    results: PromiseSettledResult<void>[]
  ): Promise<void> {
    await this.supabase.from("notification_logs").insert({
      notification_id: notificationId,
      channels_attempted: results.length,
      channels_successful: results.filter((r) => r.status === "fulfilled").length,
      timestamp: new Date().toISOString(),
    });
  }

  private async scheduleRetries(
    notificationId: string,
    results: PromiseSettledResult<void>[]
  ): Promise<void> {
    const failedChannels = results
      .map((r, i) => (r.status === "rejected" ? i : null))
      .filter((i) => i !== null);

    if (failedChannels.length > 0) {
      // Schedule retry with exponential backoff
      await this.scheduleRetry(notificationId, 5000); // 5 seconds
    }
  }

  private async createInAppNotification(payload: NotificationPayload): Promise<void> {
    await this.supabase.from("notifications").insert({
      user_id: payload.user_id,
      type: payload.type,
      title: payload.title,
      message: payload.message,
      action_url: payload.action_url,
      context: payload.context,
      is_read: false,
      expires_at: payload.expires_at,
      created_at: new Date().toISOString(),
    });
  }

  private async scheduleRetry(notificationId: string, delayMs: number): Promise<void> {
    // Implementation: Use job queue (e.g., Bull, RabbitMQ)
  }

  private async getUserNotificationPrefs(
    userId: string
  ): Promise<UserNotificationPreferences> {
    const { data } = await this.supabase
      .from("user_notification_settings")
      .select("*")
      .eq("user_id", userId)
      .single();

    return data || getDefaultPreferences();
  }
}

interface UserNotificationPreferences {
  push_enabled: boolean;
  push_token?: string;
  email_enabled: boolean;
  email?: string;
  sms_enabled: boolean;
  phone?: string;
  webhook_url?: string;
  quiet_hours_start?: string; // HH:MM format
  quiet_hours_end?: string;
  do_not_disturb: boolean;
}

function getDefaultPreferences(): UserNotificationPreferences {
  return {
    push_enabled: true,
    email_enabled: true,
    sms_enabled: false,
    webhook_url: undefined,
    do_not_disturb: false,
  };
}
```

### 2.2 Web Push Notifications

```typescript
// services/web-push-service.ts

import webpush from "web-push";

export class WebPushService {
  constructor() {
    webpush.setVapidDetails(
      process.env.WEB_PUSH_SUBJECT || "mailto:support@trustmesh.ai",
      process.env.WEB_PUSH_PUBLIC_KEY || "",
      process.env.WEB_PUSH_PRIVATE_KEY || ""
    );
  }

  async send(payload: NotificationPayload): Promise<void> {
    // Get user's push subscription
    const { data: subscription } = await supabase
      .from("user_push_subscriptions")
      .select("subscription")
      .eq("user_id", payload.user_id)
      .single();

    if (!subscription?.subscription) {
      throw new Error("No push subscription for user");
    }

    const pushPayload = {
      title: payload.title,
      body: payload.message,
      icon: "https://trustmesh.ai/icon-192x192.png",
      badge: "https://trustmesh.ai/badge-72x72.png",
      tag: payload.context.request_id, // Group similar notifications
      requireInteraction: payload.priority === "urgent",
      actions: [
        {
          action: "open",
          title: "Review",
          icon: "https://trustmesh.ai/open-icon.png",
        },
        {
          action: "dismiss",
          title: "Dismiss",
          icon: "https://trustmesh.ai/dismiss-icon.png",
        },
      ],
      data: {
        action_url: payload.action_url,
        context: JSON.stringify(payload.context),
      },
    };

    await webpush.sendNotification(
      JSON.parse(subscription.subscription),
      JSON.stringify(pushPayload)
    );
  }
}

/**
 * Frontend: Register for web push notifications
 * Place this in your React component (e.g., layout or settings page)
 */
export async function registerPushNotifications(userId: string): Promise<void> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    console.warn("Push notifications not supported");
    return;
  }

  try {
    const registration = await navigator.serviceWorker.register("/sw.js");
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(
        process.env.NEXT_PUBLIC_WEB_PUSH_PUBLIC_KEY || ""
      ),
    });

    // Send subscription to server
    await fetch("/api/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        subscription: subscription,
      }),
    });
  } catch (error) {
    console.error("Failed to register push notifications:", error);
  }
}

// Service Worker (public/sw.js)
self.addEventListener("push", (event) => {
  const data = event.data?.json() ?? {};

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon,
      badge: data.badge,
      tag: data.tag,
      requireInteraction: data.requireInteraction,
      actions: data.actions,
      data: data.data,
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  if (event.action === "dismiss") {
    return;
  }

  const actionUrl = event.notification.data.action_url;
  event.waitUntil(
    clients.matchAll({ type: "window" }).then((clientList) => {
      // Focus existing window if open
      for (const client of clientList) {
        if (client.url === actionUrl && "focus" in client) {
          return (client as any).focus();
        }
      }
      // Open new window if not open
      if (clients.openWindow) {
        return clients.openWindow(actionUrl);
      }
    })
  );
});

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding)
    .replace(/\-/g, "+")
    .replace(/_/g, "/");

  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);

  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }

  return outputArray;
}
```

### 2.3 Email Notifications

```typescript
// services/email-service.ts

import nodemailer from "nodemailer";

export class EmailService {
  private transporter: nodemailer.Transporter;

  constructor() {
    this.transporter = nodemailer.createTransport({
      host: process.env.SMTP_HOST,
      port: parseInt(process.env.SMTP_PORT || "587"),
      secure: process.env.SMTP_SECURE === "true",
      auth: {
        user: process.env.SMTP_USER,
        pass: process.env.SMTP_PASSWORD,
      },
    });
  }

  async send(payload: NotificationPayload): Promise<void> {
    const user = await this.getUser(payload.user_id);
    if (!user?.email) {
      throw new Error("User has no email");
    }

    // Check quiet hours
    if (this.isInQuietHours(user)) {
      // Queue for later delivery
      await this.queueForLaterDelivery(payload, user.email);
      return;
    }

    const emailContent = this.formatEmailContent(payload);

    await this.transporter.sendMail({
      from: process.env.EMAIL_FROM,
      to: user.email,
      subject: `[TrustMesh ${payload.priority.toUpperCase()}] ${payload.title}`,
      html: emailContent,
      text: this.stripHtml(emailContent),
      replyTo: process.env.SUPPORT_EMAIL,
      headers: {
        "X-Trustmesh-Request-ID": payload.context.request_id,
        "X-Trustmesh-Type": payload.type,
      },
    });
  }

  private formatEmailContent(payload: NotificationPayload): string {
    return `
      <html>
        <head>
          <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif; }
            .container { max-width: 600px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
            .body { line-height: 1.6; color: #333; }
            .button { display: inline-block; background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 20px 0; }
            .context { background: #f5f5f5; padding: 15px; border-left: 4px solid #667eea; margin: 15px 0; border-radius: 4px; font-family: monospace; }
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>${payload.title}</h1>
            </div>
            <div class="body">
              <p>${payload.message}</p>

              ${payload.context.original_question ? `
                <div class="context">
                  <strong>Original Question:</strong><br/>
                  ${payload.context.original_question}
                </div>
              ` : ""}

              ${payload.context.suggested_action ? `
                <p><strong>Suggested Action:</strong> ${payload.context.suggested_action}</p>
              ` : ""}

              ${payload.action_url ? `
                <a href="${payload.action_url}" class="button">Review in TrustMesh</a>
              ` : ""}

              <hr style="margin: 30px 0; border: none; border-top: 1px solid #ddd;">
              <p style="color: #999; font-size: 12px;">
                Request ID: ${payload.context.request_id}<br/>
                Priority: ${payload.priority}<br/>
                This notification will expire at ${new Date(payload.expires_at).toLocaleString()}
              </p>
            </div>
          </div>
        </body>
      </html>
    `;
  }

  private isInQuietHours(user: any): boolean {
    // Implementation: Check user's quiet hours settings
    return false;
  }

  private async getUser(userId: string) {
    return null;
  }

  private async queueForLaterDelivery(payload: NotificationPayload, email: string) {
    // Queue for delivery at end of quiet hours
  }

  private stripHtml(html: string): string {
    return html.replace(/<[^>]*>/g, "");
  }
}
```

### 2.4 SMS Notifications (Twilio)

```typescript
// services/sms-service.ts

import twilio from "twilio";

export class SmsService {
  private client: twilio.Twilio;

  constructor() {
    this.client = twilio(
      process.env.TWILIO_ACCOUNT_SID,
      process.env.TWILIO_AUTH_TOKEN
    );
  }

  async send(payload: NotificationPayload): Promise<void> {
    const user = await this.getUser(payload.user_id);
    if (!user?.phone) {
      throw new Error("User has no phone number");
    }

    // Compose SMS message (max 160 chars)
    const smsBody = this.composeSmsMessage(payload);

    const message = await this.client.messages.create({
      body: smsBody,
      from: process.env.TWILIO_PHONE_NUMBER,
      to: user.phone,
    });

    // Log SMS delivery
    await this.logSmsDelivery(payload.user_id, payload.id, message.sid);
  }

  private composeSmsMessage(payload: NotificationPayload): string {
    const maxLength = 160;
    const priority = payload.priority === "urgent" ? "[URGENT] " : "";
    const baseMessage = `${priority}${payload.title}: ${payload.message}`;

    if (payload.action_url) {
      const shortUrl = this.generateShortUrl(payload.action_url);
      return `${baseMessage} ${shortUrl}`.substring(0, maxLength);
    }

    return baseMessage.substring(0, maxLength);
  }

  private generateShortUrl(url: string): string {
    // In production, use a URL shortener service
    return "tm.sh/req123";
  }

  private async getUser(userId: string) {
    return null;
  }

  private async logSmsDelivery(userId: string, notificationId: string, messageSid: string) {
    // Log for delivery tracking
  }
}
```

### 2.5 Webhook Notifications

```typescript
// services/webhook-service.ts

export class WebhookService {
  async send(payload: NotificationPayload): Promise<void> {
    const user = await this.getUser(payload.user_id);
    const webhookUrl = user?.notification_webhook_url;

    if (!webhookUrl) {
      throw new Error("User has no webhook URL configured");
    }

    const webhookPayload = {
      event: "agent.escalation",
      timestamp: new Date().toISOString(),
      notification: payload,
      signature: this.generateHmacSignature(payload),
    };

    // Retry logic with exponential backoff
    const maxRetries = 3;
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const response = await fetch(webhookUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-TrustMesh-Signature": webhookPayload.signature,
            "X-TrustMesh-Delivery": payload.id,
          },
          body: JSON.stringify(webhookPayload),
          timeout: 10000,
        });

        if (response.ok) {
          await this.logWebhookDelivery(payload.id, true);
          return;
        }

        if (!response.ok && response.status >= 500) {
          // Retry on server errors
          throw new Error(`Server error: ${response.status}`);
        }
      } catch (error) {
        if (attempt === maxRetries - 1) {
          await this.logWebhookDelivery(payload.id, false, error);
          throw error;
        }
        // Exponential backoff
        await new Promise((resolve) =>
          setTimeout(resolve, Math.pow(2, attempt) * 1000)
        );
      }
    }
  }

  private generateHmacSignature(payload: any): string {
    const crypto = require("crypto");
    const secret = process.env.WEBHOOK_SECRET || "";
    return crypto
      .createHmac("sha256", secret)
      .update(JSON.stringify(payload))
      .digest("hex");
  }

  private async getUser(userId: string) {
    return null;
  }

  private async logWebhookDelivery(
    notificationId: string,
    success: boolean,
    error?: any
  ) {
    // Log delivery attempt
  }
}
```

---

## 3. Async Request Queues

### 3.1 Pending Request Queue Architecture

When a query can't be answered immediately, it enters an async workflow:

```typescript
// models/pending-request.ts

export interface PendingRequest {
  id: string; // Unique request ID
  from_agent_id: string;
  from_user_id: string;
  to_agent_id: string;
  to_user_id: string;
  question: string;

  // Status tracking
  status: "pending" | "owner_notified" | "owner_viewing" | "answered" | "expired" | "failed";

  // Timeline
  created_at: string;
  owner_notified_at?: string;
  owner_viewed_at?: string;
  answered_at?: string;
  expires_at: string;

  // Response handling
  response?: string;
  response_confidence?: number;

  // Callback information
  callback?: {
    webhook_url: string;
    retry_count: number;
    last_attempt_at?: string;
  };

  // Metadata
  priority: "low" | "medium" | "high" | "urgent";
  context: Record<string, any>;
  tags: string[];
}

// Supabase schema (SQL):
/*
CREATE TABLE pending_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  from_agent_id UUID NOT NULL REFERENCES agents(id),
  from_user_id UUID NOT NULL REFERENCES users(id),
  to_agent_id UUID NOT NULL REFERENCES agents(id),
  to_user_id UUID NOT NULL REFERENCES users(id),
  question TEXT NOT NULL,

  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT NOW(),
  owner_notified_at TIMESTAMP,
  owner_viewed_at TIMESTAMP,
  answered_at TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,

  response TEXT,
  response_confidence FLOAT,

  callback_webhook_url TEXT,
  callback_retry_count INT DEFAULT 0,
  callback_last_attempt TIMESTAMP,

  priority TEXT DEFAULT 'medium',
  context JSONB,
  tags TEXT[],

  FOREIGN KEY (from_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
  FOREIGN KEY (from_user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (to_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
  FOREIGN KEY (to_user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_pending_requests_status ON pending_requests(status);
CREATE INDEX idx_pending_requests_to_user ON pending_requests(to_user_id);
CREATE INDEX idx_pending_requests_expires ON pending_requests(expires_at);
*/
```

### 3.2 Async Request Service

```typescript
// services/pending-request-service.ts

export class PendingRequestService {
  constructor(
    private supabase: any,
    private notificationService: NotificationService,
    private webhookService: WebhookService
  ) {}

  /**
   * Create a new pending request when agent can't answer
   */
  async createPendingRequest(
    fromAgentId: string,
    toAgentId: string,
    toUserId: string,
    question: string,
    priority: string = "medium",
    callbackUrl?: string
  ): Promise<PendingRequest> {
    const expiresAt = new Date();
    expiresAt.setHours(expiresAt.getHours() + 24); // 24-hour expiry

    const { data, error } = await this.supabase
      .from("pending_requests")
      .insert({
        from_agent_id: fromAgentId,
        from_user_id: await this.getAgentOwner(fromAgentId),
        to_agent_id: toAgentId,
        to_user_id: toUserId,
        question,
        status: "pending",
        priority,
        expires_at: expiresAt.toISOString(),
        callback_webhook_url: callbackUrl,
        created_at: new Date().toISOString(),
      })
      .select()
      .single();

    if (error) throw error;

    // Notify owner immediately
    await this.notifyOwner(data);

    return data;
  }

  /**
   * Poll for pending requests (called by human owner's UI)
   */
  async getPendingRequests(userId: string): Promise<PendingRequest[]> {
    const { data, error } = await this.supabase
      .from("pending_requests")
      .select(
        `
        *,
        from_agent:from_agent_id(id, name),
        from_user:from_user_id(id, username, display_name)
      `
      )
      .eq("to_user_id", userId)
      .eq("status", "pending")
      .order("priority", { ascending: false })
      .order("created_at", { ascending: true });

    if (error) throw error;

    // Mark as viewed
    await this.markAsViewed(data.map((r) => r.id), userId);

    return data;
  }

  /**
   * Human submits response to pending request
   */
  async respondToPendingRequest(
    requestId: string,
    response: string,
    confidence: number = 0.9
  ): Promise<void> {
    // Step 1: Update request with response
    const { data: request, error } = await this.supabase
      .from("pending_requests")
      .update({
        response,
        response_confidence: confidence,
        status: "answered",
        answered_at: new Date().toISOString(),
      })
      .eq("id", requestId)
      .select()
      .single();

    if (error) throw error;

    // Step 2: Trigger webhook callback if configured
    if (request.callback_webhook_url) {
      await this.deliverCallback(request);
    }

    // Step 3: Notify original requester
    await this.notifyRequester(request);
  }

  /**
   * Deliver response back to requesting agent via webhook
   */
  private async deliverCallback(request: PendingRequest): Promise<void> {
    const callback = {
      event: "pending_request.answered",
      request_id: request.id,
      response: request.response,
      confidence: request.response_confidence,
      answered_at: request.answered_at,
      timestamp: new Date().toISOString(),
    };

    const maxRetries = 5;
    let lastError: Error | null = null;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const response = await fetch(request.callback_webhook_url!, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-TrustMesh-Signature": this.generateSignature(callback),
            "X-Request-ID": request.id,
          },
          body: JSON.stringify(callback),
          timeout: 10000,
        });

        if (response.ok) {
          // Success
          await this.updateCallbackStatus(request.id, true, attempt);
          return;
        }

        if (response.status >= 500) {
          // Retry on server errors
          throw new Error(`Server error: ${response.status}`);
        }

        // Client error - don't retry
        throw new Error(`Client error: ${response.status}`);
      } catch (error) {
        lastError = error as Error;

        if (attempt < maxRetries - 1) {
          // Exponential backoff: 1s, 2s, 4s, 8s, 16s
          const delayMs = Math.pow(2, attempt) * 1000;
          await new Promise((resolve) => setTimeout(resolve, delayMs));
        }
      }
    }

    // Failed after all retries
    await this.updateCallbackStatus(request.id, false, maxRetries, lastError);
  }

  /**
   * Clean up expired pending requests
   * (Run as scheduled job, e.g., every hour)
   */
  async cleanupExpiredRequests(): Promise<number> {
    const now = new Date().toISOString();

    const { error, rowCount } = await this.supabase
      .from("pending_requests")
      .update({ status: "expired" })
      .eq("status", "pending")
      .lt("expires_at", now);

    if (error) throw error;

    // Notify original requesters that their queries expired
    await this.notifyExpiredRequests();

    return rowCount || 0;
  }

  /**
   * Check request timeout and escalate if needed
   */
  async checkRequestTimeout(
    requestId: string,
    timeoutMs: number = 3600000
  ): Promise<void> {
    const { data: request } = await this.supabase
      .from("pending_requests")
      .select()
      .eq("id", requestId)
      .single();

    if (!request) return;

    const createdTime = new Date(request.created_at).getTime();
    const elapsedTime = Date.now() - createdTime;

    if (elapsedTime > timeoutMs && request.status === "pending") {
      // Escalate - send reminder notification
      await this.notificationService.notifyEscalation({
        id: `reminder-${requestId}`,
        user_id: request.to_user_id,
        type: "escalation",
        priority: "high",
        title: "Pending Request Awaiting Your Response",
        message: `An agent is waiting for your response to this question: "${request.question}"`,
        action_url: `/dashboard/pending/${requestId}`,
        context: {
          request_id: requestId,
          from_agent_id: request.from_agent_id,
          from_user_id: request.from_user_id,
          original_question: request.question,
        },
        expires_at: request.expires_at,
      });
    }
  }

  private async notifyOwner(request: PendingRequest): Promise<void> {
    await this.notificationService.notifyEscalation({
      id: request.id,
      user_id: request.to_user_id,
      type: "escalation",
      priority: request.priority as any,
      title: "New Question from Agent",
      message: `Agent "${request.from_agent_id}" has forwarded a question: "${request.question}"`,
      action_url: `/dashboard/pending-requests`,
      context: {
        request_id: request.id,
        from_agent_id: request.from_agent_id,
        from_user_id: request.from_user_id,
        original_question: request.question,
      },
      expires_at: request.expires_at,
    });
  }

  private async notifyRequester(request: PendingRequest): Promise<void> {
    // Notify the agent that requested this query that a response is ready
    // This could be via webhook, push notification to agent system, etc.
  }

  private async notifyExpiredRequests(): Promise<void> {
    // Query all recently expired requests and notify their owners
  }

  private async markAsViewed(
    requestIds: string[],
    userId: string
  ): Promise<void> {
    await this.supabase
      .from("pending_requests")
      .update({
        status: "owner_viewing",
        owner_viewed_at: new Date().toISOString(),
      })
      .in("id", requestIds);
  }

  private async updateCallbackStatus(
    requestId: string,
    success: boolean,
    attempts: number,
    error?: Error
  ): Promise<void> {
    await this.supabase
      .from("pending_requests")
      .update({
        callback_retry_count: attempts,
        callback_last_attempt: new Date().toISOString(),
      })
      .eq("id", requestId);
  }

  private generateSignature(payload: any): string {
    const crypto = require("crypto");
    return crypto
      .createHmac("sha256", process.env.WEBHOOK_SECRET || "")
      .update(JSON.stringify(payload))
      .digest("hex");
  }

  private async getAgentOwner(agentId: string): Promise<string> {
    const { data } = await this.supabase
      .from("agents")
      .select("owner_id")
      .eq("id", agentId)
      .single();
    return data?.owner_id;
  }
}
```

### 3.3 Status Tracking & State Machine

```typescript
// types/request-state.ts

export type RequestState =
  | { status: "pending"; created_at: string }
  | { status: "owner_notified"; notified_at: string }
  | { status: "owner_viewing"; viewed_at: string }
  | { status: "answered"; response: string; answered_at: string }
  | { status: "callback_pending"; callback_url: string; retry_count: number }
  | { status: "callback_delivered"; delivered_at: string }
  | { status: "callback_failed"; reason: string; final_attempt_at: string }
  | { status: "expired"; expired_at: string }
  | { status: "failed"; reason: string; failed_at: string };

/**
 * State machine for pending requests
 * Ensures valid state transitions
 */
export class RequestStateMachine {
  private currentState: RequestState;

  constructor(initialState: RequestState) {
    this.currentState = initialState;
  }

  /**
   * Attempt to transition to new state
   * Returns true if transition is valid, false otherwise
   */
  transition(newState: RequestState): boolean {
    const validTransitions: Record<string, string[]> = {
      pending: ["owner_notified", "expired", "failed"],
      owner_notified: ["owner_viewing", "expired", "failed"],
      owner_viewing: ["answered", "expired", "failed"],
      answered: ["callback_pending", "expired"],
      callback_pending: ["callback_delivered", "callback_failed"],
      callback_delivered: [],
      callback_failed: [],
      expired: [],
      failed: [],
    };

    const currentStatus = this.currentState.status;
    const newStatus = newState.status;

    if (!validTransitions[currentStatus]?.includes(newStatus)) {
      return false;
    }

    this.currentState = newState;
    return true;
  }

  getState(): RequestState {
    return this.currentState;
  }
}
```

---

## 4. Multi-Agent Orchestration Frameworks (2025-2026)

### 4.1 LangGraph Integration

LangGraph is an excellent framework for multi-agent orchestration with built-in support for delegation:

```typescript
// agents/langgraph-orchestrator.ts

import { StateGraph, END, START } from "@langchain/langgraph";
import { BaseMessage, HumanMessage } from "@langchain/core/messages";
import { ToolNode } from "@langchain/langgraph/prebuilt";

/**
 * LangGraph State Definition for TrustMesh
 */
interface AgentState {
  messages: BaseMessage[];
  question: string;
  agent_id: string;
  delegated_to?: string;
  response?: string;
  is_escalated: boolean;
  delegation_chain: string[];
  request_metadata: {
    created_at: string;
    timeout_ms: number;
    max_hops: number;
    trust_score: number;
  };
}

/**
 * Create a LangGraph-based agent orchestration workflow
 */
function createTrustMeshOrchestrator() {
  const workflow = new StateGraph<AgentState>();

  // Define nodes (steps in the workflow)

  // 1. Question Router - Decide what to do
  workflow.addNode("route_question", async (state: AgentState) => {
    const { question, agent_id, request_metadata } = state;

    // Check if agent has local answer
    const localAnswer = await checkLocalKnowledge(agent_id, question);

    if (localAnswer?.confidence > 0.7) {
      return {
        ...state,
        response: localAnswer.answer,
        messages: [
          ...state.messages,
          new HumanMessage({ content: `Found answer with confidence ${localAnswer.confidence}` }),
        ],
      };
    }

    // Check if we should delegate
    if (request_metadata.max_hops > 0) {
      return { ...state, /* delegate logic */ };
    }

    // Escalate to human
    return { ...state, is_escalated: true };
  });

  // 2. Delegate Agent - Find suitable delegates
  workflow.addNode("find_delegates", async (state: AgentState) => {
    const candidates = await findDelegateCandidates(
      state.question,
      state.request_metadata
    );

    return {
      ...state,
      delegated_to: candidates[0]?.agent_id,
      messages: [
        ...state.messages,
        new HumanMessage({
          content: `Found ${candidates.length} potential delegates`,
        }),
      ],
    };
  });

  // 3. Verify Trust - Ensure delegation is safe
  workflow.addNode("verify_trust", async (state: AgentState) => {
    if (!state.delegated_to) return state;

    const trustScore = await calculateTrustScore(
      state.agent_id,
      state.delegated_to,
      state.request_metadata
    );

    return {
      ...state,
      request_metadata: {
        ...state.request_metadata,
        trust_score: trustScore,
      },
    };
  });

  // 4. Forward Request - Send to delegate
  workflow.addNode("forward_request", async (state: AgentState) => {
    if (!state.delegated_to) return state;

    const delegatedResponse = await forwardToDelegate(
      state.delegated_to,
      state
    );

    return {
      ...state,
      response: delegatedResponse.answer,
      delegation_chain: [
        ...state.delegation_chain,
        state.delegated_to,
      ],
      messages: [
        ...state.messages,
        new HumanMessage({
          content: `Received delegated response: ${delegatedResponse.answer}`,
        }),
      ],
    };
  });

  // 5. Escalate to Human - Queue pending request
  workflow.addNode("escalate_to_human", async (state: AgentState) => {
    const pendingRequest = await createPendingRequest(state);

    return {
      ...state,
      is_escalated: true,
      messages: [
        ...state.messages,
        new HumanMessage({
          content: `Escalated to human with request ID: ${pendingRequest.id}`,
        }),
      ],
    };
  });

  // Define edges (transitions between nodes)
  workflow.setEntryPoint("route_question");

  // Conditional routing based on state
  workflow.addConditionalEdges(
    "route_question",
    (state: AgentState) => {
      if (state.response) return "generate_response"; // Found answer
      if (state.delegated_to) return "find_delegates"; // Will delegate
      return "escalate_to_human"; // No answer, escalate
    },
    {
      find_delegates: "find_delegates",
      generate_response: "generate_response",
      escalate_to_human: "escalate_to_human",
    }
  );

  workflow.addEdge("find_delegates", "verify_trust");
  workflow.addEdge("verify_trust", "forward_request");

  workflow.addConditionalEdges(
    "forward_request",
    (state: AgentState) => {
      if (state.response) return "generate_response";
      return "escalate_to_human";
    }
  );

  workflow.addNode("generate_response", async (state: AgentState) => {
    return state; // Response already set
  });

  workflow.addEdge("generate_response", END);
  workflow.addEdge("escalate_to_human", END);

  return workflow.compile();
}

// Helper functions
async function checkLocalKnowledge(
  agentId: string,
  question: string
): Promise<{ answer: string; confidence: number } | null> {
  // Implementation
  return null;
}

async function findDelegateCandidates(
  question: string,
  metadata: any
): Promise<any[]> {
  // Implementation
  return [];
}

async function calculateTrustScore(
  fromAgentId: string,
  toAgentId: string,
  metadata: any
): Promise<number> {
  // Implementation
  return 0;
}

async function forwardToDelegate(
  delegateId: string,
  state: AgentState
): Promise<{ answer: string }> {
  // Implementation
  return { answer: "" };
}

async function createPendingRequest(state: AgentState): Promise<any> {
  // Implementation
  return {};
}
```

### 4.2 CrewAI Pattern

CrewAI excels at hierarchical agent teams with role-based delegation:

```typescript
// agents/crewai-orchestrator.ts

/**
 * CrewAI-inspired agent team structure for TrustMesh
 * Implemented using TypeScript (CrewAI is Python, but pattern is portable)
 */

interface AgentRole {
  name: string;
  description: string;
  expertise_areas: string[];
  tools: Tool[];
  capabilities: string[];
}

interface TeamStructure {
  manager: AgentRole;
  specialists: AgentRole[];
  escalation_coordinator: AgentRole;
}

const trustmeshTeamStructure: TeamStructure = {
  manager: {
    name: "Query Router Agent",
    description: "Routes queries to appropriate specialists or escalates",
    expertise_areas: ["routing", "delegation", "trust-evaluation"],
    tools: [],
    capabilities: ["analyze-question", "route-to-specialist", "escalate"],
  },
  specialists: [
    {
      name: "Financial Expert Agent",
      description: "Handles financial analysis and investment questions",
      expertise_areas: ["finance", "investment", "accounting"],
      tools: [],
      capabilities: ["analyze-financial-data", "calculate-risks", "provide-recommendations"],
    },
    {
      name: "Technical Expert Agent",
      description: "Handles technical and engineering questions",
      expertise_areas: ["software", "infrastructure", "architecture"],
      tools: [],
      capabilities: ["code-review", "system-design", "technical-analysis"],
    },
    {
      name: "Domain Expert Agent",
      description: "Handles industry-specific questions",
      expertise_areas: ["domain-specific", "market-analysis"],
      tools: [],
      capabilities: ["market-research", "competitive-analysis"],
    },
  ],
  escalation_coordinator: {
    name: "Escalation Coordinator",
    description: "Handles escalation to human when needed",
    expertise_areas: ["escalation", "human-handoff"],
    tools: [],
    capabilities: ["notify-owner", "create-pending-request", "track-escalation"],
  },
};

/**
 * Hierarchical agent system
 */
class CrewAIOrchestrator {
  private manager: Agent;
  private specialists: Map<string, Agent>;
  private escalationCoordinator: Agent;

  async executeQuery(
    question: string,
    originalAgent: string,
    trustContext: any
  ): Promise<QueryResult> {
    // Step 1: Manager analyzes question
    const analysis = await this.manager.analyze({
      question,
      originalAgent,
      trustContext,
    });

    // Step 2: Manager delegates to appropriate specialist
    const specialist = this.selectSpecialist(analysis.relevant_areas);

    if (!specialist) {
      // No specialist can handle it
      return this.escalationCoordinator.escalate({
        question,
        originalAgent,
        reason: "No specialist available",
      });
    }

    // Step 3: Specialist attempts to answer
    const specialistResult = await specialist.answer(question, trustContext);

    if (specialistResult.confidence > 0.7) {
      return specialistResult;
    }

    // Step 4: If specialist not confident, escalate
    return this.escalationCoordinator.escalate({
      question,
      originalAgent,
      specialist_feedback: specialistResult.confidence,
      reason: "Specialist not confident in answer",
    });
  }

  private selectSpecialist(areas: string[]): Agent | null {
    // Find best matching specialist
    return null;
  }
}

interface Agent {
  analyze(data: any): Promise<any>;
  answer(question: string, context: any): Promise<QueryResult>;
}

interface QueryResult {
  confidence: number;
}
```

### 4.3 AutoGen Pattern

AutoGen (Microsoft) focuses on agent conversations and collaboration:

```typescript
// agents/autogen-orchestrator.ts

/**
 * AutoGen-inspired conversational multi-agent system
 */

interface ConversableAgent {
  name: string;
  system_prompt: string;
  capabilities: string[];
  async_mode: boolean;
}

const queryResolverConversation: ConversableAgent[] = [
  {
    name: "question_analyzer",
    system_prompt: `You are a question analyzer for the TrustMesh network.
      Your job is to:
      1. Analyze the incoming question
      2. Determine required expertise areas
      3. Suggest which agents should handle this
      4. Assess complexity (simple/medium/complex)`,
    capabilities: ["analyze", "classify"],
    async_mode: true,
  },
  {
    name: "knowledge_agent",
    system_prompt: `You are a knowledge search agent.
      Your job is to:
      1. Search through available capsules
      2. Find relevant information
      3. Rate answer confidence
      4. Suggest if delegation is needed`,
    capabilities: ["search", "rank", "assess-confidence"],
    async_mode: true,
  },
  {
    name: "delegation_coordinator",
    system_prompt: `You are the delegation coordinator.
      Your job is to:
      1. Find suitable agents to delegate to
      2. Check trust relationships
      3. Forward requests with context
      4. Collect responses from delegates`,
    capabilities: ["delegate", "verify-trust", "forward", "aggregate"],
    async_mode: true,
  },
  {
    name: "escalation_handler",
    system_prompt: `You are the escalation handler.
      Your job is to:
      1. Determine if human escalation is needed
      2. Create pending requests
      3. Notify the human owner
      4. Track escalation status`,
    capabilities: ["escalate", "notify", "track"],
    async_mode: true,
  },
];

/**
 * Conversational message passing system
 */
interface ConversationMessage {
  from: string;
  to: string;
  role: "user" | "assistant";
  content: string;
  metadata?: {
    request_id: string;
    timestamp: string;
    context?: any;
  };
}

class AutoGenOrchestrator {
  private agents: Map<string, ConversableAgent>;
  private messageQueue: ConversationMessage[];
  private conversationHistory: ConversationMessage[];

  async orchestrateQuery(question: string): Promise<void> {
    const initialMessage: ConversationMessage = {
      from: "system",
      to: "question_analyzer",
      role: "user",
      content: `Analyze this question and determine the best approach: "${question}"`,
      metadata: {
        request_id: generateId(),
        timestamp: new Date().toISOString(),
      },
    };

    this.messageQueue.push(initialMessage);

    // Process messages in queue
    while (this.messageQueue.length > 0) {
      const message = this.messageQueue.shift()!;
      const response = await this.processMessage(message);

      this.conversationHistory.push(message);
      this.conversationHistory.push(response);

      // If response indicates delegation needed, queue delegation messages
      if (this.shouldDelegate(response)) {
        const delegationMessages = await this.createDelegationMessages(response);
        this.messageQueue.push(...delegationMessages);
      }

      // If response indicates escalation needed, handle escalation
      if (this.shouldEscalate(response)) {
        await this.handleEscalation(response);
        break;
      }
    }
  }

  private async processMessage(
    message: ConversationMessage
  ): Promise<ConversationMessage> {
    const agent = this.agents.get(message.to);
    if (!agent) throw new Error(`Agent ${message.to} not found`);

    const response = await this.callAgentLLM(agent, message);

    return {
      from: message.to,
      to: message.from,
      role: "assistant",
      content: response,
      metadata: message.metadata,
    };
  }

  private async callAgentLLM(
    agent: ConversableAgent,
    message: ConversationMessage
  ): Promise<string> {
    // Call LLM (e.g., Claude) with agent's system prompt and conversation history
    return "";
  }

  private shouldDelegate(message: ConversationMessage): boolean {
    // Parse message to check if delegation is needed
    return message.content.toLowerCase().includes("delegate");
  }

  private shouldEscalate(message: ConversationMessage): boolean {
    // Parse message to check if escalation is needed
    return message.content.toLowerCase().includes("escalate");
  }

  private async createDelegationMessages(
    message: ConversationMessage
  ): Promise<ConversationMessage[]> {
    // Create delegation messages for coordinator
    return [];
  }

  private async handleEscalation(message: ConversationMessage): Promise<void> {
    // Delegate to escalation handler
  }
}

function generateId(): string {
  return Math.random().toString(36).substring(7);
}
```

### 4.4 Claude Agent SDK Pattern

Native support for agent-based workflows in Anthropic's Claude Agent SDK:

```typescript
// agents/claude-agent-orchestrator.ts

import Anthropic from "@anthropic-ai/sdk";

/**
 * Claude Agent SDK provides native support for multi-turn agent workflows
 * with tool use and delegation patterns
 */

const client = new Anthropic();

interface AgentTool {
  name: string;
  description: string;
  input_schema: Record<string, any>;
}

const trustmeshTools: AgentTool[] = [
  {
    name: "search_capsules",
    description: "Search through knowledge capsules for relevant information",
    input_schema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search query" },
        categories: { type: "array", items: { type: "string" } },
        min_trust_level: { type: "number", minimum: 0, maximum: 1 },
      },
      required: ["query"],
    },
  },
  {
    name: "delegate_query",
    description: "Delegate question to another agent in the network",
    input_schema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "Target agent ID" },
        question: { type: "string" },
        context: { type: "object" },
      },
      required: ["agent_id", "question"],
    },
  },
  {
    name: "escalate_to_human",
    description: "Escalate query to human owner for decision",
    input_schema: {
      type: "object",
      properties: {
        reason: { type: "string" },
        question: { type: "string" },
        suggested_action: { type: "string" },
        priority: {
          type: "string",
          enum: ["low", "medium", "high", "urgent"],
        },
      },
      required: ["reason", "question"],
    },
  },
  {
    name: "create_pending_request",
    description: "Create async pending request when human response needed",
    input_schema: {
      type: "object",
      properties: {
        question: { type: "string" },
        timeout_hours: { type: "number" },
        callback_url: { type: "string" },
        priority: {
          type: "string",
          enum: ["low", "medium", "high", "urgent"],
        },
      },
      required: ["question"],
    },
  },
];

/**
 * Main agent function using Claude with tool use
 */
async function trustmeshQueryAgent(question: string, agentId: string) {
  const messages: Anthropic.Messages.MessageParam[] = [
    {
      role: "user",
      content: question,
    },
  ];

  const systemPrompt = `You are an agent in the TrustMesh knowledge-sharing network.
Your job is to answer questions using available tools:

1. First, try to search local knowledge capsules
2. If you find good answers, return them
3. If not confident, consider delegating to other agents
4. If no agent can help, escalate to human owner

Always be explicit about:
- Your confidence level
- Information sources
- Why you're delegating or escalating

Current agent ID: ${agentId}`;

  // Multi-turn conversation loop
  for (let i = 0; i < 10; i++) {
    // Max 10 turns to prevent infinite loops
    const response = await client.messages.create({
      model: "claude-opus-4-6",
      max_tokens: 1024,
      system: systemPrompt,
      tools: trustmeshTools,
      messages,
    });

    // Add assistant response to messages
    messages.push({
      role: "assistant",
      content: response.content,
    });

    // Check if agent is done
    if (response.stop_reason === "end_turn") {
      // Extract final answer
      const finalAnswer = response.content
        .filter((block) => block.type === "text")
        .map((block) => (block as any).text)
        .join("\n");

      console.log("Final Answer:", finalAnswer);
      return;
    }

    // Process tool calls
    if (response.stop_reason === "tool_use") {
      const toolResults: Anthropic.Messages.MessageParam = {
        role: "user",
        content: [],
      };

      for (const block of response.content) {
        if (block.type === "tool_use") {
          const result = await executeTool(block.name, block.input);

          (toolResults.content as Anthropic.Messages.ToolResultBlockParam[]).push(
            {
              type: "tool_result",
              tool_use_id: block.id,
              content: JSON.stringify(result),
            }
          );
        }
      }

      messages.push(toolResults);
    }
  }
}

/**
 * Execute tool calls
 */
async function executeTool(
  toolName: string,
  input: Record<string, any>
): Promise<any> {
  switch (toolName) {
    case "search_capsules":
      return searchCapsules(input.query, input.categories, input.min_trust_level);

    case "delegate_query":
      return delegateToAgent(input.agent_id, input.question, input.context);

    case "escalate_to_human":
      return escalateToHuman(
        input.reason,
        input.question,
        input.suggested_action,
        input.priority
      );

    case "create_pending_request":
      return createPendingRequest(
        input.question,
        input.timeout_hours,
        input.callback_url,
        input.priority
      );

    default:
      throw new Error(`Unknown tool: ${toolName}`);
  }
}

async function searchCapsules(
  query: string,
  categories?: string[],
  minTrustLevel?: number
): Promise<any> {
  // Implementation
  return { results: [] };
}

async function delegateToAgent(
  agentId: string,
  question: string,
  context?: any
): Promise<any> {
  // Implementation - forward to another agent
  return { delegated: true, agent_id: agentId };
}

async function escalateToHuman(
  reason: string,
  question: string,
  suggestedAction?: string,
  priority?: string
): Promise<any> {
  // Implementation
  return { escalated: true };
}

async function createPendingRequest(
  question: string,
  timeoutHours?: number,
  callbackUrl?: string,
  priority?: string
): Promise<any> {
  // Implementation
  return { request_id: "req-123", status: "pending" };
}
```

---

## 5. Human-in-the-Loop Patterns

### 5.1 Approval Gate for Sensitive Information

```typescript
// services/approval-gate.ts

export interface SensitiveQueryApproval {
  request_id: string;
  from_user_id: string;
  from_agent_id: string;
  to_user_id: string;
  question: string;
  reason_sensitive: string; // Why is this sensitive?
  requires_approval: boolean;
  approved: boolean;
  approved_by?: string;
  approved_at?: string;
  approval_expires_at: string;
  conditions?: ApprovalCondition[];
}

export interface ApprovalCondition {
  type: "redact_sensitive_data" | "limit_scope" | "time_limited" | "one_time_use";
  parameters: Record<string, any>;
}

/**
 * Approval Gate Service
 * Ensures sensitive information sharing is approved by owner
 */
export class ApprovalGateService {
  constructor(
    private supabase: any,
    private notificationService: NotificationService,
    private citadelService: CitadelService // Trust evaluation service
  ) {}

  /**
   * Check if query requires approval
   */
  async requiresApproval(
    question: string,
    fromUserId: string,
    toUserId: string
  ): Promise<boolean> {
    // Factors that trigger approval requirement:
    // 1. Low trust between users
    // 2. Query contains sensitive keywords
    // 3. Information is marked as sensitive
    // 4. Network policies require it

    const trustLevel = await this.calculateTrustLevel(fromUserId, toUserId);
    const querySensitivity = await this.analyzeQuerySensitivity(question);
    const networkPolicy = await this.getNetworkPolicy(toUserId);

    return (
      trustLevel < 0.6 ||
      querySensitivity.is_sensitive ||
      networkPolicy.require_approval
    );
  }

  /**
   * Request approval from data owner
   */
  async requestApproval(
    fromUserId: string,
    fromAgentId: string,
    toUserId: string,
    question: string,
    conditions?: ApprovalCondition[]
  ): Promise<SensitiveQueryApproval> {
    const requestId = generateId();
    const sensitivityAnalysis = await this.analyzeQuerySensitivity(question);

    const approval: SensitiveQueryApproval = {
      request_id: requestId,
      from_user_id: fromUserId,
      from_agent_id: fromAgentId,
      to_user_id: toUserId,
      question,
      reason_sensitive: sensitivityAnalysis.reason,
      requires_approval: true,
      approved: false,
      approval_expires_at: new Date(
        Date.now() + 24 * 60 * 60 * 1000
      ).toISOString(), // 24-hour expiry
      conditions,
    };

    // Store in database
    await this.supabase
      .from("sensitive_query_approvals")
      .insert(approval);

    // Notify data owner
    await this.notificationService.notifyEscalation({
      id: requestId,
      user_id: toUserId,
      type: "approval",
      priority: "high",
      title: "Sensitive Information Access Request",
      message: `User "${fromUserId}" is requesting access to sensitive information. Question: "${question}"`,
      action_url: `/dashboard/approvals/${requestId}`,
      context: {
        request_id: requestId,
        from_user_id: fromUserId,
        from_agent_id: fromAgentId,
        original_question: question,
        sensitivity_level: sensitivityAnalysis.severity,
      },
      expires_at: approval.approval_expires_at,
    });

    return approval;
  }

  /**
   * Approve or deny sensitive information sharing
   */
  async respondToApproval(
    requestId: string,
    approved: boolean,
    approverUserId: string,
    conditions?: ApprovalCondition[]
  ): Promise<void> {
    // Update approval status
    await this.supabase
      .from("sensitive_query_approvals")
      .update({
        approved,
        approved_by: approverUserId,
        approved_at: new Date().toISOString(),
        conditions: conditions || [],
      })
      .eq("request_id", requestId);

    // Get approval record
    const { data: approval } = await this.supabase
      .from("sensitive_query_approvals")
      .select()
      .eq("request_id", requestId)
      .single();

    if (!approval) return;

    // Notify requester
    await this.notificationService.notifyEscalation({
      id: `approval-response-${requestId}`,
      user_id: approval.from_user_id,
      type: "approval",
      priority: "high",
      title: approved ? "Access Approved" : "Access Denied",
      message: approved
        ? `Your request for sensitive information has been approved${conditions ? ` with conditions` : ""}.`
        : "Your request for sensitive information has been denied.",
      action_url: `/dashboard/queries/${requestId}`,
      context: {
        request_id: requestId,
        approved,
        conditions: conditions || [],
      },
      expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
    });

    // Apply conditions if approved
    if (approved && conditions) {
      await this.applyConditions(requestId, conditions);
    }
  }

  /**
   * Apply approval conditions to shared information
   */
  private async applyConditions(
    requestId: string,
    conditions: ApprovalCondition[]
  ): Promise<void> {
    for (const condition of conditions) {
      switch (condition.type) {
        case "redact_sensitive_data":
          // Remove PII, credit card numbers, etc.
          // Implementation details depend on data structure
          break;

        case "limit_scope":
          // Only share specific fields/categories
          break;

        case "time_limited":
          // Delete access after X hours
          await this.scheduleAccessExpiry(
            requestId,
            condition.parameters.duration_hours
          );
          break;

        case "one_time_use":
          // Can only be accessed once, then deleted
          break;
      }
    }
  }

  /**
   * Analyze query for sensitive data/topics
   */
  private async analyzeQuerySensitivity(
    question: string
  ): Promise<{ is_sensitive: boolean; severity: "low" | "medium" | "high"; reason: string }> {
    // Keywords/topics that are sensitive
    const sensitiveKeywords = [
      "health",
      "medical",
      "financial",
      "salary",
      "personal",
      "password",
      "credit",
      "ssn",
      "account",
    ];

    const hasSensitiveKeyword = sensitiveKeywords.some((keyword) =>
      question.toLowerCase().includes(keyword)
    );

    return {
      is_sensitive: hasSensitiveKeyword,
      severity: hasSensitiveKeyword ? "high" : "low",
      reason: hasSensitiveKeyword
        ? "Query contains sensitive keywords"
        : "No sensitive content detected",
    };
  }

  private async calculateTrustLevel(
    fromUserId: string,
    toUserId: string
  ): Promise<number> {
    // Use Citadel or your trust calculation engine
    return 0.5;
  }

  private async getNetworkPolicy(userId: string): Promise<any> {
    return { require_approval: false };
  }

  private async scheduleAccessExpiry(
    requestId: string,
    durationHours: number
  ): Promise<void> {
    // Schedule cleanup job
  }
}
```

### 5.2 Interactive Query Refinement

When agents need clarification from humans:

```typescript
// services/query-refinement.ts

export interface QueryRefinementRequest {
  id: string;
  from_agent_id: string;
  from_user_id: string;
  to_user_id: string;
  original_question: string;
  clarification_needed: string;
  suggested_options?: string[];
  response?: string;
  resolved_question?: string;
  status: "pending" | "answered" | "expired";
  created_at: string;
  expires_at: string;
}

/**
 * Query Refinement Service
 * When an agent's question is too ambiguous, ask human for clarification
 */
export class QueryRefinementService {
  constructor(
    private supabase: any,
    private notificationService: NotificationService
  ) {}

  /**
   * Request clarification from data owner
   */
  async requestClarification(
    fromAgentId: string,
    fromUserId: string,
    toUserId: string,
    originalQuestion: string,
    clarificationNeeded: string,
    suggestedOptions?: string[]
  ): Promise<QueryRefinementRequest> {
    const requestId = generateId();

    const refinementRequest: QueryRefinementRequest = {
      id: requestId,
      from_agent_id: fromAgentId,
      from_user_id: fromUserId,
      to_user_id: toUserId,
      original_question: originalQuestion,
      clarification_needed: clarificationNeeded,
      suggested_options: suggestedOptions,
      status: "pending",
      created_at: new Date().toISOString(),
      expires_at: new Date(
        Date.now() + 6 * 60 * 60 * 1000
      ).toISOString(), // 6-hour expiry
    };

    await this.supabase
      .from("query_refinement_requests")
      .insert(refinementRequest);

    // Notify human owner
    await this.notificationService.notifyEscalation({
      id: requestId,
      user_id: toUserId,
      type: "escalation",
      priority: "high",
      title: "Clarification Needed for Query",
      message: clarificationNeeded,
      action_url: `/dashboard/refinements/${requestId}`,
      context: {
        request_id: requestId,
        from_agent_id: fromAgentId,
        from_user_id: fromUserId,
        original_question: originalQuestion,
        suggested_options: suggestedOptions,
      },
      expires_at: refinementRequest.expires_at,
    });

    return refinementRequest;
  }

  /**
   * Provide clarification response
   */
  async provideClarification(
    requestId: string,
    response: string,
    resolvedQuestion: string
  ): Promise<void> {
    await this.supabase
      .from("query_refinement_requests")
      .update({
        response,
        resolved_question: resolvedQuestion,
        status: "answered",
      })
      .eq("id", requestId);

    // Queue the resolved question for answer
    const { data: request } = await this.supabase
      .from("query_refinement_requests")
      .select()
      .eq("id", requestId)
      .single();

    // Notify agent that clarification is ready
    await this.notifyAgentOfClarification(request.from_agent_id, {
      request_id: requestId,
      resolved_question: resolvedQuestion,
      clarification: response,
    });
  }

  private async notifyAgentOfClarification(agentId: string, data: any) {
    // Implementation: Send webhook or push notification to agent
  }
}
```

### 5.3 Human Review Dashboard

```typescript
// components/HumanReviewDashboard.tsx

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface DashboardItem {
  id: string;
  type: "approval" | "refinement" | "pending_request";
  title: string;
  message: string;
  priority: "low" | "medium" | "high" | "urgent";
  created_at: string;
  expires_at: string;
}

export function HumanReviewDashboard({ userId }: { userId: string }) {
  const [items, setItems] = useState<DashboardItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadDashboardItems();
    // Poll for updates
    const interval = setInterval(loadDashboardItems, 30000);
    return () => clearInterval(interval);
  }, [userId]);

  const loadDashboardItems = async () => {
    try {
      // Load pending approvals
      const approvalsRes = await fetch(
        `/api/users/${userId}/sensitive-approvals`
      );
      const approvals = await approvalsRes.json();

      // Load pending query refinements
      const refinementsRes = await fetch(
        `/api/users/${userId}/query-refinements`
      );
      const refinements = await refinementsRes.json();

      // Load pending requests
      const pendingRes = await fetch(`/api/users/${userId}/pending-requests`);
      const pending = await pendingRes.json();

      const allItems: DashboardItem[] = [
        ...approvals.map((a) => ({
          id: a.id,
          type: "approval" as const,
          title: "Sensitive Data Access Request",
          message: a.question,
          priority: a.priority || "high" as const,
          created_at: a.created_at,
          expires_at: a.approval_expires_at,
        })),
        ...refinements.map((r) => ({
          id: r.id,
          type: "refinement" as const,
          title: "Query Clarification Needed",
          message: r.clarification_needed,
          priority: "high" as const,
          created_at: r.created_at,
          expires_at: r.expires_at,
        })),
        ...pending.map((p) => ({
          id: p.id,
          type: "pending_request" as const,
          title: "Forwarded Query Awaiting Response",
          message: p.question,
          priority: p.priority as any,
          created_at: p.created_at,
          expires_at: p.expires_at,
        })),
      ];

      setItems(allItems.sort((a, b) => {
        const priorityOrder = { urgent: 0, high: 1, medium: 2, low: 3 };
        return priorityOrder[a.priority] - priorityOrder[b.priority];
      }));
    } catch (error) {
      console.error("Failed to load dashboard items:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleApproval = async (itemId: string, approved: boolean) => {
    try {
      await fetch(`/api/sensitive-approvals/${itemId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      });
      loadDashboardItems();
    } catch (error) {
      console.error("Failed to update approval:", error);
    }
  };

  const handleRefinement = async (itemId: string, response: string) => {
    try {
      await fetch(`/api/query-refinements/${itemId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response }),
      });
      loadDashboardItems();
    } catch (error) {
      console.error("Failed to provide refinement:", error);
    }
  };

  const handlePendingResponse = async (itemId: string, response: string) => {
    try {
      await fetch(`/api/pending-requests/${itemId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response }),
      });
      loadDashboardItems();
    } catch (error) {
      console.error("Failed to respond to pending request:", error);
    }
  };

  if (loading) return <div>Loading...</div>;

  return (
    <div className="space-y-4 p-6">
      <h1 className="text-2xl font-bold">Review Requests</h1>

      {items.length === 0 ? (
        <div className="p-4 bg-green-50 border border-green-200 rounded">
          <p className="text-green-800">All caught up! No pending items.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item) => (
            <DashboardItemCard
              key={item.id}
              item={item}
              onApproval={handleApproval}
              onRefinement={handleRefinement}
              onResponse={handlePendingResponse}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DashboardItemCard({
  item,
  onApproval,
  onRefinement,
  onResponse,
}: {
  item: DashboardItem;
  onApproval: (id: string, approved: boolean) => void;
  onRefinement: (id: string, response: string) => void;
  onResponse: (id: string, response: string) => void;
}) {
  const [response, setResponse] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      if (item.type === "approval") {
        onApproval(item.id, true);
      } else if (item.type === "refinement") {
        onRefinement(item.id, response);
      } else if (item.type === "pending_request") {
        onResponse(item.id, response);
      }
      setResponse("");
    } finally {
      setSubmitting(false);
    }
  };

  const priorityColor = {
    urgent: "bg-red-50 border-red-200",
    high: "bg-orange-50 border-orange-200",
    medium: "bg-yellow-50 border-yellow-200",
    low: "bg-gray-50 border-gray-200",
  };

  const expiresIn = Math.floor(
    (new Date(item.expires_at).getTime() - Date.now()) / 1000 / 60
  );

  return (
    <div className={`p-4 border rounded ${priorityColor[item.priority]}`}>
      <div className="flex justify-between items-start mb-2">
        <div>
          <h3 className="font-semibold">{item.title}</h3>
          <p className="text-sm text-gray-600 mt-1">{item.message}</p>
        </div>
        <span className={`text-xs font-semibold px-2 py-1 rounded ${
          item.priority === "urgent" ? "bg-red-200 text-red-800" :
          item.priority === "high" ? "bg-orange-200 text-orange-800" :
          "bg-gray-200 text-gray-800"
        }`}>
          {item.priority.toUpperCase()}
        </span>
      </div>

      {expiresIn < 60 && (
        <p className="text-xs text-red-600 mb-2">
          ⚠ Expires in {expiresIn} minutes
        </p>
      )}

      <div className="mt-4 space-y-3">
        {item.type === "approval" && (
          <div className="flex gap-2">
            <button
              onClick={() => onApproval(item.id, true)}
              className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
              disabled={submitting}
            >
              Approve
            </button>
            <button
              onClick={() => onApproval(item.id, false)}
              className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
              disabled={submitting}
            >
              Deny
            </button>
          </div>
        )}

        {(item.type === "refinement" || item.type === "pending_request") && (
          <div>
            <textarea
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              placeholder="Enter your response..."
              className="w-full p-2 border rounded text-sm"
              rows={3}
              disabled={submitting}
            />
            <button
              onClick={handleSubmit}
              className="mt-2 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              disabled={!response.trim() || submitting}
            >
              {submitting ? "Submitting..." : "Submit Response"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
```

---

## Summary Table: Escalation Decision Matrix

```
┌──────────────────┬──────────────┬─────────────────┬──────────────────┐
│ Confidence       │ Hop Count    │ Trust Score     │ Action           │
├──────────────────┼──────────────┼─────────────────┼──────────────────┤
│ High (>0.8)      │ Any          │ Any             │ Answer           │
│ Medium (0.5-0.8) │ >0           │ >0.5            │ Delegate         │
│ Low (<0.5)       │ >0           │ >0.5            │ Delegate + Retry │
│ Low (<0.5)       │ 0            │ Any             │ Escalate         │
│ Low (<0.5)       │ Any          │ <0.5            │ Escalate         │
│ Any              │ <0           │ Any             │ Escalate         │
└──────────────────┴──────────────┴─────────────────┴──────────────────┘
```

---

## Implementation Roadmap

1. **Phase 1: Basic Escalation (Week 1-2)**
   - Implement PendingRequestService
   - Basic email notifications
   - In-app notification queue

2. **Phase 2: Multi-Channel Notifications (Week 2-3)**
   - Web push notifications
   - SMS/Twilio integration
   - Webhook support

3. **Phase 3: Agent Delegation (Week 3-4)**
   - Implement AgentDelegationService
   - Multi-hop query resolution
   - Delegation chain tracking

4. **Phase 4: Human-in-the-Loop (Week 4-5)**
   - Approval gates for sensitive data
   - Query refinement requests
   - Human review dashboard

5. **Phase 5: Framework Integration (Week 5-6)**
   - LangGraph orchestration
   - Claude Agent SDK native tools
   - Advanced delegation patterns

---

## References & Best Practices

1. **Agent Communication**: Follow OpenAPI specs for agent-to-agent APIs
2. **Notification Standards**: Use Web Push API, SMTP (RFC 5322), Twilio SDK
3. **Async Patterns**: Implement retry with exponential backoff (2^n seconds)
4. **State Management**: Use explicit state machines for reliability
5. **Security**: Always validate webhook signatures, use HMAC-SHA256
6. **Monitoring**: Log all escalations, delegations, and timeouts for audit
7. **GDPR Compliance**: Implement data minimization in escalations

