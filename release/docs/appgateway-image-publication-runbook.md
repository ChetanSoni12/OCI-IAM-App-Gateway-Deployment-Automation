# App Gateway Image Publication Runbook

## Purpose

Use this runbook when the tenancy does not yet contain an approved OCI IAM App
Gateway image in private OCI Container Registry (OCIR), or when a new App
Gateway version must be published.

This is a release-administration procedure. Application deployment operators
normally need only the approved repository path, version tag, OCIR username,
and OCIR auth token.

## Result

The procedure creates a shared release platform and publishes a versioned,
`amd64` App Gateway runtime image to private OCIR. The resulting image contains
the approved App Gateway runtime software. Identity Domain settings, Enterprise
Application definitions, wallet, and deployment credentials are generated
separately for each target environment during deployment.

```text
Release IAM Domain
        |
        | App Gateway packages
        v
OCI DevOps Release Pipeline ---> Validate and build amd64 image
        |                                      |
        |                                      v
        +----------------------------> Private OCIR
                                               |
                                               v
                                Customer deployment bootstrap
```

## Responsibilities

| Role | Responsibility |
|---|---|
| Release administrator | Creates the shared release platform, publishes the build source, runs the release pipeline, and approves the resulting image tag |
| Deployment administrator | Supplies the approved repository path, tag, and pull credentials to the deployment bootstrap |
| Runtime operator | Operates the deployed Container Instance or Compute Instance; no release-domain credential is required |

## Before You Start

Collect the following:

- OCI region, tenancy OCID, and release-platform compartment OCID
- Release IAM Identity Domain base URL
- Dedicated confidential-application client ID and secret authorized to obtain
  an access token and retrieve App Gateway packages from that release domain
- OCIR username in the format accepted by the tenancy and a current OCI auth
  token
- OCI DevOps Git username and a separate OCI user auth token for HTTPS Git
  authentication
- Existing Vault and active encryption-key OCIDs, if the platform must use an
  existing Vault
- Permission to create DevOps, OCIR, Vault, Secrets, Logging, Notifications,
  dynamic-group, and policy resources

Before creating the stack, confirm that the dedicated confidential application
can obtain a client-credentials token and retrieve the App Gateway package
metadata from the selected release Identity Domain. See Oracle's
[App Gateway setup documentation](https://docs.oracle.com/en-us/iaas/Content/Identity/appgateways/set-app-gateway.htm)
for the Identity Domain and App Gateway prerequisites. Do not use a target
application's App Gateway client credential as the release credential.

### Keep the credentials distinct

| Credential | Used for | Stored by the platform |
|---|---|---|
| Release IAM client ID and secret | Download App Gateway release packages | Yes, as two Vault secrets |
| OCIR username and auth token | Pull the approved private image during later deployments | Yes, as two Vault secrets |
| DevOps Git username and OCI user auth token | Push build source to the private DevOps repository | No; entered only at the Git prompt |

Never use the OCIR token as the DevOps Git password. Do not commit any of these
values to source control.

## 1. Build the Resource Manager Package

From the project root:

```bash
bash platform/scripts/package-resource-manager.sh
```

The command creates:

```text
platform/dist/oci-iam-appgateway-release-platform.zip
```

## 2. Create the Release Platform

1. In OCI Console, open **Developer Services**, **Resource Manager**, then
   **Stacks**.
2. Create a stack from **My configuration** and upload
   `oci-iam-appgateway-release-platform.zip`.
3. Select Terraform version **1.5.x**.
4. Enter the platform location, release IAM credentials, private repository
   name, and OCIR pull credentials.
5. Select either **Create a new Vault** or **Use existing Vault**.
6. Run **Plan** and resolve every error before continuing.
7. Run **Apply**.

The stack creates:

- Private OCIR repository
- Vault, key, and named secrets, or secrets in the selected existing Vault
- OCI DevOps project, private source repository, build pipeline, and image
  delivery stage
- DevOps service log and Notifications topic
- DevOps dynamic group and compartment-scoped policies

Creating the dynamic group and policy requires tenancy-level IAM permission.
The platform Terraform variable `create_platform_policies` defaults to `true`.
Organizations that manage IAM policy separately must review that setting before
packaging the stack.

## 3. Record the Stack Outputs

Retain these Resource Manager outputs:

| Output | Use |
|---|---|
| `release_source_repository_url` | Private DevOps Git URL used for source publication |
| `release_client_id_secret_id` | Vault secret OCID inserted into the build specification |
| `release_client_secret_secret_id` | Vault secret OCID inserted into the build specification |
| `release_pipeline_id` | Release pipeline to run manually |
| `private_ocir_repository` | Full registry URI of the approved-image repository |
| `ocir_pull_username_secret_id` | Stored OCIR username reference |
| `ocir_pull_auth_token_secret_id` | Stored OCIR token reference |
| `release_log_id` | DevOps service log used for troubleshooting |

## 4. Publish the Release Source

OCI Resource Manager creates the empty private DevOps repository but does not
commit files to it. From Cloud Shell, change to the project root and run:

```bash
bash platform/scripts/publish-release-source.sh \
  --repository-url '<release_source_repository_url>' \
  --release-domain-url 'https://idcs-example.identity.oraclecloud.com' \
  --release-client-id-secret-id '<release_client_id_secret_id>' \
  --release-client-secret-secret-id '<release_client_secret_secret_id>'
```

At the Git prompt, enter the OCI DevOps Git username and use an OCI user auth
token as the password. A successful command ends with:

```text
Release source published. Run the release DevOps build pipeline from the OCI Console.
```

In the private repository, confirm that branch `main` contains
`build_spec.yaml` and the `release/` directory. The build specification contains
Vault secret OCIDs, not secret values.

## 5. Run the Release Pipeline

1. Open the DevOps project named `<platform-name>-release`.
2. Open **Build pipelines** and select the release pipeline.
3. Choose **Start manual run**.
4. Confirm that both stages succeed:
   - **Validate App Gateway release**
   - **Publish validated image**
5. In the build log, record the version shown in:

```text
Prepared App Gateway release: <version>
```

The managed build uses Oracle Linux 8, Podman, and the operating system's
trusted CA bundle. It downloads the App Gateway and wallet-tool packages,
validates them, builds the runtime image, verifies `amd64` architecture, and
hands the image to the DevOps delivery stage.

## 6. Verify the Published Image

In **Developer Services**, **Container Registry**:

1. Open the repository selected during stack creation.
2. Confirm that the repository is private.
3. Confirm that the exact version tag from the build log exists.
4. Confirm that the image architecture is `amd64`/`x86_64`.
5. Record the image digest for release audit purposes.

Do not use `latest` as the deployment version. The deployment workflow accepts
the exact approved version tag; the digest is retained as audit evidence.

## 7. Hand Off to Deployment

Provide the deployment administrator with:

- Repository path, for example `iam-appgateway/appgateway`
- Approved image tag, for example `26.3.33-2608171245`
- OCIR pull username
- OCIR auth token

The deployment bootstrap constructs the regional image URI from these values.
Do not pass a repository path or namespace copied from another tenancy.

After handoff, the deployment administrator continues with the deployment
prerequisites supplied in the deployment package.

## Publishing a New Version

Run this process only when a new App Gateway package version has been
identified and approved:

1. Keep the existing OCIR repository and release platform.
2. Republish source only when the release code or build specification changed.
3. Start a new manual release-pipeline run.
4. Verify and approve the new version tag and digest.
5. Use the new tag only for new deployments or an intentional runtime update.

Existing deployments remain pinned to their selected image tag. Publishing a
new image does not replace or restart them.

## Troubleshooting

| Symptom | Check |
|---|---|
| Resource Manager schema or plan fails | Use Terraform 1.5.x and validate every required form value |
| `build_spec.yaml` cannot be fetched | Confirm source was pushed to branch `main` and the file is at repository root |
| Git authentication fails | Use the DevOps Git username and an OCI user auth token, not the OCIR token |
| IAM token or package download fails | Verify the release-domain URL, confidential-application grants, secret OCIDs, and DevOps access to secret bundles |
| TLS certificate verification fails | Confirm the managed build can read the Oracle Linux CA bundle and that no TLS-intercepting path supplies an untrusted issuer |
| Image delivery fails | Verify the DevOps policy, OCIR repository compartment, repository name, and exported release tag |
| Image cannot be used by the runtime | Confirm it is private, the tag exists, pull credentials are current, and architecture is `amd64` |

Use the enabled DevOps service log and the failed build-stage log before
retrying. Do not repeatedly run the release pipeline for the same version while
the cause is unknown.

## Completion Checklist

- Resource Manager plan and apply succeeded.
- The private DevOps repository contains `build_spec.yaml` and release source.
- Both release-pipeline stages succeeded.
- Private OCIR contains the exact versioned `amd64` image.
- The image tag and digest were recorded.
- Deployment operators received only the repository path, approved tag, and
  required pull credentials.
