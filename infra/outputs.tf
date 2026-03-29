output "pod_urls" {
  description = "Map of pod_key -> Cloud Run URL"
  value = {
    for k, svc in google_cloud_run_v2_service.pods : k => svc.uri
  }
}

output "frontend_url" {
  description = "Frontend Cloud Run URL"
  value       = google_cloud_run_v2_service.frontend.uri
}

output "registry_url" {
  description = "Registry Cloud Run URL"
  value       = google_cloud_run_v2_service.registry.uri
}

output "pod_user_url" {
  description = "User pod Cloud Run URL"
  value       = google_cloud_run_v2_service.pods["user"].uri
}

output "pods_db_bucket" {
  description = "GCS bucket name for Litestream DB replicas"
  value       = google_storage_bucket.pods_db.name
}

output "pool_sync_secret_name" {
  description = "Secret Manager secret ID for TRUSTMESH_POOL_SYNC_SECRET (auto-generated)"
  value       = google_secret_manager_secret.pool_sync_secret.secret_id
  sensitive   = false # Just the name, not the value
}
