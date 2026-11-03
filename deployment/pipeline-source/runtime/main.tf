resource "oci_core_network_security_group" "appgateway" {
  compartment_id = var.compartment_ocid
  vcn_id         = data.oci_core_subnet.runtime.vcn_id
  display_name   = "${var.deployment_name}-appgateway"
  freeform_tags  = local.tags
}

data "oci_core_subnet" "runtime" {
  subnet_id = var.subnet_id
}

resource "oci_core_network_security_group_security_rule" "ingress" {
  for_each                  = toset(var.allowed_ingress_cidrs)
  network_security_group_id = oci_core_network_security_group.appgateway.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = each.value
  source_type               = "CIDR_BLOCK"

  tcp_options {
    destination_port_range {
      min = var.gateway_https_port
      max = var.gateway_https_port
    }
  }
}

resource "oci_core_network_security_group_security_rule" "egress" {
  network_security_group_id = oci_core_network_security_group.appgateway.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
}

resource "oci_core_network_security_group_security_rule" "compute_ssh" {
  count                     = local.is_compute && var.enable_compute_ssh ? 1 : 0
  network_security_group_id = oci_core_network_security_group.appgateway.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = var.compute_ssh_allowed_cidr
  source_type               = "CIDR_BLOCK"

  tcp_options {
    destination_port_range {
      min = 22
      max = 22
    }
  }
}

data "oci_secrets_secretbundle" "wallet" {
  secret_id = var.wallet_secret_id
}

data "oci_secrets_secretbundle" "tls_cert" {
  secret_id = var.tls_cert_secret_id
}

data "oci_secrets_secretbundle" "tls_key" {
  secret_id = var.tls_key_secret_id
}

data "oci_secrets_secretbundle" "ocir_pull" {
  secret_id = var.ocir_pull_secret_id
}

resource "oci_container_instances_container_instance" "appgateway" {
  count               = local.is_container ? 1 : 0
  availability_domain = var.availability_domain
  compartment_id      = var.compartment_ocid
  display_name        = "${var.deployment_name}-appgateway"
  shape               = "CI.Standard.E4.Flex"
  freeform_tags       = local.tags

  shape_config {
    ocpus         = local.profile.ocpus
    memory_in_gbs = local.profile.memory
  }

  # OCI Container Instances expects BASIC image credentials. The DevOps runner
  # reads the protected Vault secret and supplies the encoded fields here.
  image_pull_secrets {
    registry_endpoint = local.image_host
    secret_type       = "BASIC"
    username          = base64encode(local.ocir_credentials.username)
    password          = base64encode(local.ocir_credentials.password)
  }

  containers {
    display_name                   = "appgateway"
    image_url                      = var.appgateway_image
    is_resource_principal_disabled = true
    environment_variables = {
      CG_APP_TENANT      = local.tenant
      IDCS_INSTANCE_URL  = var.target_identity_domain_url
      NGINX_DNS_RESOLVER = "169.254.169.254"
      HOST_MACHINE       = local.runtime_hostname
    }
    resource_config {
      vcpus_limit         = local.appgateway_vcpus
      memory_limit_in_gbs = local.appgateway_memory
    }
    volume_mounts {
      mount_path   = "/usr/local/nginx/conf/cwallet.sso"
      sub_path     = "cwallet.sso"
      volume_name  = "appgateway-wallet"
      is_read_only = true
    }
    volume_mounts {
      mount_path   = "/usr/local/nginx/conf/cert.pem"
      sub_path     = "cert.pem"
      volume_name  = "appgateway-tls"
      is_read_only = true
    }
    volume_mounts {
      mount_path   = "/usr/local/nginx/conf/key.pem"
      sub_path     = "key.pem"
      volume_name  = "appgateway-tls"
      is_read_only = true
    }
  }

  dynamic "containers" {
    for_each = var.deploy_smoke_backend ? [1] : []
    content {
      display_name                   = "header-sample"
      image_url                      = var.smoke_backend_image
      is_resource_principal_disabled = true
      resource_config {
        vcpus_limit         = 0.5
        memory_limit_in_gbs = 0.5
      }
    }
  }

  volumes {
    name        = "appgateway-wallet"
    volume_type = "CONFIGFILE"
    configs {
      file_name = "cwallet.sso"
      data      = data.oci_secrets_secretbundle.wallet.secret_bundle_content[0].content
    }
  }

  volumes {
    name        = "appgateway-tls"
    volume_type = "CONFIGFILE"
    configs {
      file_name = "cert.pem"
      data      = data.oci_secrets_secretbundle.tls_cert.secret_bundle_content[0].content
    }
    configs {
      file_name = "key.pem"
      data      = data.oci_secrets_secretbundle.tls_key.secret_bundle_content[0].content
    }
  }

  vnics {
    hostname_label        = local.runtime_hostname
    subnet_id             = var.subnet_id
    is_public_ip_assigned = var.assign_public_ip
    nsg_ids               = [oci_core_network_security_group.appgateway.id]
  }

  lifecycle {
    precondition {
      condition     = !var.assign_public_ip || !data.oci_core_subnet.runtime.prohibit_public_ip_on_vnic
      error_message = "The selected subnet prohibits public IP assignment. Disable assign_public_ip and use an existing OCI or external load balancer."
    }
  }
}

resource "oci_core_instance" "appgateway" {
  count               = local.is_compute ? 1 : 0
  availability_domain = var.availability_domain
  compartment_id      = var.compartment_ocid
  display_name        = "${var.deployment_name}-appgateway"
  shape               = "VM.Standard.E4.Flex"
  freeform_tags       = local.tags

  shape_config {
    ocpus         = local.profile.ocpus
    memory_in_gbs = local.profile.memory
  }
  create_vnic_details {
    hostname_label   = local.runtime_hostname
    subnet_id        = var.subnet_id
    assign_public_ip = var.assign_public_ip
    nsg_ids          = [oci_core_network_security_group.appgateway.id]
  }
  source_details {
    source_type = "image"
    source_id   = var.compute_image_ocid
  }
  metadata = merge({
    user_data = base64encode(templatefile("${path.module}/compute-cloud-init.sh.tftpl", {
      image               = var.appgateway_image
      image_host          = local.image_host
      wallet_secret_id    = var.wallet_secret_id
      tls_cert_secret_id  = var.tls_cert_secret_id
      tls_key_secret_id   = var.tls_key_secret_id
      ocir_secret_id      = var.ocir_pull_secret_id
      tenant              = local.tenant
      domain_url          = var.target_identity_domain_url
      resolver            = "169.254.169.254"
      runtime_hostname    = local.runtime_hostname
      gateway_https_port  = var.gateway_https_port
      smoke_backend       = var.deploy_smoke_backend
      smoke_backend_image = var.smoke_backend_image
    }))
  }, var.enable_compute_ssh ? { ssh_authorized_keys = var.compute_ssh_public_key } : {})

  lifecycle {
    precondition {
      condition     = var.compute_image_ocid != ""
      error_message = "Compute Instance runtime requires an Oracle Linux image OCID."
    }
    precondition {
      condition     = !var.assign_public_ip || !data.oci_core_subnet.runtime.prohibit_public_ip_on_vnic
      error_message = "The selected subnet prohibits public IP assignment. Disable assign_public_ip and use an existing OCI or external load balancer."
    }
    precondition {
      condition = !var.enable_compute_ssh || (
        trimspace(var.compute_ssh_public_key) != "" &&
        can(cidrnetmask(var.compute_ssh_allowed_cidr)) &&
        !contains(["0.0.0.0/0", "::/0"], var.compute_ssh_allowed_cidr)
      )
      error_message = "Compute SSH requires an OpenSSH public key and one valid allowed source CIDR."
    }
  }
}

data "oci_core_vnic" "container" {
  count   = local.is_container ? 1 : 0
  vnic_id = oci_container_instances_container_instance.appgateway[0].vnics[0].vnic_id
}

data "oci_core_vnic_attachments" "compute" {
  count          = local.is_compute ? 1 : 0
  compartment_id = var.compartment_ocid
  instance_id    = oci_core_instance.appgateway[0].id
}

data "oci_core_vnic" "compute" {
  count   = local.is_compute ? 1 : 0
  vnic_id = data.oci_core_vnic_attachments.compute[0].vnic_attachments[0].vnic_id
}

resource "oci_load_balancer_backend" "appgateway" {
  count            = var.use_existing_oci_load_balancer ? 1 : 0
  load_balancer_id = var.existing_load_balancer_id
  backendset_name  = var.existing_load_balancer_backend_set_name
  ip_address       = local.is_container ? data.oci_core_vnic.container[0].private_ip_address : data.oci_core_vnic.compute[0].private_ip_address
  port             = var.gateway_https_port
  drain            = false
  backup           = false
  offline          = false
}
