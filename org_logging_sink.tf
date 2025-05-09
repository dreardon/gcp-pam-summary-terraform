resource "google_pubsub_topic" "pam_events_topic" {
  name                       = "pam-events-topic"
  message_retention_duration = "86600s"
}

resource "google_logging_organization_sink" "pam-events-sink" {
  name             = "pam-events-sink-tf"
  description      = "Organization Log Sink to Capture PAM Events"
  org_id           = var.ORG_ID
  include_children = true
  destination      = "pubsub.googleapis.com/projects/${var.PROJECT_ID}/topics/${google_pubsub_topic.pam_events_topic.name}"
  filter           = "proto_payload.method_name=(\"PAMActivateGrant\" OR \"PAMEndGrant\" OR \"google.cloud.privilegedaccessmanager.v1alpha.PrivilegedAccessManager.RevokeGrant\")"
}

resource "google_pubsub_topic_iam_binding" "topic_publisher_binding" {
  project = var.PROJECT_ID
  topic   = google_pubsub_topic.pam_events_topic.name
  role    = "roles/pubsub.publisher"
  members = [
    "serviceAccount:service-org-${var.ORG_ID}@gcp-sa-logging.iam.gserviceaccount.com",
  ]
}