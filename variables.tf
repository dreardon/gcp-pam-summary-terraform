
variable "ORG_ID" {
  description = "GCP Organization ID"
  type        = string
}
variable "PROJECT_ID" {
  description = "GCP Project ID"
  type        = string
}

variable "PROJECT_NUMBER" {
  description = "GCP Project Number"
  type        = string
}

variable "DEFAULT_REGION" {
  description = "Default region to create resources where applicable."
  type        = string
  default     = "us-central1"
}

variable "SUMMARY_RECIPIENT" {
  description = "Default recipient of the PAM summary email"
  type        = string
}