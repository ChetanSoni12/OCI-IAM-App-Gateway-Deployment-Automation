locals {
  profiles = {
    Development = { ocpus = 1, memory = 4 }
    Standard    = { ocpus = 2, memory = 8 }
    Production  = { ocpus = 4, memory = 16 }
  }
  profile           = local.profiles[var.container_size]
  tenant            = split(".", trimprefix(var.target_identity_domain_url, "https://"))[0]
  is_container      = var.runtime_type == "Container Instance"
  is_compute        = var.runtime_type == "Compute Instance"
  image_host        = split("/", var.appgateway_image)[0]
  ocir_credentials  = jsondecode(base64decode(data.oci_secrets_secretbundle.ocir_pull.secret_bundle_content[0].content))
  runtime_hostname  = var.deployment_name
  appgateway_vcpus  = (local.profile.ocpus * 2) - (var.deploy_smoke_backend ? 0.5 : 0)
  appgateway_memory = local.profile.memory - (var.deploy_smoke_backend ? 0.5 : 0)
  tags              = { "managed-by" = "iam-appgateway-devops", "deployment" = var.deployment_name }
}
