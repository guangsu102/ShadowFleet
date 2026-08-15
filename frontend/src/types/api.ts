// Auto-generated from API OpenAPI schema — DO NOT EDIT MANUALLY
// Regenerate with: python scripts/generate_ts_types.py

// ============ Auth ============
export interface LoginRequest {
  username: string
  password: string
}

export type LoginCredentials = LoginRequest

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface RefreshRequest {
  refresh_token: string
}

export type UserRole = 'admin' | 'operator' | 'viewer'

export interface CurrentUser {
  id: number
  username: string
  role: UserRole
  is_active: boolean
  created_at: string
  updated_at: string | null
}

export interface UserCreate {
  username: string
  password: string
  role: UserRole
}

export interface UserUpdate {
  role?: UserRole
  password?: string
}

export interface UserResponse {
  id: number
  username: string
  role: UserRole
  is_active: boolean
  created_at: string
  updated_at: string | null
}

// ============ Dashboard ============
export interface DashboardOverviewResponse {
  expected_node_count: number
  total_node_count: number
  online_node_count: number
  healing_node_count: number
  offline_or_failed_node_count: number
  overall_survival_rate: number
  monthly_healing_count: number
  total_asset_count: number
  active_asset_count: number
  full_asset_count: number
  banned_asset_count: number
  deploying_asset_count: number
  offline_asset_count: number
  aws_asset_count: number
  active_aws_asset_count: number
  full_aws_asset_count: number
  banned_aws_asset_count: number
  allocated_aws_node_count: number
  target_aws_capacity: number
  max_aws_capacity: number
  aws_capacity_utilization_rate: number
  total_probe_count: number
  active_probe_count: number
  offline_probe_count: number
  disabled_probe_count: number
}

export interface RegionProtocolHealthRowResponse {
  region: string
  protocol_type: string
  desired_count: number
  min_alert_threshold: number
  online_count: number
  total_count: number
  gap_count: number
  survival_rate: number
  alert_level: 'healthy' | 'warning' | 'critical'
}

export interface AssetHealthRowResponse {
  asset_id: number
  asset_name: string
  asset_type: string
  region: string | null
  status: string
  aws_account_id: string | null
  account_total_vcpu: number | null
  allocated_count: number
  target_count: number
  max_count: number
  supported_protocols: string[]
  cpu_cores: number | null
  memory_gb: number | null
  remarks: string | null
  updated_at: string
}

export interface FleetNodeDashboardRowResponse {
  xboard_node_id: number
  node_name: string
  protocol_type: string
  asset_type: string
  region: string | null
  status: string
  instance_id: string | null
  domain_name: string | null
  ipv6_address: string | null
  aws_account_id: string | null
  last_healed_at: string | null
  updated_at: string
  last_error: string | null
  xboard_status: string | null
  xboard_show: boolean | null
  xboard_updated_at: string | null
}

export interface MonitorCycleSummaryResponse {
  cycle_id: number
  status: string
  candidate_count: number
  confirmed_count: number
  healed_count: number
  failed_count: number
  started_at: string
  finished_at: string | null
  error_message: string | null
}

export interface ProbeHealthRowResponse {
  probe_id: string
  probe_name: string
  status: string
  public_ip: string | null
  region: string | null
  isp: string | null
  tags: string[]
  config_version: number
  last_seen_at: string | null
  updated_at: string
}

export interface ProbeMeasurementRowResponse {
  measurement_id: string
  xboard_node_id: number
  final_status: string
  reason: string | null
  created_at: string
  finished_at: string | null
}

export interface DashboardSnapshotResponse {
  overview: DashboardOverviewResponse
  region_protocol_rows: RegionProtocolHealthRowResponse[]
  asset_rows: AssetHealthRowResponse[]
  node_rows: FleetNodeDashboardRowResponse[]
  latest_monitor_cycle: MonitorCycleSummaryResponse | null
  probe_rows: ProbeHealthRowResponse[]
  probe_measurement_rows: ProbeMeasurementRowResponse[]
}

// ============ Assets ============
export interface AssetResponse {
  asset_id: number
  asset_name: string
  asset_type: string
  region: string | null
  status: string
  aws_account_id: string | null
  aws_access_key: string | null
  aws_secret_key: string | null
  account_total_vcpu: number | null
  allocated_count: number
  target_count: number
  max_count: number
  supported_protocols: string[]
  cpu_cores: number | null
  memory_gb: number | null
  remarks: string | null
  updated_at: string
}

export interface AmiInfo {
  ami_id: string
  name: string
  owner: string
  description?: string
}

export interface AmiQueryResponse {
  region: string
  amis: AmiInfo[]
}

export interface HardwareProbeRequest {
  host: string
  ssh_port?: number
  ssh_username?: string
  ssh_password?: string | null
  ssh_private_key?: string | null
}

export interface HardwareProbeResponse {
  cpu_cores: number
  memory_gb: number
  hostname?: string | null
  os_info?: string | null
}

export interface AWSAssetCreateRequest {
  asset_name: string
  region: string
  aws_access_key: string
  aws_secret_key: string
  aws_account_id?: string | null
  default_instance_type?: string | null
  default_vcpu?: number | null
  account_total_vcpu?: number | null
  default_architecture?: string | null
  remarks?: string | null
  protocol_type?: string | null
  additional_protocol_types?: string[]
  target_count?: number
  max_count?: number
  priority?: number
  allow_cdn_proxy?: boolean
  ami_id?: string | null
  vpc_id?: string | null
  subnet_id?: string | null
  security_group_id?: string | null
  auto_create_security_group?: boolean
  security_group_name?: string | null
  security_group_ports?: number[]
}

export interface SelfHostedAssetCreateRequest {
  asset_name: string
  region: string
  host: string
  ssh_port?: number
  ssh_username?: string
  ssh_password?: string | null
  ssh_private_key?: string | null
  remarks?: string | null
  protocol_type?: string | null
  additional_protocol_types?: string[]
  target_count?: number
  max_count?: number
  priority?: number
  cpu_cores?: number | null
  memory_gb?: number | null
}

export interface DigitalOceanAssetCreateRequest {
  asset_name: string
  region: string
  digitalocean_token: string
  default_size?: string
  default_image?: string
  ssh_keys?: string[]
  vpc_uuid?: string | null
  tags?: string[]
  remarks?: string | null
  protocol_type?: string | null
  additional_protocol_types?: string[]
  target_count?: number
  max_count?: number
  priority?: number
  allow_cdn_proxy?: boolean
  default_vcpu?: number | null
}

export interface VultrAssetCreateRequest {
  asset_name: string
  region: string
  vultr_token: string
  default_plan?: string
  default_os_id?: number
  ssh_key_ids?: string[]
  vpc_ids?: string[]
  firewall_group_id?: string | null
  tags?: string[]
  remarks?: string | null
  protocol_type?: string | null
  additional_protocol_types?: string[]
  target_count?: number
  max_count?: number
  priority?: number
  allow_cdn_proxy?: boolean
  default_vcpu?: number | null
}

export interface KamateraAssetCreateRequest {
  asset_name: string
  datacenter: string
  client_id: string
  secret: string
  image: string
  ssh_public_key: string
  cpu_type?: string
  cpu_cores?: number
  ram_mb?: number
  disk_sizes_gb?: number[]
  billing_cycle?: string
  monthly_package?: string | null
  daily_backup?: boolean
  managed?: boolean
  tags?: string[]
  remarks?: string | null
  protocol_type?: string | null
  additional_protocol_types?: string[]
  target_count?: number
  max_count?: number
  priority?: number
  allow_cdn_proxy?: boolean
}

export interface KamateraDatacenterInfo {
  id?: string | null
  region?: string | null
  [key: string]: unknown
}

export interface KamateraImageInfo {
  id?: string | null
  description?: string | null
  [key: string]: unknown
}

export interface KamateraCatalogResponse {
  datacenters: KamateraDatacenterInfo[]
  images: KamateraImageInfo[]
  capabilities: Record<string, unknown>
}

export interface AzureAssetCreateRequest {
  asset_name: string
  region: string
  tenant_id: string
  client_id: string
  client_secret: string
  subscription_id: string
  resource_group: string
  ssh_public_key: string
  default_vm_size?: string
  admin_username?: string
  image_publisher?: string
  image_offer?: string
  image_sku?: string
  image_version?: string
  vnet_name?: string
  subnet_name?: string
  tags?: string[]
  remarks?: string | null
  protocol_type?: string | null
  additional_protocol_types?: string[]
  target_count?: number
  max_count?: number
  priority?: number
  allow_cdn_proxy?: boolean
  default_vcpu?: number | null
}
export interface GCPAssetCreateRequest {
  asset_name: string
  project_id: string
  service_account_json: string
  zone: string
  machine_type?: string
  source_image?: string
  network?: string
  subnetwork?: string | null
  ssh_username?: string
  ssh_public_key: string
  labels?: string[]
  remarks?: string | null
  protocol_type?: string | null
  additional_protocol_types?: string[]
  target_count?: number
  max_count?: number
  priority?: number
  allow_cdn_proxy?: boolean
  default_vcpu?: number | null
}

export interface OCIAssetCreateRequest {
  asset_name: string
  region: string
  tenancy_ocid: string
  user_ocid: string
  fingerprint: string
  private_key: string
  private_key_passphrase?: string | null
  compartment_ocid: string
  subnet_ocid: string
  network_security_group_ocid: string
  image_ocid: string
  shape?: string
  ssh_public_key: string
  availability_domain?: string | null
  ocpus?: number | null
  memory_in_gbs?: number | null
  tags?: string[]
  remarks?: string | null
  protocol_type?: string | null
  additional_protocol_types?: string[]
  target_count?: number
  max_count?: number
  priority?: number
  allow_cdn_proxy?: boolean
  default_vcpu?: number | null
}


export interface DigitalOceanImageInfo {
  id: number | string | null
  name: string | null
  slug: string | null
  distribution: string | null
  regions: string[]
}

export interface DigitalOceanSizeInfo {
  slug: string | null
  memory: number | null
  vcpus: number | null
  disk: number | null
  transfer: number | null
  price_monthly: number | null
  regions: string[]
  available: boolean | null
}

export interface DigitalOceanImageQueryResponse {
  images: DigitalOceanImageInfo[]
}

export interface DigitalOceanSizeQueryResponse {
  sizes: DigitalOceanSizeInfo[]
}

export interface VultrCatalogResponse {
  regions: Array<{ id: string; city?: string; country?: string }>
  plans: Array<{ id: string; vcpu_count?: number; ram?: number; monthly_cost?: number; locations?: string[] }>
  operating_systems: Array<{ id: number; name?: string; arch?: string; family?: string }>
  ssh_keys: Array<{ id: string; name?: string }>
  vpcs: Array<{ id: string; description?: string; region?: string; date_created?: string }>
  firewall_groups: Array<{ id: string; description?: string }>
}

export interface AzureCatalogResponse {
  locations: Array<{
    name?: string
    displayName?: string
    regionalDisplayName?: string
  }>
  vm_sizes: Array<{
    name?: string
    numberOfCores?: number
    memoryInMB?: number
    maxDataDiskCount?: number
    osDiskSizeInMB?: number
    resourceDiskSizeInMB?: number
  }>
}
export interface GCPCatalogResponse {
  zones: Array<{ name?: string; status?: string; region?: string; description?: string }>
  machine_types: Array<{
    name?: string
    guestCpus?: number
    memoryMb?: number
    isSharedCpu?: boolean
    description?: string
  }>
  images: Array<{
    name?: string
    selfLink?: string
    family?: string
    architecture?: string
    description?: string
    status?: string
  }>
  networks: Array<{
    name?: string
    selfLink?: string
    autoCreateSubnetworks?: boolean
    description?: string
  }>
  subnetworks: Array<{
    name?: string
    selfLink?: string
    network?: string
    region?: string
    ipCidrRange?: string
  }>
}

export interface OCICatalogResponse {
  availability_domains: Array<{ name?: string; id?: string; compartmentId?: string }>
  images: Array<{
    id?: string
    displayName?: string
    operatingSystem?: string
    operatingSystemVersion?: string
    lifecycleState?: string
  }>
  shapes: Array<{
    shape?: string
    ocpus?: number
    memoryInGBs?: number
    isFlexible?: boolean
  }>
  subnets: Array<{
    id?: string
    displayName?: string
    vcnId?: string
    cidrBlock?: string
    ipv6CidrBlock?: string
    ipv6CidrBlocks?: string[]
  }>
  network_security_groups: Array<{
    id?: string
    displayName?: string
    vcnId?: string
    lifecycleState?: string
  }>
}


// ============ Nodes ============
export interface NodeResponse {
  xboard_node_id: number
  node_name: string
  protocol_type: string
  asset_type: string
  region: string | null
  status: string
  instance_id: string | null
  domain_name: string | null
  ipv6_address: string | null
  aws_account_id: string | null
  last_healed_at: string | null
  updated_at: string
  last_error: string | null
}

export interface NodeEventResponse {
  event_id: number
  event_type: string
  from_status: string | null
  to_status: string | null
  message: string | null
  correlation_id: string
  created_at: string
}

export type FleetNodeStatus = 'provisioning' | 'online' | 'offline' | 'healing' | 'deleting' | 'deleted' | 'failed'

export interface NodeStatusUpdateRequest {
  status: FleetNodeStatus
  reason?: string | null
}

// ============ Tasks ============
export type TaskStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export type TaskType = 'provision_node' | 'force_heal' | 'decommission_node' | 'reprobe_node' | 'mark_manual_review'

export interface TaskStatsResponse {
  total: number
  queued: number
  running: number
  succeeded: number
  failed: number
}

export interface ProvisionTaskCreateRequest {
  protocol_type: string
  node_name: string
  port: string
  server_port: number
  rate?: number
  asset_type?: string
  region?: string | null
  domain_name?: string | null
  require_cdn_proxy?: boolean
  cert_mode?: string
  code?: string | null
  parent_id?: number | null
  group_ids?: number[]
  route_ids?: number[]
  tags?: string[] | Record<string, string>
  protocol_settings?: Record<string, unknown>
  show?: boolean
  sort?: number | null
  rate_time_enable?: boolean
  rate_time_ranges?: unknown[]
  status_reason?: string | null
  // Protocol-specific fields
  sni_domain?: string | null
  reality_private_key?: string | null
  reality_public_key?: string | null
  reality_dest?: string | null
  allow_insecure?: boolean
  network?: string
  flow?: string | null
  // SSH fields
  ssh_host?: string
  ssh_port?: number
  ssh_username?: string
  ssh_password?: string
  ssh_private_key?: string
}

export interface ManualTaskCreateRequest {
  task_type: string
  xboard_node_id: number
  operator_name?: string | null
  reason?: string | null
  force_strategy?: string | null
}

export interface TaskResponse {
  id: number
  task_type: string
  status: string
  correlation_id: string
  attempt_count: number
  max_attempts: number
  locked_by: string | null
  next_run_at: string
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  last_error: string | null
  node_name: string | null
  region: string | null
  protocol_type: string | null
  asset_type: string | null
  xboard_node_id: number | null
}

export interface SubmitResult {
  task_id: number
  correlation_id: string
  status: string
}

// ============ Probes ============
export interface ProbeResponse {
  probe_id: string
  probe_name: string
  status: string
  public_ip: string | null
  region: string | null
  isp: string | null
  tags: string[]
  config_version: number
  last_seen_at: string | null
  updated_at: string
}

export interface ProbeStatusUpdateRequest {
  status: 'active' | 'disabled'
}

export interface ProbeTokenResponse {
  token: string
  created_at: string
  expires_at?: string | null
  note?: string
}

// ============ Monitor ============
export interface MonitorCycleResponse {
  cycle_id: number
  status: string
  candidate_count: number
  confirmed_count: number
  healed_count: number
  failed_count: number
  started_at: string
  finished_at: string | null
  error_message: string | null
}

export interface DetectionRecordResponse {
  id: number
  cycle_id: number
  xboard_node_id: number
  node_name: string | null
  region: string | null
  protocol_type: string | null
  status: string | null
  uplink_bytes: number | null
  downlink_bytes: number | null
  total_bytes: number | null
  detection_type: string
  detection_status: string
  reason: string | null
  probe_provider: string | null
  created_at: string
  // Detailed probe information
  probe_status: string | null
  probe_failure_stage: string | null
  probe_latency_ms: number | null
  probe_success_region_count: number | null
  probe_failed_region_count: number | null
  probe_resolved_ip: string | null
  measurement_id: string | null
  selected_probe_ids: string[]
}

export interface MonitorSummaryStats {
  total_cycles: number
  total_confirmed: number
  total_healed: number
  pending_healing: number
}

export interface MonitorSummaryResponse {
  latest_cycle: MonitorCycleResponse | null
  stats: MonitorSummaryStats
}

// ============ Config ============
export interface ConfigResponse {
  app: Record<string, unknown>
  logging: Record<string, unknown>
  telegram: Record<string, unknown>
  cloudflare: Record<string, unknown>
  aws_proxy: Record<string, unknown>
  xboard: Record<string, unknown> | null
  fleet_matrix: Record<string, unknown>
  fleet_scheduler: Record<string, unknown>
}

export interface FleetMatrixUpdateRequest {
  fleet_matrix: Record<string, unknown>
}

export interface SentinelUpdateRequest {
  sentinel_enabled?: boolean | null
  sentinel_poll_interval_seconds?: number | null
  sentinel_probe_timeout_seconds?: number | null
  sentinel_heal_cooldown_seconds?: number | null
  sentinel_probe_retry_cooldown_seconds?: number | null
  sentinel_suspicious_lookback_minutes?: number | null
  sentinel_zero_uplink_window_minutes?: number | null
  sentinel_probe_mode?: string | null
  sentinel_probe_confirm_cycles?: number | null
  sentinel_probe_min_cn_probe_count?: number | null
  sentinel_probe_required_success_ratio?: number | null
  sentinel_probe_allow_auto_heal_hy2?: boolean | null
  sentinel_probe_zero_traffic_nodes?: boolean | null
}

export interface AppUpdateRequest {
  environment?: string | null
  request_timeout_seconds?: number | null
  max_retries?: number | null
  retry_backoff_seconds?: number | null
  daemon_idle_poll_interval_seconds?: number | null
  daemon_failure_backoff_seconds?: number | null
  daemon_stale_task_recovery_interval_seconds?: number | null
  daemon_running_task_timeout_seconds?: number | null
  daemon_recovered_task_retry_delay_seconds?: number | null
  phone_home_base_url?: string | null
  phone_home_listen_host?: string | null
  phone_home_listen_port?: number | null
  phone_home_ready_timeout_seconds?: number | null
  phone_home_poll_interval_seconds?: number | null
  artifact_cache_listen_port?: number | null
  artifact_cache_base_url_override?: string | null
  probe_server_enabled?: boolean | null
  probe_poll_interval_seconds?: number | null
  probe_heartbeat_timeout_seconds?: number | null
  key_pair_local_dir?: string | null
}

export interface LoggingUpdateRequest {
  level?: string | null
  log_retention_days?: number | null
}

export interface FleetSchedulerUpdateRequest {
  enabled?: boolean | null
  poll_interval_seconds?: number | null
  cooldown_seconds?: number | null
  max_tasks_per_cycle?: number | null
  enabled_regions?: string[] | null
  enabled_protocols?: string[] | null
  enabled_asset_types?: string[] | null
}

export interface ConfigValidateRequest {
  config: Record<string, unknown>
}

// ============ Abandonment ============
export interface AbandonmentRequest {
  aws_account_id: string
  error_code: string
  error_message: string
  source_xboard_node_id?: number | null
}

export interface AbandonmentResultResponse {
  aws_account_id: string
  deleted_node_count: number
  asset_count: number
}

export interface QuotaRowResponse {
  aws_account_id: string
  region: string | null
  active_count: number
  full_count: number
  banned_count: number
  total: number
}

// ============ Xboard ============
export interface XboardGroupResponse {
  id: number
  name: string
}

// ============ Error ============
export interface APIError {
  error: string
  code: string
  correlation_id: string
  detail?: unknown
}
