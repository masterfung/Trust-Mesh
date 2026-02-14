const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include", // Send httpOnly cookies with every request
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.text();
    // Redirect to login on auth failure (session expired or missing)
    if (res.status === 401 && typeof window !== "undefined" && !path.includes("/auth/")) {
      window.location.href = "/";
    }
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

// ── Types ──

export interface ProfileData {
  occupation?: { title: string; industry: string } | null;
  skills?: { name: string; category: string }[];
  interests?: { name: string; category: string }[];
  family_status?: string | null;
  age_range?: string | null;
  location_hints?: string[];
}

export type ContextMode = "work" | "personal" | "all";

export interface User {
  id: string;
  username: string;
  display_name: string;
  bio: string;
  user_type?: string;
  profile_data?: ProfileData | null;
  is_discoverable?: boolean;
  is_demo?: boolean;
  active_context?: ContextMode;
  created_at?: string;
}

export interface Agent {
  id: string;
  owner_id: string;
  name: string;
  personality: string;
}

export interface AgentSkill {
  id: string;
  name: string;
  description: string;
  tags: string[];
}

export interface AgentCard {
  name: string;
  description: string;
  url: string;
  version: string;
  owner: User;
  capabilities: string[];
  skills: AgentSkill[];
  protocol: string;
}

export interface Connection {
  id: string;
  from_user_id: string;
  to_user_id: string;
  status: string;
  context?: string;
  created_at: string;
  accepted_at?: string;
  peer?: User;
}

export interface ConnectionRequest {
  id: string;
  from_user_id: string;
  to_user_id: string;
  message: string;
  status: string;
  created_at: string;
  reviewed_at?: string;
  from_user?: User;
  to_user?: User;
}

export interface Network {
  id: string;
  owner_id: string;
  name: string;
  description: string;
  network_type: string;
  is_public?: boolean;
  join_policy?: string;
  context?: ContextMode;
  created_at: string;
  members: User[];
}

export interface NetworkDiscovery {
  id: string;
  name: string;
  description: string;
  network_type: string;
  join_policy: string;
  context?: ContextMode;
  member_count: number;
  owner_name: string;
}

export interface Capsule {
  id: string;
  owner_id: string;
  capsule_type: string;
  title: string;
  content: string;
  tier: string;
  category: string;
  context?: string;
  freshness: string;
  expires_at?: string;
  last_verified_at: string;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  network_ids: string[];
}

export interface CitadelResult {
  score?: number;
  decision?: string;
  is_safe?: boolean;
  findings?: string[];
}

export interface AgentAction {
  type: "capsule_created" | "capsule_updated" | "task_created" | "peer_queried" | "quotes_requested";
  capsule_id?: string;
  task_id?: string;
  title?: string;
  old_title?: string;
  capsule_type?: string;
  tier?: string;
  category?: string;
  networks?: string[];
  target_username?: string;
  question?: string;
  service_type?: string;
  providers_queried?: number;
}

export interface QueryResult {
  id: string;
  from_user_id: string;
  to_user_id: string;
  question: string;
  trust_level: string;
  shared_networks: string[];
  response?: string;
  decision: string;
  citadel_input?: CitadelResult;
  citadel_output?: CitadelResult;
  agent_actions?: AgentAction[];
  latency_ms: number;
  created_at: string;
}

export interface AgentTask {
  id: string;
  owner_id: string;
  title: string;
  description: string;
  status: string;
  task_type: string;
  result?: string;
  source_message?: string;
  created_at: string;
  completed_at?: string;
}

export interface Notification {
  id: string;
  user_id: string;
  notification_type: string;
  title: string;
  body: string;
  is_read: boolean;
  related_id?: string;
  created_at: string;
}

export interface ServiceProvider {
  id: string;
  username: string;
  display_name: string;
  bio: string;
  user_type: string;
  profile_data?: ProfileData | null;
  agent_card?: AgentCard | null;
}

export interface Briefing {
  user_id: string;
  briefing: string;
  generated_at: string;
  sections?: Record<string, unknown>;
}

export interface HealthStatus {
  status: string;
  providers: {
    anthropic: boolean;
    tee: { enabled: boolean; provider: string | null };
    tavily: boolean;
    citadel: { configured: boolean; reachable: boolean; heuristic_active?: boolean; active?: boolean };
    google_oauth: boolean;
  };
}

export interface NetworkInvite {
  id: string;
  email: string;
  token: string;
  status: string;
  network_name: string;
}

export interface NetworkInviteListItem {
  id: string;
  email: string;
  status: string;
  created_at: string | null;
}

export interface GraphData {
  nodes: { id: string; username: string; display_name: string; bio: string; user_type?: string; profile_data?: ProfileData | null }[];
  edges: { source: string; target: string; type: string }[];
  networks: { id: string; name: string; network_type: string; members: string[] }[];
}

export interface AuditLogEntry {
  id: string;
  actor_user_id?: string;
  actor_did?: string;
  actor_role?: string;
  actor_institution?: string;
  target_user_id?: string;
  action: string;
  event_type: string;
  capsule_ids_accessed: string[];
  categories_accessed: string[];
  token_hash?: string;
  token_role?: string;
  token_expires_at?: string;
  case_id?: string;
  reason?: string;
  query_id?: string;
  decision: string;
  details?: Record<string, unknown>;
  created_at: string;
}

export interface FhirResource {
  resourceType: string;
  id: string;
  meta?: { lastUpdated: string };
  // Patient
  name?: { use?: string; text?: string; given?: string[]; family?: string }[];
  active?: boolean;
  // AllergyIntolerance
  clinicalStatus?: { coding: { system: string; code: string }[] };
  verificationStatus?: { coding: { system: string; code: string }[] };
  type?: string;
  category?: string[];
  // MedicationStatement
  status?: string;
  subject?: { reference: string };
  patient?: { reference: string };
  medicationCodeableConcept?: { text: string };
  dateAsserted?: string;
  // Condition / Observation
  code?: { text: string };
  valueString?: string;
  // Common
  note?: { text: string }[];
  relationship?: { text: string }[];
  communication?: { text: string }[];
  _trustmesh?: {
    capsule_id?: string;
    visibility?: string;
    emergency_accessible?: boolean;
    can_reshare?: boolean;
    substances?: string[];
    username?: string;
    user_id?: string;
  };
}

export interface FhirBundle {
  resourceType: "Bundle";
  id: string;
  meta: { lastUpdated: string };
  type: string;
  total: number;
  entry: { resource: FhirResource; fullUrl: string }[];
  _trustmesh_emergency?: {
    audit_id: string;
    access_role: string;
    institution: string;
    case_id: string;
  };
}

// ── API Functions ──

export const api = {
  // Auth (session managed via httpOnly cookies — no tokens in JS)
  login: (username: string, password: string) =>
    apiFetch<User>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () =>
    apiFetch<{ status: string }>("/api/auth/logout", { method: "POST" }),
  getMe: () => apiFetch<User>("/api/auth/me"),
  createUser: (data: { username: string; display_name: string; bio: string; password: string; user_type?: string }) =>
    apiFetch<User>("/api/users", { method: "POST", body: JSON.stringify(data) }),

  // Users
  listUsers: () => apiFetch<User[]>("/api/users"),
  getUser: (id: string) => apiFetch<User>(`/api/users/${id}`),
  getAgent: (id: string) => apiFetch<Agent>(`/api/users/${id}/agent`),
  getAgentCard: (id: string) => apiFetch<AgentCard>(`/api/users/${id}/agent/card`),
  switchContext: (userId: string, context: ContextMode) =>
    apiFetch<{ context: string }>(`/api/users/${userId}/context`, {
      method: "PUT",
      body: JSON.stringify({ context }),
    }),

  // Connections
  listConnections: (userId: string) =>
    apiFetch<Connection[]>(`/api/users/${userId}/connections`),
  listConnectionRequests: (userId: string) =>
    apiFetch<ConnectionRequest[]>(`/api/users/${userId}/connection-requests`),
  sendConnectionRequest: (fromUserId: string, toUserId: string, message: string) =>
    apiFetch<ConnectionRequest>("/api/connections/request", {
      method: "POST",
      body: JSON.stringify({ from_user_id: fromUserId, to_user_id: toUserId, message }),
    }),
  updateConnectionRequest: (requestId: string, status: "accepted" | "declined") =>
    apiFetch<ConnectionRequest>(`/api/connection-requests/${requestId}`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),

  // Networks
  listNetworks: (userId: string) =>
    apiFetch<Network[]>(`/api/users/${userId}/networks`),
  getNetwork: (id: string) => apiFetch<Network>(`/api/networks/${id}`),
  createNetwork: (data: { name: string; description: string; network_type: string; owner_id: string; is_public?: boolean; join_policy?: string }) =>
    apiFetch<Network>("/api/networks", { method: "POST", body: JSON.stringify(data) }),
  addNetworkMember: (networkId: string, userId: string) =>
    apiFetch<Network>(`/api/networks/${networkId}/members`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),
  removeNetworkMember: (networkId: string, userId: string) =>
    apiFetch(`/api/networks/${networkId}/members/${userId}`, { method: "DELETE" }),
  discoverNetworks: () =>
    apiFetch<NetworkDiscovery[]>("/api/networks/discover"),
  requestJoinNetwork: (networkId: string, userId: string, message: string) =>
    apiFetch(`/api/networks/${networkId}/join-request?user_id=${userId}`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  listJoinRequests: (networkId: string) =>
    apiFetch<{ id: string; user_id: string; network_id: string; message: string; status: string; created_at: string; user?: User }[]>(
      `/api/networks/${networkId}/join-requests`
    ),
  reviewJoinRequest: (networkId: string, requestId: string, status: "approved" | "declined") =>
    apiFetch<{ ok: boolean; status: string }>(`/api/networks/${networkId}/join-requests/${requestId}`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),

  // Invites
  sendInvite: (networkId: string, email: string, message?: string) =>
    apiFetch<NetworkInvite>(`/api/networks/${networkId}/invite`, {
      method: "POST",
      body: JSON.stringify({ email, message: message || "" }),
    }),
  listInvites: (networkId: string) =>
    apiFetch<NetworkInviteListItem[]>(`/api/networks/${networkId}/invites`),

  // Capsules
  listCapsules: (userId: string) =>
    apiFetch<Capsule[]>(`/api/users/${userId}/capsules`),
  createCapsule: (userId: string, data: Partial<Capsule> & { content: string; network_ids?: string[] }) =>
    apiFetch<Capsule>(`/api/users/${userId}/capsules`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateCapsule: (capsuleId: string, data: Partial<Capsule> & { network_ids?: string[] }) =>
    apiFetch<Capsule>(`/api/capsules/${capsuleId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deleteCapsule: (capsuleId: string) =>
    apiFetch(`/api/capsules/${capsuleId}`, { method: "DELETE" }),

  // Queries
  query: (fromUserId: string, toUserId: string, question: string) =>
    apiFetch<QueryResult>("/api/query", {
      method: "POST",
      body: JSON.stringify({ from_user_id: fromUserId, to_user_id: toUserId, question }),
    }),
  listQueries: (userId: string) =>
    apiFetch<QueryResult[]>(`/api/users/${userId}/queries`),

  // Tasks
  listTasks: (userId: string) =>
    apiFetch<AgentTask[]>(`/api/users/${userId}/tasks`),
  getTask: (taskId: string) =>
    apiFetch<AgentTask>(`/api/tasks/${taskId}`),

  // Notifications
  listNotifications: (userId: string) =>
    apiFetch<Notification[]>(`/api/users/${userId}/notifications`),
  getUnreadCount: (userId: string) =>
    apiFetch<{ count: number }>(`/api/users/${userId}/notifications/unread-count`),
  markNotificationRead: (notificationId: string) =>
    apiFetch(`/api/notifications/${notificationId}/read`, { method: "PUT" }),
  markAllNotificationsRead: (userId: string) =>
    apiFetch(`/api/users/${userId}/notifications/read-all`, { method: "PUT" }),

  // Briefing
  getBriefing: (userId: string) =>
    apiFetch<Briefing>(`/api/users/${userId}/briefing`),

  // Services
  listServices: () =>
    apiFetch<ServiceProvider[]>("/api/services"),

  // Health / Status
  getHealthFull: () => apiFetch<HealthStatus>("/health/full"),

  // Streaming query
  queryStream: (fromUserId: string, toUserId: string, question: string, conversationHistory?: { role: string; content: string }[]) => {
    return fetch(`${API_BASE}/api/query/stream`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        from_user_id: fromUserId,
        to_user_id: toUserId,
        question,
        conversation_history: conversationHistory?.length ? conversationHistory : undefined,
      }),
    });
  },

  // Intake onboarding
  intakeStep: (userId: string, message: string, conversationHistory: { role: string; content: string }[]) => {
    return fetch(`${API_BASE}/api/users/${userId}/intake`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, conversation_history: conversationHistory }),
    });
  },

  // Audit
  listAuditLogs: (userId: string, eventType?: string) =>
    apiFetch<AuditLogEntry[]>(`/api/users/${userId}/audit${eventType ? `?event_type=${eventType}` : ""}`),
  listEmergencyLogs: (userId: string) =>
    apiFetch<AuditLogEntry[]>(`/api/users/${userId}/audit/emergency`),

  // Graph
  getGraph: () => apiFetch<GraphData>("/api/graph"),
  getUserGraph: (userId: string) => apiFetch<GraphData>(`/api/graph/${userId}`),

  // PIN
  setPin: (userId: string, pin: string) =>
    apiFetch<{ has_pin: boolean }>(`/api/users/${userId}/pin`, {
      method: "POST",
      body: JSON.stringify({ pin }),
    }),
  verifyPin: (userId: string, pin: string) =>
    apiFetch<{ verified: boolean; token: string | null; expires_in: number }>(`/api/users/${userId}/pin/verify`, {
      method: "POST",
      body: JSON.stringify({ pin }),
    }),
  getPinStatus: (userId: string) =>
    apiFetch<{ has_pin: boolean }>(`/api/users/${userId}/pin/status`),

  // FHIR
  getEmergencyFhirBundle: (auditId: string) =>
    apiFetch<FhirBundle>(`/api/emergency/${auditId}/fhir`),

  // Demo
  demoWarmup: () =>
    apiFetch<{ status: string; keys_loaded: number }>("/api/demo/warmup", { method: "POST" }),
};
