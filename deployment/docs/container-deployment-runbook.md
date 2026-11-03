# Container Instance Deployment Runbook

Use this runbook to deploy App Gateway on an OCI Container Instance.

## 1. Prepare the Application

For a sample deployment, leave these files unchanged:

```text
pipeline-source/config/application.properties
pipeline-source/config/app_resources.csv
pipeline-source/config/header_mappings.json
```

For a customer application, update all three files as described in
[Application configuration](prerequisites.md#application-configuration). Custom
mode deploys only App Gateway; it does not deploy the sample backend.

## 2. Extract the Package

In OCI Cloud Shell:

```bash
work_dir="$HOME/appgateway-container-$(date +%Y%m%d%H%M%S)"
mkdir -p "$work_dir"
unzip -oq "$HOME/oci-iam-appgateway-devops-bootstrap.zip" -d "$work_dir"
cd "$work_dir/oci-iam-appgateway-devops-bootstrap"
chmod +x bootstrap-devops.sh
```

## 3. Run Bootstrap

```bash
./bootstrap-devops.sh \
  --region 'us-ashburn-1' \
  --compartment-ocid '<deployment-compartment-ocid>'
```

Recommended sample values:

| Prompt | Value |
|---|---|
| Deployment name | A unique name such as `iam-appgateway-container-test` |
| Runtime type | `Container Instance` |
| Runtime size | `Standard` |
| Gateway access | `Public direct` for the initial smoke test |
| Assign a public IP | `true` for public direct access |
| Allowed ingress CIDRs | Trusted client CIDR, preferably `/32` |
| OCIR repository path | Approved path such as `iam-appgateway/appgateway` |
| Approved image tag | Version supplied by the image release owner |

Enter the collected Identity Domain, Vault, OCIR, subnet, and credential values
when prompted. For Git authentication, use the OCI DevOps Git username and an
OCI auth token.

## 4. Start the Pipeline

1. Open **Developer Services > DevOps > Projects**.
2. Open the project matching the deployment name.
3. Open the generated build pipeline.
4. Choose **Start manual run**.
5. Confirm `OPERATION=APPLY` and review the remaining pre-filled parameters.
6. Start the run and wait for it to succeed.

## 5. Verify the Deployment

In the IAM Identity Domain, confirm:

- Enterprise Application is active.
- App Gateway is active.
- App Gateway server hostname matches `application_landing_url`.
- Protected resources and header mappings match the configuration files.

In OCI Container Instances, confirm:

- Container Instance is Active.
- `appgateway` container is Active.
- `header-sample` is Active only for the included sample application.

For public direct access, test with the configured hostname:

```bash
curl -k -I \
  --resolve appgateway.example.com:4443:<container-public-ip> \
  https://appgateway.example.com:4443/
```

The sample should return an HTTP redirect to the IAM Identity Domain. Add a
temporary workstation hosts-file entry or create DNS before browser testing.

## 6. Verify a Customer Application

For custom mode:

1. Confirm there is no `header-sample` container.
2. Confirm the origin is reachable from the Container Instance subnet.
3. Sign in through the App Gateway landing URL.
4. Verify the application receives the configured identity headers.
5. Test public and protected paths from `app_resources.csv`.

## Updating Configuration

After editing the three application files, publish them to the existing DevOps
repository:

```bash
./bootstrap-devops.sh \
  --repository-url '<application-source-repository-url>' \
  --config-dir '/path/to/config'
```

Then start the existing build pipeline.

## Troubleshooting

- Review the DevOps build-run log first.
- Review each container's logs in the Container Instance console.
- Confirm the private OCIR image path and tag exist.
- Confirm the Container Instance dynamic group can read the repository.
- Confirm the ingress CIDR includes the test client or load balancer.
- Use the landing hostname in the request; testing only the IP does not provide
  the hostname expected by App Gateway.
