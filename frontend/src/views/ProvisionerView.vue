<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import {
  NGrid,
  NGi,
  NStatistic,
  NDataTable,
  NCard,
  NSelect,
  NButton,
  NTag,
  NSpin,
  NAlert,
  NSpace,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NCheckbox,
  NText,
  NDivider,
  NDynamicInput,
  NPagination,
  NCode,
  NDrawer,
  NDrawerContent,
  NPopconfirm,
  useMessage,
} from 'naive-ui'
import type { SelectOption } from 'naive-ui'
import apiClient from '@/api/client'
import type { AssetResponse, ProvisionTaskCreateRequest, TaskResponse, SubmitResult, XboardGroupResponse } from '@/types/api'

const message = useMessage()

// ── Constants ─────────────────────────────────────────────────────────────────
const PROTOCOLS = ['AnyTLS', 'Trojan', 'vless', 'vmess', 'Hysteria2']
const REGION_MAP: Record<string, string> = {
  'ap-northeast-1': '东京',
  'ap-northeast-2': '韩国',
  'ap-northeast-3': '大阪',
  'ap-east-1': '香港',
  'ap-southeast-1': '新加坡',
  'ap-southeast-2': '悉尼',
  'us-west-1': '洛杉矶',
  'us-west-2': '美西2',
  'us-east-1': '美东',
  'eu-west-1': '伦敦',
  'eu-west-2': '巴黎',
  'eu-central-1': '法兰克福',
}
const REGIONS = Object.keys(REGION_MAP)

const REGION_TAGS: Record<string, string> = {
  'ap-northeast-1': 'jp-tokyo',
  'ap-northeast-2': 'kr-seoul',
  'ap-northeast-3': 'jp-osaka',
  'ap-east-1': 'hk-hongkong',
  'ap-southeast-1': 'sg-singapore',
  'ap-southeast-2': 'au-sydney',
  'us-west-1': 'us-losangeles',
  'us-west-2': 'us-west-2',
  'us-east-1': 'us-east-1',
  'eu-west-1': 'uk-london',
  'eu-west-2': 'fr-paris',
  'eu-central-1': 'de-frankfurt',
}

// ── State ─────────────────────────────────────────────────────────────────────
const tasks = ref<TaskResponse[]>([])
const loading = ref(true)
const errorMsg = ref<string | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | null = null

// Stats
const stats = ref({ total: 0, queued: 0, running: 0, succeeded: 0, failed: 0 })

// Filters
const filterStatus = ref<string | null>(null)
const filterTaskType = ref<string | null>(null)
const filterLimit = ref<number>(50)
const page = ref(1)
const pageSize = ref(15)

// ── New Task Modal ────────────────────────────────────────────────────────────
const showNewTaskModal = ref(false)
const submitting = ref(false)
const submitError = ref<string | null>(null)
const submitSuccess = ref<SubmitResult | null>(null)

// Groups
const groups = ref<XboardGroupResponse[]>([])
const groupsLoading = ref(false)
const assets = ref<AssetResponse[]>([])

// ── Detail Drawer ─────────────────────────────────────────────────────────────
const showDetailDrawer = ref(false)
const selectedTask = ref<TaskResponse | null>(null)
const detailLoading = ref(false)
const retryingTaskId = ref<number | null>(null)
const deletingTaskId = ref<number | null>(null)
const selectedTaskIds = ref<number[]>([])
const batchDeleting = ref(false)

// ── Form ──────────────────────────────────────────────────────────────────────
const protocolType = ref('AnyTLS')
const assetType = ref('aws')
const nodeName = ref('')
const region = ref('ap-northeast-1')
const port = ref('443')
const serverPort = ref(443)
const rate = ref<number | null>(1.0)
const requireCdnProxy = ref(false)
const statusReason = ref('')
const groupIds = ref<number[]>([])
const routeIds = ref<number[]>([])
const sortVal = ref<number | null>(null)
const showNode = ref(true)
const rateTimeEnable = ref(false)
const tagsJson = ref('')
const protocolSettingsJson = ref('')
const rateTimeRangesJson = ref('')

// Protocol-specific fields
const sniDomain = ref('www.bilibili.com')
const realityPrivateKey = ref('')
const realityPublicKey = ref('')
const realityDest = ref('www.bilibili.com')
const allowInsecure = ref(true)
const network = ref('grpc')
const flow = ref('xtls-rprx-vision')

// Self-hosted SSH
const sshHost = ref('')
const sshPort = ref(22)
const sshUsername = ref('root')
const sshPassword = ref('')
const sshPrivateKey = ref('')

// ── Computed ──────────────────────────────────────────────────────────────────
const totalCount = computed(() => stats.value.total)
const queuedCount = computed(() => stats.value.queued)
const runningCount = computed(() => stats.value.running)
const succeededCount = computed(() => stats.value.succeeded)
const failedCount = computed(() => stats.value.failed)

const filteredTasks = computed(() => {
  let result = tasks.value
  if (filterStatus.value) {
    result = result.filter(t => t.status === filterStatus.value)
  }
  if (filterTaskType.value) {
    result = result.filter(t => t.task_type === filterTaskType.value)
  }
  return result
})

const paginatedTasks = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredTasks.value.slice(start, start + pageSize.value)
})

const totalFiltered = computed(() => filteredTasks.value.length)

// Protocol-specific field visibility
const showSniField = computed(() => ['AnyTLS', 'Trojan', 'vless'].includes(protocolType.value))
const showRealityFields = computed(() => protocolType.value === 'vless')
const showNetworkField = computed(() => ['Trojan', 'vmess', 'vless'].includes(protocolType.value))
const showFlowField = computed(() => protocolType.value === 'vless')

// ── Options ──────────────────────────────────────────────────────────────────
const protocolOptions = computed<SelectOption[]>(() =>
  PROTOCOLS
    .filter(protocol => assetType.value === 'self_hosted' || protocol !== 'Hysteria2')
    .map(protocol => ({ label: protocol, value: protocol }))
)
const regionOptions: SelectOption[] = REGIONS.map(r => ({ label: `${REGION_MAP[r]} (${r})`, value: r }))
const digitalOceanRegionOptions: SelectOption[] = [
  { label: '新加坡 (sgp1)', value: 'sgp1' },
  { label: '纽约 (nyc3)', value: 'nyc3' },
  { label: '旧金山 (sfo3)', value: 'sfo3' },
  { label: '阿姆斯特丹 (ams3)', value: 'ams3' },
  { label: '伦敦 (lon1)', value: 'lon1' },
  { label: '法兰克福 (fra1)', value: 'fra1' },
  { label: '多伦多 (tor1)', value: 'tor1' },
  { label: '班加罗尔 (blr1)', value: 'blr1' },
  { label: '悉尼 (syd1)', value: 'syd1' },
]
const vultrRegionOptions: SelectOption[] = [
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
const gcpRegionOptions: SelectOption[] = [
  { label: '东京 (asia-northeast1-a)', value: 'asia-northeast1-a' },
  { label: '大阪 (asia-northeast2-a)', value: 'asia-northeast2-a' },
  { label: '首尔 (asia-northeast3-a)', value: 'asia-northeast3-a' },
  { label: '新加坡 (asia-southeast1-a)', value: 'asia-southeast1-a' },
  { label: '台湾 (asia-east1-a)', value: 'asia-east1-a' },
  { label: '悉尼 (australia-southeast1-a)', value: 'australia-southeast1-a' },
  { label: '美国西部 (us-west1-a)', value: 'us-west1-a' },
  { label: '美国中部 (us-central1-a)', value: 'us-central1-a' },
  { label: '比利时 (europe-west1-b)', value: 'europe-west1-b' },
]
const azureRegionOptions: SelectOption[] = [
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
const ociRegionOptions: SelectOption[] = [
  { label: '东京 (ap-tokyo-1)', value: 'ap-tokyo-1' },
  { label: '大阪 (ap-osaka-1)', value: 'ap-osaka-1' },
  { label: '首尔 (ap-seoul-1)', value: 'ap-seoul-1' },
  { label: '春川 (ap-chuncheon-1)', value: 'ap-chuncheon-1' },
  { label: '新加坡 (ap-singapore-1)', value: 'ap-singapore-1' },
  { label: '悉尼 (ap-sydney-1)', value: 'ap-sydney-1' },
  { label: '圣何塞 (us-sanjose-1)', value: 'us-sanjose-1' },
  { label: '凤凰城 (us-phoenix-1)', value: 'us-phoenix-1' },
  { label: '阿什本 (us-ashburn-1)', value: 'us-ashburn-1' },
  { label: '伦敦 (uk-london-1)', value: 'uk-london-1' },
  { label: '法兰克福 (eu-frankfurt-1)', value: 'eu-frankfurt-1' },
]
const kamateraRegionOptions: SelectOption[] = [
  { label: '亚洲 (AS)', value: 'AS' },
]

const selectedRegionOptions = computed<SelectOption[]>(() => {
  const registeredRegions = [...new Set(
    assets.value
      .filter(asset => asset.status === 'active' && asset.asset_type === assetType.value)
      .map(asset => asset.region)
      .filter((value): value is string => Boolean(value))
  )]
  if (registeredRegions.length > 0) {
    return registeredRegions.map(value => ({ label: value, value }))
  }
  if (assetType.value === 'digitalocean') return digitalOceanRegionOptions
  if (assetType.value === 'vultr') return vultrRegionOptions
  if (assetType.value === 'gcp') return gcpRegionOptions
  if (assetType.value === 'azure') return azureRegionOptions
  if (assetType.value === 'oci') return ociRegionOptions
  if (assetType.value === 'kamatera') return kamateraRegionOptions
  return regionOptions
})
const assetTypeOptions: SelectOption[] = [
  { label: 'AWS', value: 'aws' },
  { label: 'DigitalOcean', value: 'digitalocean' },
  { label: 'Vultr', value: 'vultr' },
  { label: 'Google Cloud', value: 'gcp' },
  { label: 'Microsoft Azure', value: 'azure' },
  { label: 'Oracle Cloud', value: 'oci' },
  { label: 'Kamatera', value: 'kamatera' },
  { label: '自建服务器', value: 'self_hosted' },
]
watch(assetType, (nextAssetType, previousAssetType) => {
  const defaultRegions: Record<string, string> = {
    aws: 'ap-northeast-1',
    digitalocean: 'sgp1',
    vultr: 'sgp',
    gcp: 'asia-northeast1-a',
    azure: 'japaneast',
    oci: 'ap-tokyo-1',
    kamatera: 'AS',
  }
  if (nextAssetType !== 'self_hosted' && protocolType.value === 'Hysteria2') {
    protocolType.value = 'AnyTLS'
  }
  if (nextAssetType !== previousAssetType && defaultRegions[nextAssetType]) {
    region.value = defaultRegions[nextAssetType]
  }
})
const groupOptions = computed<SelectOption[]>(() =>
  groups.value.map(g => ({ label: g.name, value: g.id }))
)
const statusOptions: SelectOption[] = [
  { label: '全部状态', value: undefined },
  { label: 'Queued', value: 'queued' },
  { label: 'Running', value: 'running' },
  { label: 'Succeeded', value: 'succeeded' },
  { label: 'Failed', value: 'failed' },
]
const taskTypeOptions: SelectOption[] = [
  { label: '全部类型', value: undefined },
  { label: 'Provision Node', value: 'provision_node' },
  { label: 'Force Heal', value: 'force_heal' },
  { label: 'Decommission Node', value: 'decommission_node' },
  { label: 'Reprobe Node', value: 'reprobe_node' },
  { label: 'Manual Review', value: 'mark_manual_review' },
]
const limitOptions: SelectOption[] = [
  { label: '20', value: 20 },
  { label: '50', value: 50 },
  { label: '100', value: 100 },
  { label: '200', value: 200 },
]

// ── Data Fetching ─────────────────────────────────────────────────────────────
async function fetchStats() {
  try {
    const { data } = await apiClient.get<typeof stats.value>('/tasks/stats')
    stats.value = data
  } catch {
    // stats is non-critical, silently fail
  }
}

async function fetchTasks() {
  try {
    const { data } = await apiClient.get<TaskResponse[]>('/tasks', { params: { limit: filterLimit.value } })
    tasks.value = data
    errorMsg.value = null
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    errorMsg.value = axiosErr.response?.data?.error || axiosErr.message || '加载任务失败'
  } finally {
    loading.value = false
  }
}

async function fetchAssets() {
  try {
    const { data } = await apiClient.get<AssetResponse[]>('/assets')
    assets.value = data
  } catch {
    assets.value = []
  }
}

async function fetchGroups() {
  groupsLoading.value = true
  try {
    const { data } = await apiClient.get<XboardGroupResponse[]>('/xboard/groups')
    groups.value = data
  } catch {
    // groups is non-critical
  } finally {
    groupsLoading.value = false
  }
}

async function fetchTaskDetail(id: number) {
  detailLoading.value = true
  try {
    const { data } = await apiClient.get<TaskResponse>(`/tasks/${id}`)
    selectedTask.value = data
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || '加载详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function retryTask(id: number) {
  retryingTaskId.value = id
  try {
    await apiClient.post<TaskResponse>(`/tasks/${id}/retry`)
    message.success(`任务 #${id} 已重置为 queued`)
    await fetchTasks()
    await fetchStats()
    if (selectedTask.value?.id === id) {
      fetchTaskDetail(id)
    }
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || '重试失败')
  } finally {
    retryingTaskId.value = null
  }
}

async function deleteTask(id: number) {
  deletingTaskId.value = id
  try {
    await apiClient.delete(`/tasks/${id}`)
    message.success(`任务 #${id} 已删除`)
    showDetailDrawer.value = false
    selectedTask.value = null
    await fetchTasks()
    await fetchStats()
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || '删除失败')
  } finally {
    deletingTaskId.value = null
  }
}

// ── Batch Delete Tasks ──────────────────────────────────────────────────────────
async function batchDeleteTasks() {
  if (selectedTaskIds.value.length === 0) {
    message.warning('请先选择要删除的任务')
    return
  }
  batchDeleting.value = true
  try {
    const deletePromises = selectedTaskIds.value.map(id => apiClient.delete(`/tasks/${id}`))
    await Promise.all(deletePromises)
    message.success(`已删除 ${selectedTaskIds.value.length} 个任务`)
    selectedTaskIds.value = []
    await fetchTasks()
    await fetchStats()
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.response?.data?.message || axiosErr.message || '批量删除失败')
  } finally {
    batchDeleting.value = false
  }
}

// ── Auto-tags ─────────────────────────────────────────────────────────────────
function buildDefaultTags(): string {
  const regionTag = REGION_TAGS[region.value] ?? region.value
  return JSON.stringify(
    [`protocol:${protocolType.value.toLowerCase()}`, `region:${regionTag}`, `asset:${assetType.value}`],
    null,
    2
  )
}

// ── Reality Key Generation ────────────────────────────────────────────────────
async function generateRealityKeys() {
  try {
    const { data } = await apiClient.post<{ private_key: string; public_key: string }>('/utils/generate-reality-keys')
    realityPrivateKey.value = data.private_key
    realityPublicKey.value = data.public_key
    message.success('Reality 密钥对已生成')
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || '生成密钥失败')
  }
}

// ── Form Actions ──────────────────────────────────────────────────────────────
function openNewTaskModal() {
  tagsJson.value = buildDefaultTags()
  showNewTaskModal.value = true
}

function closeModal() {
  showNewTaskModal.value = false
  resetForm()
}

function resetForm() {
  nodeName.value = ''
  port.value = '443'
  serverPort.value = 443
  rate.value = 1.0
  requireCdnProxy.value = false
  statusReason.value = ''
  groupIds.value = []
  routeIds.value = []
  sortVal.value = null
  showNode.value = true
  rateTimeEnable.value = false
  tagsJson.value = buildDefaultTags()
  protocolSettingsJson.value = ''
  rateTimeRangesJson.value = ''
  // Protocol-specific fields
  sniDomain.value = 'www.bilibili.com'
  realityPrivateKey.value = ''
  realityPublicKey.value = ''
  realityDest.value = 'www.bilibili.com'
  allowInsecure.value = true
  network.value = 'grpc'
  flow.value = 'xtls-rprx-vision'
  // Self-hosted
  sshHost.value = ''
  sshPort.value = 22
  sshUsername.value = 'root'
  sshPassword.value = ''
  sshPrivateKey.value = ''
}

async function handleSubmit() {
  if (!nodeName.value.trim()) {
    message.warning('节点名称不能为空')
    return
  }

  submitting.value = true
  submitError.value = null
  submitSuccess.value = null

  const body: ProvisionTaskCreateRequest = {
    protocol_type: protocolType.value,
    node_name: nodeName.value.trim(),
    port: port.value,
    server_port: serverPort.value,
    rate: rate.value ?? 1.0,
    asset_type: assetType.value,
    region: ['aws', 'digitalocean', 'vultr', 'gcp', 'kamatera', 'azure', 'oci'].includes(assetType.value) ? region.value : undefined,
    require_cdn_proxy: requireCdnProxy.value,
    show: showNode.value,
    parent_id: undefined,
    group_ids: groupIds.value.length > 0 ? groupIds.value : undefined,
    route_ids: routeIds.value.length > 0 ? routeIds.value : undefined,
    sort: sortVal.value ?? undefined,
    rate_time_enable: rateTimeEnable.value,
    tags: tagsJson.value
      ? (() => { try { return JSON.parse(tagsJson.value) } catch { return undefined } })()
      : undefined,
    protocol_settings: protocolSettingsJson.value
      ? (() => { try { return JSON.parse(protocolSettingsJson.value) } catch { return undefined } })()
      : undefined,
    rate_time_ranges: rateTimeRangesJson.value
      ? (() => { try { return JSON.parse(rateTimeRangesJson.value) } catch { return undefined } })()
      : undefined,
    status_reason: statusReason.value || undefined,
    // Protocol-specific fields
    sni_domain: showSniField.value ? (sniDomain.value || undefined) : undefined,
    reality_private_key: showRealityFields.value ? (realityPrivateKey.value || undefined) : undefined,
    reality_public_key: showRealityFields.value ? (realityPublicKey.value || undefined) : undefined,
    reality_dest: showRealityFields.value ? (realityDest.value || undefined) : undefined,
    allow_insecure: allowInsecure.value,
    network: showNetworkField.value ? network.value : undefined,
    flow: showFlowField.value ? (flow.value || undefined) : undefined,
    // Self-hosted SSH
    ssh_host: assetType.value === 'self_hosted' ? (sshHost.value || undefined) : undefined,
    ssh_port: assetType.value === 'self_hosted' ? (sshPort.value || undefined) : undefined,
    ssh_username: assetType.value === 'self_hosted' ? (sshUsername.value || undefined) : undefined,
    ssh_password: assetType.value === 'self_hosted' ? (sshPassword.value || undefined) : undefined,
    ssh_private_key: assetType.value === 'self_hosted' ? (sshPrivateKey.value || undefined) : undefined,
  }

  try {
    const { data } = await apiClient.post<SubmitResult>('/tasks', body)
    submitSuccess.value = data
    message.success(`任务已提交 — #${data.task_id}`)
    showNewTaskModal.value = false
    resetForm()
    await fetchTasks()
    await fetchStats()
  } catch (err: unknown) {
    const axiosErr = err as { response?: { status?: number; data?: { error?: string; message?: string; detail?: unknown } }; message?: string }
    const data = axiosErr.response?.data
    if (axiosErr.response?.status === 422 && data?.detail) {
      const detail = data.detail
      if (Array.isArray(detail)) {
        submitError.value = (detail as Array<{ msg: string; loc: string[] }>).map(d => `${d.loc.join('.')}: ${d.msg}`).join('; ')
      } else if (typeof detail === 'string') {
        submitError.value = detail
      } else {
        submitError.value = JSON.stringify(detail)
      }
    } else {
      submitError.value = data?.error || data?.message || axiosErr.message || '提交失败'
    }
  } finally {
    submitting.value = false
  }
}

// ── Detail Drawer ─────────────────────────────────────────────────────────────
function openDetail(task: TaskResponse) {
  selectedTask.value = task
  showDetailDrawer.value = true
}

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtTs(value: string | null | undefined): string {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return String(value)
  }
}

function statusTagType(status: string): 'default' | 'info' | 'success' | 'error' | 'warning' {
  switch (status) {
    case 'queued': return 'default'
    case 'running': return 'info'
    case 'succeeded': return 'success'
    case 'failed': return 'error'
    default: return 'default'
  }
}

function taskTypeLabel(tt: string): string {
  const map: Record<string, string> = {
    provision_node: '初始化节点',
    force_heal: '强制修复',
    decommission_node: '下线节点',
    reprobe_node: '重探节点',
    mark_manual_review: '人工审核',
  }
  return map[tt] ?? tt
}

// ── Table Columns ─────────────────────────────────────────────────────────────
const columns = [
  {
    type: 'selection' as const,
    disabled: (row: TaskResponse) => row.status === 'running',
  },
  { title: 'ID', key: 'id', align: 'center' as const, width: 70 },
  { title: '任务类型', key: 'task_type', render: (row: TaskResponse) => taskTypeLabel(row.task_type) },
  {
    title: '节点名称', key: 'node_name', width: 150,
    render: (row: TaskResponse) => row.node_name
      ? h('a', { href: `/fleet?node=${row.xboard_node_id}`, style: 'color: #2080f0; text-decoration: none' }, row.node_name)
      : '—',
  },
  { title: '区域', key: 'region', width: 120, render: (row: TaskResponse) => row.region ?? '—' },
  { title: '协议', key: 'protocol_type', width: 80, render: (row: TaskResponse) => row.protocol_type ?? '—' },
  {
    title: '状态', key: 'status', align: 'center' as const, width: 100,
    render: (row: TaskResponse) => h(NTag, { type: statusTagType(row.status), size: 'small' }, { default: () => row.status }),
  },
  {
    title: '进度', key: 'attempt_count', align: 'center' as const, width: 90,
    render: (row: TaskResponse) => `${row.attempt_count} / ${row.max_attempts}`,
  },
  { title: '创建时间', key: 'created_at', render: (row: TaskResponse) => fmtTs(row.created_at) },
  { title: '锁定者', key: 'locked_by', render: (row: TaskResponse) => row.locked_by ?? '—' },
  {
    title: '操作', key: 'actions', align: 'center' as const, width: 160,
    render: (row: TaskResponse) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', onClick: () => openDetail(row) }, { default: () => '详情' }),
        row.status !== 'running' ? h(NPopconfirm, {
          onPositiveClick: () => deleteTask(row.id),
        }, {
          trigger: () => h(NButton, { size: 'small', type: 'error' }, { default: () => '删除' }),
          default: () => '确认删除？',
        }) : null,
      ],
    }),
  },
]

// ── Watchers ──────────────────────────────────────────────────────────────────
function onFiltersChanged() {
  page.value = 1
}

function onPageChange(p: number) {
  page.value = p
}

function onPageSizeChange(s: number) {
  pageSize.value = s
  page.value = 1
}

// ── Lifecycle ────────────────────────────────────────────────────────────────
onMounted(() => {
  fetchStats()
  fetchTasks()
  fetchGroups()
  fetchAssets()
  refreshTimer = setInterval(() => {
    fetchStats()
    fetchTasks()
  }, 15_000)
})

onUnmounted(() => {
  if (refreshTimer !== null) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<script lang="ts">
import { h } from 'vue'
export default { name: 'ProvisionerView' }
</script>

<template>
  <div style="padding: 16px; max-width: 1400px; margin: 0 auto">
    <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px" closable @close="errorMsg = null" />

    <!-- ── Statistics Row ─────────────────────────────────────────────────────── -->
    <NCard style="margin-bottom: 16px">
      <NGrid :cols="6" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
        <NGi span="1">
          <NStatistic label="全部任务" :value="totalCount" />
        </NGi>
        <NGi span="1">
          <NStatistic label="排队中">
            <template #default>
              <NText :style="{ color: queuedCount > 0 ? '#f0a020' : 'inherit' }">{{ queuedCount }}</NText>
            </template>
          </NStatistic>
        </NGi>
        <NGi span="1">
          <NStatistic label="执行中">
            <template #default>
              <NText :style="{ color: runningCount > 0 ? '#2080f0' : 'inherit' }">{{ runningCount }}</NText>
            </template>
          </NStatistic>
        </NGi>
        <NGi span="1">
          <NStatistic label="成功" :value="succeededCount" />
        </NGi>
        <NGi span="1">
          <NStatistic label="失败">
            <template #default>
              <NText :style="{ color: failedCount > 0 ? '#d03050' : 'inherit' }">{{ failedCount }}</NText>
            </template>
          </NStatistic>
        </NGi>
        <NGi span="1" style="display: flex; align-items: center; justify-content: flex-end">
          <NButton type="primary" size="large" @click="openNewTaskModal">
            + 新建任务
          </NButton>
        </NGi>
      </NGrid>
    </NCard>

    <!-- ── Filter Bar ────────────────────────────────────────────────────────── -->
    <NCard style="margin-bottom: 16px">
      <NSpace align="center" justify="space-between">
        <NSpace>
          <NSelect v-model:value="filterStatus" :options="statusOptions" placeholder="按状态筛选"
            clearable style="width: 140px" @update:value="onFiltersChanged" />
          <NSelect v-model:value="filterTaskType" :options="taskTypeOptions" placeholder="按类型筛选"
            clearable style="width: 160px" @update:value="onFiltersChanged" />
          <NSelect v-model:value="filterLimit" :options="limitOptions" placeholder="显示条数"
            style="width: 100px" @update:value="onFiltersChanged" />
        </NSpace>
        <NSpace v-if="selectedTaskIds.length > 0">
          <NText style="font-size: 13px; font-weight: 600; color: #6366f1">
            已选择 {{ selectedTaskIds.length }} 个任务
          </NText>
          <NPopconfirm @positive-click="batchDeleteTasks">
            <template #trigger>
              <NButton type="error" size="small" :loading="batchDeleting">
                批量删除
              </NButton>
            </template>
            确认删除选中的 {{ selectedTaskIds.length }} 个任务？
          </NPopconfirm>
        </NSpace>
      </NSpace>
    </NCard>

    <!-- ── Task Table ────────────────────────────────────────────────────────── -->
    <NCard>
      <NSpin :show="loading" description="加载中…">
        <NDataTable
          :columns="columns"
          :data="paginatedTasks"
          :bordered="false"
          :single-line="false"
          size="small"
          :row-key="(row: TaskResponse) => row.id"
          :pagination="false"
          :loading="loading"
          v-model:checked-row-keys="selectedTaskIds"
          @click-row="(row: TaskResponse) => openDetail(row)"
          style="cursor: pointer"
        />

        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 16px">
          <NText depth="3" style="font-size: 13px">
            共 {{ totalFiltered }} 条，第 {{ page }} / {{ Math.max(1, Math.ceil(totalFiltered / pageSize)) }} 页
          </NText>
          <NPagination
            v-model:page="page"
            :page-size="pageSize"
            :page-sizes="[15, 30, 50, 100]"
            :item-count="totalFiltered"
            show-size-picker
            @update:page="onPageChange"
            @update:page-size="onPageSizeChange"
          />
        </div>
      </NSpin>
    </NCard>

    <!-- ── New Task Modal ─────────────────────────────────────────────────────── -->
    <NModal
      v-model:show="showNewTaskModal"
      preset="card"
      title="新建初始化任务"
      style="max-width: 700px; width: 95vw"
      :mask-closable="!submitting"
      :close-on-esc="!submitting"
    >
      <NSpin :show="submitting">
        <NAlert v-if="submitError" type="error" :title="submitError" style="margin-bottom: 12px" closable
          @close="submitError = null" />
        <NAlert v-if="submitSuccess" type="success" style="margin-bottom: 12px" closable
          @close="submitSuccess = null">
          任务已提交 — #{{ submitSuccess.task_id }}, Correlation: {{ submitSuccess.correlation_id }}
        </NAlert>

        <NForm label-placement="left" label-width="130" size="small">
          <NDivider title-placement="left">基础配置</NDivider>
          <NGrid :cols="2" :x-gap="12">
            <NGi>
              <NFormItem label="协议类型">
                <NSelect v-model:value="protocolType" :options="protocolOptions" />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="资产类型">
                <NSelect v-model:value="assetType" :options="assetTypeOptions" />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="节点名称" required>
                <NInput v-model:value="nodeName" placeholder="sf-xxx" clearable />
              </NFormItem>
            </NGi>
            <NGi v-if="['aws', 'digitalocean', 'vultr', 'gcp', 'kamatera', 'azure', 'oci'].includes(assetType)">
              <NFormItem label="目标区域">
                <NSelect v-model:value="region" :options="selectedRegionOptions" />
              </NFormItem>
            </NGi>
            <NGi v-if="['aws', 'digitalocean', 'vultr', 'gcp', 'kamatera', 'azure', 'oci'].includes(assetType)">
              <NFormItem label="服务监听端口">
                <NInputNumber v-model:value="serverPort" :min="1" :max="65535" style="width: 100%" />
              </NFormItem>
            </NGi>
            <NGi v-if="assetType === 'self_hosted'">
              <NFormItem label="服务监听端口">
                <NInput value="自动分配 (40000-60000)" disabled />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="Xboard 节点端口">
                <NInput v-model:value="port" placeholder="443" />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="倍率">
                <NInputNumber v-model:value="rate" :min="0" :step="0.1" style="width: 100%" />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="Cloudflare CDN">
                <NCheckbox v-model:checked="requireCdnProxy">
                  启用 CDN 代理
                </NCheckbox>
              </NFormItem>
            </NGi>
          </NGrid>

          <!-- 协议特定配置 -->
          <NDivider title-placement="left">协议配置</NDivider>
          <NGrid :cols="2" :x-gap="12">
            <!-- SNI 域名 (AnyTLS, Trojan, VLESS) -->
            <NGi v-if="showSniField" :span="2">
              <NFormItem label="SNI 伪装域名">
                <NInput v-model:value="sniDomain" placeholder="www.bilibili.com" clearable />
              </NFormItem>
            </NGi>

            <!-- 允许不安全连接 -->
            <NGi v-if="showSniField">
              <NFormItem label="安全设置">
                <NCheckbox v-model:checked="allowInsecure">
                  允许不安全连接
                </NCheckbox>
              </NFormItem>
            </NGi>

            <!-- 传输协议 (Trojan, VMess, VLESS) -->
            <NGi v-if="showNetworkField">
              <NFormItem label="传输协议">
                <NSelect v-model:value="network" :options="[
                  { label: 'gRPC', value: 'grpc' },
                  { label: 'WebSocket', value: 'ws' },
                  { label: 'TCP', value: 'tcp' },
                ]" />
              </NFormItem>
            </NGi>
          </NGrid>

          <!-- VLESS Reality 配置 -->
          <template v-if="showRealityFields">
            <NFormItem label="Reality 伪装站点">
              <NInput v-model:value="realityDest" placeholder="www.bilibili.com" clearable />
            </NFormItem>

            <NFormItem label="Reality 密钥对">
              <NSpace vertical style="width: 100%">
                <NButton @click="generateRealityKeys" type="primary" size="small">
                  自动生成密钥对
                </NButton>
                <NInput
                  v-model:value="realityPrivateKey"
                  placeholder="私钥 (Private Key) - 留空自动生成"
                  clearable
                />
                <NInput
                  v-model:value="realityPublicKey"
                  placeholder="公钥 (Public Key) - 留空自动生成"
                  clearable
                />
              </NSpace>
            </NFormItem>

            <NFormItem label="流控模式">
              <NSelect v-model:value="flow" :options="[
                { label: 'xtls-rprx-vision', value: 'xtls-rprx-vision' },
                { label: 'xtls-rprx-vision-udp443', value: 'xtls-rprx-vision-udp443' },
              ]" />
            </NFormItem>
          </template>

          <!-- Self-Hosted SSH 字段 -->
          <NDivider v-if="assetType === 'self_hosted'" title-placement="left">自建服务器 SSH 配置</NDivider>
          <NGrid v-if="assetType === 'self_hosted'" :cols="2" :x-gap="12">
            <NGi>
              <NFormItem label="服务器地址" required>
                <NInput v-model:value="sshHost" placeholder="1.2.3.4 或域名" clearable />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="SSH 端口">
                <NInputNumber v-model:value="sshPort" :min="1" :max="65535" style="width: 100%" />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="SSH 用户名">
                <NInput v-model:value="sshUsername" placeholder="root" clearable />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="SSH 密码">
                <NInput v-model:value="sshPassword" type="password" placeholder="密码或私钥二选一" show-password-on="mousedown" clearable />
              </NFormItem>
            </NGi>
            <NGi :span="2">
              <NFormItem label="SSH 私钥">
                <NInput
                  v-model:value="sshPrivateKey"
                  type="textarea"
                  placeholder="-----BEGIN RSA PRIVATE KEY----- ... (可选)"
                  :autosize="{ minRows: 2, maxRows: 5 }"
                  clearable
                />
              </NFormItem>
            </NGi>
          </NGrid>

          <NDivider title-placement="left">分组与路由</NDivider>
          <NGrid :cols="2" :x-gap="12">
            <NGi>
              <NFormItem label="Xboard 分组">
                <NSelect
                  v-model:value="groupIds"
                  :options="groupOptions"
                  placeholder="选择分组"
                  multiple
                  clearable
                />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="路由 ID">
                <NDynamicInput
                  v-model:value="routeIds"
                  placeholder="输入路由 ID，按回车添加"
                  :min="1"
                />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="排序">
                <NInputNumber v-model:value="sortVal" placeholder="可选" clearable style="width: 100%" />
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="状态备注">
                <NInput v-model:value="statusReason" placeholder="可选" />
              </NFormItem>
            </NGi>
          </NGrid>

          <NDivider title-placement="left">高级选项</NDivider>
          <NGrid :cols="2" :x-gap="12">
            <NGi>
              <NFormItem label="Xboard show">
                <NCheckbox v-model:checked="showNode">show=true</NCheckbox>
              </NFormItem>
            </NGi>
            <NGi>
              <NFormItem label="限速时段">
                <NCheckbox v-model:checked="rateTimeEnable">启用限速时段</NCheckbox>
              </NFormItem>
            </NGi>
          </NGrid>

          <NDivider title-placement="left">JSON 配置</NDivider>
          <NFormItem label="标签 JSON">
            <NInput
              v-model:value="tagsJson"
              type="textarea"
              placeholder="自动生成，可手动修改"
              :autosize="{ minRows: 2, maxRows: 4 }"
            />
          </NFormItem>
          <NFormItem label="协议设置 JSON">
            <NInput
              v-model:value="protocolSettingsJson"
              type="textarea"
              placeholder="可选"
              :autosize="{ minRows: 2, maxRows: 5 }"
            />
          </NFormItem>
          <NFormItem label="限速时段 JSON">
            <NInput
              v-model:value="rateTimeRangesJson"
              type="textarea"
              placeholder="可选"
              :autosize="{ minRows: 2, maxRows: 4 }"
            />
          </NFormItem>
        </NForm>

        <NSpace style="margin-top: 16px">
          <NButton type="primary" :loading="submitting" @click="handleSubmit">
            提交任务
          </NButton>
          <NButton :disabled="submitting" @click="closeModal">取消</NButton>
        </NSpace>
      </NSpin>
    </NModal>

    <!-- ── Detail Drawer ─────────────────────────────────────────────────────── -->
    <NDrawer v-model:show="showDetailDrawer" :width="520" placement="right">
      <NDrawerContent title="任务详情" closable>
        <NSpin :show="detailLoading">
          <template v-if="selectedTask">
            <!-- Status Banner -->
            <NAlert
              :type="statusTagType(selectedTask.status)"
              style="margin-bottom: 16px"
            >
              <NText strong style="font-size: 16px">
                #{{ selectedTask.id }} — {{ taskTypeLabel(selectedTask.task_type) }}
              </NText>
              <br />
              <NText depth="3">状态: {{ selectedTask.status }} | 进度: {{ selectedTask.attempt_count }} / {{ selectedTask.max_attempts }}</NText>
            </NAlert>

            <!-- Basic Info -->
            <NCard title="基本信息" size="small" style="margin-bottom: 12px">
              <NGrid :cols="2" :x-gap="8" :y-gap="6">
                <NGi><NText depth="3">ID:</NText> {{ selectedTask.id }}</NGi>
                <NGi><NText depth="3">Locked By:</NText> {{ selectedTask.locked_by ?? '—' }}</NGi>
                <NGi><NText depth="3">创建时间:</NText></NGi>
                <NGi><NText depth="3">{{ fmtTs(selectedTask.created_at) }}</NText></NGi>
                <NGi><NText depth="3">开始时间:</NText></NGi>
                <NGi><NText depth="3">{{ fmtTs(selectedTask.started_at) }}</NText></NGi>
                <NGi><NText depth="3">结束时间:</NText></NGi>
                <NGi><NText depth="3">{{ fmtTs(selectedTask.finished_at) }}</NText></NGi>
              </NGrid>
            </NCard>

            <!-- Correlation ID -->
            <NCard title="Correlation ID" size="small" style="margin-bottom: 12px">
              <NCode :code="selectedTask.correlation_id" language="text" word-wrap />
            </NCard>

            <!-- Error -->
            <NCard v-if="selectedTask.last_error" title="错误信息" size="small" style="margin-bottom: 12px">
              <NAlert type="error">{{ selectedTask.last_error }}</NAlert>
            </NCard>

            <!-- Actions -->
            <NSpace>
              <NButton
                v-if="selectedTask.status === 'failed'"
                type="warning"
                :loading="retryingTaskId === selectedTask.id"
                :disabled="retryingTaskId !== null"
                @click="retryTask(selectedTask.id)"
              >
                重试任务
              </NButton>
              <NButton
                v-if="selectedTask.status === 'succeeded'"
                type="success"
                disabled
              >
                任务成功
              </NButton>
              <NButton
                v-if="selectedTask.status === 'running'"
                type="info"
                disabled
              >
                执行中
              </NButton>
              <NButton
                v-if="selectedTask.status === 'queued'"
                type="default"
                disabled
              >
                排队中
              </NButton>
              <NPopconfirm
                v-if="selectedTask.status !== 'running'"
                @positive-click="deleteTask(selectedTask.id)"
              >
                <template #trigger>
                  <NButton
                    type="error"
                    :loading="deletingTaskId === selectedTask.id"
                    :disabled="deletingTaskId !== null"
                  >
                    删除任务
                  </NButton>
                </template>
                确认删除任务 #{{ selectedTask.id }}？此操作不可撤销。
              </NPopconfirm>
            </NSpace>
          </template>

          <NAlert v-else type="info" title="暂无选中任务" />
        </NSpin>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>
