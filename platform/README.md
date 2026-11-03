# Private App Gateway Image Release Platform

Deploy this Resource Manager stack once in the tenancy. It creates the shared release foundation used by all later App Gateway deployments:

- Private OCIR repository for versioned App Gateway images.
- OCI Vault and named secrets for the release IAM client and OCIR pull credentials.
- OCI DevOps project, private source repository, managed build stage, and Deliver Artifacts stage.
- An enabled OCI Logging service log for the DevOps project, retained for 30 days.
- OCI Notifications topic for release events.
- Least-privilege DevOps dynamic group and policies.

## Release activation

Resource Manager can create the empty OCI DevOps source repository but cannot commit the build source into it. This is an OCI DevOps service boundary, not an App Gateway requirement.

After the stack completes, use Cloud Shell to run [publish-release-source.sh](scripts/publish-release-source.sh). The helper copies only the non-secret `release/` source, writes `build_spec.yaml` with secret **OCIDs** (not their values), and creates or safely updates the private OCI DevOps repository.

Run the DevOps pipeline once after publishing the source. The pipeline builds a versioned image in private OCIR. This is the only package-image download from the release IAM domain. The managed build stage uses Oracle Linux 8 and Podman, so it does not depend on a Docker installation.

The build specification explicitly uses the Oracle Linux trusted CA bundle when it contacts the release IAM domain. TLS certificate verification remains enabled.

Do not manually run the pipeline a second time for the same App Gateway version. Start it only after a new package version has been identified and approved. Future application deployments use the exact approved version tag; retain the published digest for audit evidence.

## Secret-handling note

The platform stack deliberately accepts four sensitive values once so it can create named OCI Vault secrets automatically: the release IAM client ID/secret and the OCIR pull username/token. Resource Manager masks these values in the form and output, but Terraform state still needs access to manage the resulting secrets. Use a restricted Resource Manager stack and state access policy, and rotate the values if stack access is ever broadened. Selecting an existing Vault changes where the new secrets are stored; it does not accept existing secret OCIDs. If tenancy policy prohibits supplying secret values to Resource Manager, adapt the stack to consume pre-created secret OCIDs before deployment.

## What this stack does not do

It does not create a customer Enterprise Application, App Gateway, wallet,
Container Instance, Compute Instance, VCN, or load balancer. Those belong to
the repeatable application deployment workflow.

For the complete Resource Manager, Cloud Shell, DevOps, OCIR verification, and
upgrade procedure, use the
[App Gateway image publication runbook](docs/appgateway-image-publication-runbook.md).

## Resource Manager package

When creating the stack, select the Resource Manager Terraform version **1.5.x**. OCI Resource Manager does not currently support Terraform 1.6 or later for stack jobs.

Create the uploadable stack ZIP with:

```bash
./scripts/package-resource-manager.sh
```

Upload the resulting file from `platform/dist/` to OCI Resource Manager. The ZIP contains only the platform Terraform configuration and schema; it does not contain any downloaded App Gateway package, local Terraform provider, or credential value.
