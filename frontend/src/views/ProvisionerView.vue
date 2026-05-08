<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
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
import type { ProvisionTaskCreateRequest, TaskResponse, SubmitResult, XboardGroupResponse } from '@/types/api'

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

// ── Detail Drawer ─────────────────────────────────────────────────────────────
const showDetailDrawer = ref(false)
const selectedTask = ref<TaskResponse | null>(null)
const detailLoading = ref(false)
const retryingTaskId = ref<number | null>(null)
const deletingTaskId = ref<number | null>(null)

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

// ── Options ──────────────────────────────────────────────────────────────────
const protocolOptions: SelectOption[] = PROTOCOLS.map(p => ({ label: p, value: p }))
const regionOptions: SelectOption[] = REGIONS.map(r => ({ label: `${REGION_MAP[r]} (${r})`, value: r }))
const assetTypeOptions: SelectOption[] = [
  { label: 'AWS', value: 'aws' },
  { label: '自建服务器', value: 'self_hosted' },
]
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

// ── Auto-tags ─────────────────────────────────────────────────────────────────
function buildDefaultTags(): string {
  const regionTag = REGION_TAGS[region.value] ?? region.value
  return JSON.stringify(
    [`protocol:${protocolType.value.toLowerCase()}`, `region:${regionTag}`, `asset:${assetType.value}`],
    null,
    2
  )
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
    region: assetType.value === 'aws' ? region.value : undefined,
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
      <NSpace>
        <NSelect v-model:value="filterStatus" :options="statusOptions" placeholder="按状态筛选"
          clearable style="width: 140px" @update:value="onFiltersChanged" />
        <NSelect v-model:value="filterTaskType" :options="taskTypeOptions" placeholder="按类型筛选"
          clearable style="width: 160px" @update:value="onFiltersChanged" />
        <NSelect v-model:value="filterLimit" :options="limitOptions" placeholder="显示条数"
          style="width: 100px" @update:value="onFiltersChanged" />
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
            <NGi v-if="assetType === 'aws'">
              <NFormItem label="目标区域">
                <NSelect v-model:value="region" :options="regionOptions" />
              </NFormItem>
            </NGi>
            <NGi v-if="assetType === 'aws'">
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
