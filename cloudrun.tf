resource "google_project_iam_member" "cloudbuild_builder_binding" {
  project = var.PROJECT_ID
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${var.PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "cloudbuild_tokencreator_binding" {
  project = var.PROJECT_ID
  role    = "roles/iam.serviceAccountTokenCreator"
  member  = "serviceAccount:service-${var.PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription" "pam-event-subscription" {
  name  = "pam-event-subscription"
  topic = google_pubsub_topic.pam_events_topic.name

  ack_deadline_seconds = 600

  push_config {
    push_endpoint = "https://cloud-run-pam-${var.PROJECT_NUMBER}.${var.DEFAULT_REGION}.run.app"
    oidc_token {
      service_account_email = "cloud-run-pam-invoker@${var.PROJECT_ID}.iam.gserviceaccount.com"
    }
  }
}

resource "google_service_account" "cloud-run-pam-invoker" {
  account_id   = "cloud-run-pam-invoker"
  display_name = "Cloud Run PAM Summary Pub/Sub Invoker"
}

resource "google_cloudfunctions2_function" "cloud-run-pam" {
  name        = "cloud-run-pam"
  location    = var.DEFAULT_REGION
  description = "PAM Cloud Run Function"

  build_config {
    runtime     = "python312"
    entry_point = "index"
    environment_variables = {
      BUILD_CONFIG_TEST = "build_test"
    }
    source {
      storage_source {
        bucket = google_storage_bucket.pam_src_zip_storage.name
        object = google_storage_bucket_object.pam_src_zip_remote.name
      }
    }
  }

  service_config {
    available_memory = "512M"
    timeout_seconds  = 60
    environment_variables = {
      PROJECT_ID        = var.PROJECT_ID
      SUMMARY_RECIPIENT = var.SUMMARY_RECIPIENT
      REGION            = var.DEFAULT_REGION
    }
    ingress_settings               = "ALLOW_INTERNAL_ONLY"
    all_traffic_on_latest_revision = true
  }
}

data "archive_file" "pam_src_zip_local" {
  type        = "zip"
  output_path = "/tmp/function-source.zip"
  source_dir  = "./src"
}

resource "random_id" "default" {
  byte_length = 8
}
resource "google_storage_bucket" "pam_src_zip_storage" {
  name                        = "gcf-source-${random_id.default.hex}"
  project                     = var.PROJECT_ID
  location                    = "US"
  uniform_bucket_level_access = true
}
resource "google_storage_bucket_object" "pam_src_zip_remote" {
  name   = "function-source.zip"
  bucket = google_storage_bucket.pam_src_zip_storage.name
  source = data.archive_file.pam_src_zip_local.output_path
}

resource "google_cloud_run_service_iam_member" "member" {
  location = google_cloudfunctions2_function.cloud-run-pam.location
  project  = google_cloudfunctions2_function.cloud-run-pam.project
  service  = google_cloudfunctions2_function.cloud-run-pam.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:cloud-run-pam-invoker@${var.PROJECT_ID}.iam.gserviceaccount.com"
}


### Cloud Run Permissions
#Org-level Cloud Run Service Account Permissions
resource "google_organization_iam_member" "org_cr_pam_binding" {
  org_id = var.ORG_ID
  role   = "roles/privilegedaccessmanager.viewer"
  member = "serviceAccount:${var.PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
}

resource "google_organization_iam_member" "org_cr_cai_binding" {
  org_id = var.ORG_ID
  role   = "roles/cloudasset.viewer"
  member = "serviceAccount:${var.PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
}

resource "google_organization_iam_member" "org_cr_logging_binding" {
  org_id = var.ORG_ID
  role   = "roles/logging.viewer"
  member = "serviceAccount:${var.PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
}

resource "google_organization_iam_member" "org_cr_config_binding" {
  org_id = var.ORG_ID
  role   = "roles/logging.configWriter"
  member = "serviceAccount:${var.PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
}

#Project-level Cloud Run Service Account Permissions
resource "google_project_iam_binding" "prj_cr_logging_binding" {
  project = var.PROJECT_ID
  role    = "roles/logging.logWriter"
  members = [
    "serviceAccount:${var.PROJECT_NUMBER}-compute@developer.gserviceaccount.com",
  ]
}

resource "google_project_iam_binding" "prj_cr_ai_binding" {
  project = var.PROJECT_ID
  role    = "roles/aiplatform.user"
  members = [
    "serviceAccount:${var.PROJECT_NUMBER}-compute@developer.gserviceaccount.com",
  ]
}

resource "google_project_iam_binding" "prj_cr_bq_binding" {
  project = var.PROJECT_ID
  role    = "roles/bigquery.user"
  members = [
    "serviceAccount:${var.PROJECT_NUMBER}-compute@developer.gserviceaccount.com",
  ]
}

resource "google_project_iam_binding" "prj_cr_appint_binding" {
  project = var.PROJECT_ID
  role    = "roles/integrations.integrationInvoker"
  members = [
    "serviceAccount:${var.PROJECT_NUMBER}-compute@developer.gserviceaccount.com",
  ]
}