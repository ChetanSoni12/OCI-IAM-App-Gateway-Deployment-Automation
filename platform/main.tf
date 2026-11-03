data "oci_objectstorage_namespace" "tenancy" {
  compartment_id = var.compartment_ocid
}

resource "terraform_data" "input_validation" {
  lifecycle {
    precondition {
      condition     = local.create_vault || (var.existing_vault_id != "" && var.existing_vault_key_id != "")
      error_message = "Use existing Vault requires selecting both an existing Vault and its encryption key."
    }
  }
}

resource "oci_kms_vault" "platform" {
  count = local.create_vault ? 1 : 0

  compartment_id = var.compartment_ocid
  display_name   = var.vault_name
  vault_type     = "DEFAULT"
  freeform_tags  = local.common_tags
}

resource "oci_kms_key" "platform" {
  count = local.create_vault ? 1 : 0

  compartment_id      = var.compartment_ocid
  display_name        = var.vault_key_name
  management_endpoint = oci_kms_vault.platform[0].management_endpoint
  freeform_tags       = local.common_tags

  key_shape {
    algorithm = "AES"
    length    = 32
  }
}

resource "oci_artifacts_container_repository" "appgateway" {
  compartment_id = var.compartment_ocid
  display_name   = var.ocir_repository_name
  is_public      = false
  freeform_tags  = local.common_tags
}

resource "oci_ons_notification_topic" "release" {
  compartment_id = var.compartment_ocid
  name           = "${local.resource_prefix}-release-events"
  description    = "Build events for the OCI IAM App Gateway release platform."
  freeform_tags  = local.common_tags
}

resource "oci_devops_project" "release" {
  compartment_id = var.compartment_ocid
  name           = "${local.resource_prefix}-release"
  description    = "Controlled OCI IAM App Gateway image release platform."
  freeform_tags  = local.common_tags

  notification_config {
    topic_id = oci_ons_notification_topic.release.id
  }
}

# OCI DevOps refuses to start build runs until the project has a service log.
resource "oci_logging_log_group" "release" {
  compartment_id = var.compartment_ocid
  display_name   = "${local.resource_prefix}-release-logs"
  description    = "Service logs for the OCI IAM App Gateway release pipeline."
  freeform_tags  = local.common_tags
}

resource "oci_logging_log" "release" {
  log_group_id       = oci_logging_log_group.release.id
  display_name       = "${local.resource_prefix}-release"
  log_type           = "SERVICE"
  is_enabled         = true
  retention_duration = 30
  freeform_tags      = local.common_tags

  configuration {
    compartment_id = var.compartment_ocid

    source {
      service     = "devops"
      source_type = "OCISERVICE"
      category    = "all"
      resource    = oci_devops_project.release.id
    }
  }
}

resource "oci_devops_repository" "release_source" {
  name            = "${local.resource_prefix}-release-source"
  project_id      = oci_devops_project.release.id
  repository_type = "HOSTED"
  default_branch  = "main"
  description     = "Source for the OCI IAM App Gateway private-image release build."
  freeform_tags   = local.common_tags
}

resource "oci_devops_build_pipeline" "release" {
  project_id    = oci_devops_project.release.id
  display_name  = "${local.resource_prefix}-release"
  description   = "Checks and packages OCI IAM App Gateway into private OCIR."
  freeform_tags = local.common_tags
}

resource "oci_devops_deploy_artifact" "appgateway_image" {
  project_id                 = oci_devops_project.release.id
  display_name               = "${local.resource_prefix}-approved-image"
  description                = "Versioned OCI IAM App Gateway image in private OCIR."
  deploy_artifact_type       = "DOCKER_IMAGE"
  argument_substitution_mode = "SUBSTITUTE_PLACEHOLDERS"
  freeform_tags              = local.common_tags

  deploy_artifact_source {
    deploy_artifact_source_type = "OCIR"
    image_uri                   = "${var.region}.ocir.io/${data.oci_objectstorage_namespace.tenancy.namespace}/${var.ocir_repository_name}:$${APPGATEWAY_RELEASE_TAG}"
  }
}

resource "oci_devops_build_pipeline_stage" "build" {
  build_pipeline_id         = oci_devops_build_pipeline.release.id
  build_pipeline_stage_type = "BUILD"
  display_name              = "Validate App Gateway release"
  description               = "Downloads, validates, and prepares the x86_64 App Gateway Docker image."
  build_spec_file           = "build_spec.yaml"
  image                     = "OL8_X86_64_STANDARD_10"
  primary_build_source      = "release-source"
  freeform_tags             = local.common_tags

  build_pipeline_stage_predecessor_collection {
    items {
      id = oci_devops_build_pipeline.release.id
    }
  }

  build_source_collection {
    items {
      connection_type = "DEVOPS_CODE_REPOSITORY"
      name            = "release-source"
      repository_id   = oci_devops_repository.release_source.id
      repository_url  = oci_devops_repository.release_source.http_url
      branch          = "main"
    }
  }
}

resource "oci_devops_build_pipeline_stage" "deliver_image" {
  build_pipeline_id         = oci_devops_build_pipeline.release.id
  build_pipeline_stage_type = "DELIVER_ARTIFACT"
  display_name              = "Publish validated image"
  description               = "Publishes the versioned candidate image to private OCIR."
  freeform_tags             = local.common_tags

  build_pipeline_stage_predecessor_collection {
    items {
      id = oci_devops_build_pipeline_stage.build.id
    }
  }

  deliver_artifact_collection {
    items {
      artifact_id   = oci_devops_deploy_artifact.appgateway_image.id
      artifact_name = "appgateway-image"
    }
  }
}

resource "oci_vault_secret" "release_client_id" {
  compartment_id = var.compartment_ocid
  key_id         = local.vault_key_id
  secret_name    = "${local.resource_prefix}-release-client-id"
  vault_id       = local.vault_id
  freeform_tags  = local.common_tags

  secret_content {
    content_type = "BASE64"
    content      = base64encode(var.release_client_id)
  }
}

resource "oci_vault_secret" "release_client_secret" {
  compartment_id = var.compartment_ocid
  key_id         = local.vault_key_id
  secret_name    = "${local.resource_prefix}-release-client-secret"
  vault_id       = local.vault_id
  freeform_tags  = local.common_tags

  secret_content {
    content_type = "BASE64"
    content      = base64encode(var.release_client_secret)
  }
}

resource "oci_vault_secret" "ocir_pull_username" {
  compartment_id = var.compartment_ocid
  key_id         = local.vault_key_id
  secret_name    = "${local.resource_prefix}-ocir-pull-username"
  vault_id       = local.vault_id
  freeform_tags  = local.common_tags

  secret_content {
    content_type = "BASE64"
    content      = base64encode(var.ocir_pull_username)
  }
}

resource "oci_vault_secret" "ocir_pull_auth_token" {
  compartment_id = var.compartment_ocid
  key_id         = local.vault_key_id
  secret_name    = "${local.resource_prefix}-ocir-pull-auth-token"
  vault_id       = local.vault_id
  freeform_tags  = local.common_tags

  secret_content {
    content_type = "BASE64"
    content      = base64encode(var.ocir_pull_auth_token)
  }
}

resource "oci_vault_secret" "release_pipeline_id" {
  compartment_id = var.compartment_ocid
  key_id         = local.vault_key_id
  secret_name    = "${local.resource_prefix}-release-pipeline-id"
  vault_id       = local.vault_id
  freeform_tags  = local.common_tags

  secret_content {
    content_type = "BASE64"
    content      = base64encode(oci_devops_build_pipeline.release.id)
  }
}

resource "oci_identity_dynamic_group" "devops" {
  count = var.create_platform_policies ? 1 : 0

  compartment_id = var.tenancy_ocid
  name           = "${local.resource_prefix}-devops"
  description    = "OCI DevOps resources for the App Gateway release platform."
  matching_rule  = "ANY {resource.type = 'devopsbuildpipeline', resource.type = 'devopsrepository'}"
}

resource "oci_identity_policy" "devops" {
  count = var.create_platform_policies ? 1 : 0

  compartment_id = var.tenancy_ocid
  name           = "${local.resource_prefix}-devops-release-policy"
  description    = "Least-privilege access for the App Gateway DevOps release pipeline."

  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.devops[0].name} to read secret-bundles in compartment id ${var.compartment_ocid}",
    "Allow dynamic-group ${oci_identity_dynamic_group.devops[0].name} to manage repos in compartment id ${var.compartment_ocid}",
    "Allow dynamic-group ${oci_identity_dynamic_group.devops[0].name} to manage devops-family in compartment id ${var.compartment_ocid}",
  ]
}
