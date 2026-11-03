output "platform_vault_id" {
  description = "Vault holding the platform release and OCIR pull secrets."
  value       = local.vault_id
}

output "platform_vault_key_id" {
  description = "Key used to encrypt platform secrets."
  value       = local.vault_key_id
}

output "release_client_id_secret_id" {
  description = "Vault secret OCID for the release IAM client ID."
  value       = oci_vault_secret.release_client_id.id
}

output "release_client_secret_secret_id" {
  description = "Vault secret OCID for the release IAM client secret."
  value       = oci_vault_secret.release_client_secret.id
}

output "ocir_pull_username_secret_id" {
  description = "Vault secret OCID for the private OCIR pull username."
  value       = oci_vault_secret.ocir_pull_username.id
}

output "ocir_pull_auth_token_secret_id" {
  description = "Vault secret OCID for the private OCIR pull token."
  value       = oci_vault_secret.ocir_pull_auth_token.id
}

output "release_pipeline_id_secret_id" {
  description = "Vault secret OCID containing the release pipeline OCID for future deployment bootstraps."
  value       = oci_vault_secret.release_pipeline_id.id
}

output "release_pipeline_id" {
  description = "OCI DevOps pipeline that builds and publishes the approved App Gateway image."
  value       = oci_devops_build_pipeline.release.id
}

output "release_notification_topic_id" {
  description = "OCI Notifications topic for release pipeline events. Add email subscriptions in the OCI Console if desired."
  value       = oci_ons_notification_topic.release.id
}

output "release_log_group_id" {
  description = "OCI Logging group containing the DevOps release pipeline logs."
  value       = oci_logging_log_group.release.id
}

output "release_log_id" {
  description = "Enabled OCI DevOps service log for the release project."
  value       = oci_logging_log.release.id
}

output "release_source_repository_url" {
  description = "Private OCI DevOps repository URL that receives the release source once."
  value       = oci_devops_repository.release_source.http_url
}

output "private_ocir_repository" {
  description = "Private OCIR repository where the DevOps pipeline publishes versioned App Gateway images."
  value       = "${var.region}.ocir.io/${data.oci_objectstorage_namespace.tenancy.namespace}/${var.ocir_repository_name}"
}

output "platform_initialization_next_step" {
  description = "One-time action after this stack completes."
  value       = "Run platform/scripts/publish-release-source.sh from Cloud Shell with release_source_repository_url and the two release client secret outputs. Then run the DevOps pipeline once."
}
