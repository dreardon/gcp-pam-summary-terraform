provider "google" {
  project               = var.PROJECT_ID
  billing_project       = var.PROJECT_ID
  region                = var.DEFAULT_REGION
  user_project_override = true
}