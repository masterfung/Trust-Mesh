locals {
  image_frontend = "${var.region}-docker.pkg.dev/${var.project_id}/trustmesh/frontend:${var.image_tag}"
}

resource "google_cloud_run_v2_service" "frontend" {
  name     = "trustmesh-frontend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.frontend.email
    timeout         = "60s"

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = local.image_frontend

      env {
        name  = "TRUSTMESH_PROXY_POD"
        value = lookup(var.pod_urls, "user", "")
      }

      env {
        name  = "TRUSTMESH_REGISTRY_URL"
        value = google_cloud_run_v2_service.registry.uri
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      startup_probe {
        http_get { path = "/" }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 12
        timeout_seconds       = 5
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_service_account.frontend,
    google_artifact_registry_repository.trustmesh,
  ]
}

# ── Cloud Armor: comprehensive WAF for the frontend ───────────────────────────
resource "google_compute_security_policy" "frontend" {
  name        = "trustmesh-frontend-armor"
  description = "Rate limiting + OWASP WAF for TrustMesh frontend"

  # ── Priority 100–199: Explicit geo / IP allowlists (none by default) ────────

  # ── Priority 1000: Rate limit — 120 req/min per IP (2 req/s) ────────────────
  rule {
    action   = "rate_based_ban"
    priority = 1000
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 120
        interval_sec = 60
      }
      ban_duration_sec = 300 # 5-min ban after burst
    }
    description = "Rate limit 120 req/min per IP; ban 5 min on exceed"
  }

  # ── Priority 2000–2099: OWASP CRS (pre-configured rule sets) ────────────────
  rule {
    action   = "deny(403)"
    priority = 2000
    match {
      expr { expression = "evaluatePreconfiguredExpr('xss-v33-stable')" }
    }
    description = "OWASP: Cross-site scripting (XSS)"
  }

  rule {
    action   = "deny(403)"
    priority = 2001
    match {
      expr { expression = "evaluatePreconfiguredExpr('sqli-v33-stable')" }
    }
    description = "OWASP: SQL injection"
  }

  rule {
    action   = "deny(403)"
    priority = 2002
    match {
      expr { expression = "evaluatePreconfiguredExpr('lfi-v33-stable')" }
    }
    description = "OWASP: Local file inclusion"
  }

  rule {
    action   = "deny(403)"
    priority = 2003
    match {
      expr { expression = "evaluatePreconfiguredExpr('rfi-v33-stable')" }
    }
    description = "OWASP: Remote file inclusion"
  }

  rule {
    action   = "deny(403)"
    priority = 2004
    match {
      expr { expression = "evaluatePreconfiguredExpr('rce-v33-stable')" }
    }
    description = "OWASP: Remote code execution"
  }

  rule {
    action   = "deny(403)"
    priority = 2005
    match {
      expr { expression = "evaluatePreconfiguredExpr('methodenforcement-v33-stable')" }
    }
    description = "OWASP: HTTP method enforcement"
  }

  rule {
    action   = "deny(403)"
    priority = 2006
    match {
      expr { expression = "evaluatePreconfiguredExpr('scannerdetection-v33-stable')" }
    }
    description = "OWASP: Scanner/bot detection"
  }

  rule {
    action   = "deny(403)"
    priority = 2007
    match {
      expr { expression = "evaluatePreconfiguredExpr('protocolattack-v33-stable')" }
    }
    description = "OWASP: Protocol attack"
  }

  rule {
    action   = "deny(403)"
    priority = 2008
    match {
      expr { expression = "evaluatePreconfiguredExpr('php-v33-stable')" }
    }
    description = "OWASP: PHP injection"
  }

  rule {
    action   = "deny(403)"
    priority = 2009
    match {
      expr { expression = "evaluatePreconfiguredExpr('java-v33-stable')" }
    }
    description = "OWASP: Java attack (includes Log4j CVE-2021-44228)"
  }

  rule {
    action   = "deny(403)"
    priority = 2010
    match {
      expr { expression = "evaluatePreconfiguredExpr('nodejs-v33-stable')" }
    }
    description = "OWASP: Node.js attack"
  }

  # ── Default: allow all other traffic ────────────────────────────────────────
  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    description = "Default allow"
  }

  depends_on = [google_project_service.apis]
}
