variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "trustmesh-hackathon"
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-west1"
}

variable "image_tag" {
  description = "Docker image tag (git short SHA)"
  type        = string
  default     = "latest"
}

variable "frontend_url" {
  description = "Deployed frontend Cloud Run URL (set after first apply)"
  type        = string
  default     = ""
}

variable "pod_urls" {
  description = "Map of pod_key -> Cloud Run URL (set after first apply)"
  type        = map(string)
  default     = {}
}

variable "alert_email" {
  description = "Email address for uptime/error-rate alerts (leave empty to disable)"
  type        = string
  default     = ""
}

# Pod definitions — keys match POD_ENTITIES in seed_multi.py
# Cloud Run service name: trustmesh-pod-{key} (underscores → hyphens)
variable "pods" {
  description = "Pod configuration map"
  type = map(object({
    display_name = string
    min          = number
    max          = number
  }))
  default = {
    user = {
      display_name = "Your Pod"
      min          = 1
      max          = 3
    }
    sarah = {
      display_name = "Sarah Johnson (Molly)"
      min          = 1
      max          = 3
    }
    mike = {
      display_name = "Mike Johnson"
      min          = 0
      max          = 2
    }
    emma = {
      display_name = "Emma Johnson"
      min          = 0
      max          = 2
    }
    grandma = {
      display_name = "Grandma Rose"
      min          = 0
      max          = 2
    }
    dr_chen = {
      display_name = "Dr. Chen"
      min          = 0
      max          = 2
    }
    tom = {
      display_name = "Tom"
      min          = 0
      max          = 2
    }
    lisa = {
      display_name = "Lisa Rodriguez"
      min          = 0
      max          = 2
    }
    priya = {
      display_name = "Priya Patel"
      min          = 0
      max          = 2
    }
    james = {
      display_name = "James Wilson"
      min          = 0
      max          = 2
    }
    maria = {
      display_name = "Maria Santos"
      min          = 0
      max          = 2
    }
    techcorp = {
      display_name = "TechCorp"
      min          = 0
      max          = 2
    }
    hospital = {
      display_name = "Riverside Hospital"
      min          = 0
      max          = 2
    }
    music = {
      display_name = "Music Collective"
      min          = 0
      max          = 2
    }
    city = {
      display_name = "City of Riverside"
      min          = 0
      max          = 2
    }
    insurance = {
      display_name = "Insurance Co"
      min          = 0
      max          = 2
    }
    dance = {
      display_name = "Dance Studio"
      min          = 0
      max          = 2
    }
  }
}
