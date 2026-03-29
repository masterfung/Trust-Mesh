locals {
  image_registry = "${var.region}-docker.pkg.dev/${var.project_id}/trustmesh/registry:${var.image_tag}"
}

resource "google_cloud_run_v2_service" "registry" {
  name     = "trustmesh-registry"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.registry.email
    timeout         = "60s"

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = local.image_registry

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      startup_probe {
        http_get {
          path = "/api/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 12
        timeout_seconds       = 5
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_service_account.registry,
    google_artifact_registry_repository.trustmesh,
  ]
}
