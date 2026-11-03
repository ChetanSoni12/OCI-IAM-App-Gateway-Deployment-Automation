resource "oci_ons_notification_topic" "application" {
  compartment_id = var.compartment_ocid
  name           = "${local.prefix}-events"
  description    = "Build events for OCI IAM App Gateway customer deployments."
  freeform_tags  = local.tags
}

data "oci_objectstorage_namespace" "tenancy" {
  compartment_id = var.compartment_ocid
}

resource "oci_objectstorage_bucket" "state" {
  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.tenancy.namespace
  name           = local.state_bucket_name
  access_type    = "NoPublicAccess"
  versioning     = "Enabled"
  freeform_tags  = local.tags
}

resource "oci_devops_project" "application" {
  compartment_id = var.compartment_ocid
  name           = local.prefix
  description    = "OCI IAM App Gateway customer deployment automation."
  freeform_tags  = local.tags

  notification_config {
    topic_id = oci_ons_notification_topic.application.id
  }
}

resource "oci_logging_log_group" "application" {
  compartment_id = var.compartment_ocid
  display_name   = "${local.prefix}-logs"
  description    = "Service logs for OCI IAM App Gateway customer deployments."
  freeform_tags  = local.tags
}

resource "oci_logging_log" "application" {
  log_group_id       = oci_logging_log_group.application.id
  display_name       = local.prefix
  log_type           = "SERVICE"
  is_enabled         = true
  retention_duration = 30
  freeform_tags      = local.tags

  configuration {
    compartment_id = var.compartment_ocid
    source {
      service     = "devops"
      source_type = "OCISERVICE"
      category    = "all"
      resource    = oci_devops_project.application.id
    }
  }
}

resource "oci_devops_repository" "application_source" {
  name            = "${local.prefix}-source"
  project_id      = oci_devops_project.application.id
  repository_type = "HOSTED"
  default_branch  = "main"
  description     = "Source for OCI IAM App Gateway customer deployment automation."
  freeform_tags   = local.tags
}

resource "oci_devops_build_pipeline" "application" {
  project_id    = oci_devops_project.application.id
  display_name  = local.prefix
  description   = "Creates, updates, and destroys OCI IAM App Gateway customer deployments."
  freeform_tags = local.tags

  build_pipeline_parameters {
    dynamic "items" {
      for_each = local.pipeline_parameters
      content {
        name          = items.key
        default_value = items.value.value
        description   = items.value.description
      }
    }
  }
}

resource "oci_devops_build_pipeline_stage" "application" {
  build_pipeline_id         = oci_devops_build_pipeline.application.id
  build_pipeline_stage_type = "BUILD"
  display_name              = "Deploy OCI IAM App Gateway"
  description               = "Creates, updates, or destroys one OCI IAM App Gateway deployment from DevOps pipeline parameters."
  build_spec_file           = "build_spec.yaml"
  image                     = "OL8_X86_64_STANDARD_10"
  primary_build_source      = "application-source"
  freeform_tags             = local.tags

  build_pipeline_stage_predecessor_collection {
    items { id = oci_devops_build_pipeline.application.id }
  }

  build_source_collection {
    items {
      connection_type = "DEVOPS_CODE_REPOSITORY"
      name            = "application-source"
      repository_id   = oci_devops_repository.application_source.id
      repository_url  = oci_devops_repository.application_source.http_url
      branch          = "main"
    }
  }
}
