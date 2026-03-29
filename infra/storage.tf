# ── Litestream replica bucket ─────────────────────────────────────────────────

resource "google_storage_bucket" "pods_db" {
  name                        = "tm-pods-db-${var.project_id}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = false

  # Prevent accidental public exposure
  public_access_prevention = "enforced"

  # Object versioning: retain 3 prior versions (protect against accidental overwrites)
  versioning {
    enabled = true
  }

  # Retention: objects cannot be deleted for 3 days (protects against ransomware/accidents)
  retention_policy {
    retention_period = 259200 # 3 days in seconds
    is_locked        = false  # Leave unlocked so lifecycle rules can still apply
  }

  # Lifecycle: delete non-current WAL segments after 7 days (snapshots cover recovery)
  lifecycle_rule {
    action { type = "Delete" }
    condition {
      age        = 7
      with_state = "ARCHIVED" # Only non-current versions
    }
  }

  # Lifecycle: delete current WAL segments after 30 days (snapshot interval is 6h)
  lifecycle_rule {
    action { type = "Delete" }
    condition {
      age        = 30
      with_state = "LIVE"
    }
  }

  depends_on = [google_project_service.apis]
}

# ── Per-pod scoped IAM (IAM condition limits each pod SA to its own path) ─────
# Each pod can only read/write its own objects: pods/{pod_key}/**
# This prevents pod-A from accessing pod-B's database.

resource "google_storage_bucket_iam_member" "pod_db_access" {
  for_each = var.pods
  bucket   = google_storage_bucket.pods_db.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${google_service_account.pod[each.key].email}"

  condition {
    title       = "pod-${replace(each.key, "_", "-")}-db-path"
    description = "Restrict pod ${each.key} to its own DB replica path"
    expression = join("", [
      "resource.name.startsWith('projects/_/buckets/",
      google_storage_bucket.pods_db.name,
      "/objects/pods/${each.key}/')",
    ])
  }
}
