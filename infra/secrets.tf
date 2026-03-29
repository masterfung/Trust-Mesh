# ── Secret resources ──────────────────────────────────────────────────────────

resource "google_secret_manager_secret" "google_api_key" {
  secret_id = "GOOGLE_API_KEY"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "anthropic_api_key" {
  secret_id = "ANTHROPIC_API_KEY"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "pool_sync_secret" {
  secret_id = "TRUSTMESH_POOL_SYNC_SECRET"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "redpill_api_key" {
  secret_id = "REDPILL_API_KEY"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# ── Auto-generate TRUSTMESH_POOL_SYNC_SECRET ──────────────────────────────────
# Cryptographically random 48-char secret shared across all pods for federation auth.
# Stored in Secret Manager — never set manually, never in any .env file.

resource "random_password" "pool_sync_secret" {
  length      = 48
  special     = false
  upper       = true
  lower       = true
  numeric     = true
  min_upper   = 8
  min_lower   = 8
  min_numeric = 8
}

resource "google_secret_manager_secret_version" "pool_sync_secret" {
  secret      = google_secret_manager_secret.pool_sync_secret.id
  secret_data = random_password.pool_sync_secret.result

  lifecycle {
    # Prevent accidental rotation on every apply.
    # To rotate: terraform taint google_secret_manager_secret_version.pool_sync_secret
    ignore_changes = [secret_data]
  }
}

# ── IAM: per-pod secret access ────────────────────────────────────────────────

resource "google_secret_manager_secret_iam_member" "pod_google_api" {
  for_each  = var.pods
  secret_id = google_secret_manager_secret.google_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.pod[each.key].email}"
}

resource "google_secret_manager_secret_iam_member" "pod_anthropic_api" {
  for_each  = var.pods
  secret_id = google_secret_manager_secret.anthropic_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.pod[each.key].email}"
}

resource "google_secret_manager_secret_iam_member" "pod_pool_sync" {
  for_each  = var.pods
  secret_id = google_secret_manager_secret.pool_sync_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.pod[each.key].email}"
}
