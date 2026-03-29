# ── Service accounts (one per Cloud Run service) ─────────────────────────────

resource "google_service_account" "pod" {
  for_each     = var.pods
  account_id   = "trustmesh-pod-${replace(each.key, "_", "-")}"
  display_name = "TrustMesh Pod — ${each.value.display_name}"
  description  = "Least-privilege SA for trustmesh-pod-${replace(each.key, "_", "-")} Cloud Run service"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account" "frontend" {
  account_id   = "trustmesh-frontend"
  display_name = "TrustMesh Frontend"
  description  = "Least-privilege SA for trustmesh-frontend Cloud Run service"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account" "registry" {
  account_id   = "trustmesh-registry"
  display_name = "TrustMesh Registry"
  description  = "Least-privilege SA for trustmesh-registry Cloud Run service"
  depends_on   = [google_project_service.apis]
}

# ── Public invoker bindings ───────────────────────────────────────────────────
# Cloud Run services accept unauthenticated traffic — application-layer auth
# handles authorization (session cookies for users, POOL_SYNC_SECRET for federation).

resource "google_cloud_run_v2_service_iam_member" "pod_public" {
  for_each = var.pods
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.pods[each.key].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "registry_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.registry.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# NOTE: IAM Deny policies (preventing pod SAs from privilege escalation) require
# the google_iam_deny_policy resource which needs the IAM Deny API and
# roles/iam.denyAdmin on the deploying account. Add post-launch:
#   https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/iam_deny_policy
