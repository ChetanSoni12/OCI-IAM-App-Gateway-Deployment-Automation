# Deployment Prerequisites

Complete this checklist before running `bootstrap-devops.sh`.

## Approved Image Prerequisite

This deployment consumes an existing, approved App Gateway image. It does not
download App Gateway software from an IAM Identity Domain or build the shared
image.

- If the private OCIR repository already contains the approved versioned
  `amd64` image, record its repository path and tag and continue below.
- If the image is not available, a release administrator must first complete
  the [App Gateway image publication runbook](appgateway-image-publication-runbook.md).

Image publication is shared preparation and is normally performed once per
approved App Gateway version, not once per application deployment.

## Required OCI Resources

- OCI region and deployment compartment
- Availability domain
- Existing VCN and subnet
- Existing OCI Vault and active master encryption key
- Private OCIR repository containing the approved App Gateway image
- OCI IAM Identity Domain
- IAM confidential application authorized to administer App Gateway resources
- OCI username and auth token used for private OCIR login
- OCI DevOps Git username and a separate OCI auth token used as the HTTPS Git password

Additional Compute requirements:

- Oracle Linux 8 x86_64 platform image OCID
- Compute runtime dynamic group and policy
- Optional RSA OpenSSH public key and trusted administrator CIDR
- OCI Bastion or another private administrative path for a private subnet

Additional Container Instance requirement:

- Container Instance dynamic group and private-OCIR repository policy

## Values to Collect

| Category | Required values |
|---|---|
| Deployment | Region, compartment OCID, unique deployment name, availability domain |
| Network | Subnet OCID, access mode, public-IP choice, allowed ingress CIDRs |
| IAM | Identity Domain URL, administrator client ID, administrator client secret |
| Vault | Vault OCID and key OCID |
| OCIR | Repository path, approved image tag, pull username, auth token |
| Compute only | Oracle Linux 8 x86_64 image OCID, optional SSH public-key path and `/32` CIDR |
| Existing OCI LB only | Load Balancer OCID and backend set name |

Use the Identity Domain base URL without an API path:

```text
https://idcs-xxxxxxxx.identity.oraclecloud.com
```

For public access, restrict App Gateway and SSH ingress to trusted CIDRs. Use
`<administrator-public-ip>/32` for one workstation.

> **Security note:** `0.0.0.0/0` permits access from every IPv4 address. Use it
> only for a temporary smoke test when necessary. For normal deployments,
> specify trusted client, load balancer, or corporate network CIDRs. Never use
> `0.0.0.0/0` for SSH.

## Network Requirements

The selected subnet must provide outbound HTTPS access to the target IAM
Identity Domain, OCI Vault and Secrets services, private OCIR, and Oracle Linux
repositories for Compute deployments.

| Access mode | Network expectation |
|---|---|
| Public direct | Subnet permits public VNIC addresses and a public IP is assigned |
| Existing OCI Load Balancer | Pipeline adds the runtime private IP to the selected backend set |
| External Load Balancer | Customer configures the load balancer, health check, DNS, and network path |

A subnet that prohibits public VNIC addresses cannot use **Public direct**.

## Application Configuration

The files under `pipeline-source/config/` define the protected application:

| File | Purpose |
|---|---|
| `application.properties` | Application name, landing URL, origin URL, and TLS mode |
| `app_resources.csv` | Protected paths and `oauth` or `public` access behavior |
| `header_mappings.json` | Identity attributes forwarded as HTTP headers |

### Included sample application

Leave all three files unchanged. The deployment creates the Header
Authentication Sample backend with these defaults:

```properties
application_name=Header Authentication Sample
application_landing_url=https://appgateway.example.com:4443/
application_origin_url=http://127.0.0.1:8080/
```

### Customer application

Update all application-specific values before bootstrap:

```properties
application_name=My Enterprise Application
application_landing_url=https://sso.example.com:4443/
application_origin_url=https://application.internal.example.com/
```

The origin URL must be reachable from the runtime subnet and cannot use
localhost or a loopback address. Review `app_resources.csv` and
`header_mappings.json` for the target application instead of retaining sample
rules accidentally.

Changing any of the three files selects custom mode. Custom mode deploys App
Gateway only; it does not deploy the included sample backend. The pipeline can
complete when the origin URL is syntactically valid but unavailable, but the
browser request will fail after authentication until the origin becomes
reachable.

Deployment names must be 3-31 characters, begin with a lowercase letter, and
contain only lowercase letters, numbers, and hyphens. Use a new deployment name
and a unique `application_name` when deliberately creating a separate test.

### PeopleSoft ERP example

The following example follows Oracle's PeopleSoft App Gateway pattern. Replace
the landing hostname, PIA site, and origin with real values for an end-to-end
deployment.

`application.properties`:

```properties
application_name=PeopleSoft ERP Test
application_landing_url=https://peoplesoft-appgateway.example.com:4443/psc/peoplesoft01_22/EMPLOYEE/ERP/c/NUI_FRAMEWORK.PT_LANDINGPAGE.GBL?
application_origin_url=http://192.0.2.10:8000/

appgateway_tls_mode=generated
appgateway_tls_cert_secret_ocid=
appgateway_tls_key_secret_ocid=
```

`192.0.2.10` is a documentation-only address. It is suitable for validating
deployment orchestration but cannot validate PeopleSoft application access.

`app_resources.csv`:

```csv
ResourceName,ResourceURL,AccessMode
default,/.*,oauth
psc,/psc/peoplesoft01_22/EMPLOYEE/ERP/c/NUI_FRAMEWORK.PT_LANDINGPAGE.GBL.*,oauth
```

`oauth` represents the App Gateway **Form or Access Token** authentication
method used for managed resources.

`header_mappings.json`:

```json
[
  {"OAM_REMOTE_USER": "$subject.user.userName"},
  {"PS_SSO_UID": "$subject.user.userName"},
  {"HTTP_REMOTE_USERID": "$subject.user.userName"},
  {"HTTP_OAM_REMOTE_USER": "$subject.user.userName"}
]
```

For PeopleSoft HCM, replace the `ERP` path segment with `HRMS`. PeopleSoft must
also be configured to consume the selected SSO headers; this automation does
not modify the PeopleSoft application itself.

For customer-provided App Gateway TLS material, store the PEM certificate and
private key as Vault secrets and set:

```properties
appgateway_tls_mode=vault
appgateway_tls_cert_secret_ocid=ocid1.vaultsecret...
appgateway_tls_key_secret_ocid=ocid1.vaultsecret...
```

Otherwise, leave `appgateway_tls_mode=generated` to create a self-signed App
Gateway certificate. A front-end load balancer can present a different
enterprise certificate; its HTTPS backend configuration must trust the App
Gateway certificate or issuing CA.

## IAM Dynamic Groups and Policies

Replace placeholders with the actual identity-domain-qualified dynamic group
names and compartment names.

### DevOps build runners

Dynamic group matching rule:

```text
ALL {resource.type = 'devopsbuildpipeline', resource.compartment.id = '<deployment-compartment-ocid>'}
```

Policies:

```text
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to manage objects in compartment <state-compartment>
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to read objectstorage-namespaces in tenancy
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to read secret-bundles in compartment <vault-compartment>
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to manage secret-family in compartment <vault-compartment>
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to use vaults in compartment <vault-compartment>
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to use keys in compartment <vault-compartment>
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to manage virtual-network-family in compartment <network-compartment>
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to manage compute-container-family in compartment <runtime-compartment>
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to manage instance-family in compartment <runtime-compartment>
Allow dynamic-group '<domain>'/'<build-dynamic-group>' to manage load-balancers in compartment <load-balancer-compartment>
```

### Compute runtime

Dynamic group matching rule:

```text
ALL {instance.compartment.id = '<runtime-compartment-ocid>'}
```

Policy:

```text
Allow dynamic-group '<domain>'/'<compute-runtime-dynamic-group>' to read secret-bundles in compartment <vault-compartment>
```

### Container Instance runtime

Dynamic group matching rule:

```text
ALL {resource.type = 'computecontainerinstance', resource.compartment.id = '<runtime-compartment-ocid>'}
```

Policy:

```text
Allow dynamic-group '<domain>'/'<container-runtime-dynamic-group>' to read repos in compartment <ocir-repository-compartment>
```

## Final Readiness Check

- Required OCIDs and credentials have been collected.
- Dynamic groups and policies are active.
- Subnet ingress and outbound paths match the selected access mode.
- The approved OCIR image and tag exist.
- The IAM administrator confidential application belongs to the target domain.
- The three application files represent either the unchanged sample or the intended customer application.
