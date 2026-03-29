# ── Uptime checks ─────────────────────────────────────────────────────────────

resource "google_monitoring_uptime_check_config" "frontend" {
  display_name = "TrustMesh Frontend"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path           = "/"
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimprefix(google_cloud_run_v2_service.frontend.uri, "https://")
    }
  }

  depends_on = [google_cloud_run_v2_service.frontend]
}

resource "google_monitoring_uptime_check_config" "registry" {
  display_name = "TrustMesh Registry"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path           = "/api/health"
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimprefix(google_cloud_run_v2_service.registry.uri, "https://")
    }
  }

  depends_on = [google_cloud_run_v2_service.registry]
}

resource "google_monitoring_uptime_check_config" "pod_user" {
  display_name = "TrustMesh User Pod"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path           = "/health"
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimprefix(google_cloud_run_v2_service.pods["user"].uri, "https://")
    }
  }

  depends_on = [google_cloud_run_v2_service.pods]
}

# ── Notification channel (email) ──────────────────────────────────────────────

resource "google_monitoring_notification_channel" "email_alert" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "TrustMesh Alerts"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
}

# ── Alert: uptime check failures ──────────────────────────────────────────────

resource "google_monitoring_alert_policy" "uptime_failure" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "TrustMesh Service Down"
  combiner     = "OR"

  conditions {
    display_name = "Frontend uptime check failed"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" resource.type=\"uptime_url\" metric.label.check_id=\"${google_monitoring_uptime_check_config.frontend.uptime_check_id}\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_FRACTION_TRUE"
      }
    }
  }

  conditions {
    display_name = "User pod uptime check failed"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" resource.type=\"uptime_url\" metric.label.check_id=\"${google_monitoring_uptime_check_config.pod_user.uptime_check_id}\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_FRACTION_TRUE"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email_alert[0].name]

  alert_strategy {
    auto_close = "7200s"
  }

  documentation {
    content   = "A TrustMesh service has failed its uptime check. Check Cloud Run logs: https://console.cloud.google.com/run?project=${var.project_id}"
    mime_type = "text/markdown"
  }
}

# ── Alert: high 5xx error rate on pods ────────────────────────────────────────

resource "google_monitoring_alert_policy" "high_error_rate" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "TrustMesh High 5xx Rate"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run 5xx error rate > 5%"
    condition_threshold {
      filter = join("", [
        "resource.type=\"cloud_run_revision\" ",
        "metric.type=\"run.googleapis.com/request_count\" ",
        "metric.label.response_code_class=\"5xx\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "300s"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.service_name"]
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email_alert[0].name]

  alert_strategy {
    auto_close = "1800s"
  }
}
