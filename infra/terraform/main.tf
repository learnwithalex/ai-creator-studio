terraform {
  required_version = ">= 1.6.0"
}

variable "project_name" {
  type    = string
  default = "ai-creator-studio"
}

output "notes" {
  value = "Provision Postgres, Redis, gateway/signaling runtime, and RunPod hooks in modules/core."
}
