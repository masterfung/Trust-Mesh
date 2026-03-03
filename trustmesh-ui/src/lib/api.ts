const DEFAULT_API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000";
const REGISTRY_URL = process.env.NEXT_PUBLIC_REGISTRY_URL || "http://localhost:8100";

/** Get the active pod URL (from localStorage or default). */
export function getPodUrl(): string {
  if (typeof window !== "undefined") {
    return localStorage.getItem("trustmesh_pod_url") || DEFAULT_API_BASE;
  }
  return DEFAULT_API_BASE;
}

/** Switch the active pod URL. */
export function setPodUrl(url: string) {
  if (typeof window !== "undefined") {
    localStorage.setItem("trustmesh_pod_url", url);
  }
}

/** Get the current API base (dynamic based on selected pod). */
function getApiBase(): string {
  return getPodUrl();
}

/** Read the CSRF cookie value (set by backend, httpOnly=false so JS can read it). */
export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)trustmesh_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  // Attach CSRF token on state-mutating requests
  const csrfHeaders: Record<string, string> = {};
  if (init?.method && ["POST", "PUT", "DELETE", "PATCH"].includes(init.method)) {
    const token = getCsrfToken();
    if (token) csrfHeaders["x-csrf-token"] = token;
  }

  const res = await fetch(`${getApiBase()}${path}`, {
    ...init,
    credentials: "include", // Send httpOnly cookies with every request
    headers: { "Content-Type": "application/json", ...csrfHeaders, ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.text();
    // Redirect to login on auth failure (session expired or missing)
    if (res.status === 401 && typeof window !== "undefined" && !path.includes("/auth/")) {
      window.location.href = "/";
    }
    // Parse error body for clean message
    let message: string;
    try {
      const parsed = JSON.parse(body);
      message = parsed.detail || parsed.error || parsed.message || body;
    } catch {
      message = body || `Request failed`;
    }
    throw new Error(message);
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
  username: string | null;
  email: string | null;
  display_name: string;
  bio: string;
  user_type?: string;
  profile_data?: ProfileData | null;
  is_discoverable?: boolean;
  is_demo?: boolean;
  active_context?: ContextMode;
  avatar_url?: string | null;
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
  relationship_type?: string;
  my_label?: string;
  peer_label?: string;
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
  relationship_type?: string;
  from_label?: string;
  mutual_connections?: number;
  mutual_networks?: number;
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
  pool_type?: string;
  shared_categories?: string[] | null;
  expires_at?: string | null;
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
  pool_type?: string;
  shared_categories?: string[] | null;
  member_count: number;
  owner_name: string;
}

export interface Capsule {
  id: string;
  owner_id: string;
  owner_display_name?: string;
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
  network_names?: string[];
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
  target_display_name?: string;
  question?: string;
  service_type?: string;
  providers_queried?: number;
  federated?: boolean;
  remote_pod?: string;
  trust_level?: string;
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
    gemini?: boolean;
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

export interface RegistryAgent {
  did: string;
  username: string;
  display_name: string;
  bio: string;
  user_type: string;
  profile_data?: ProfileData | null;
  skills: { name: string; category: string }[];
  pools: string[];
  is_discoverable?: boolean;
}

export interface RegistryPodAgent {
  name: string;
  did: string;
  pod_url: string;
  entity_type: string;
  capabilities: string[];
  username: string;
  display_name: string;
  bio: string;
  registered_at: string;
}

export interface PeerPod {
  id: string;
  name: string;
  url: string;
  status: string;
  agent_count: number;
  last_seen_at: string | null;
  created_at: string | null;
}

export interface GraphData {
  nodes: { id: string; username: string; display_name: string; bio: string; user_type?: string; profile_data?: ProfileData | null }[];
  edges: { source: string; target: string; type: string }[];
  networks: { id: string; name: string; network_type: string; pool_type?: string; shared_categories?: string[] | null; members: string[] }[];
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
  // Login accepts name (display_name) or username (public handle)
  login: (name: string, password: string) =>
    apiFetch<User>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ name, password }),
    }),
  logout: () =>
    apiFetch<{ status: string }>("/api/auth/logout", { method: "POST" }),
  getMe: () => apiFetch<User>("/api/auth/me"),
  // Signup: name + password + optional email/avatar. Username (public handle) is optional.
  createUser: (data: { display_name: string; bio: string; password: string; email?: string; avatar_url?: string; user_type?: string; username?: string }) =>
    apiFetch<User>("/api/users", { method: "POST", body: JSON.stringify(data) }),
  // Claim a public handle (Go Live)
  claimHandle: (userId: string, handle: string) =>
    apiFetch<User>(`/api/users/${userId}/claim-handle`, {
      method: "POST",
      body: JSON.stringify({ handle }),
    }),
  checkHandle: (userId: string, handle: string) =>
    apiFetch<{ available: boolean; reason?: string }>(`/api/users/${userId}/check-handle?handle=${encodeURIComponent(handle)}`),

  // Users
  listUsers: () => apiFetch<User[]>("/api/users"),
  getUser: (id: string) => apiFetch<User>(`/api/users/${id}`),
  getAgent: (id: string) => apiFetch<Agent>(`/api/users/${id}/agent`),
  updateAgent: (id: string, data: { personality: string }) =>
    apiFetch<Agent>(`/api/users/${id}/agent`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
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
  sendConnectionRequest: (fromUserId: string, toUserId: string, message: string, relationshipType?: string, fromLabel?: string) =>
    apiFetch<ConnectionRequest>("/api/connections/request", {
      method: "POST",
      body: JSON.stringify({
        from_user_id: fromUserId,
        to_user_id: toUserId,
        message,
        relationship_type: relationshipType || undefined,
        from_label: fromLabel || undefined,
      }),
    }),
  updateConnectionRequest: (requestId: string, status: "accepted" | "declined", toLabel?: string) =>
    apiFetch<ConnectionRequest>(`/api/connection-requests/${requestId}`, {
      method: "PUT",
      body: JSON.stringify({ status, to_label: toLabel || undefined }),
    }),
  deleteConnection: (connectionId: string) =>
    apiFetch<{ status: string }>(`/api/connections/${connectionId}`, { method: "DELETE" }),
  updateConnectionLabel: (connectionId: string, myLabel?: string, relationshipType?: string) =>
    apiFetch<Connection>(`/api/connections/${connectionId}/label`, {
      method: "PATCH",
      body: JSON.stringify({
        my_label: myLabel ?? undefined,
        relationship_type: relationshipType ?? undefined,
      }),
    }),

  // Networks
  listNetworks: (userId: string) =>
    apiFetch<Network[]>(`/api/users/${userId}/networks`),
  getNetwork: (id: string) => apiFetch<Network>(`/api/networks/${id}`),
  createNetwork: (data: { name: string; description: string; network_type: string; owner_id: string; is_public?: boolean; join_policy?: string; pool_type?: string; shared_categories?: string[]; expires_at?: string; initial_member_ids?: string[] }) =>
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
  sendInvite: (networkId: string, email?: string, message?: string) =>
    apiFetch<NetworkInvite>(`/api/networks/${networkId}/invite`, {
      method: "POST",
      body: JSON.stringify({ email: email || "", message: message || "" }),
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
    const csrf = getCsrfToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (csrf) headers["x-csrf-token"] = csrf;
    return fetch(`${getApiBase()}/api/query/stream`, {
      method: "POST",
      credentials: "include",
      headers,
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
    const csrf = getCsrfToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (csrf) headers["x-csrf-token"] = csrf;
    return fetch(`${getApiBase()}/api/users/${userId}/intake`, {
      method: "POST",
      credentials: "include",
      headers,
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

  // Registry / Discovery
  registryAgents: (params?: { user_type?: string }) => {
    const qs = params?.user_type ? `?user_type=${params.user_type}` : "";
    return apiFetch<{ agents: RegistryAgent[]; count: number }>(`/api/registry/agents${qs}`);
  },
  registrySearch: (q: string, params?: { capability?: string; user_type?: string }) => {
    const sp = new URLSearchParams({ q });
    if (params?.capability) sp.set("capability", params.capability);
    if (params?.user_type) sp.set("user_type", params.user_type);
    return apiFetch<{ query: string; results: RegistryAgent[]; count: number }>(`/api/registry/search?${sp}`);
  },
  registryLookup: (did: string) =>
    apiFetch<RegistryAgent & { pod?: { name: string; url: string } }>(`/api/registry/lookup/${encodeURIComponent(did)}`),

  // Pod info
  getPodInfo: () =>
    apiFetch<{ pod_name: string; pod_url: string; protocol: string; agent_count: number; agents: { owner_username: string; did: string }[] }>("/api/pod"),

  // Pod peers
  listPeers: () =>
    apiFetch<{ pod_name: string; pod_url: string; peers: PeerPod[] }>("/api/pod/peers"),
  addPeer: (url: string) =>
    apiFetch<{ status: string; peer: PeerPod }>("/api/pod/peers", { method: "POST", body: JSON.stringify({ url }) }),
  removePeer: (peerId: string) =>
    apiFetch<{ status: string }>(`/api/pod/peers/${peerId}`, { method: "DELETE" }),
  pingPeer: (peerId: string) =>
    apiFetch<{ status: string; info: Record<string, unknown> | null }>(`/api/pod/peers/${peerId}/ping`, { method: "POST" }),

  // User profile update
  updateUser: (userId: string, data: { is_discoverable?: boolean; bio?: string; display_name?: string; email?: string; avatar_url?: string }) =>
    apiFetch<User>(`/api/users/${userId}`, { method: "PUT", body: JSON.stringify(data) }),

  // Demo
  demoWarmup: () =>
    apiFetch<{ status: string; keys_loaded: number }>("/api/demo/warmup", { method: "POST" }),

  // Public Registry (separate service on port 8100)
  registryListAll: () =>
    fetch(`${REGISTRY_URL}/api/agents`, { headers: { "Content-Type": "application/json" } })
      .then(r => r.json()) as Promise<{ agents: RegistryPodAgent[]; count: number }>,
  registrySearchAll: (q: string) =>
    fetch(`${REGISTRY_URL}/api/search?q=${encodeURIComponent(q)}`, { headers: { "Content-Type": "application/json" } })
      .then(r => r.json()) as Promise<{ query: string; results: RegistryPodAgent[]; count: number }>,
  registryHealth: () =>
    fetch(`${REGISTRY_URL}/api/health`).then(r => r.json()) as Promise<{ status: string; agent_count: number }>,

  // Timeline
  getTimelineHealth: () =>
    apiFetch<TimelineHealth>("/api/timeline/health"),
  getTimelineState: () =>
    apiFetch<TimelineEngineState>("/api/timeline/state"),
  listTimelineEntries: () =>
    apiFetch<TimelineEntry[]>("/api/timeline/entries"),
  createTimelineEntry: (data: { label: string; category: string; salience?: number; activation_trigger?: { kind: string; at_ms?: number; cron?: string; event_type?: string }; hooks?: { action: number; phase: number; prompt: string }[] }) =>
    apiFetch<TimelineEntry>("/api/timeline/entries", { method: "POST", body: JSON.stringify(data) }),
  tickTimeline: () =>
    apiFetch<{ tick_count: number; next_wake_at: number }>("/api/timeline/tick", { method: "POST" }),
  transitionTimelineEntry: (entryId: string, newState: number) =>
    apiFetch<TimelineEntry>(`/api/timeline/entries/${entryId}/transition`, { method: "POST", body: JSON.stringify({ new_state: newState }) }),
  startTimeline: () =>
    apiFetch<{ status: string }>("/api/timeline/start", { method: "POST" }),
  stopTimeline: () =>
    apiFetch<{ status: string }>("/api/timeline/stop", { method: "POST" }),
};

// ── Timeline Types ──

export interface TimelineHealth {
  status: string;
  kernel_built: boolean;
  tick_count?: number;
  entry_count?: number;
  version?: number;
  message?: string;
}

export interface TimelineEngineState {
  active_count: number;
  pending_count: number;
  dormant_count: number;
  failed_count: number;
  total_count: number;
  tick_count: number;
  signal_count: number;
  is_running: boolean;
  signals: { severity: string; message: string; related_entry_id: string }[];
  active_ids: string[];
}

export interface TimelineEntry {
  id: string;
  label: string;
  category: string;
  state: number;
  state_name: string;
  salience: number;
  visibility: number;
  entry_type: number;
  entry_type_name: string;
  visibility_name: string;
  trigger_kind: string | null;
  trigger_detail: string | null;
  hook_summary: string | null;
  dep_count: number;
}

// ── Message API helpers ──

export interface MessageItem {
  id: string;
  sender_id: string;
  sender_username: string;
  sender_display_name: string;
  sender_pod_url: string | null;
  recipient_id: string;
  subject: string;
  body: string | null;
  scope: string;
  trust_level_at_send: string;
  expires_at: string | null;
  rekey_needed: boolean;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export async function getInbox(
  userId: string,
  opts?: { unread_only?: boolean; limit?: number; offset?: number }
): Promise<MessageItem[]> {
  const params = new URLSearchParams();
  if (opts?.unread_only) params.set("unread_only", "true");
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString() ? `?${params}` : "";
  return apiFetch<MessageItem[]>(`/api/users/${userId}/messages/inbox${qs}`);
}

export async function getSent(userId: string): Promise<MessageItem[]> {
  return apiFetch<MessageItem[]>(`/api/users/${userId}/messages/sent`);
}

export async function getUnreadCount(userId: string): Promise<number> {
  const data = await apiFetch<{ count: number }>(
    `/api/users/${userId}/messages/unread-count`
  );
  return data.count;
}

export async function markMessageRead(messageId: string): Promise<void> {
  await apiFetch<{ status: string }>(`/api/messages/${messageId}/read`, {
    method: "PUT",
  });
}

export async function deleteMessage(messageId: string): Promise<void> {
  await apiFetch<{ status: string }>(`/api/messages/${messageId}`, {
    method: "DELETE",
  });
}
