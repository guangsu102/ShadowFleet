# Google Cloud Platform Setup Guide

ShadowFleet uses the Compute Engine REST API with a service account key to
create, inspect, heal, and delete VM instances. The configured asset region is
a Compute Engine zone such as `asia-east1-a`.

## 1. Enable Compute Engine

Select the target project, attach a billing account, and enable the API:

```bash
gcloud config set project PROJECT_ID
gcloud services enable compute.googleapis.com
```

The project must have enough VM CPU, persistent disk, and external IPv4 quota
in the selected region.

## 2. Create a service account

```bash
gcloud iam service-accounts create shadowfleet \
  --display-name="ShadowFleet Compute provisioner"
```

For initial validation, the predefined `Compute Instance Admin (v1)` and
`Compute Network Admin` roles cover the operations used by ShadowFleet. For
production, replace them with a custom role limited to the selected project
and the following capabilities:

- Read projects, zones, machine types, images, networks, and subnetworks.
- Create, read, list, and delete Compute Engine instances and boot disks.
- Add and delete an instance external access configuration.
- Use the selected network, subnetwork, image, and external IPv4 addresses.
- Read, create, and update ShadowFleet-managed firewall rules.
- Read zone and global operation status.

Example predefined role bindings:

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:shadowfleet@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/compute.instanceAdmin.v1"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:shadowfleet@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/compute.networkAdmin"
```

If an organization policy requires a VM service account, grant
`roles/iam.serviceAccountUser` only for that service account. ShadowFleet does
not require project-wide service account impersonation.

## 3. Prepare networking

The default auto-mode network works without an explicit subnetwork. A custom
mode network requires a subnetwork in the region that contains the selected
zone.

ShadowFleet creates or expands one firewall rule per VPC. The default network uses
`shadowfleet-ingress`; custom networks use a stable `shadowfleet-ingress-NETWORK`
name. Each rule targets instances tagged `shadowfleet` and opens TCP 22 plus the node server port. Review the source ranges before using
the default `0.0.0.0/0` and `::/0` policy in a restricted environment.

Provisioned instances currently use an ephemeral public IPv4 address. GCP
self-healing replaces that access configuration, waits for the node port, and
updates the Cloudflare A record. Cloudflare must therefore be enabled for GCP
self-healing.

## 4. Create the JSON key

```bash
gcloud iam service-accounts keys create shadowfleet-service-account.json \
  --iam-account="shadowfleet@PROJECT_ID.iam.gserviceaccount.com"
```

In ShadowFleet, open Assets, choose Google Cloud, and provide:

- Project ID and the complete service account JSON.
- Zone, machine type, Ubuntu image, network, and optional subnetwork.
- SSH username and public key.
- Protocol capacity and optional labels in `key=value` form.

The catalog query validates the project and loads zones, machine types, Ubuntu
images, networks, and subnetworks before registration.

Service account private keys are sensitive. Restrict access to the ShadowFleet
database, configuration, logs, and backups. Rotate the key immediately if it
is exposed.

## 5. Real-account smoke test

Use a disposable project or a tightly limited test zone:

1. Register the GCP asset and confirm catalog values load.
2. Provision one AnyTLS, Trojan, vless, or vmess node.
3. Confirm the VM is running, tagged `shadowfleet`, and has a public IPv4.
4. Confirm the readiness callback, asset allocation, and Cloudflare A record.
5. Trigger manual healing and verify both the IPv4 and A record change.
6. Delete the node and confirm the VM is removed before the local/Xboard node.
7. Create an old, managed test VM not recorded in ShadowFleet and verify both
   orphan scanners report it before enabling cleanup.

Hysteria2 is intentionally unsupported for cloud assets in the current
product rules.

## 6. Cost and cleanup

Compute Engine instances, boot disks, external IPv4 addresses, and network
traffic may incur charges. A failed provisioning task attempts to remove its
DNS records, VM, and registered node. Periodically review the system health
orphan report, and delete unused service account keys and test projects after
validation.
