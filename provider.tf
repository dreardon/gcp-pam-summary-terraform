provider "google" {
  project               = var.PROJECT_ID
  billing_project       = var.PROJECT_ID
  region                = var.DEFAULT_REGION
  user_project_override = true
}

terraform {
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    google = {
      source = "hashicorp/google"
      version = "~> 6.34.0"
    }
    archive = {
      source = "hashicorp/archive"
      version = "2.7.0"
    }
  }
}