# Compute Instance Deployment Runbook

Use this runbook to deploy App Gateway on an Oracle Linux 8 x86_64 Compute
Instance. The default shape is `VM.Standard.E4.Flex`.

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

## 2. Find the Oracle Linux 8 Image OCID

The Compute runtime uses `VM.Standard.E4.Flex`, which requires an x86_64 image
available in the deployment region.

In the OCI Console:

1. Open **Compute**, **Instances**, and select **Create instance**.
2. Under **Image and shape**, select **Change image**.
3. Select **Oracle Linux**, then an available **Oracle Linux 8** platform image.
4. Confirm the image is x86_64 and compatible with `VM.Standard.E4.Flex`.
5. Open the image details and copy its OCID. You can then cancel instance
   creation.

Alternatively, use OCI Cloud Shell:

```bash
REGION='us-ashburn-1'
COMPARTMENT_OCID='<deployment-compartment-ocid>'

oci compute image list \
  --region "$REGION" \
  --compartment-id "$COMPARTMENT_OCID" \
  --operating-system 'Oracle Linux' \
  --operating-system-version '8' \
  --shape 'VM.Standard.E4.Flex' \
  --lifecycle-state AVAILABLE \
  --sort-by TIMECREATED \
  --sort-order DESC \
  --limit 1 \
  --query 'data[0].{Name:"display-name",OCID:id}' \
  --output table
```

Use the returned OCID only when the image name does not contain `aarch64`.
Platform image OCIDs are regional, so run the command for the same region used
by the deployment.

References: [OCI platform images](https://docs.oracle.com/en-us/iaas/Content/Compute/References/images.htm)
and [OCI CLI image list](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/compute/image/list.html).

## 3. Prepare Optional SSH Access

SSH is recommended for the first Compute deployment and operational
troubleshooting. Create an RSA key when the environment requires FIPS-compatible
keys:

```bash
mkdir -p "$HOME/.ssh"
ssh-keygen -t rsa -b 3072 -f "$HOME/.ssh/appgateway-compute" -N ''
```

Use the `.pub` file during bootstrap. Restrict SSH to the administrator's public
IP with `/32`. A private Compute instance requires an existing OCI Bastion or
another customer-managed private access path.

## 4. Extract the Package

In OCI Cloud Shell:

```bash
work_dir="$HOME/appgateway-compute-$(date +%Y%m%d%H%M%S)"
mkdir -p "$work_dir"
unzip -oq "$HOME/oci-iam-appgateway-devops-bootstrap.zip" -d "$work_dir"
cd "$work_dir/oci-iam-appgateway-devops-bootstrap"
chmod +x bootstrap-devops.sh
```

## 5. Run Bootstrap

```bash
./bootstrap-devops.sh \
  --region 'us-ashburn-1' \
  --compartment-ocid '<deployment-compartment-ocid>'
```

Recommended sample values:

| Prompt | Value |
|---|---|
| Deployment name | A unique name such as `iam-appgateway-compute-test` |
| Runtime type | `Compute Instance` |
| Runtime size | `Standard` |
| Gateway access | `Public direct` for the initial smoke test |
| Assign a public IP | `true` for public direct access |
| Allowed ingress CIDRs | Trusted client CIDR, preferably `/32` |
| Oracle Linux image | Current Oracle Linux 8 x86_64 platform image OCID |
| Enable optional SSH | `true` for the initial deployment |
| SSH public-key path | `$HOME/.ssh/appgateway-compute.pub` |
| SSH allowed CIDR | Administrator public IP with `/32` |
| OCIR repository path | Approved path such as `iam-appgateway/appgateway` |
| Approved image tag | Version supplied by the image release owner |

Enter the collected Identity Domain, Vault, OCIR, subnet, and credential values
when prompted. For Git authentication, use the OCI DevOps Git username and an
OCI auth token.

## 6. Start the Pipeline

1. Open **Developer Services > DevOps > Projects**.
2. Open the project matching the deployment name.
3. Open the generated build pipeline.
4. Choose **Start manual run**.
5. Confirm `OPERATION=APPLY` and review the remaining pre-filled parameters.
6. Start the run and wait for it to succeed.

The build run creates the VM. Cloud-init continues inside the VM after the build
run completes, so allow it to finish before testing App Gateway.

## 7. Verify Cloud-init and Services

Connect as `opc`, then run:

```bash
sudo cloud-init status --wait
sudo systemctl status iam-appgateway --no-pager
sudo podman ps
```

In sample mode, both `iam-appgateway` and `iam-appgateway-sample` should be
running.

Test locally from the VM:

```bash
curl -k -I \
  --resolve appgateway.example.com:4443:127.0.0.1 \
  https://appgateway.example.com:4443/
```

Then test from an allowed client:

```bash
curl -k -I \
  --resolve appgateway.example.com:4443:<compute-public-ip> \
  https://appgateway.example.com:4443/
```

The sample should return an HTTP redirect to the IAM Identity Domain. Add a
temporary workstation hosts-file entry or create DNS before browser testing.

## 8. Verify a Customer Application

For custom mode:

1. Confirm `iam-appgateway-sample` is not present.
2. Test the origin URL from the Compute host.
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

Use this order:

```bash
sudo cloud-init status --long
sudo tail -n 200 /var/log/iam-appgateway-bootstrap.log
sudo systemctl status iam-appgateway --no-pager
sudo journalctl -u iam-appgateway -n 200 --no-pager
sudo podman logs iam-appgateway
sudo podman logs iam-appgateway-sample
sudo firewall-cmd --list-ports
```

If App Gateway works locally but not from the client, verify:

1. OCI NSG permits the client or load-balancer CIDR on the configured HTTPS port.
2. Oracle Linux firewalld permits the configured HTTPS port.
3. The runtime has the expected public or load-balancer network path.

If the service repeatedly restarts, stop the restart loop before collecting the
complete container log:

```bash
sudo systemctl stop iam-appgateway
sudo podman logs iam-appgateway 2>&1 | head -n 200
```

`Invalid wallet` together with file `Permission denied` indicates that the
wallet or TLS file ownership and SELinux mount labels should be checked.

### Known issue: firewalld command does not return

On some Oracle Linux boots, `firewall-cmd --state` can wait indefinitely even
though firewalld is running. Confirm the blocked process:

```bash
sudo ps -eo pid,ppid,stat,wchan:30,etime,cmd | \
  grep -E 'cloud-init|part-001|firewall-cmd' | grep -v grep
```

If the command has been waiting for several minutes, terminate only its PID,
allow cloud-init to finish, then recover firewalld:

```bash
sudo kill <firewall-cmd-pid>
sudo cloud-init status --wait
sudo systemctl restart firewalld
sudo timeout 15 firewall-cmd --permanent --add-port=4443/tcp
sudo timeout 15 firewall-cmd --reload
sudo timeout 15 firewall-cmd --list-ports
```

Use the actual configured App Gateway port if it is not `4443`.
