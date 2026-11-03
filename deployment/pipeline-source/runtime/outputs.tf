output "private_ip" { value = local.is_container ? data.oci_core_vnic.container[0].private_ip_address : data.oci_core_vnic.compute[0].private_ip_address }
output "public_ip" { value = local.is_container ? data.oci_core_vnic.container[0].public_ip_address : data.oci_core_vnic.compute[0].public_ip_address }
output "runtime_id" { value = local.is_container ? oci_container_instances_container_instance.appgateway[0].id : oci_core_instance.appgateway[0].id }
output "compute_ssh_command" {
  value = local.is_compute && var.enable_compute_ssh && var.assign_public_ip ? "ssh opc@${data.oci_core_vnic.compute[0].public_ip_address}" : null
}
