# Kamatera setup

ShadowFleet integrates with the Kamatera CloudCLI API. It uses an API Client ID
and Secret, not the password for an interactive Kamatera user.

## Required values

Create a dedicated API client in the Kamatera console and collect:

- API Client ID
- API Secret
- Datacenter ID
- Image ID available in that datacenter
- SSH public key installed on created servers
- CPU type and core count
- RAM in MB and one to four disk sizes in GB
- Billing cycle and, for monthly billing, the monthly package ID

The Assets page validates the credentials and loads datacenters, images, and
server capabilities before an asset is saved.

## API permissions

The API client must be able to:

- Read datacenters, images, capabilities, servers, and server tags
- Create and clone servers
- Read asynchronous command status
- Terminate servers

Use a dedicated least-privilege client when the Kamatera account supports
permission scoping. Rotate the Secret if it is exposed.

## Registration

Open Assets, choose Kamatera, enter the Client ID and Secret, then select
`Verify credentials and load resources`. Choose a datacenter and image, enter
an SSH public key, and configure the server size.

ShadowFleet stores the Client ID and Secret in its database because the daemon
needs them for provisioning, replacement healing, node deletion, and orphan
cleanup. Protect database files and backups with host-level encryption and
restrictive filesystem permissions.

Hourly billing is the simplest default. Monthly billing also requires a valid
monthly package ID for the selected datacenter and server configuration.

## Network and DNS

Servers are created with an automatically assigned public WAN address. Both
IPv4-only and dual-stack responses are supported. Protocols that require DNS
also require Cloudflare to be enabled. Replacement healing updates or removes
the A and AAAA records to match the addresses returned by Kamatera.

The startup script must be able to reach the ShadowFleet callback endpoint,
Xboard, package repositories, and any certificate or DNS endpoints required by
the selected protocol.

## Live smoke test

The following validation creates billable Kamatera resources:

1. Register a dedicated test asset and load its catalog.
2. Provision one node and confirm the callback, Xboard state, public addresses,
   and DNS records.
3. Trigger force heal and confirm traffic moves to the cloned replacement.
4. Delete the node and confirm the old and replacement servers are terminated.
5. Create a tagged test orphan, wait past the configured grace period, run a
   dry orphan scan, then explicitly approve cleanup.
6. Remove the test asset and verify no Kamatera server or DNS record remains.
