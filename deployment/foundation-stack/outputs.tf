output "application_source_repository_url" {
  value       = oci_devops_repository.application_source.http_url
  description = "Private DevOps repository where the non-secret application deployment pipeline source must be published once."
}

output "application_pipeline_id" {
  value       = oci_devops_build_pipeline.application.id
  description = "OCI DevOps pipeline started manually after Cloud Shell bootstrap is complete."
}

output "next_step" {
  value = "The Cloud Shell bootstrap publishes source and configuration to application_source_repository_url automatically. Open the pipeline and choose Start Manual Run."
}

output "terraform_state_bucket" {
  value       = oci_objectstorage_bucket.state.name
  description = "Private bucket used only for Terraform state and deployment metadata."
}
