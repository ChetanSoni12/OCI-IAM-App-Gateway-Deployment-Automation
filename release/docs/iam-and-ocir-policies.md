# Release IAM and OCIR Policy Intent

Use the least-privilege model below. The release-platform stack creates its
implemented dynamic group and policy by default. Review generated policy in
the Resource Manager plan before applying it, especially when the release
resources are split across compartments.

## Release IAM domain

Create one dedicated confidential application for package retrieval. It is not a customer deployment administrator and is not embedded in the released image.

Required secret storage:

- `release-appgateway-client-id`
- `release-appgateway-client-secret`

## OCI Vault

The OCI DevOps build dynamic group needs permission to read secret bundles in
the release compartment. Keep unrelated application secrets in a separate
compartment or Vault where stricter isolation is required.

## OCIR

The OCI DevOps build and delivery process needs permission to publish to the
private App Gateway repository in the release compartment. Deployment runtimes
need pull access to the approved repository only.

## Separation of duties

- Release pipeline credentials: retrieve package metadata and packages only.
- Target deployment credentials: create Enterprise Application, CloudGate/App Gateway, mappings, and wallet in that target IAM domain.
- Runtime wallet: unique per deployed App Gateway and retained only in its runtime secret/config location.

See the
[App Gateway image publication runbook](appgateway-image-publication-runbook.md)
for the implemented platform flow and validation steps.

