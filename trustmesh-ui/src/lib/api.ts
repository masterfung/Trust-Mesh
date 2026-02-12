const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

// ── Types ──

export interface User {
  id: string;
  username: string;
  display_name: string;
  bio: string;
  is_discoverable?: boolean;
  created_at?: string;
}

export interface Agent {
  id: string;
  owner_id: string;
  name: string;
  personality: string;
}

export interface Connection {
  id: string;
  from_user_id: string;
  to_user_id: string;
  status: string;
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
  created_at: string;
  members: User[];
}

export interface Capsule {
  id: string;
  owner_id: string;
  capsule_type: string;
  title: string;
  content: string;
  tier: string;
  category: string;
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
  latency_ms: number;
  created_at: string;
}

export interface GraphData {
  nodes: { id: string; username: string; display_name: string; bio: string }[];
  edges: { source: string; target: string; type: string }[];
  networks: { id: string; name: string; network_type: string; members: string[] }[];
}

// ── API Functions ──

export const api = {
  // Users
  listUsers: () => apiFetch<User[]>("/api/users"),
  getUser: (id: string) => apiFetch<User>(`/api/users/${id}`),
  getAgent: (id: string) => apiFetch<Agent>(`/api/users/${id}/agent`),

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
  createNetwork: (data: { name: string; description: string; network_type: string; owner_id: string }) =>
    apiFetch<Network>("/api/networks", { method: "POST", body: JSON.stringify(data) }),
  addNetworkMember: (networkId: string, userId: string) =>
    apiFetch<Network>(`/api/networks/${networkId}/members`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),
  removeNetworkMember: (networkId: string, userId: string) =>
    apiFetch(`/api/networks/${networkId}/members/${userId}`, { method: "DELETE" }),

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

  // Graph
  getGraph: () => apiFetch<GraphData>("/api/graph"),
};
