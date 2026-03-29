locals {
  image_backend = "${var.region}-docker.pkg.dev/${var.project_id}/trustmesh/backend:${var.image_tag}"
}

resource "google_cloud_run_v2_service" "pods" {
  for_each = var.pods
  name     = "trustmesh-pod-${replace(each.key, "_", "-")}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account  = google_service_account.pod[each.key].email
    session_affinity = true # Required for WebSocket (Gemini Live voice)
    timeout          = "300s"

    scaling {
      min_instance_count = each.value.min
      max_instance_count = each.value.max
    }

    containers {
      image = local.image_backend

      # DB lives in /tmp (writable tmpfs — Cloud Run default). Litestream replicates
      # to GCS and restores on cold start, so data is durable across container restarts.
      env {
        name  = "TRUSTMESH_POD_NAME"
        value = each.value.display_name
      }
      env {
        name  = "TRUSTMESH_POD_URL"
        value = lookup(var.pod_urls, each.key, "")
      }
      env {
        name  = "TRUSTMESH_DB"
        value = "/tmp/trustmesh.db"
      }
      env {
        name  = "TRUSTMESH_REGISTRY_URL"
        value = google_cloud_run_v2_service.registry.uri
      }
      env {
        name  = "TRUSTMESH_FRONTEND_URL"
        value = var.frontend_url
      }
      env {
        name  = "SEED_POD_KEY"
        value = each.key
      }
      # Litestream GCS disabled for now — pods reseed on cold start from SEED_POD_KEY.
      # Re-enable after verifying GCS replica type support in the deployed Litestream version.
      # env { name = "LITESTREAM_GCS_BUCKET"; value = google_storage_bucket.pods_db.name }
      # env { name = "LITESTREAM_GCS_PATH";   value = "pods/${each.key}/db" }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.google_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "ANTHROPIC_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.anthropic_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "TRUSTMESH_POOL_SYNC_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.pool_sync_secret.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle = true
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 30
        period_seconds        = 30
        failure_threshold     = 3
        timeout_seconds       = 5
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 10
        period_seconds        = 10
        failure_threshold     = 30
        timeout_seconds       = 5
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_service_account.pod,
    google_storage_bucket.pods_db,
    google_artifact_registry_repository.trustmesh,
    google_secret_manager_secret_version.pool_sync_secret,
  ]
}
