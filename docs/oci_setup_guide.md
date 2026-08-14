# Oracle Cloud Infrastructure setup

ShadowFleet uses the OCI REST API with an API signing key. It does not use an
OCI user password, auth token, instance principal, or resource principal.

## Required values

Create an API signing key for a dedicated OCI user and collect:

- Region identifier, for example `ap-tokyo-1`
- Tenancy OCID
- User OCID
- API key fingerprint
- PEM private key and its optional passphrase
- Compartment OCID
- Availability domain
- IPv6-enabled public subnet OCID
- Network security group OCID
- Compute image OCID
- Compatible compute Shape
- SSH public key installed on created instances

ShadowFleet validates the identity, compartment resources, Image/Shape
compatibility, and Shape architecture before saving the asset.

## IAM policy

Use a dedicated group and limit the policy to the target compartment. The exact
policy can vary with the tenancy hierarchy, but the user needs permission to:

- Inspect the tenancy, compartments, and availability domains
- Read compute images and Shapes
- Manage instances in the target compartment
- Use the VCN, subnet, VNIC, IPv6, and NSG resources in the target compartment
- Read and add NSG security rules

A typical starting policy is:

```text
Allow group ShadowFleetOperators to inspect compartments in tenancy
Allow group ShadowFleetOperators to inspect availability-domains in tenancy
Allow group ShadowFleetOperators to read instance-images in compartment ShadowFleet
Allow group ShadowFleetOperators to manage instance-family in compartment ShadowFleet
Allow group ShadowFleetOperators to use virtual-network-family in compartment ShadowFleet
Allow group ShadowFleetOperators to manage network-security-groups in compartment ShadowFleet
```

Review the policy with the OCI policy simulator and narrow it for the tenancy's
compartment layout before production use.

## Network requirements

The selected VCN and subnet must already exist. ShadowFleet does not create or
delete shared OCI network foundations.

1. Enable an Oracle-provided IPv6 prefix on the VCN.
2. Assign an IPv6 prefix to the subnet.
3. Configure the subnet as public and allow public IPv4 and IPv6 assignment.
4. Attach an Internet Gateway.
5. Add `0.0.0.0/0` and `::/0` routes to the Internet Gateway.
6. Use an NSG in the same VCN as the subnet.

During provisioning, ShadowFleet adds TCP ingress rules for SSH port 22 and the
node service port from both `0.0.0.0/0` and `::/0`. Restrict these sources after
deployment when the operational access ranges are known.

## Registration and validation

Open Assets, select Oracle Cloud, enter the signing credentials and compartment,
then load the catalog. Choose resources from the returned availability domains,
subnets, NSGs, images, and Shapes. OCPU and memory overrides are valid only for
flexible Shapes.

The private key and passphrase are stored in the ShadowFleet database because
the daemon needs them for provisioning, healing, deletion, and orphan cleanup.
Protect database files and backups with host-level encryption and restrictive
filesystem permissions.

## Live smoke test

The following validation creates billable OCI resources and must be run with an
approved test compartment:

1. Register a dedicated OCI test asset.
2. Provision one node and confirm IPv4, IPv6, DNS, Xboard, and callback readiness.
3. Trigger force heal and confirm the AAAA record moves to the replacement IPv6.
4. Delete the node and confirm the OCI instance reaches `TERMINATED`.
5. Create a tagged test orphan, wait past the configured grace period, run a dry
   orphan scan, then explicitly approve cleanup.
6. Remove the test asset and verify no instance, VNIC, IPv6, or DNS resources remain.
