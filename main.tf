variable "gcp_service_list" {
  description = "Required APIs"
  type        = list(string)
  default = [
    "cloudresourcemanager.googleapis.com",
    "cloudfunctions.googleapis.com",
    "pubsub.googleapis.com",
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "containerscanning.googleapis.com",
    "run.googleapis.com",
    "aiplatform.googleapis.com",
    "integrations.googleapis.com",
    "cloudasset.googleapis.com",
    "orgpolicy.googleapis.com",
  ]
}

resource "google_project_service" "gcp_services" {
  for_each                   = toset(var.gcp_service_list)
  project                    = var.PROJECT_ID
  service                    = each.key
  disable_dependent_services = true
  disable_on_destroy         = false
}