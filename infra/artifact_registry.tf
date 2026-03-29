resource "google_artifact_registry_repository" "trustmesh" {
  location      = var.region
  repository_id = "trustmesh"
  format        = "DOCKER"
  description   = "TrustMesh Docker images"

  depends_on = [google_project_service.apis]
}
