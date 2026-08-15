<script setup lang="ts">
import { ref, computed, onMounted, h, watch } from 'vue'
import {
  NDataTable,
  NTag,
  NSpin,
  NAlert,
  NButton,
  NSpace,
  NText,
  NModal,
  NTabs,
  NTabPane,
  NGrid,
  NGi,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSwitch,
  NCheckbox,
  NCheckboxGroup,
  NCollapse,
  NCollapseItem,
  NDivider,
  useMessage,
  useDialog,
} from 'naive-ui'
import type { SelectOption, DataTableColumns } from 'naive-ui'
import apiClient from '@/api/client'
import type {
  AssetResponse,
  AWSAssetCreateRequest,
  SelfHostedAssetCreateRequest,
  DigitalOceanAssetCreateRequest,
  DigitalOceanImageInfo,
  DigitalOceanImageQueryResponse,
  DigitalOceanSizeInfo,
  DigitalOceanSizeQueryResponse,
  VultrAssetCreateRequest,
  VultrCatalogResponse,
  KamateraAssetCreateRequest,
  KamateraCatalogResponse,
  AzureAssetCreateRequest,
  AzureCatalogResponse,
  GCPAssetCreateRequest,
  GCPCatalogResponse,
  OCIAssetCreateRequest,
  OCICatalogResponse,
  AmiQueryResponse,
  AmiInfo,
} from '@/types/api'

type AssetFilter = 'all' | 'aws' | 'digitalocean' | 'vultr' | 'gcp' | 'kamatera' | 'azure' | 'oci' | 'self_hosted'
type AssetModalTab = 'aws' | 'digitalocean' | 'vultr' | 'gcp' | 'kamatera' | 'azure' | 'oci' | 'self'

// ── Helpers ────────────────────────────────────────────────────────────────────
function statusTagType(status: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  switch (status) {
    case 'active':    return 'success'
    case 'full':      return 'warning'
    case 'offline':   return 'error'
    case 'deploying':  return 'info'
    case 'banned':    return 'error'
    default:          return 'default'
  }
}

function fmtTs(value: string | null | undefined): string {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return value
  }
}

function maskAccountId(id: string | null): string {
  if (!id) return '—'
  return id.slice(0, 4) + '...'
}

function assetTypeLabel(assetType: string): string {
  if (assetType === 'aws') return 'AWS'
  if (assetType === 'digitalocean') return 'DO'
  if (assetType === 'vultr') return 'Vultr'
  if (assetType === 'gcp') return 'GCP'
  if (assetType === 'kamatera') return 'Kamatera'
  if (assetType === 'azure') return 'Azure'
  if (assetType === 'oci') return 'OCI'
  if (assetType === 'self_hosted') return '自建'
  return assetType
}

function assetTypeTagType(assetType: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  if (assetType === 'aws') return 'info'
  if (assetType === 'digitalocean') return 'success'
  if (assetType === 'vultr') return 'error'
  if (assetType === 'gcp') return 'success'
  if (assetType === 'kamatera') return 'default'
  if (assetType === 'azure') return 'info'
  if (assetType === 'oci') return 'warning'
  if (assetType === 'self_hosted') return 'warning'
  return 'default'
}

function modalTitle(tab: AssetModalTab): string {
  if (tab === 'aws') return '新增 AWS 资产'
  if (tab === 'digitalocean') return '新增 DigitalOcean 资产'
  if (tab === 'vultr') return '新增 Vultr 资产'
  if (tab === 'gcp') return '新增 Google Cloud 资产'
  if (tab === 'kamatera') return '新增 Kamatera 资产'
  if (tab === 'azure') return '新增 Microsoft Azure 资产'
  if (tab === 'oci') return '新增 Oracle Cloud 资产'
  return '新增自建资产'
}

function splitList(raw: string): string[] {
  return raw
    .split(/[\n,，]+/)
    .map(value => value.trim())
    .filter(Boolean)
}

// ── State ──────────────────────────────────────────────────────────────────────
const message = useMessage()
const dialog = useDialog()

const assets = ref<AssetResponse[]>([])
const loading = ref(true)
const errorMsg = ref<string | null>(null)
const selectedAssetIds = ref<number[]>([])
const batchDeleting = ref(false)
const activeAssetFilter = ref<AssetFilter>('all')

// ── Modal ──────────────────────────────────────────────────────────────────────
const showModal = ref(false)
const modalTab = ref<AssetModalTab>('aws')

function openModal(tab: AssetModalTab = 'aws') {
  modalTab.value = tab
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

// ── Delete ─────────────────────────────────────────────────────────────────────
function confirmDelete(asset: AssetResponse) {
  dialog.warning({
    title: '确认删除资产',
    content: `确定要删除资产 "${asset.asset_name}" (ID: ${asset.asset_id}) 吗？此操作不可恢复。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: () => doDelete(asset),
  })
}

const deleting = ref(false)

async function doDelete(asset: AssetResponse) {
  deleting.value = true
  try {
    await apiClient.delete(`/assets/${asset.asset_id}`)
    message.success(`资产 "${asset.asset_name}" 已删除`)
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.message || '删除失败')
  } finally {
    deleting.value = false
  }
}

// ── Batch Delete Assets ────────────────────────────────────────────────────────
async function batchDeleteAssets() {
  if (selectedAssetIds.value.length === 0) {
    message.warning('请先选择要删除的资产')
    return
  }

  dialog.warning({
    title: '确认批量删除',
    content: `确定要删除选中的 ${selectedAssetIds.value.length} 个资产吗？此操作不可恢复。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      batchDeleting.value = true
      try {
        const deletePromises = selectedAssetIds.value.map(id => apiClient.delete(`/assets/${id}`))
        await Promise.all(deletePromises)
        message.success(`已删除 ${selectedAssetIds.value.length} 个资产`)
        selectedAssetIds.value = []
        await fetchAssets()
      } catch (err: unknown) {
        const e = err as { response?: { data?: { error?: string; message?: string } } }
        message.error(e.response?.data?.error || e.response?.data?.message || '批量删除失败')
      } finally {
        batchDeleting.value = false
      }
    },
  })
}

// ── Computed: filtered assets ─────────────────────────────────────────────────
const awsAssets  = computed(() => assets.value.filter(a => a.asset_type === 'aws'))
const digitalOceanAssets = computed(() => assets.value.filter(a => a.asset_type === 'digitalocean'))
const vultrAssets = computed(() => assets.value.filter(a => a.asset_type === 'vultr'))
const gcpAssets = computed(() => assets.value.filter(a => a.asset_type === 'gcp'))
const kamateraAssets = computed(() => assets.value.filter(a => a.asset_type === 'kamatera'))
const azureAssets = computed(() => assets.value.filter(a => a.asset_type === 'azure'))
const ociAssets = computed(() => assets.value.filter(a => a.asset_type === 'oci'))
const selfAssets = computed(() => assets.value.filter(a => a.asset_type === 'self_hosted'))
const filteredAssets = computed(() => {
  if (activeAssetFilter.value === 'all') return assets.value
  return assets.value.filter(a => a.asset_type === activeAssetFilter.value)
})

// ── Table columns ──────────────────────────────────────────────────────────────
function buildColumns(onDelete: (asset: AssetResponse) => void): DataTableColumns<AssetResponse> {
  return [
    {
      type: 'selection' as const,
    },
    { title: 'Asset ID', key: 'asset_id', width: 90, align: 'center' },
    { title: 'Name', key: 'asset_name', ellipsis: { tooltip: true } },
    {
      title: 'Type', key: 'asset_type', width: 80,
      render: (row) => h(NTag, { size: 'small', type: assetTypeTagType(row.asset_type) },
        { default: () => assetTypeLabel(row.asset_type) }),
    },
    { title: 'Region', key: 'region', render: (r) => r.region ?? '—' },
    {
      title: 'Status', key: 'status', width: 100,
      render: (row) => h(NTag, { type: statusTagType(row.status), size: 'small' },
        { default: () => row.status }),
    },
    { title: 'Provider Account', key: 'aws_account_id', render: (row) => maskAccountId(row.aws_account_id) },
    {
      title: 'vCPU', key: 'account_total_vcpu', width: 70,
      render: (r) => r.account_total_vcpu ?? r.cpu_cores ?? '—',
    },
    { title: 'Memory (GB)', key: 'memory_gb', width: 100, render: (r) => r.memory_gb ?? '—' },
    {
      title: 'Allocated', key: 'allocated', width: 100,
      render: (r) => `${r.allocated_count} / ${r.target_count}`,
    },
    { title: 'Max', key: 'max_count', width: 70, align: 'center' },
    {
      title: 'Protocols', key: 'supported_protocols',
      ellipsis: { tooltip: true },
      render: (r) =>
        h('div', { style: 'display:flex;flex-wrap:wrap;gap:4px' },
          r.supported_protocols.map(p =>
            h(NTag, { key: p, size: 'tiny', bordered: false }, { default: () => p })
          )
        ),
    },
    {
      title: 'Remarks', key: 'remarks',
      ellipsis: { tooltip: true },
      render: (r) => r.remarks ?? '—',
    },
    { title: 'Updated', key: 'updated_at', width: 160, render: (r) => fmtTs(r.updated_at) },
    {
      title: 'Actions', key: 'actions', width: 80, align: 'center',
      render: (row) =>
        h(NButton, { size: 'small', type: 'error', quaternary: true, onClick: () => onDelete(row) },
          { default: () => '删除' }),
    },
  ]
}

const allColumns = buildColumns(a => confirmDelete(a))

// ── Data fetching ─────────────────────────────────────────────────────────────
async function fetchAssets() {
  try {
    const { data } = await apiClient.get<AssetResponse[]>('/assets')
    assets.value = data
    errorMsg.value = null
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string }; status?: number }; message?: string }
    errorMsg.value = e.response?.data?.error || e.response?.data?.message || 'Failed to load assets'
  } finally {
    loading.value = false
  }
}

// ── AWS Registration Form ──────────────────────────────────────────────────────
const awsForm = ref({
  asset_name: '',
  region: 'ap-northeast-1',
  account_total_vcpu: 8,
  aws_access_key: '',
  aws_secret_key: '',
  aws_account_id: '',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  priority: 100,
  allow_cdn_proxy: false,
  auto_create_sg: false,
  vpc_id: '',
  sg_name: '',
  sg_ports_raw: '',
  ami_id: '',
})

const awsRegions: SelectOption[] = [
  { label: '美东 (us-east-1)', value: 'us-east-1' },
  { label: '美西 (us-west-1)', value: 'us-west-1' },
  { label: '美西2 (us-west-2)', value: 'us-west-2' },
  { label: '伦敦 (eu-west-1)', value: 'eu-west-1' },
  { label: '巴黎 (eu-west-2)', value: 'eu-west-2' },
  { label: '法兰克福 (eu-central-1)', value: 'eu-central-1' },
  { label: '东京 (ap-northeast-1)', value: 'ap-northeast-1' },
  { label: '新加坡 (ap-southeast-1)', value: 'ap-southeast-1' },
  { label: '悉尼 (ap-southeast-2)', value: 'ap-southeast-2' },
]

const awsProtocolOptions: SelectOption[] = [
  { label: 'AnyTLS', value: 'AnyTLS' },
  { label: 'Trojan', value: 'Trojan' },
  { label: 'vless',  value: 'vless' },
  { label: 'vmess',  value: 'vmess' },
]

const sgPortsHint = computed(() => {
  const ports = new Set<number>([22, 80, 443])
  if (awsForm.value.protocol_types.includes('AnyTLS') ||
      awsForm.value.protocol_types.includes('Trojan') ||
      awsForm.value.protocol_types.includes('vless') ||
      awsForm.value.protocol_types.includes('vmess')) {
    ports.add(443)
  }
  return '计算端口: ' + [...ports].sort((a, b) => a - b).join(', ')
})

const sgPorts = computed<number[]>(() => {
  const ports = new Set<number>([22, 80, 443])
  if (awsForm.value.protocol_types.includes('AnyTLS') ||
      awsForm.value.protocol_types.includes('Trojan') ||
      awsForm.value.protocol_types.includes('vless') ||
      awsForm.value.protocol_types.includes('vmess')) {
    ports.add(443)
  }
  return [...ports]
})

const submittingAws = ref(false)

function resetAwsForm() {
  awsForm.value = {
    asset_name: '', region: 'ap-northeast-1', account_total_vcpu: 8,
    aws_access_key: '', aws_secret_key: '', aws_account_id: '',
    remarks: '', protocol_types: ['AnyTLS'], target_count: 1,
    priority: 100, allow_cdn_proxy: false, auto_create_sg: false,
    vpc_id: '', sg_name: '', sg_ports_raw: '', ami_id: '',
  }
}

async function submitAwsForm() {
  if (!awsForm.value.asset_name.trim()) { message.warning('请填写资产名称'); return }
  if (!awsForm.value.region)           { message.warning('请选择 Region');   return }
  if (!awsForm.value.aws_access_key)  { message.warning('请填写 AWS Access Key'); return }
  if (!awsForm.value.aws_secret_key)  { message.warning('请填写 AWS Secret Key'); return }

  submittingAws.value = true
  try {
    const body: AWSAssetCreateRequest = {
      asset_name:         awsForm.value.asset_name.trim(),
      region:             awsForm.value.region,
      aws_access_key:     awsForm.value.aws_access_key,
      aws_secret_key:     awsForm.value.aws_secret_key,
      account_total_vcpu: awsForm.value.account_total_vcpu,
      remarks:           awsForm.value.remarks || undefined,
      protocol_type:     awsForm.value.protocol_types[0] ?? null,
      additional_protocol_types: awsForm.value.protocol_types.slice(1),
      target_count:      awsForm.value.target_count,
      priority:          awsForm.value.priority,
      allow_cdn_proxy:   awsForm.value.allow_cdn_proxy,
      auto_create_security_group: awsForm.value.auto_create_sg,
      vpc_id:            awsForm.value.vpc_id || undefined,
      security_group_name: awsForm.value.sg_name || undefined,
      security_group_ports: sgPorts.value,
      ami_id:            awsForm.value.ami_id || undefined,
      aws_account_id:    awsForm.value.aws_account_id || undefined,
    }
    await apiClient.post<AssetResponse>('/assets', body)
    message.success('AWS 资产注册成功')
    closeModal()
    resetAwsForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string }; message?: string } }
    message.error(e.response?.data?.error || e.response?.data?.message || '注册失败')
  } finally {
    submittingAws.value = false
  }
}

// ── AMI Query ──────────────────────────────────────────────────────────────────
const queryingAmi = ref(false)
const fetchingAccountId = ref(false)
const amiResults = ref<AmiInfo[]>([])
const amiError = ref<string | null>(null)

async function queryAmi() {
  if (!awsForm.value.aws_access_key) {
    message.warning('请先填写 AWS Access Key')
    return
  }
  if (!awsForm.value.aws_secret_key) {
    message.warning('请先填写 AWS Secret Key')
    return
  }
  queryingAmi.value = true
  amiError.value = null
  amiResults.value = []
  try {
    const { data } = await apiClient.post<AmiQueryResponse>('/assets/query-amis', {
      aws_access_key: awsForm.value.aws_access_key,
      aws_secret_key: awsForm.value.aws_secret_key,
      region: awsForm.value.region,
    })
    amiResults.value = data.amis
    if (data.amis.length === 0) {
      message.info('该账号/区域未找到 Debian ARM64 AMI')
    }
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string }; message?: string } }
    amiError.value = e.response?.data?.error || e.response?.data?.detail || '查询失败'
    message.error(amiError.value)
  } finally {
    queryingAmi.value = false
  }
}

function selectAmi(ami: AmiInfo) {
  awsForm.value.ami_id = ami.ami_id
  amiResults.value = []
  message.success(`已选择: ${ami.name} (${ami.ami_id})`)
}

async function fetchAccountId() {
  if (!awsForm.value.aws_access_key) {
    message.warning('请先填写 AWS Access Key')
    return
  }
  if (!awsForm.value.aws_secret_key) {
    message.warning('请先填写 AWS Secret Key')
    return
  }
  fetchingAccountId.value = true
  try {
    const { data } = await apiClient.post<{ aws_account_id: string; arn: string; user_id: string }>(
      '/assets/resolve-aws-account-id',
      {
        aws_access_key: awsForm.value.aws_access_key,
        aws_secret_key: awsForm.value.aws_secret_key,
        region: awsForm.value.region,
      }
    )
    awsForm.value.aws_account_id = data.aws_account_id
    message.success(`Account ID 已获取: ${data.aws_account_id}`)
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.detail || '获取 Account ID 失败')
  } finally {
    fetchingAccountId.value = false
  }
}

// ── DigitalOcean Registration Form ────────────────────────────────────────────
const digitalOceanForm = ref({
  asset_name: '',
  region: 'sgp1',
  digitalocean_token: '',
  default_size: 's-2vcpu-2gb',
  default_image: 'ubuntu-24-04-x64',
  ssh_keys_raw: '',
  vpc_uuid: '',
  tags_raw: 'shadowfleet',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  max_count: 0,
  priority: 100,
  allow_cdn_proxy: false,
  default_vcpu: 2 as number | null,
})

const digitalOceanRegions: SelectOption[] = [
  { label: '纽约 1 (nyc1)', value: 'nyc1' },
  { label: '纽约 3 (nyc3)', value: 'nyc3' },
  { label: '旧金山 3 (sfo3)', value: 'sfo3' },
  { label: '阿姆斯特丹 3 (ams3)', value: 'ams3' },
  { label: '新加坡 (sgp1)', value: 'sgp1' },
  { label: '伦敦 (lon1)', value: 'lon1' },
  { label: '法兰克福 (fra1)', value: 'fra1' },
  { label: '多伦多 (tor1)', value: 'tor1' },
  { label: '班加罗尔 (blr1)', value: 'blr1' },
  { label: '悉尼 (syd1)', value: 'syd1' },
]

const digitalOceanProtocolOptions = awsProtocolOptions
const submittingDigitalOcean = ref(false)
const queryingDigitalOceanImages = ref(false)
const queryingDigitalOceanSizes = ref(false)
const digitalOceanImageResults = ref<DigitalOceanImageInfo[]>([])
const digitalOceanSizeResults = ref<DigitalOceanSizeInfo[]>([])
const digitalOceanCatalogError = ref<string | null>(null)

function resetDigitalOceanForm() {
  digitalOceanForm.value = {
    asset_name: '',
    region: 'sgp1',
    digitalocean_token: '',
    default_size: 's-2vcpu-2gb',
    default_image: 'ubuntu-24-04-x64',
    ssh_keys_raw: '',
    vpc_uuid: '',
    tags_raw: 'shadowfleet',
    remarks: '',
    protocol_types: ['AnyTLS'],
    target_count: 1,
    max_count: 0,
    priority: 100,
    allow_cdn_proxy: false,
    default_vcpu: 2,
  }
  digitalOceanImageResults.value = []
  digitalOceanSizeResults.value = []
  digitalOceanCatalogError.value = null
}

function requireDigitalOceanToken(): boolean {
  if (!digitalOceanForm.value.digitalocean_token.trim()) {
    message.warning('请先填写 DigitalOcean Token')
    return false
  }
  return true
}

async function queryDigitalOceanImages() {
  if (!requireDigitalOceanToken()) return
  queryingDigitalOceanImages.value = true
  digitalOceanCatalogError.value = null
  digitalOceanImageResults.value = []
  try {
    const { data } = await apiClient.post<DigitalOceanImageQueryResponse>('/assets/digitalocean/query-images', {
      digitalocean_token: digitalOceanForm.value.digitalocean_token,
      limit: 80,
    })
    digitalOceanImageResults.value = data.images.filter(image => image.slug || image.id)
    if (digitalOceanImageResults.value.length === 0) {
      message.info('未查询到可用镜像')
    }
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string }; message?: string } }
    digitalOceanCatalogError.value = e.response?.data?.error || e.response?.data?.detail || '镜像查询失败'
    message.error(digitalOceanCatalogError.value)
  } finally {
    queryingDigitalOceanImages.value = false
  }
}

async function queryDigitalOceanSizes() {
  if (!requireDigitalOceanToken()) return
  queryingDigitalOceanSizes.value = true
  digitalOceanCatalogError.value = null
  digitalOceanSizeResults.value = []
  try {
    const { data } = await apiClient.post<DigitalOceanSizeQueryResponse>('/assets/digitalocean/query-sizes', {
      digitalocean_token: digitalOceanForm.value.digitalocean_token,
      limit: 200,
    })
    digitalOceanSizeResults.value = data.sizes.filter(size =>
      Boolean(size.slug) &&
      size.available !== false &&
      (!size.regions.length || size.regions.includes(digitalOceanForm.value.region))
    )
    if (digitalOceanSizeResults.value.length === 0) {
      message.info('当前区域未查询到可用规格')
    }
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string }; message?: string } }
    digitalOceanCatalogError.value = e.response?.data?.error || e.response?.data?.detail || '规格查询失败'
    message.error(digitalOceanCatalogError.value)
  } finally {
    queryingDigitalOceanSizes.value = false
  }
}

function selectDigitalOceanImage(image: DigitalOceanImageInfo) {
  const imageId = image.slug || String(image.id)
  digitalOceanForm.value.default_image = imageId
  digitalOceanImageResults.value = []
  message.success(`已选择镜像: ${image.name || imageId}`)
}

function selectDigitalOceanSize(size: DigitalOceanSizeInfo) {
  if (!size.slug) return
  digitalOceanForm.value.default_size = size.slug
  digitalOceanForm.value.default_vcpu = size.vcpus ?? digitalOceanForm.value.default_vcpu
  digitalOceanSizeResults.value = []
  message.success(`已选择规格: ${size.slug}`)
}

async function submitDigitalOceanForm() {
  if (!digitalOceanForm.value.asset_name.trim()) { message.warning('请填写资产名称'); return }
  if (!digitalOceanForm.value.region)            { message.warning('请选择 Region'); return }
  if (!digitalOceanForm.value.digitalocean_token.trim()) { message.warning('请填写 DigitalOcean Token'); return }
  if (!digitalOceanForm.value.default_size.trim())       { message.warning('请填写 Droplet Size'); return }
  if (!digitalOceanForm.value.default_image.trim())      { message.warning('请填写镜像 Slug'); return }

  submittingDigitalOcean.value = true
  try {
    const body: DigitalOceanAssetCreateRequest = {
      asset_name: digitalOceanForm.value.asset_name.trim(),
      region: digitalOceanForm.value.region,
      digitalocean_token: digitalOceanForm.value.digitalocean_token.trim(),
      default_size: digitalOceanForm.value.default_size.trim(),
      default_image: digitalOceanForm.value.default_image.trim(),
      ssh_keys: splitList(digitalOceanForm.value.ssh_keys_raw),
      vpc_uuid: digitalOceanForm.value.vpc_uuid || undefined,
      tags: splitList(digitalOceanForm.value.tags_raw),
      remarks: digitalOceanForm.value.remarks || undefined,
      protocol_type: digitalOceanForm.value.protocol_types[0] ?? null,
      additional_protocol_types: digitalOceanForm.value.protocol_types.slice(1),
      target_count: digitalOceanForm.value.target_count,
      max_count: digitalOceanForm.value.max_count,
      priority: digitalOceanForm.value.priority,
      allow_cdn_proxy: digitalOceanForm.value.allow_cdn_proxy,
      default_vcpu: digitalOceanForm.value.default_vcpu ?? undefined,
    }
    await apiClient.post<AssetResponse>('/assets/digitalocean', body)
    message.success('DigitalOcean 资产注册成功')
    closeModal()
    resetDigitalOceanForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string; message?: string }; message?: string } }
    message.error(e.response?.data?.error || e.response?.data?.detail || e.response?.data?.message || '注册失败')
  } finally {
    submittingDigitalOcean.value = false
  }
}

// ── Vultr Registration Form ──────────────────────────────────────────────────
const vultrForm = ref({
  asset_name: '',
  region: 'sgp',
  vultr_token: '',
  default_plan: 'vc2-1c-1gb',
  default_os_id: 2284,
  ssh_key_ids: [] as string[],
  vpc_ids: [] as string[],
  firewall_group_id: '',
  tags_raw: 'shadowfleet',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  max_count: 0,
  priority: 100,
  allow_cdn_proxy: false,
  default_vcpu: 1 as number | null,
})

const defaultVultrRegions: SelectOption[] = [
  { label: '新加坡 (sgp)', value: 'sgp' },
  { label: '东京 (nrt)', value: 'nrt' },
  { label: '首尔 (icn)', value: 'icn' },
  { label: '洛杉矶 (lax)', value: 'lax' },
  { label: '硅谷 (sjc)', value: 'sjc' },
  { label: '西雅图 (sea)', value: 'sea' },
  { label: '芝加哥 (ord)', value: 'ord' },
  { label: '纽约 (ewr)', value: 'ewr' },
  { label: '伦敦 (lhr)', value: 'lhr' },
  { label: '法兰克福 (fra)', value: 'fra' },
]

const vultrCatalog = ref<VultrCatalogResponse | null>(null)
const queryingVultrCatalog = ref(false)
const vultrCatalogError = ref<string | null>(null)
const vultrRegions = computed<SelectOption[]>(() => {
  const regions = vultrCatalog.value?.regions ?? []
  if (!regions.length) return defaultVultrRegions
  return regions.map(region => ({
    label: `${region.city || region.id}${region.country ? ` (${region.country})` : ''} - ${region.id}`,
    value: region.id,
  }))
})
const vultrPlans = computed<SelectOption[]>(() => (vultrCatalog.value?.plans ?? [])
  .filter(plan => !plan.locations?.length || plan.locations.includes(vultrForm.value.region))
  .map(plan => ({
    label: `${plan.id} · ${plan.vcpu_count ?? '?'} vCPU · ${plan.ram ?? '?'} MB · $${plan.monthly_cost ?? '?'}/月`,
    value: plan.id,
  })))
const vultrOperatingSystems = computed<SelectOption[]>(() => (vultrCatalog.value?.operating_systems ?? [])
  .map(os => ({ label: `${os.name || os.id}${os.arch ? ` (${os.arch})` : ''}`, value: os.id })))
const vultrSshKeys = computed<SelectOption[]>(() => (vultrCatalog.value?.ssh_keys ?? [])
  .map(key => ({ label: key.name || key.id, value: key.id })))
const vultrVpcs = computed<SelectOption[]>(() => (vultrCatalog.value?.vpcs ?? [])
  .filter(vpc => !vpc.region || vpc.region === vultrForm.value.region)
  .map(vpc => ({ label: vpc.description || vpc.id, value: vpc.id })))
const vultrFirewallGroups = computed<SelectOption[]>(() => (vultrCatalog.value?.firewall_groups ?? [])
  .map(group => ({ label: group.description || group.id, value: group.id })))

const vultrProtocolOptions = awsProtocolOptions
const submittingVultr = ref(false)

function resetVultrForm() {
  vultrForm.value = {
    asset_name: '', region: 'sgp', vultr_token: '', default_plan: 'vc2-1c-1gb',
    default_os_id: 2284, ssh_key_ids: [], vpc_ids: [], firewall_group_id: '',
    tags_raw: 'shadowfleet', remarks: '', protocol_types: ['AnyTLS'], target_count: 1,
    max_count: 0, priority: 100, allow_cdn_proxy: false, default_vcpu: 1,
  }
}

async function queryVultrCatalog() {
  if (!vultrForm.value.vultr_token.trim()) {
    message.warning('请先填写 Vultr API Token')
    return
  }
  queryingVultrCatalog.value = true
  vultrCatalogError.value = null
  try {
    const { data } = await apiClient.post<VultrCatalogResponse>('/assets/vultr/query-catalog', {
      vultr_token: vultrForm.value.vultr_token.trim(),
    })
    vultrCatalog.value = data
    message.success('Vultr 资源目录已加载')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    vultrCatalogError.value = e.response?.data?.detail || 'Vultr 资源目录查询失败'
    message.error(vultrCatalogError.value)
  } finally {
    queryingVultrCatalog.value = false
  }
}

async function submitVultrForm() {
  if (!vultrForm.value.asset_name.trim()) { message.warning('请填写资产名称'); return }
  if (!vultrForm.value.region) { message.warning('请选择 Region'); return }
  if (!vultrForm.value.vultr_token.trim()) { message.warning('请填写 Vultr API Token'); return }
  if (!vultrForm.value.default_plan.trim()) { message.warning('请填写 Vultr Plan'); return }

  submittingVultr.value = true
  try {
    const body: VultrAssetCreateRequest = {
      asset_name: vultrForm.value.asset_name.trim(),
      region: vultrForm.value.region,
      vultr_token: vultrForm.value.vultr_token.trim(),
      default_plan: vultrForm.value.default_plan.trim(),
      default_os_id: vultrForm.value.default_os_id,
      ssh_key_ids: vultrForm.value.ssh_key_ids,
      vpc_ids: vultrForm.value.vpc_ids,
      firewall_group_id: vultrForm.value.firewall_group_id || undefined,
      tags: splitList(vultrForm.value.tags_raw),
      remarks: vultrForm.value.remarks || undefined,
      protocol_type: vultrForm.value.protocol_types[0] ?? null,
      additional_protocol_types: vultrForm.value.protocol_types.slice(1),
      target_count: vultrForm.value.target_count,
      max_count: vultrForm.value.max_count,
      priority: vultrForm.value.priority,
      allow_cdn_proxy: vultrForm.value.allow_cdn_proxy,
      default_vcpu: vultrForm.value.default_vcpu ?? undefined,
    }
    await apiClient.post<AssetResponse>('/assets/vultr', body)
    message.success('Vultr 资产注册成功')
    closeModal()
    resetVultrForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string; message?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.detail || e.response?.data?.message || '注册失败')
  } finally {
    submittingVultr.value = false
  }
}

// ── Kamatera Registration Form ───────────────────────────────────────────────
const kamateraForm = ref({
  asset_name: '',
  datacenter: '',
  client_id: '',
  secret: '',
  image: '',
  ssh_public_key: '',
  cpu_type: 'B',
  cpu_cores: 2,
  ram_mb: 2048,
  disk_size_gb: 20,
  billing_cycle: 'hourly',
  monthly_package: '',
  daily_backup: false,
  managed: false,
  tags_raw: 'shadowfleet',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  max_count: 0,
  priority: 100,
  allow_cdn_proxy: false,
})
const kamateraCatalog = ref<KamateraCatalogResponse | null>(null)
const queryingKamateraCatalog = ref(false)
const kamateraCatalogError = ref<string | null>(null)
const submittingKamatera = ref(false)
const kamateraDatacenters = computed<SelectOption[]>(() =>
  (kamateraCatalog.value?.datacenters ?? [])
    .filter(item => item.id)
    .map(item => ({
      label: `${item.region || item.id} (${item.id})`,
      value: item.id as string,
    }))
)
const kamateraImages = computed<SelectOption[]>(() =>
  (kamateraCatalog.value?.images ?? [])
    .filter(item => item.id)
    .map(item => ({
      label: item.description ? `${item.description} (${item.id})` : String(item.id),
      value: item.id as string,
    }))
)
const defaultKamateraCpuTypes: SelectOption[] = [
  { label: 'A - Availability', value: 'A' },
  { label: 'B - General Purpose', value: 'B' },
  { label: 'T - Burstable', value: 'T' },
  { label: 'D - Dedicated', value: 'D' },
]
const defaultKamateraBillingCycles: SelectOption[] = [
  { label: '按小时计费', value: 'hourly' },
  { label: '按月计费', value: 'monthly' },
]

type KamateraCapabilityValue = string | number

function normalizeKamateraCapabilityKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, '')
}

function kamateraCapabilityItemValue(item: unknown): KamateraCapabilityValue | null {
  if (typeof item === 'string' || typeof item === 'number') return item
  if (!item || typeof item !== 'object') return null
  const record = item as Record<string, unknown>
  for (const key of ['id', 'value', 'name', 'code']) {
    const value = record[key]
    if (typeof value === 'string' || typeof value === 'number') return value
  }
  return null
}

function kamateraCapabilityValues(raw: unknown): KamateraCapabilityValue[] {
  let values: unknown = raw
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    const record = raw as Record<string, unknown>
    const normalized = new Map(
      Object.entries(record).map(([key, value]) => [normalizeKamateraCapabilityKey(key), value])
    )
    values = ['values', 'options', 'allowed', 'items']
      .map(key => normalized.get(key))
      .find(value => Array.isArray(value))
  }
  if (!Array.isArray(values)) return []
  return values
    .map(kamateraCapabilityItemValue)
    .filter((value): value is KamateraCapabilityValue => value !== null)
}

function readKamateraCapabilityValues(...aliases: string[]): KamateraCapabilityValue[] {
  const capabilities = kamateraCatalog.value?.capabilities
  if (!capabilities) return []
  const normalizedAliases = new Set(aliases.map(normalizeKamateraCapabilityKey))
  const pending: Array<{ value: Record<string, unknown>; depth: number }> = [
    { value: capabilities, depth: 0 },
  ]
  while (pending.length) {
    const current = pending.shift()
    if (!current) break
    for (const [key, value] of Object.entries(current.value)) {
      if (normalizedAliases.has(normalizeKamateraCapabilityKey(key))) {
        return kamateraCapabilityValues(value)
      }
    }
    if (current.depth >= 2) continue
    for (const value of Object.values(current.value)) {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        pending.push({ value: value as Record<string, unknown>, depth: current.depth + 1 })
      }
    }
  }
  return []
}

const kamateraCpuCodes = computed(() =>
  readKamateraCapabilityValues('cpu', 'cpus')
    .map(value => String(value).trim().toUpperCase())
    .filter(value => /^\d+[ABTD]$/.test(value))
)
const kamateraCpuTypes = computed<SelectOption[]>(() => {
  const available = new Set(kamateraCpuCodes.value.map(value => value.slice(-1)))
  if (!available.size) return defaultKamateraCpuTypes
  return defaultKamateraCpuTypes.filter(option => available.has(String(option.value)))
})
const kamateraCpuCoreOptions = computed<SelectOption[]>(() => {
  const cpuType = kamateraForm.value.cpu_type.toUpperCase()
  const values = kamateraCpuCodes.value
    .filter(value => value.endsWith(cpuType))
    .map(value => Number(value.slice(0, -1)))
    .filter(value => Number.isInteger(value) && value > 0)
  return [...new Set(values)].sort((left, right) => left - right)
    .map(value => ({ label: String(value), value }))
})
function numericKamateraCapabilityOptions(...aliases: string[]): SelectOption[] {
  const values = readKamateraCapabilityValues(...aliases)
    .map(value => Number(value))
    .filter(value => Number.isFinite(value) && value > 0)
  return [...new Set(values)].sort((left, right) => left - right)
    .map(value => ({ label: String(value), value }))
}
const kamateraRamOptions = computed<SelectOption[]>(() =>
  numericKamateraCapabilityOptions('ram', 'memory', 'ram_mb')
)
const kamateraDiskOptions = computed<SelectOption[]>(() =>
  numericKamateraCapabilityOptions('disk', 'disk_size', 'disk_sizes')
)
const kamateraBillingCycles = computed<SelectOption[]>(() => {
  const values = readKamateraCapabilityValues('billingcycle', 'billing_cycle', 'billing_cycles')
    .map(value => String(value).trim().toLowerCase())
    .filter(value => value === 'hourly' || value === 'monthly')
  if (!values.length) return defaultKamateraBillingCycles
  const available = new Set<string>(values)
  return defaultKamateraBillingCycles.filter(option => available.has(String(option.value)))
})
const kamateraMonthlyPackageOptions = computed<SelectOption[]>(() =>
  readKamateraCapabilityValues('monthlypackage', 'monthly_package', 'monthly_packages')
    .map(value => ({ label: String(value), value: String(value) }))
)
const kamateraProtocolOptions = awsProtocolOptions

function resetKamateraForm() {
  kamateraForm.value = {
    asset_name: '', datacenter: '', client_id: '', secret: '', image: '',
    ssh_public_key: '', cpu_type: 'B', cpu_cores: 2, ram_mb: 2048,
    disk_size_gb: 20, billing_cycle: 'hourly', monthly_package: '',
    daily_backup: false, managed: false, tags_raw: 'shadowfleet', remarks: '',
    protocol_types: ['AnyTLS'], target_count: 1, max_count: 0, priority: 100,
    allow_cdn_proxy: false,
  }
  kamateraCatalog.value = null
  kamateraCatalogError.value = null
}

async function requestKamateraCatalog(datacenter?: string): Promise<KamateraCatalogResponse> {
  const { data } = await apiClient.post<KamateraCatalogResponse>('/assets/kamatera/query-catalog', {
    client_id: kamateraForm.value.client_id.trim(),
    secret: kamateraForm.value.secret.trim(),
    datacenter: datacenter || undefined,
  })
  return data
}

function normalizeKamateraCapabilitySelections() {
  const cpuTypes = kamateraCpuTypes.value.map(option => String(option.value))
  if (cpuTypes.length && !cpuTypes.includes(kamateraForm.value.cpu_type)) {
    kamateraForm.value.cpu_type = cpuTypes[0]
  }
  const cpuCores = kamateraCpuCoreOptions.value.map(option => Number(option.value))
  if (cpuCores.length && !cpuCores.includes(kamateraForm.value.cpu_cores)) {
    kamateraForm.value.cpu_cores = cpuCores[0]
  }
  const ramValues = kamateraRamOptions.value.map(option => Number(option.value))
  if (ramValues.length && !ramValues.includes(kamateraForm.value.ram_mb)) {
    kamateraForm.value.ram_mb = ramValues[0]
  }
  const diskValues = kamateraDiskOptions.value.map(option => Number(option.value))
  if (diskValues.length && !diskValues.includes(kamateraForm.value.disk_size_gb)) {
    kamateraForm.value.disk_size_gb = diskValues[0]
  }
  const billingCycles = kamateraBillingCycles.value.map(option => String(option.value))
  if (billingCycles.length && !billingCycles.includes(kamateraForm.value.billing_cycle)) {
    kamateraForm.value.billing_cycle = billingCycles[0]
  }
  const monthlyPackages = kamateraMonthlyPackageOptions.value.map(option => String(option.value))
  if (
    monthlyPackages.length
    && kamateraForm.value.monthly_package
    && !monthlyPackages.includes(kamateraForm.value.monthly_package)
  ) {
    kamateraForm.value.monthly_package = ''
  }
}

function selectFirstAvailableKamateraImage() {
  const imageIds = kamateraImages.value.map(option => String(option.value))
  if (!imageIds.includes(kamateraForm.value.image)) {
    kamateraForm.value.image = imageIds[0] ?? ''
  }
}

async function queryKamateraCatalog() {
  if (!kamateraForm.value.client_id.trim() || !kamateraForm.value.secret.trim()) {
    message.warning('请填写 Kamatera Client ID 和 Secret')
    return
  }
  queryingKamateraCatalog.value = true
  kamateraCatalogError.value = null
  try {
    const accountCatalog = await requestKamateraCatalog()
    const datacenterIds = accountCatalog.datacenters
      .map(item => String(item.id ?? '').trim())
      .filter(Boolean)
    const selectedDatacenter = datacenterIds.includes(kamateraForm.value.datacenter)
      ? kamateraForm.value.datacenter
      : (datacenterIds[0] ?? '')
    kamateraForm.value.datacenter = selectedDatacenter
    if (!selectedDatacenter) {
      kamateraCatalog.value = accountCatalog
      kamateraForm.value.image = ''
    } else {
      const scopedCatalog = await requestKamateraCatalog(selectedDatacenter)
      kamateraCatalog.value = {
        datacenters: accountCatalog.datacenters,
        images: scopedCatalog.images,
        capabilities: scopedCatalog.capabilities,
      }
      selectFirstAvailableKamateraImage()
      normalizeKamateraCapabilitySelections()
    }
    message.success('Kamatera 凭据验证成功，资源目录已加载')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    kamateraCatalogError.value = e.response?.data?.detail || 'Kamatera 资源目录查询失败'
    message.error(kamateraCatalogError.value)
  } finally {
    queryingKamateraCatalog.value = false
  }
}

async function handleKamateraDatacenterChange(value: string | null) {
  kamateraForm.value.datacenter = String(value ?? '')
  kamateraForm.value.image = ''
  if (
    !kamateraForm.value.datacenter
    || !kamateraForm.value.client_id.trim()
    || !kamateraForm.value.secret.trim()
  ) {
    return
  }
  queryingKamateraCatalog.value = true
  kamateraCatalogError.value = null
  try {
    const scopedCatalog = await requestKamateraCatalog(kamateraForm.value.datacenter)
    kamateraCatalog.value = {
      datacenters: kamateraCatalog.value?.datacenters ?? scopedCatalog.datacenters,
      images: scopedCatalog.images,
      capabilities: scopedCatalog.capabilities,
    }
    selectFirstAvailableKamateraImage()
    normalizeKamateraCapabilitySelections()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    kamateraCatalogError.value = e.response?.data?.detail || 'Kamatera Datacenter 资源加载失败'
    message.error(kamateraCatalogError.value)
  } finally {
    queryingKamateraCatalog.value = false
  }
}

watch(() => kamateraForm.value.cpu_type, () => {
  const cpuCores = kamateraCpuCoreOptions.value.map(option => Number(option.value))
  if (cpuCores.length && !cpuCores.includes(kamateraForm.value.cpu_cores)) {
    kamateraForm.value.cpu_cores = cpuCores[0]
  }
})

async function submitKamateraForm() {
  const required: Array<[string, string]> = [
    ['资产名称', kamateraForm.value.asset_name],
    ['Datacenter', kamateraForm.value.datacenter],
    ['Client ID', kamateraForm.value.client_id],
    ['Secret', kamateraForm.value.secret],
    ['Image', kamateraForm.value.image],
    ['SSH 公钥', kamateraForm.value.ssh_public_key],
  ]
  const missing = required.find(([, value]) => !value.trim())
  if (missing) { message.warning(`请填写${missing[0]}`); return }
  if (kamateraForm.value.billing_cycle === 'monthly' && !kamateraForm.value.monthly_package.trim()) {
    message.warning('按月计费时必须填写 Monthly Package')
    return
  }
  submittingKamatera.value = true
  try {
    const body: KamateraAssetCreateRequest = {
      asset_name: kamateraForm.value.asset_name.trim(),
      datacenter: kamateraForm.value.datacenter.trim(),
      client_id: kamateraForm.value.client_id.trim(),
      secret: kamateraForm.value.secret.trim(),
      image: kamateraForm.value.image.trim(),
      ssh_public_key: kamateraForm.value.ssh_public_key.trim(),
      cpu_type: kamateraForm.value.cpu_type,
      cpu_cores: kamateraForm.value.cpu_cores,
      ram_mb: kamateraForm.value.ram_mb,
      disk_sizes_gb: [kamateraForm.value.disk_size_gb],
      billing_cycle: kamateraForm.value.billing_cycle,
      monthly_package: kamateraForm.value.monthly_package || undefined,
      daily_backup: kamateraForm.value.daily_backup,
      managed: kamateraForm.value.managed,
      tags: splitList(kamateraForm.value.tags_raw),
      remarks: kamateraForm.value.remarks || undefined,
      protocol_type: kamateraForm.value.protocol_types[0] ?? null,
      additional_protocol_types: kamateraForm.value.protocol_types.slice(1),
      target_count: kamateraForm.value.target_count,
      max_count: kamateraForm.value.max_count,
      priority: kamateraForm.value.priority,
      allow_cdn_proxy: kamateraForm.value.allow_cdn_proxy,
    }
    await apiClient.post<AssetResponse>('/assets/kamatera', body)
    message.success('Kamatera 资产注册成功')
    closeModal()
    resetKamateraForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string; message?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.detail || e.response?.data?.message || '注册失败')
  } finally {
    submittingKamatera.value = false
  }
}

// ── Microsoft Azure Registration Form ─────────────────────────────────────────
const azureForm = ref({
  asset_name: '',
  region: 'japaneast',
  tenant_id: '',
  client_id: '',
  client_secret: '',
  subscription_id: '',
  resource_group: 'shadowfleet',
  ssh_public_key: '',
  default_vm_size: 'Standard_B1s',
  admin_username: 'azureuser',
  image_publisher: 'Canonical',
  image_offer: '0001-com-ubuntu-server-jammy',
  image_sku: '22_04-lts-gen2',
  image_version: 'latest',
  vnet_name: 'shadowfleet-vnet',
  subnet_name: 'default',
  tags_raw: 'shadowfleet',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  max_count: 0,
  priority: 100,
  allow_cdn_proxy: false,
  default_vcpu: 1 as number | null,
})

const defaultAzureLocations: SelectOption[] = [
  { label: '日本东部 (japaneast)', value: 'japaneast' },
  { label: '东南亚 (southeastasia)', value: 'southeastasia' },
  { label: '东亚 (eastasia)', value: 'eastasia' },
  { label: '美国西部 2 (westus2)', value: 'westus2' },
  { label: '美国东部 (eastus)', value: 'eastus' },
  { label: '英国南部 (uksouth)', value: 'uksouth' },
  { label: '西欧 (westeurope)', value: 'westeurope' },
  { label: '德国中西部 (germanywestcentral)', value: 'germanywestcentral' },
  { label: '澳大利亚东部 (australiaeast)', value: 'australiaeast' },
]

const azureCatalog = ref<AzureCatalogResponse | null>(null)
const queryingAzureCatalog = ref(false)
const azureCatalogError = ref<string | null>(null)
const azureLocations = computed<SelectOption[]>(() => {
  const locations = azureCatalog.value?.locations ?? []
  if (!locations.length) return defaultAzureLocations
  return locations
    .filter(location => location.name)
    .map(location => ({
      label: `${location.regionalDisplayName || location.displayName || location.name} (${location.name})`,
      value: location.name as string,
    }))
})
const azureVmSizes = computed<SelectOption[]>(() => {
  const sizes = azureCatalog.value?.vm_sizes ?? []
  if (!sizes.length) {
    return [{ label: 'Standard_B1s', value: 'Standard_B1s' }]
  }
  return sizes
    .filter(size => size.name)
    .map(size => ({
      label: `${size.name} · ${size.numberOfCores ?? '?'} vCPU · ${size.memoryInMB ?? '?'} MB`,
      value: size.name as string,
    }))
})
const submittingAzure = ref(false)

function resetAzureForm() {
  azureForm.value = {
    asset_name: '', region: 'japaneast', tenant_id: '', client_id: '', client_secret: '',
    subscription_id: '', resource_group: 'shadowfleet', ssh_public_key: '',
    default_vm_size: 'Standard_B1s', admin_username: 'azureuser', image_publisher: 'Canonical',
    image_offer: '0001-com-ubuntu-server-jammy', image_sku: '22_04-lts-gen2',
    image_version: 'latest', vnet_name: 'shadowfleet-vnet', subnet_name: 'default',
    tags_raw: 'shadowfleet', remarks: '', protocol_types: ['AnyTLS'], target_count: 1,
    max_count: 0, priority: 100, allow_cdn_proxy: false, default_vcpu: 1,
  }
  azureCatalog.value = null
  azureCatalogError.value = null
}

function azureCredentialsComplete(): boolean {
  return [
    azureForm.value.tenant_id,
    azureForm.value.client_id,
    azureForm.value.client_secret,
    azureForm.value.subscription_id,
  ].every(value => value.trim())
}

async function queryAzureCatalog() {
  if (!azureCredentialsComplete()) {
    message.warning('请先填写 Tenant ID、Client ID、Client Secret 和 Subscription ID')
    return
  }
  queryingAzureCatalog.value = true
  azureCatalogError.value = null
  try {
    const { data } = await apiClient.post<AzureCatalogResponse>('/assets/azure/query-catalog', {
      tenant_id: azureForm.value.tenant_id.trim(),
      client_id: azureForm.value.client_id.trim(),
      client_secret: azureForm.value.client_secret.trim(),
      subscription_id: azureForm.value.subscription_id.trim(),
      location: azureForm.value.region || undefined,
    })
    azureCatalog.value = data
    message.success('Azure 订阅与资源目录已验证')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    azureCatalogError.value = e.response?.data?.detail || 'Azure 资源目录查询失败'
    message.error(azureCatalogError.value)
  } finally {
    queryingAzureCatalog.value = false
  }
}

async function submitAzureForm() {
  const required: Array<[string, string]> = [
    ['资产名称', azureForm.value.asset_name],
    ['Region', azureForm.value.region],
    ['Tenant ID', azureForm.value.tenant_id],
    ['Client ID', azureForm.value.client_id],
    ['Client Secret', azureForm.value.client_secret],
    ['Subscription ID', azureForm.value.subscription_id],
    ['Resource Group', azureForm.value.resource_group],
    ['SSH 公钥', azureForm.value.ssh_public_key],
    ['VM Size', azureForm.value.default_vm_size],
  ]
  const missing = required.find(([, value]) => !value.trim())
  if (missing) {
    message.warning(`请填写${missing[0]}`)
    return
  }

  submittingAzure.value = true
  try {
    const body: AzureAssetCreateRequest = {
      asset_name: azureForm.value.asset_name.trim(),
      region: azureForm.value.region.trim(),
      tenant_id: azureForm.value.tenant_id.trim(),
      client_id: azureForm.value.client_id.trim(),
      client_secret: azureForm.value.client_secret.trim(),
      subscription_id: azureForm.value.subscription_id.trim(),
      resource_group: azureForm.value.resource_group.trim(),
      ssh_public_key: azureForm.value.ssh_public_key.trim(),
      default_vm_size: azureForm.value.default_vm_size.trim(),
      admin_username: azureForm.value.admin_username.trim(),
      image_publisher: azureForm.value.image_publisher.trim(),
      image_offer: azureForm.value.image_offer.trim(),
      image_sku: azureForm.value.image_sku.trim(),
      image_version: azureForm.value.image_version.trim(),
      vnet_name: azureForm.value.vnet_name.trim(),
      subnet_name: azureForm.value.subnet_name.trim(),
      tags: splitList(azureForm.value.tags_raw),
      remarks: azureForm.value.remarks || undefined,
      protocol_type: azureForm.value.protocol_types[0] ?? null,
      additional_protocol_types: azureForm.value.protocol_types.slice(1),
      target_count: azureForm.value.target_count,
      max_count: azureForm.value.max_count,
      priority: azureForm.value.priority,
      allow_cdn_proxy: azureForm.value.allow_cdn_proxy,
      default_vcpu: azureForm.value.default_vcpu ?? undefined,
    }
    await apiClient.post<AssetResponse>('/assets/azure', body)
    message.success('Microsoft Azure 资产注册成功')
    closeModal()
    resetAzureForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string; message?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.detail || e.response?.data?.message || '注册失败')
  } finally {
    submittingAzure.value = false
  }
}
// -- Google Cloud Platform Registration Form ---------------------------------
const gcpForm = ref({
  asset_name: '',
  project_id: '',
  service_account_json: '',
  zone: '',
  machine_type: 'e2-small',
  source_image: 'projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64',
  network: 'default',
  subnetwork: '',
  ssh_username: 'ubuntu',
  ssh_public_key: '',
  labels_raw: '',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  max_count: 0,
  priority: 100,
  allow_cdn_proxy: false,
  default_vcpu: 2 as number | null,
})

const gcpCatalog = ref<GCPCatalogResponse | null>(null)
const queryingGcpCatalog = ref(false)
const gcpCatalogError = ref<string | null>(null)
const submittingGcp = ref(false)

const gcpZones = computed<SelectOption[]>(() =>
  (gcpCatalog.value?.zones ?? [])
    .filter(item => item.name && item.status !== 'DOWN')
    .map(item => ({
      label: String(item.name),
      value: String(item.name),
    }))
)
const gcpMachineTypes = computed<SelectOption[]>(() =>
  (gcpCatalog.value?.machine_types ?? [])
    .filter(item => item.name)
    .map(item => ({
      label: String(item.name) + ' · ' + String(item.guestCpus ?? '?') + ' vCPU · ' +
        String(item.memoryMb ? Math.round(item.memoryMb / 1024 * 10) / 10 : '?') + ' GB',
      value: String(item.name),
    }))
)
const gcpImages = computed<SelectOption[]>(() =>
  (gcpCatalog.value?.images ?? [])
    .filter(item => item.selfLink && item.status !== 'DEPRECATED')
    .map(item => ({
      label: String(item.family || item.name) + ' · ' + String(item.architecture || ''),
      value: String(item.selfLink),
    }))
)
const gcpNetworks = computed<SelectOption[]>(() =>
  (gcpCatalog.value?.networks ?? [])
    .filter(item => item.name)
    .map(item => ({
      label: String(item.name) + (item.autoCreateSubnetworks ? ' · auto' : ' · custom'),
      value: String(item.name),
    }))
)
function gcpResourceName(value: unknown): string {
  return String(value ?? '').replace(/\/$/, '').split('/').pop() ?? ''
}

const gcpSubnetworks = computed<SelectOption[]>(() => {
  const selectedNetwork = gcpResourceName(gcpForm.value.network)
  return (gcpCatalog.value?.subnetworks ?? [])
    .filter(item =>
      item.name
      && (!item.network || gcpResourceName(item.network) === selectedNetwork)
    )
    .map(item => ({
      label: String(item.name) + ' · ' + String(item.ipCidrRange || ''),
      value: String(item.name),
    }))
})

function resetGcpForm() {
  gcpForm.value = {
    asset_name: '',
    project_id: '',
    service_account_json: '',
    zone: '',
    machine_type: 'e2-small',
    source_image: 'projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64',
    network: 'default',
    subnetwork: '',
    ssh_username: 'ubuntu',
    ssh_public_key: '',
    labels_raw: '',
    remarks: '',
    protocol_types: ['AnyTLS'],
    target_count: 1,
    max_count: 0,
    priority: 100,
    allow_cdn_proxy: false,
    default_vcpu: 2,
  }
  gcpCatalog.value = null
  gcpCatalogError.value = null
}

function applyProjectIdFromServiceAccount() {
  try {
    const parsed = JSON.parse(gcpForm.value.service_account_json) as { project_id?: string }
    if (parsed.project_id && !gcpForm.value.project_id.trim()) {
      gcpForm.value.project_id = parsed.project_id
    }
  } catch {
    // The backend returns the authoritative validation error.
  }
}

async function requestGcpCatalog(zone?: string): Promise<GCPCatalogResponse> {
  const { data } = await apiClient.post<GCPCatalogResponse>('/assets/gcp/query-catalog', {
    service_account_json: gcpForm.value.service_account_json,
    project_id: gcpForm.value.project_id.trim() || undefined,
    zone: zone || undefined,
    image_project: 'ubuntu-os-cloud',
  })
  return data
}

function applyGcpCatalog(data: GCPCatalogResponse) {
  gcpCatalog.value = data
  const machineTypes = data.machine_types
    .map(item => String(item.name ?? ''))
    .filter(Boolean)
  if (!machineTypes.includes(gcpForm.value.machine_type)) {
    gcpForm.value.machine_type = machineTypes[0] ?? ''
  }
  if (!gcpForm.value.source_image && gcpImages.value[0]) {
    gcpForm.value.source_image = String(gcpImages.value[0].value)
  }
  const networks = data.networks
    .map(item => String(item.name ?? ''))
    .filter(Boolean)
  if (!networks.includes(gcpForm.value.network)) {
    gcpForm.value.network = networks[0] ?? ''
  }
  const subnetworks = gcpSubnetworks.value.map(option => String(option.value))
  if (!subnetworks.includes(gcpForm.value.subnetwork)) {
    gcpForm.value.subnetwork = ''
  }
  const selectedMachine = data.machine_types.find(
    item => item.name === gcpForm.value.machine_type
  )
  if (selectedMachine?.guestCpus) {
    gcpForm.value.default_vcpu = selectedMachine.guestCpus
  }
}

async function queryGcpCatalog() {
  if (!gcpForm.value.service_account_json.trim()) {
    message.warning('请填写服务账号 JSON')
    return
  }
  applyProjectIdFromServiceAccount()
  queryingGcpCatalog.value = true
  gcpCatalogError.value = null
  try {
    let data = await requestGcpCatalog(gcpForm.value.zone || undefined)
    if (!gcpForm.value.zone && data.zones[0]?.name) {
      gcpForm.value.zone = String(data.zones[0].name)
      data = await requestGcpCatalog(gcpForm.value.zone)
    }
    applyGcpCatalog(data)
    message.success('GCP 服务账号验证成功，资源目录已加载')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    gcpCatalogError.value = e.response?.data?.detail || 'GCP 资源目录查询失败'
    message.error(gcpCatalogError.value)
  } finally {
    queryingGcpCatalog.value = false
  }
}

async function handleGcpZoneChange(value: string | null) {
  gcpForm.value.zone = String(value ?? '')
  gcpForm.value.subnetwork = ''
  if (!gcpForm.value.zone || !gcpForm.value.service_account_json.trim()) return
  queryingGcpCatalog.value = true
  gcpCatalogError.value = null
  try {
    applyGcpCatalog(await requestGcpCatalog(gcpForm.value.zone))
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    gcpCatalogError.value = e.response?.data?.detail || 'GCP Zone 资源加载失败'
    message.error(gcpCatalogError.value)
  } finally {
    queryingGcpCatalog.value = false
  }
}

watch(() => gcpForm.value.machine_type, machineType => {
  const selected = gcpCatalog.value?.machine_types.find(item => item.name === machineType)
  if (selected?.guestCpus) gcpForm.value.default_vcpu = selected.guestCpus
})

watch(() => gcpForm.value.network, () => {
  const subnetworks = gcpSubnetworks.value.map(option => String(option.value))
  if (!subnetworks.includes(gcpForm.value.subnetwork)) {
    gcpForm.value.subnetwork = ''
  }
})

async function submitGcpForm() {
  applyProjectIdFromServiceAccount()
  const required: Array<[string, string]> = [
    ['资产名称', gcpForm.value.asset_name],
    ['Project ID', gcpForm.value.project_id],
    ['服务账号 JSON', gcpForm.value.service_account_json],
    ['Zone', gcpForm.value.zone],
    ['Machine Type', gcpForm.value.machine_type],
    ['Source Image', gcpForm.value.source_image],
    ['Network', gcpForm.value.network],
    ['SSH 用户名', gcpForm.value.ssh_username],
    ['SSH 公钥', gcpForm.value.ssh_public_key],
  ]
  const missing = required.find(([, value]) => !value.trim())
  if (missing) {
    message.warning('请填写' + missing[0])
    return
  }
  submittingGcp.value = true
  try {
    const body: GCPAssetCreateRequest = {
      asset_name: gcpForm.value.asset_name.trim(),
      project_id: gcpForm.value.project_id.trim(),
      service_account_json: gcpForm.value.service_account_json.trim(),
      zone: gcpForm.value.zone.trim(),
      machine_type: gcpForm.value.machine_type.trim(),
      source_image: gcpForm.value.source_image.trim(),
      network: gcpForm.value.network.trim(),
      subnetwork: gcpForm.value.subnetwork.trim() || undefined,
      ssh_username: gcpForm.value.ssh_username.trim(),
      ssh_public_key: gcpForm.value.ssh_public_key.trim(),
      labels: splitList(gcpForm.value.labels_raw),
      remarks: gcpForm.value.remarks || undefined,
      protocol_type: gcpForm.value.protocol_types[0] ?? null,
      additional_protocol_types: gcpForm.value.protocol_types.slice(1),
      target_count: gcpForm.value.target_count,
      max_count: gcpForm.value.max_count,
      priority: gcpForm.value.priority,
      allow_cdn_proxy: gcpForm.value.allow_cdn_proxy,
      default_vcpu: gcpForm.value.default_vcpu ?? undefined,
    }
    await apiClient.post<AssetResponse>('/assets/gcp', body)
    message.success('Google Cloud 资产注册成功')
    closeModal()
    resetGcpForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string; message?: string } } }
    message.error(
      e.response?.data?.error ||
      e.response?.data?.detail ||
      e.response?.data?.message ||
      '注册失败'
    )
  } finally {
    submittingGcp.value = false
  }
}

// -- Oracle Cloud Infrastructure Registration Form --------------------------
const ociForm = ref({
  asset_name: '',
  region: 'ap-tokyo-1',
  tenancy_ocid: '',
  user_ocid: '',
  fingerprint: '',
  private_key: '',
  private_key_passphrase: '',
  compartment_ocid: '',
  subnet_ocid: '',
  network_security_group_ocid: '',
  image_ocid: '',
  shape: 'VM.Standard.E4.Flex',
  ssh_public_key: '',
  availability_domain: '',
  ocpus: 1 as number | null,
  memory_in_gbs: 6 as number | null,
  tags_raw: '',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  max_count: 0,
  priority: 100,
  allow_cdn_proxy: false,
})

const ociCatalog = ref<OCICatalogResponse | null>(null)
const queryingOciCatalog = ref(false)
const ociCatalogError = ref<string | null>(null)
const submittingOci = ref(false)
const ociAvailabilityDomains = computed<SelectOption[]>(() =>
  (ociCatalog.value?.availability_domains ?? [])
    .filter(item => item.name)
    .map(item => ({ label: item.name as string, value: item.name as string }))
)
const ociImages = computed<SelectOption[]>(() =>
  (ociCatalog.value?.images ?? [])
    .filter(item => item.id && item.lifecycleState !== 'DELETED')
    .map(item => ({
      label: `${item.displayName || item.id} · ${item.operatingSystem || ''} ${item.operatingSystemVersion || ''}`.trim(),
      value: item.id as string,
    }))
)
const ociShapes = computed<SelectOption[]>(() =>
  (ociCatalog.value?.shapes ?? [])
    .filter(item => item.shape)
    .map(item => ({
      label: `${item.shape} · ${item.ocpus ?? '?'} OCPU · ${item.memoryInGBs ?? '?'} GB`,
      value: item.shape as string,
    }))
)
const ociSelectedShape = computed(() =>
  (ociCatalog.value?.shapes ?? []).find(item => item.shape === ociForm.value.shape)
)
function applyOciShapeConfiguration(shape: string) {
  const selected = (ociCatalog.value?.shapes ?? []).find(item => item.shape === shape)
  if (!selected) return
  if (selected.isFlexible === false) {
    ociForm.value.ocpus = null
    ociForm.value.memory_in_gbs = null
    return
  }
  if (selected.isFlexible) {
    ociForm.value.ocpus = ociForm.value.ocpus ?? selected.ocpus ?? 1
    ociForm.value.memory_in_gbs = ociForm.value.memory_in_gbs ?? selected.memoryInGBs ?? 6
  }
}
watch(() => ociForm.value.shape, applyOciShapeConfiguration)
const ociSubnets = computed<SelectOption[]>(() =>
  (ociCatalog.value?.subnets ?? [])
    .filter(item => item.id)
    .map(item => ({
      label: `${item.displayName || item.id} · ${item.ipv6CidrBlock || item.ipv6CidrBlocks?.[0] || '未启用 IPv6'}`,
      value: item.id as string,
    }))
)
const ociNetworkSecurityGroups = computed<SelectOption[]>(() =>
  (ociCatalog.value?.network_security_groups ?? [])
    .filter(item => item.id)
    .map(item => ({ label: item.displayName || item.id, value: item.id as string }))
)

function resetOciForm() {
  ociForm.value = {
    asset_name: '', region: 'ap-tokyo-1', tenancy_ocid: '', user_ocid: '',
    fingerprint: '', private_key: '', private_key_passphrase: '', compartment_ocid: '',
    subnet_ocid: '', network_security_group_ocid: '', image_ocid: '',
    shape: 'VM.Standard.E4.Flex', ssh_public_key: '', availability_domain: '',
    ocpus: 1, memory_in_gbs: 6, tags_raw: '', remarks: '',
    protocol_types: ['AnyTLS'], target_count: 1, max_count: 0, priority: 100,
    allow_cdn_proxy: false,
  }
  ociCatalog.value = null
  ociCatalogError.value = null
}

function ociCatalogCredentialsComplete(): boolean {
  return [
    ociForm.value.region,
    ociForm.value.tenancy_ocid,
    ociForm.value.user_ocid,
    ociForm.value.fingerprint,
    ociForm.value.private_key,
    ociForm.value.compartment_ocid,
  ].every(value => value.trim())
}

async function queryOciCatalog() {
  if (!ociCatalogCredentialsComplete()) {
    message.warning('请填写 Region、Tenancy/User OCID、Fingerprint、PEM 私钥和 Compartment OCID')
    return
  }
  queryingOciCatalog.value = true
  ociCatalogError.value = null
  try {
    const { data } = await apiClient.post<OCICatalogResponse>('/assets/oci/query-catalog', {
      region: ociForm.value.region.trim(),
      tenancy_ocid: ociForm.value.tenancy_ocid.trim(),
      user_ocid: ociForm.value.user_ocid.trim(),
      fingerprint: ociForm.value.fingerprint.trim(),
      private_key: ociForm.value.private_key.trim(),
      private_key_passphrase: ociForm.value.private_key_passphrase || undefined,
      compartment_ocid: ociForm.value.compartment_ocid.trim(),
      availability_domain: ociForm.value.availability_domain || undefined,
      operating_system: 'Canonical Ubuntu',
    })
    ociCatalog.value = data
    applyOciShapeConfiguration(ociForm.value.shape)
    if (!ociForm.value.availability_domain && ociAvailabilityDomains.value[0]) {
      ociForm.value.availability_domain = String(ociAvailabilityDomains.value[0].value)
    }
    message.success('OCI 凭据验证成功，资源目录已加载')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    ociCatalogError.value = e.response?.data?.detail || 'OCI 资源目录查询失败'
    message.error(ociCatalogError.value)
  } finally {
    queryingOciCatalog.value = false
  }
}

async function submitOciForm() {
  const required: Array<[string, string]> = [
    ['资产名称', ociForm.value.asset_name],
    ['Region', ociForm.value.region],
    ['Tenancy OCID', ociForm.value.tenancy_ocid],
    ['User OCID', ociForm.value.user_ocid],
    ['Fingerprint', ociForm.value.fingerprint],
    ['PEM 私钥', ociForm.value.private_key],
    ['Compartment OCID', ociForm.value.compartment_ocid],
    ['Subnet OCID', ociForm.value.subnet_ocid],
    ['NSG OCID', ociForm.value.network_security_group_ocid],
    ['Image OCID', ociForm.value.image_ocid],
    ['Shape', ociForm.value.shape],
    ['SSH 公钥', ociForm.value.ssh_public_key],
  ]
  const missing = required.find(([, value]) => !value.trim())
  if (missing) {
    message.warning(`请填写${missing[0]}`)
    return
  }

  submittingOci.value = true
  try {
    const body: OCIAssetCreateRequest = {
      asset_name: ociForm.value.asset_name.trim(),
      region: ociForm.value.region.trim(),
      tenancy_ocid: ociForm.value.tenancy_ocid.trim(),
      user_ocid: ociForm.value.user_ocid.trim(),
      fingerprint: ociForm.value.fingerprint.trim(),
      private_key: ociForm.value.private_key.trim(),
      private_key_passphrase: ociForm.value.private_key_passphrase || undefined,
      compartment_ocid: ociForm.value.compartment_ocid.trim(),
      subnet_ocid: ociForm.value.subnet_ocid.trim(),
      network_security_group_ocid: ociForm.value.network_security_group_ocid.trim(),
      image_ocid: ociForm.value.image_ocid.trim(),
      shape: ociForm.value.shape.trim(),
      ssh_public_key: ociForm.value.ssh_public_key.trim(),
      availability_domain: ociForm.value.availability_domain || undefined,
      ocpus: ociForm.value.ocpus ?? undefined,
      memory_in_gbs: ociForm.value.memory_in_gbs ?? undefined,
      tags: splitList(ociForm.value.tags_raw),
      remarks: ociForm.value.remarks || undefined,
      protocol_type: ociForm.value.protocol_types[0] ?? null,
      additional_protocol_types: ociForm.value.protocol_types.slice(1),
      target_count: ociForm.value.target_count,
      max_count: ociForm.value.max_count,
      priority: ociForm.value.priority,
      allow_cdn_proxy: ociForm.value.allow_cdn_proxy,
      default_vcpu: Math.max(1, Math.ceil(ociForm.value.ocpus ?? 1)),
    }
    await apiClient.post<AssetResponse>('/assets/oci', body)
    message.success('Oracle Cloud 资产注册成功')
    closeModal()
    resetOciForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string; message?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.detail || e.response?.data?.message || '注册失败')
  } finally {
    submittingOci.value = false
  }
}


// ── Self-Hosted Registration Form ──────────────────────────────────────────────
const selfForm = ref({
  asset_name: '',
  region: '',
  host: '',
  ssh_port: 22,
  ssh_username: 'root',
  ssh_password: '',
  ssh_private_key: '',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  max_count: 10,
  priority: 100,
  cpu_cores: null as number | null,
  memory_gb: null as number | null,
})

const selfProtocolOptions: SelectOption[] = [
  { label: 'AnyTLS',   value: 'AnyTLS' },
  { label: 'Trojan',   value: 'Trojan' },
  { label: 'vless',    value: 'vless' },
  { label: 'vmess',    value: 'vmess' },
  { label: 'Hysteria2', value: 'Hysteria2' },
]

const submittingSelf = ref(false)
const probingHw = ref(false)

function resetSelfForm() {
  selfForm.value = {
    asset_name: '', region: '', host: '', ssh_port: 22,
    ssh_username: 'root', ssh_password: '', ssh_private_key: '',
    remarks: '', protocol_types: ['AnyTLS'], target_count: 1,
    max_count: 10, priority: 100, cpu_cores: null, memory_gb: null,
  }
}

async function probeHardware() {
  if (!selfForm.value.host.trim()) {
    message.warning('请先填写主机地址再探测硬件')
    return
  }
  probingHw.value = true
  try {
    const { data } = await apiClient.post<{ cpu_cores: number; memory_gb: number }>(
      '/assets/self-hosted/probe-hardware',
      {
        host: selfForm.value.host,
        ssh_port: selfForm.value.ssh_port,
        ssh_username: selfForm.value.ssh_username,
        ssh_password: selfForm.value.ssh_password || undefined,
        ssh_private_key: selfForm.value.ssh_private_key || undefined,
      }
    )
    selfForm.value.cpu_cores = data.cpu_cores
    selfForm.value.memory_gb = data.memory_gb
    message.success('硬件探测成功')
  } catch {
    message.info('硬件探测需要通过 SSH 连接，请手动填写 CPU 核心数和内存大小')
  } finally {
    probingHw.value = false
  }
}

async function submitSelfForm() {
  if (!selfForm.value.asset_name.trim()) { message.warning('请填写资产名称'); return }
  if (!selfForm.value.region.trim())     { message.warning('请填写 Region');   return }
  if (!selfForm.value.host.trim())       { message.warning('请填写主机地址');   return }

  submittingSelf.value = true
  try {
    const body: SelfHostedAssetCreateRequest = {
      asset_name:      selfForm.value.asset_name.trim(),
      region:          selfForm.value.region.trim(),
      host:            selfForm.value.host.trim(),
      ssh_port:        selfForm.value.ssh_port,
      ssh_username:    selfForm.value.ssh_username || undefined,
      ssh_password:    selfForm.value.ssh_password || undefined,
      ssh_private_key: selfForm.value.ssh_private_key || undefined,
      remarks:        selfForm.value.remarks || undefined,
      protocol_type:   selfForm.value.protocol_types[0] ?? null,
      additional_protocol_types: selfForm.value.protocol_types.slice(1),
      target_count:   selfForm.value.target_count,
      max_count:      selfForm.value.max_count,
      priority:       selfForm.value.priority,
      cpu_cores:      selfForm.value.cpu_cores ?? undefined,
      memory_gb:      selfForm.value.memory_gb ?? undefined,
    }
    await apiClient.post<AssetResponse>('/assets/self-hosted', body)
    message.success('自建资产注册成功')
    closeModal()
    resetSelfForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string }; message?: string } }
    message.error(e.response?.data?.error || e.response?.data?.message || '注册失败')
  } finally {
    submittingSelf.value = false
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(fetchAssets)
</script>

<template>
  <div class="assets-page">
    <!-- ── Header ──────────────────────────────────────────────────────────── -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">账号与资产池</h1>
        <p class="page-subtitle">管理 AWS、DigitalOcean、Vultr、Google Cloud、Kamatera、Microsoft Azure、Oracle Cloud 与自建资产，统一调度节点配额与协议</p>
      </div>
      <div class="header-right">
        <NSpace>
          <NButton v-if="selectedAssetIds.length > 0" type="error" size="large" :loading="batchDeleting" @click="batchDeleteAssets">
            批量删除 ({{ selectedAssetIds.length }})
          </NButton>
          <NButton type="primary" size="large" @click="openModal('aws')">
            <template #icon>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor">
                <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
              </svg>
            </template>
            新增资产
          </NButton>
        </NSpace>
      </div>
    </div>

    <!-- ── Summary Stats ──────────────────────────────────────────────────── -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ assets.length }}</div>
        <div class="stat-label">全部资产</div>
      </div>
      <div class="stat-card stat-aws">
        <div class="stat-value">{{ awsAssets.length }}</div>
        <div class="stat-label">AWS 资产</div>
      </div>
      <div class="stat-card stat-do">
        <div class="stat-value">{{ digitalOceanAssets.length }}</div>
        <div class="stat-label">DO 资产</div>
      </div>
      <div class="stat-card stat-vultr">
        <div class="stat-value">{{ vultrAssets.length }}</div>
        <div class="stat-label">Vultr 资产</div>
      </div>
      <div class="stat-card stat-gcp">
        <div class="stat-value">{{ gcpAssets.length }}</div>
        <div class="stat-label">GCP 资产</div>
      </div>
      <div class="stat-card stat-kamatera">
        <div class="stat-value">{{ kamateraAssets.length }}</div>
        <div class="stat-label">Kamatera 资产</div>
      </div>
      <div class="stat-card stat-azure">
        <div class="stat-value">{{ azureAssets.length }}</div>
        <div class="stat-label">Azure 资产</div>
      </div>
      <div class="stat-card stat-oci">
        <div class="stat-value">{{ ociAssets.length }}</div>
        <div class="stat-label">OCI 资产</div>
      </div>
      <div class="stat-card stat-self">
        <div class="stat-value">{{ selfAssets.length }}</div>
        <div class="stat-label">自建资产</div>
      </div>
      <div class="stat-card stat-active">
        <div class="stat-value">{{ assets.filter(a => a.status === 'active').length }}</div>
        <div class="stat-label">在线</div>
      </div>
      <div class="stat-card stat-full">
        <div class="stat-value">{{ assets.filter(a => a.status === 'full').length }}</div>
        <div class="stat-label">配额满</div>
      </div>
    </div>

    <!-- ── Asset Table ─────────────────────────────────────────────────────── -->
    <div class="table-card">
      <NSpin :show="loading" description="加载资产列表…">
        <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px"
          closable @close="errorMsg = null" />

        <!-- ── Filter Tabs ────────────────────────────────────────────────── -->
        <div class="tab-bar">
          <button
            class="tab-btn"
            :class="{ active: activeAssetFilter === 'all' }"
            @click="activeAssetFilter = 'all'"
          >
            全部
            <span class="tab-badge">{{ assets.length }}</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeAssetFilter === 'aws' }"
            @click="activeAssetFilter = 'aws'"
          >
            AWS
            <span class="tab-badge tab-badge-aws">{{ awsAssets.length }}</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeAssetFilter === 'digitalocean' }"
            @click="activeAssetFilter = 'digitalocean'"
          >
            DigitalOcean
            <span class="tab-badge tab-badge-do">{{ digitalOceanAssets.length }}</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeAssetFilter === 'vultr' }"
            @click="activeAssetFilter = 'vultr'"
          >
            Vultr
            <span class="tab-badge tab-badge-vultr">{{ vultrAssets.length }}</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeAssetFilter === 'gcp' }"
            @click="activeAssetFilter = 'gcp'"
          >
            GCP
            <span class="tab-badge tab-badge-gcp">{{ gcpAssets.length }}</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeAssetFilter === 'kamatera' }"
            @click="activeAssetFilter = 'kamatera'"
          >
            Kamatera
            <span class="tab-badge tab-badge-kamatera">{{ kamateraAssets.length }}</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeAssetFilter === 'azure' }"
            @click="activeAssetFilter = 'azure'"
          >
            Azure
            <span class="tab-badge tab-badge-azure">{{ azureAssets.length }}</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeAssetFilter === 'oci' }"
            @click="activeAssetFilter = 'oci'"
          >
            OCI
            <span class="tab-badge tab-badge-oci">{{ ociAssets.length }}</span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeAssetFilter === 'self_hosted' }"
            @click="activeAssetFilter = 'self_hosted'"
          >
            自建
            <span class="tab-badge tab-badge-self">{{ selfAssets.length }}</span>
          </button>
        </div>

        <!-- ── Data Table ──────────────────────────────────────────────────── -->
        <NDataTable
          :columns="allColumns"
          :data="filteredAssets"
          :bordered="false"
          :single-line="false"
          size="small"
          :pagination="{ pageSize: 15 }"
          :row-key="(row: AssetResponse) => row.asset_id"
          v-model:checked-row-keys="selectedAssetIds"
          class="assets-table"
        />
      </NSpin>
    </div>

    <!-- ── Add Asset Modal ─────────────────────────────────────────────────── -->
    <NModal
      v-model:show="showModal"
      preset="card"
      class="asset-modal"
      :style="{ width: '860px', maxWidth: '95vw' }"
      :title="modalTitle(modalTab)"
      :mask-closable="false"
      :segmented="{ content: true, footer: 'soft' }"
    >
      <NTabs v-model:value="modalTab" type="line" animated>
        <!-- ── AWS Tab ───────────────────────────────────────────────────── -->
        <NTabPane name="aws" tab="AWS 资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="140" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="awsForm.asset_name" placeholder="my-aws-asset-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Region" required>
                    <NSelect v-model:value="awsForm.region" :options="awsRegions" placeholder="选择 Region" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="账户总 vCPU">
                    <NInputNumber v-model:value="awsForm.account_total_vcpu" :min="1" :max="256" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="AWS Account ID">
                    <NSpace vertical>
                      <NSpace>
                        <NInput v-model:value="awsForm.aws_account_id" placeholder="12 位数字或别名" style="width: 200px" />
                        <NButton
                          :loading="fetchingAccountId"
                          :disabled="!awsForm.aws_access_key || !awsForm.aws_secret_key"
                          @click="fetchAccountId"
                        >
                          自动获取
                        </NButton>
                      </NSpace>
                      <NText depth="3" style="font-size: 12px">
                        填写 Access Key 和 Secret Key 后点击自动获取
                      </NText>
                    </NSpace>
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="AWS Access Key" required>
                    <NInput v-model:value="awsForm.aws_access_key" placeholder="AKIA..." />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="AWS Secret Key" required>
                    <NInput v-model:value="awsForm.aws_secret_key" type="password" placeholder="Secret Key" show-password-on="click" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="备注">
                    <NInput v-model:value="awsForm.remarks" type="textarea" placeholder="可选备注信息" :rows="2" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>AMI 配置（可选）</NDivider>
              <NGrid :cols="1" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="AMI ID">
                    <NSpace vertical>
                      <NSpace>
                        <NInput v-model:value="awsForm.ami_id" placeholder="ami-xxxxxxxx 或留空" style="width: 300px" />
                        <NButton :loading="queryingAmi" @click="queryAmi" :disabled="!awsForm.aws_access_key || !awsForm.aws_secret_key">
                          自动获取 Debian ARM64 AMI
                        </NButton>
                      </NSpace>
                      <NSpin v-if="queryingAmi" description="正在查询 AWS..." />
                      <NAlert v-if="amiError" type="error" :title="amiError" style="margin-top: 4px" closable @close="amiError = null" />
                      <NAlert v-if="amiResults.length > 0" type="info" title="查询到以下 AMI，点击选择" style="margin-top: 4px">
                        <NSpace vertical>
                          <div v-for="ami in amiResults" :key="ami.ami_id" style="cursor: pointer; padding: 4px 0; border-bottom: 1px solid #eee" @click="selectAmi(ami)">
                            <NText strong style="font-size: 12px">{{ ami.name }}</NText>
                            <NText depth="3" style="font-size: 11px; margin-left: 8px">{{ ami.ami_id }}</NText>
                            <NText depth="3" style="font-size: 11px; display: block">{{ ami.description || '' }}</NText>
                          </div>
                        </NSpace>
                      </NAlert>
                    </NSpace>
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="协议类型">
                    <NCheckboxGroup v-model:value="awsForm.protocol_types">
                      <NSpace>
                        <NCheckbox v-for="opt in awsProtocolOptions" :key="String(opt.value)" :value="opt.value" :label="String(opt.label)" />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="awsForm.target_count" :min="1" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="优先级">
                    <NInputNumber v-model:value="awsForm.priority" :min="1" :max="1000" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="允许 CDN Proxy">
                    <NSwitch v-model:value="awsForm.allow_cdn_proxy" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <!-- Network / Security Group expand -->
              <NCollapse>
                <NCollapseItem title="网络与安全组配置（可选）" name="net">
                  <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                    <NGi span="2">
                      <NFormItem label="自动创建安全组">
                        <NSwitch v-model:value="awsForm.auto_create_sg" />
                      </NFormItem>
                    </NGi>
                    <NGi span="1">
                      <NFormItem label="VPC ID">
                        <NInput v-model:value="awsForm.vpc_id" placeholder="vpc-xxxxxxxx" />
                      </NFormItem>
                    </NGi>
                    <NGi span="1">
                      <NFormItem label="安全组名称">
                        <NInput v-model:value="awsForm.sg_name" placeholder="shadowfleet-sg" />
                      </NFormItem>
                    </NGi>
                    <NGi span="2">
                      <NFormItem label="计算端口">
                        <NText depth="3" style="font-size: 13px">{{ sgPortsHint }}</NText>
                      </NFormItem>
                    </NGi>
                  </NGrid>
                </NCollapseItem>
              </NCollapse>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton type="primary" :loading="submittingAws" @click="submitAwsForm">
                  注册 AWS 资产
                </NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>

        <!-- ── DigitalOcean Tab ───────────────────────────────────────────── -->
        <NTabPane name="digitalocean" tab="DigitalOcean 资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="140" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="digitalOceanForm.asset_name" placeholder="my-do-sgp1-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Region" required>
                    <NSelect v-model:value="digitalOceanForm.region" :options="digitalOceanRegions" placeholder="选择 Region" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="DO Token" required>
                    <NInput
                      v-model:value="digitalOceanForm.digitalocean_token"
                      type="password"
                      placeholder="dop_v1_..."
                      show-password-on="click"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="备注">
                    <NInput v-model:value="digitalOceanForm.remarks" type="textarea" placeholder="可选备注信息" :rows="2" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>Droplet 配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="Size" required>
                    <NSpace vertical>
                      <NSpace>
                        <NInput v-model:value="digitalOceanForm.default_size" placeholder="s-2vcpu-2gb" style="width: 220px" />
                        <NButton :loading="queryingDigitalOceanSizes" @click="queryDigitalOceanSizes" :disabled="!digitalOceanForm.digitalocean_token">
                          查询规格
                        </NButton>
                      </NSpace>
                      <NAlert
                        v-if="digitalOceanSizeResults.length > 0"
                        type="info"
                        title="可用规格"
                        style="margin-top: 4px"
                      >
                        <NSpace vertical>
                          <div
                            v-for="size in digitalOceanSizeResults"
                            :key="String(size.slug)"
                            class="choice-row"
                            @click="selectDigitalOceanSize(size)"
                          >
                            <NText strong style="font-size: 12px">{{ size.slug }}</NText>
                            <NText depth="3" style="font-size: 11px; margin-left: 8px">
                              {{ size.vcpus ?? '—' }} vCPU / {{ size.memory ?? '—' }} MB / ${{ size.price_monthly ?? '—' }}
                            </NText>
                          </div>
                        </NSpace>
                      </NAlert>
                    </NSpace>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="默认 vCPU">
                    <NInputNumber v-model:value="digitalOceanForm.default_vcpu" :min="1" :max="256" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="Image Slug" required>
                    <NSpace vertical>
                      <NSpace>
                        <NInput v-model:value="digitalOceanForm.default_image" placeholder="ubuntu-24-04-x64" style="width: 300px" />
                        <NButton :loading="queryingDigitalOceanImages" @click="queryDigitalOceanImages" :disabled="!digitalOceanForm.digitalocean_token">
                          查询镜像
                        </NButton>
                      </NSpace>
                      <NAlert
                        v-if="digitalOceanCatalogError"
                        type="error"
                        :title="digitalOceanCatalogError"
                        style="margin-top: 4px"
                        closable
                        @close="digitalOceanCatalogError = null"
                      />
                      <NAlert
                        v-if="digitalOceanImageResults.length > 0"
                        type="info"
                        title="可用镜像"
                        style="margin-top: 4px"
                      >
                        <NSpace vertical>
                          <div
                            v-for="image in digitalOceanImageResults"
                            :key="String(image.slug || image.id)"
                            class="choice-row"
                            @click="selectDigitalOceanImage(image)"
                          >
                            <NText strong style="font-size: 12px">{{ image.name || image.slug || image.id }}</NText>
                            <NText depth="3" style="font-size: 11px; margin-left: 8px">{{ image.slug || image.id }}</NText>
                            <NText depth="3" style="font-size: 11px; display: block">{{ image.distribution || '' }}</NText>
                          </div>
                        </NSpace>
                      </NAlert>
                    </NSpace>
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="协议类型">
                    <NCheckboxGroup v-model:value="digitalOceanForm.protocol_types">
                      <NSpace>
                        <NCheckbox v-for="opt in digitalOceanProtocolOptions" :key="String(opt.value)" :value="opt.value" :label="String(opt.label)" />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="digitalOceanForm.target_count" :min="1" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="最大节点数">
                    <NInputNumber v-model:value="digitalOceanForm.max_count" :min="0" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="优先级">
                    <NInputNumber v-model:value="digitalOceanForm.priority" :min="1" :max="1000" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="允许 CDN Proxy">
                    <NSwitch v-model:value="digitalOceanForm.allow_cdn_proxy" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NCollapse>
                <NCollapseItem title="网络与标签配置（可选）" name="do-network">
                  <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                    <NGi span="1">
                      <NFormItem label="VPC UUID">
                        <NInput v-model:value="digitalOceanForm.vpc_uuid" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
                      </NFormItem>
                    </NGi>
                    <NGi span="1">
                      <NFormItem label="Tags">
                        <NInput v-model:value="digitalOceanForm.tags_raw" placeholder="shadowfleet, prod" />
                      </NFormItem>
                    </NGi>
                    <NGi span="2">
                      <NFormItem label="SSH Keys">
                        <NInput
                          v-model:value="digitalOceanForm.ssh_keys_raw"
                          type="textarea"
                          placeholder="fingerprint 或 key id，逗号/换行分隔"
                          :rows="3"
                        />
                      </NFormItem>
                    </NGi>
                  </NGrid>
                </NCollapseItem>
              </NCollapse>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton type="primary" :loading="submittingDigitalOcean" @click="submitDigitalOceanForm">
                  注册 DigitalOcean 资产
                </NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>

        <!-- ── Vultr Tab ────────────────────────────────────────────────── -->
        <NTabPane name="vultr" tab="Vultr 资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="140" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="vultrForm.asset_name" placeholder="my-vultr-sgp-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Region" required>
                    <NSelect v-model:value="vultrForm.region" :options="vultrRegions" placeholder="选择 Region" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="Vultr API Token" required>
                    <NSpace vertical style="width: 100%">
                      <NSpace>
                        <NInput v-model:value="vultrForm.vultr_token" type="password" placeholder="Vultr API Token" show-password-on="click" style="width: 420px" />
                        <NButton :loading="queryingVultrCatalog" @click="queryVultrCatalog">加载资源</NButton>
                      </NSpace>
                      <NAlert v-if="vultrCatalogError" type="error" :title="vultrCatalogError" closable @close="vultrCatalogError = null" />
                    </NSpace>
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="备注">
                    <NInput v-model:value="vultrForm.remarks" type="textarea" placeholder="可选备注信息" :rows="2" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>实例配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="Plan" required>
                    <NSelect v-model:value="vultrForm.default_plan" :options="vultrPlans" filterable tag placeholder="选择或输入 Plan" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="默认 vCPU">
                    <NInputNumber v-model:value="vultrForm.default_vcpu" :min="1" :max="256" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="OS ID" required>
                    <NSelect v-model:value="vultrForm.default_os_id" :options="vultrOperatingSystems" filterable placeholder="选择 OS" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="允许 CDN Proxy">
                    <NSwitch v-model:value="vultrForm.allow_cdn_proxy" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="协议类型">
                    <NCheckboxGroup v-model:value="vultrForm.protocol_types">
                      <NSpace>
                        <NCheckbox v-for="opt in vultrProtocolOptions" :key="String(opt.value)" :value="opt.value" :label="String(opt.label)" />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="vultrForm.target_count" :min="1" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="最大节点数">
                    <NInputNumber v-model:value="vultrForm.max_count" :min="0" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="优先级">
                    <NInputNumber v-model:value="vultrForm.priority" :min="1" :max="1000" style="width: 100%" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NCollapse>
                <NCollapseItem title="网络、SSH Key 与标签（可选）" name="vultr-network">
                  <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                    <NGi span="1">
                      <NFormItem label="VPCs">
                        <NSelect v-model:value="vultrForm.vpc_ids" :options="vultrVpcs" multiple filterable tag clearable placeholder="选择或输入 VPC IDs" />
                      </NFormItem>
                    </NGi>
                    <NGi span="1">
                      <NFormItem label="Firewall Group ID">
                        <NSelect v-model:value="vultrForm.firewall_group_id" :options="vultrFirewallGroups" filterable tag clearable placeholder="选择或输入 Firewall Group" />
                      </NFormItem>
                    </NGi>
                    <NGi span="1">
                      <NFormItem label="Tags">
                        <NInput v-model:value="vultrForm.tags_raw" placeholder="shadowfleet, prod" />
                      </NFormItem>
                    </NGi>
                    <NGi span="2">
                      <NFormItem label="SSH Key IDs">
                        <NSelect v-model:value="vultrForm.ssh_key_ids" :options="vultrSshKeys" multiple filterable tag clearable placeholder="选择 SSH Keys" />
                      </NFormItem>
                    </NGi>
                  </NGrid>
                </NCollapseItem>
              </NCollapse>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton type="primary" :loading="submittingVultr" @click="submitVultrForm">注册 Vultr 资产</NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>

        <!-- ── Kamatera Tab ──────────────────────────────────────────────── -->
        <NTabPane name="kamatera" tab="Kamatera 资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="140" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="kamateraForm.asset_name" placeholder="my-kamatera-as-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Datacenter" required>
                    <NSelect
                      v-model:value="kamateraForm.datacenter"
                      :options="kamateraDatacenters"
                      :disabled="queryingKamateraCatalog"
                      filterable
                      tag
                      placeholder="选择或输入 Datacenter"
                      @update:value="handleKamateraDatacenterChange"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Client ID" required>
                    <NInput v-model:value="kamateraForm.client_id" placeholder="Kamatera API Client ID" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Secret" required>
                    <NInput v-model:value="kamateraForm.secret" type="password" show-password-on="click" placeholder="Kamatera API Secret" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="验证凭据">
                    <NSpace vertical style="width: 100%">
                      <NButton :loading="queryingKamateraCatalog" @click="queryKamateraCatalog">验证凭据并加载资源</NButton>
                      <NAlert v-if="kamateraCatalogError" type="error" :title="kamateraCatalogError" closable @close="kamateraCatalogError = null" />
                    </NSpace>
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="Image" required>
                    <NSelect v-model:value="kamateraForm.image" :options="kamateraImages" filterable tag placeholder="验证凭据后选择或输入 Image ID" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="CPU 类型">
                    <NSelect v-model:value="kamateraForm.cpu_type" :options="kamateraCpuTypes" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="CPU 核数">
                    <NSelect
                      v-if="kamateraCpuCoreOptions.length"
                      v-model:value="kamateraForm.cpu_cores"
                      :options="kamateraCpuCoreOptions"
                    />
                    <NInputNumber v-else v-model:value="kamateraForm.cpu_cores" :min="1" :max="104" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="内存 (MB)">
                    <NSelect
                      v-if="kamateraRamOptions.length"
                      v-model:value="kamateraForm.ram_mb"
                      :options="kamateraRamOptions"
                      filterable
                    />
                    <NInputNumber v-else v-model:value="kamateraForm.ram_mb" :min="256" :step="256" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="系统盘 (GB)">
                    <NSelect
                      v-if="kamateraDiskOptions.length"
                      v-model:value="kamateraForm.disk_size_gb"
                      :options="kamateraDiskOptions"
                      filterable
                    />
                    <NInputNumber v-else v-model:value="kamateraForm.disk_size_gb" :min="10" :max="4000" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="SSH 公钥" required>
                    <NInput v-model:value="kamateraForm.ssh_public_key" type="textarea" :rows="3" placeholder="ssh-ed25519 AAAA..." />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="计费周期">
                    <NSelect v-model:value="kamateraForm.billing_cycle" :options="kamateraBillingCycles" />
                  </NFormItem>
                </NGi>
                <NGi span="1" v-if="kamateraForm.billing_cycle === 'monthly'">
                  <NFormItem label="Monthly Package" required>
                    <NSelect
                      v-if="kamateraMonthlyPackageOptions.length"
                      v-model:value="kamateraForm.monthly_package"
                      :options="kamateraMonthlyPackageOptions"
                      filterable
                    />
                    <NInput v-else v-model:value="kamateraForm.monthly_package" placeholder="t5000" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="每日备份">
                    <NSwitch v-model:value="kamateraForm.daily_backup" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Managed 服务">
                    <NSwitch v-model:value="kamateraForm.managed" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="协议类型">
                    <NCheckboxGroup v-model:value="kamateraForm.protocol_types">
                      <NSpace>
                        <NCheckbox v-for="opt in kamateraProtocolOptions" :key="String(opt.value)" :value="opt.value" :label="String(opt.label)" />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="kamateraForm.target_count" :min="0" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="最大节点数">
                    <NInputNumber v-model:value="kamateraForm.max_count" :min="0" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="优先级">
                    <NInputNumber v-model:value="kamateraForm.priority" :min="1" :max="1000" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="允许 CDN Proxy">
                    <NSwitch v-model:value="kamateraForm.allow_cdn_proxy" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Tags">
                    <NInput v-model:value="kamateraForm.tags_raw" placeholder="shadowfleet, prod" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="备注">
                    <NInput v-model:value="kamateraForm.remarks" type="textarea" :rows="2" />
                  </NFormItem>
                </NGi>
              </NGrid>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton type="primary" :loading="submittingKamatera" @click="submitKamateraForm">注册 Kamatera 资产</NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>

        <!-- ── Microsoft Azure Tab ───────────────────────────────────────── -->
        <NTabPane name="azure" tab="Microsoft Azure 资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="140" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="azureForm.asset_name" placeholder="my-azure-jp-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Region" required>
                    <NSelect v-model:value="azureForm.region" :options="azureLocations" filterable tag placeholder="选择或输入 Azure 区域" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Tenant ID" required>
                    <NInput v-model:value="azureForm.tenant_id" placeholder="Directory (tenant) ID" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Subscription ID" required>
                    <NInput v-model:value="azureForm.subscription_id" placeholder="Subscription ID" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Client ID" required>
                    <NInput v-model:value="azureForm.client_id" placeholder="Application (client) ID" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Client Secret" required>
                    <NInput v-model:value="azureForm.client_secret" type="password" show-password-on="click" placeholder="Client secret value" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="验证 Azure">
                    <NSpace vertical style="width: 100%">
                      <NButton :loading="queryingAzureCatalog" @click="queryAzureCatalog">验证订阅并加载资源</NButton>
                      <NAlert v-if="azureCatalogError" type="error" :title="azureCatalogError" closable @close="azureCatalogError = null" />
                    </NSpace>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Resource Group" required>
                    <NInput v-model:value="azureForm.resource_group" placeholder="shadowfleet" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="管理员用户名" required>
                    <NInput v-model:value="azureForm.admin_username" placeholder="azureuser" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="SSH 公钥" required>
                    <NInput v-model:value="azureForm.ssh_public_key" type="textarea" :rows="3" placeholder="ssh-ed25519 AAAA..." />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>虚拟机配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="VM Size" required>
                    <NSelect v-model:value="azureForm.default_vm_size" :options="azureVmSizes" filterable tag placeholder="选择或输入 VM Size" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="默认 vCPU">
                    <NInputNumber v-model:value="azureForm.default_vcpu" :min="1" :max="256" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Image Publisher">
                    <NInput v-model:value="azureForm.image_publisher" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Image Offer">
                    <NInput v-model:value="azureForm.image_offer" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Image SKU">
                    <NInput v-model:value="azureForm.image_sku" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Image Version">
                    <NInput v-model:value="azureForm.image_version" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="VNet">
                    <NInput v-model:value="azureForm.vnet_name" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Subnet">
                    <NInput v-model:value="azureForm.subnet_name" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="允许 CDN Proxy">
                    <NSwitch v-model:value="azureForm.allow_cdn_proxy" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="协议类型">
                    <NCheckboxGroup v-model:value="azureForm.protocol_types">
                      <NSpace>
                        <NCheckbox v-for="opt in awsProtocolOptions" :key="String(opt.value)" :value="opt.value" :label="String(opt.label)" />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="azureForm.target_count" :min="0" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="最大节点数">
                    <NInputNumber v-model:value="azureForm.max_count" :min="0" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="优先级">
                    <NInputNumber v-model:value="azureForm.priority" :min="1" :max="1000" style="width: 100%" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NCollapse>
                <NCollapseItem title="标签与备注（可选）" name="azure-metadata">
                  <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                    <NGi span="1">
                      <NFormItem label="Tags">
                        <NInput v-model:value="azureForm.tags_raw" placeholder="shadowfleet, prod" />
                      </NFormItem>
                    </NGi>
                    <NGi span="2">
                      <NFormItem label="备注">
                        <NInput v-model:value="azureForm.remarks" type="textarea" :rows="2" placeholder="可选备注信息" />
                      </NFormItem>
                    </NGi>
                  </NGrid>
                </NCollapseItem>
              </NCollapse>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton type="primary" :loading="submittingAzure" @click="submitAzureForm">注册 Microsoft Azure 资产</NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>
        <!-- Google Cloud Platform Tab -->
        <NTabPane name="gcp" tab="Google Cloud 资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="150" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="gcpForm.asset_name" placeholder="my-gcp-tokyo-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Project ID" required>
                    <NInput v-model:value="gcpForm.project_id" placeholder="my-gcp-project" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="服务账号 JSON" required>
                    <NSpace vertical style="width: 100%">
                      <NInput
                        v-model:value="gcpForm.service_account_json"
                        type="textarea"
                        :autosize="{ minRows: 5, maxRows: 10 }"
                        placeholder='{"type":"service_account","project_id":"..."}'
                        style="font-family: monospace; font-size: 12px"
                        @blur="applyProjectIdFromServiceAccount"
                      />
                      <NButton
                        :loading="queryingGcpCatalog"
                        :disabled="!gcpForm.service_account_json.trim()"
                        @click="queryGcpCatalog"
                      >
                        验证凭据并加载资源
                      </NButton>
                      <NAlert
                        v-if="gcpCatalogError"
                        type="error"
                        :title="gcpCatalogError"
                        closable
                        @close="gcpCatalogError = null"
                      />
                    </NSpace>
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>Compute Engine 配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="Zone" required>
                    <NSelect
                      v-model:value="gcpForm.zone"
                      :options="gcpZones"
                      @update:value="handleGcpZoneChange"
                      filterable
                      tag
                      placeholder="asia-northeast1-a"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Machine Type" required>
                    <NSelect
                      v-model:value="gcpForm.machine_type"
                      :options="gcpMachineTypes"
                      filterable
                      tag
                      placeholder="e2-small"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="默认 vCPU">
                    <NInputNumber
                      v-model:value="gcpForm.default_vcpu"
                      :min="1"
                      :max="416"
                      style="width: 100%"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="SSH 用户名" required>
                    <NInput v-model:value="gcpForm.ssh_username" placeholder="ubuntu" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="Source Image" required>
                    <NSelect
                      v-model:value="gcpForm.source_image"
                      :options="gcpImages"
                      filterable
                      tag
                      placeholder="Ubuntu 24.04 LTS"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Network" required>
                    <NSelect
                      v-model:value="gcpForm.network"
                      :options="gcpNetworks"
                      filterable
                      tag
                      placeholder="default"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Subnetwork">
                    <NSelect
                      v-model:value="gcpForm.subnetwork"
                      :options="gcpSubnetworks"
                      filterable
                      tag
                      clearable
                      placeholder="自动网络可留空"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="SSH 公钥" required>
                    <NInput
                      v-model:value="gcpForm.ssh_public_key"
                      type="textarea"
                      :rows="3"
                      placeholder="ssh-ed25519 AAAA..."
                    />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="协议类型">
                    <NCheckboxGroup v-model:value="gcpForm.protocol_types">
                      <NSpace>
                        <NCheckbox
                          v-for="opt in awsProtocolOptions"
                          :key="String(opt.value)"
                          :value="opt.value"
                          :label="String(opt.label)"
                        />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="gcpForm.target_count" :min="0" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="最大节点数">
                    <NInputNumber v-model:value="gcpForm.max_count" :min="0" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="优先级">
                    <NInputNumber v-model:value="gcpForm.priority" :min="1" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="允许 CDN Proxy">
                    <NSwitch v-model:value="gcpForm.allow_cdn_proxy" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NCollapse>
                <NCollapseItem title="标签与备注（可选）" name="gcp-metadata">
                  <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                    <NGi span="1">
                      <NFormItem label="Labels">
                        <NInput
                          v-model:value="gcpForm.labels_raw"
                          placeholder="environment=production, owner=platform"
                        />
                      </NFormItem>
                    </NGi>
                    <NGi span="2">
                      <NFormItem label="备注">
                        <NInput v-model:value="gcpForm.remarks" type="textarea" :rows="2" />
                      </NFormItem>
                    </NGi>
                  </NGrid>
                </NCollapseItem>
              </NCollapse>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton
                  type="primary"
                  :loading="submittingGcp"
                  @click="submitGcpForm"
                >
                  注册 Google Cloud 资产
                </NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>

        <!-- Oracle Cloud Infrastructure Tab -->
        <NTabPane name="oci" tab="Oracle Cloud 资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="150" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="ociForm.asset_name" placeholder="my-oci-asset-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Region" required>
                    <NInput v-model:value="ociForm.region" placeholder="ap-tokyo-1" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="Tenancy OCID" required>
                    <NInput v-model:value="ociForm.tenancy_ocid" placeholder="ocid1.tenancy.oc1..." />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="User OCID" required>
                    <NInput v-model:value="ociForm.user_ocid" placeholder="ocid1.user.oc1..." />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Fingerprint" required>
                    <NInput v-model:value="ociForm.fingerprint" placeholder="aa:bb:cc:..." />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="私钥密码">
                    <NInput v-model:value="ociForm.private_key_passphrase" type="password" show-password-on="click" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="PEM 私钥" required>
                    <NInput
                      v-model:value="ociForm.private_key"
                      type="textarea"
                      :autosize="{ minRows: 4, maxRows: 8 }"
                      placeholder="-----BEGIN PRIVATE KEY-----"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="Compartment OCID" required>
                    <NSpace vertical style="width: 100%">
                      <NInput v-model:value="ociForm.compartment_ocid" placeholder="ocid1.compartment.oc1..." />
                      <NButton
                        :loading="queryingOciCatalog"
                        :disabled="!ociCatalogCredentialsComplete()"
                        @click="queryOciCatalog"
                      >
                        验证凭据并查询资源
                      </NButton>
                      <NAlert
                        v-if="ociCatalogError"
                        type="error"
                        :title="ociCatalogError"
                        closable
                        @close="ociCatalogError = null"
                      />
                    </NSpace>
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>计算与网络</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="Availability Domain">
                    <NSelect
                      v-model:value="ociForm.availability_domain"
                      :options="ociAvailabilityDomains"
                      filterable
                      tag
                      clearable
                      placeholder="留空时自动选择第一个"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="Subnet OCID" required>
                    <NSelect v-model:value="ociForm.subnet_ocid" :options="ociSubnets" filterable tag />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="NSG OCID" required>
                    <NSelect
                      v-model:value="ociForm.network_security_group_ocid"
                      :options="ociNetworkSecurityGroups"
                      filterable
                      tag
                    />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="Image OCID" required>
                    <NSelect v-model:value="ociForm.image_ocid" :options="ociImages" filterable tag />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="Shape" required>
                    <NSelect v-model:value="ociForm.shape" :options="ociShapes" filterable tag />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="OCPU">
                    <NInputNumber v-model:value="ociForm.ocpus" :min="1" :step="1" :disabled="ociSelectedShape?.isFlexible === false" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="内存 (GB)">
                    <NInputNumber v-model:value="ociForm.memory_in_gbs" :min="1" :step="1" :disabled="ociSelectedShape?.isFlexible === false" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="SSH 公钥" required>
                    <NInput
                      v-model:value="ociForm.ssh_public_key"
                      type="textarea"
                      :autosize="{ minRows: 2, maxRows: 4 }"
                      placeholder="ssh-ed25519 AAAA..."
                    />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="支持协议">
                    <NCheckboxGroup v-model:value="ociForm.protocol_types">
                      <NSpace>
                        <NCheckbox v-for="opt in awsProtocolOptions" :key="String(opt.value)" :value="opt.value" :label="String(opt.label)" />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="ociForm.target_count" :min="0" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="最大节点数">
                    <NInputNumber v-model:value="ociForm.max_count" :min="0" style="width: 100%" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NCollapse>
                <NCollapseItem title="高级设置" name="oci-advanced">
                  <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                    <NGi span="1">
                      <NFormItem label="优先级">
                        <NInputNumber v-model:value="ociForm.priority" :min="1" style="width: 100%" />
                      </NFormItem>
                    </NGi>
                    <NGi span="1">
                      <NFormItem label="允许 CDN">
                        <NSwitch v-model:value="ociForm.allow_cdn_proxy" />
                      </NFormItem>
                    </NGi>
                    <NGi span="2">
                      <NFormItem label="Freeform Tags">
                        <NInput v-model:value="ociForm.tags_raw" type="textarea" :rows="2" placeholder="environment=production, owner=platform" />
                      </NFormItem>
                    </NGi>
                    <NGi span="2">
                      <NFormItem label="备注">
                        <NInput v-model:value="ociForm.remarks" type="textarea" :rows="2" />
                      </NFormItem>
                    </NGi>
                  </NGrid>
                </NCollapseItem>
              </NCollapse>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton type="primary" :loading="submittingOci" @click="submitOciForm">注册 Oracle Cloud 资产</NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>


        <!-- ── Self-Hosted Tab ───────────────────────────────────────────── -->
        <NTabPane name="self" tab="自建资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="140" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="selfForm.asset_name" placeholder="my-self-hosted-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Region" required>
                    <NInput v-model:value="selfForm.region" placeholder="hk, us-west, eu-central..." />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="主机地址" required>
                    <NInput v-model:value="selfForm.host" placeholder="1.2.3.4 或域名" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="SSH 端口">
                    <NInputNumber v-model:value="selfForm.ssh_port" :min="1" :max="65535" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="SSH 用户名">
                    <NInput v-model:value="selfForm.ssh_username" placeholder="root" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="SSH 密码">
                    <NInput v-model:value="selfForm.ssh_password" type="password" placeholder="密码或留空使用私钥" show-password-on="click" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="备注">
                    <NInput v-model:value="selfForm.remarks" placeholder="可选备注信息" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NCollapse>
                    <NCollapseItem title="SSH 私钥（可选）" name="ssh-key">
                      <NInput
                        v-model:value="selfForm.ssh_private_key"
                        type="textarea"
                        placeholder="Paste OpenSSH private key here"
                        :rows="6"
                        style="font-family: monospace; font-size: 12px"
                      />
                    </NCollapseItem>
                  </NCollapse>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="协议类型">
                    <NCheckboxGroup v-model:value="selfForm.protocol_types">
                      <NSpace>
                        <NCheckbox v-for="opt in selfProtocolOptions" :key="String(opt.value)" :value="opt.value" :label="String(opt.label)" />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="selfForm.target_count" :min="1" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="最大节点数">
                    <NInputNumber v-model:value="selfForm.max_count" :min="1" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="优先级">
                    <NInputNumber v-model:value="selfForm.priority" :min="1" :max="1000" style="width: 100%" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>硬件配置</NDivider>
              <NGrid :cols="3" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="CPU 核心数">
                    <NInputNumber
                      v-model:value="selfForm.cpu_cores"
                      :min="1" :max="256"
                      placeholder="自动或手动填写"
                      style="width: 100%"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="内存 (GB)">
                    <NInputNumber
                      v-model:value="selfForm.memory_gb"
                      :min="1" :max="1024"
                      placeholder="自动或手动填写"
                      style="width: 100%"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label=" ">
                    <NButton :loading="probingHw" block @click="probeHardware">
                      探测硬件
                    </NButton>
                  </NFormItem>
                </NGi>
              </NGrid>
              <NText depth="3" style="font-size: 12px; display: block; margin-top: 4px">
                硬件探测需要通过 SSH 连接目标主机，成功后会自动填入 CPU 核心数和内存大小。
              </NText>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton type="primary" :loading="submittingSelf" @click="submitSelfForm">
                  注册自建资产
                </NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>
      </NTabs>
    </NModal>
  </div>
</template>

<style scoped>
/* ── Page Layout ────────────────────────────────────────────────────────────── */
.assets-page {
  padding: 24px 28px;
  max-width: 1400px;
  margin: 0 auto;
  min-height: 100%;
  background: transparent;
}

/* ── Header ─────────────────────────────────────────────────────────────────── */
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
  gap: 16px;
}

.header-left {
  flex: 1;
}

.page-title {
  margin: 0 0 6px 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--n-text-color-1, #18181b);
  letter-spacing: -0.3px;
}

.page-subtitle {
  margin: 0;
  font-size: 14px;
  color: var(--n-text-color-3, #a1a1aa);
}

.header-right {
  flex-shrink: 0;
}

/* ── Stats Row ──────────────────────────────────────────────────────────────── */
.stats-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}

.stat-card {
  flex: 1 1 120px;
  background: white;
  border-radius: 12px;
  padding: 16px 20px;
  border: 1px solid var(--n-border-color, #e5e7eb);
  transition: box-shadow 0.2s ease;
}

.stat-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 6px;
  color: var(--n-text-color-1, #18181b);
}

.stat-label {
  font-size: 12px;
  color: var(--n-text-color-3, #a1a1aa);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-aws .stat-value  { color: #f59e0b; }
.stat-do .stat-value   { color: #0080ff; }
.stat-vultr .stat-value { color: #007bfc; }
.stat-gcp .stat-value { color: #4285f4; }
.stat-kamatera .stat-value { color: #d6532f; }
.stat-azure .stat-value { color: #0078d4; }
.stat-oci .stat-value { color: #c74634; }
.stat-self .stat-value { color: #8b5cf6; }
.stat-active .stat-value { color: #10b981; }
.stat-full .stat-value  { color: #f97316; }

/* ── Table Card ─────────────────────────────────────────────────────────────── */
.table-card {
  background: white;
  border-radius: 14px;
  border: 1px solid var(--n-border-color, #e5e7eb);
  padding: 20px 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

/* ── Tab Bar ─────────────────────────────────────────────────────────────────── */
.tab-bar {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--n-border-color, #e5e7eb);
  padding-bottom: 0;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  color: var(--n-text-color-3, #71717a);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  border-radius: 6px 6px 0 0;
  transition: color 0.15s ease, background 0.15s ease;
}

.tab-btn:hover {
  color: var(--n-text-color-1, #18181b);
  background: rgba(0, 0, 0, 0.03);
}

.tab-btn.active {
  color: #6366f1;
  border-bottom-color: #6366f1;
  background: rgba(99, 102, 241, 0.04);
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 10px;
  background: var(--n-color-pressed, #f4f4f5);
  color: var(--n-text-color-3, #71717a);
}

.tab-btn.active .tab-badge {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.tab-badge-aws  { background: rgba(245, 158, 11, 0.1); color: #f59e0b; }
.tab-badge-do   { background: rgba(0, 128, 255, 0.1); color: #0080ff; }
.tab-badge-vultr { background: rgba(0, 123, 252, 0.1); color: #007bfc; }
.tab-badge-gcp { background: rgba(66, 133, 244, 0.1); color: #4285f4; }
.tab-badge-kamatera { background: rgba(214, 83, 47, 0.1); color: #d6532f; }
.tab-badge-azure { background: rgba(0, 120, 212, 0.1); color: #0078d4; }
.tab-badge-oci { background: rgba(199, 70, 52, 0.1); color: #c74634; }
.tab-badge-self { background: rgba(139, 92, 246, 0.1); color: #8b5cf6; }

/* ── Table ──────────────────────────────────────────────────────────────────── */
.assets-table {
  font-size: 13px;
}

.choice-row {
  cursor: pointer;
  padding: 4px 0;
  border-bottom: 1px solid #eee;
}

.choice-row:hover {
  background: rgba(0, 0, 0, 0.03);
}

/* ── Modal Form ─────────────────────────────────────────────────────────────── */
.modal-form {
  padding: 8px 4px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--n-border-color, #e5e7eb);
}
</style>
