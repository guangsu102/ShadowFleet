<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import {
  NDataTable,
  NTag,
  NSpin,
  NAlert,
  NSelect,
  NCheckbox,
  NCode,
  NDivider,
  NButton,
  NForm,
  NFormItem,
  NInput,
  NPopconfirm,
  useMessage,
} from 'naive-ui'
import type { SelectOption } from 'naive-ui'
import apiClient from '@/api/client'
import { useSSE } from '@/composables/useSSE'
import { useI18n } from '@/composables/useI18n'
import type {
  DashboardSnapshotResponse,
  FleetNodeDashboardRowResponse,
  NodeEventResponse,
} from '@/types/api'

const { t } = useI18n()
const message = useMessage()

// ── State ────────────────────────────────────────────────────────────────────
const snapshot = ref<DashboardSnapshotResponse | null>(null)
const loading = ref(true)
const errorMsg = ref<string | null>(null)

const events = ref<NodeEventResponse[]>([])
const eventsLoading = ref(false)

const selectedNodeId = ref<number | null>(null)

const formOperatorName = ref('')
const formTaskType = ref<string | null>(null)
const formReason = ref('')
const formForceStrategy = ref<string | null>(null)
const submitting = ref(false)
const syncing = ref(false)
const deletingNodeId = ref<number | null>(null)

let refreshTimer: ReturnType<typeof setInterval> | null = null

// ── Inline SVG Icons ─────────────────────────────────────────────────────────
function makeIcon(paths: string) {
  return () =>
    h('svg', {
      xmlns: 'http://www.w3.org/2000/svg',
      viewBox: '0 0 24 24',
      style: 'width:18px;height:18px;fill:currentColor',
    }, [h('path', { d: paths })])
}

const IconFleet = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z')
const IconNode = makeIcon('M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z')
const IconRegion = makeIcon('M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z')
const IconHeart = makeIcon('M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z')
const IconWarn = makeIcon('M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z')
const IconError = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z')
const IconFilter = makeIcon('M10 18h4v-2h-4v2zM3 6v2h18V6H3zm3 7h12v-2H6v2z')
const IconDetail = makeIcon('M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z')
const IconEvent = makeIcon('M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z')
const IconSend = makeIcon('M2.01 21L23 12 2.01 3 2 10l15 2-15 2z')
const IconCheck = makeIcon('M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z')

// ── Computed: Filter Options ──────────────────────────────────────────────────
const regionOptions = computed<SelectOption[]>(() => {
  if (!snapshot.value) return []
  const uniq = [...new Set(snapshot.value.node_rows.map((n) => n.region).filter(Boolean))] as string[]
  return uniq.map((v) => ({ label: v, value: v }))
})

const protocolOptions = computed<SelectOption[]>(() => {
  if (!snapshot.value) return []
  const uniq = [...new Set(snapshot.value.node_rows.map((n) => n.protocol_type))]
  return uniq.map((v) => ({ label: v, value: v }))
})

const assetTypeOptions = computed<SelectOption[]>(() => {
  if (!snapshot.value) return []
  const uniq = [...new Set(snapshot.value.node_rows.map((n) => n.asset_type))]
  return uniq.map((v) => ({ label: v, value: v }))
})

const statusOptions = computed<SelectOption[]>(() => {
  if (!snapshot.value) return []
  const uniq = [...new Set(snapshot.value.node_rows.map((n) => n.status))]
  return uniq.map((v) => ({ label: v, value: v }))
})

// ── Filter State ─────────────────────────────────────────────────────────────
const filterRegion = ref<string | null>(null)
const filterProtocol = ref<string | null>(null)
const filterAssetType = ref<string | null>(null)
const filterStatus = ref<string | null>(null)
const onlyAnomalies = ref(false)

// ── Computed: Filtered Nodes ──────────────────────────────────────────────────
const filteredNodes = computed<FleetNodeDashboardRowResponse[]>(() => {
  if (!snapshot.value) return []
  return snapshot.value.node_rows.filter((n) => {
    if (filterRegion.value && n.region !== filterRegion.value) return false
    if (filterProtocol.value && n.protocol_type !== filterProtocol.value) return false
    if (filterAssetType.value && n.asset_type !== filterAssetType.value) return false
    if (filterStatus.value && n.status !== filterStatus.value) return false
    if (onlyAnomalies.value) {
      const isAnomaly = ['offline', 'failed', 'healing'].includes(n.status) || n.last_error !== null
      if (!isAnomaly) return false
    }
    return true
  })
})

// ── Computed: Selected Node ───────────────────────────────────────────────────
const selectedNode = computed<FleetNodeDashboardRowResponse | null>(() => {
  if (selectedNodeId.value === null || !snapshot.value) return null
  return snapshot.value.node_rows.find((n) => n.xboard_node_id === selectedNodeId.value) ?? null
})

// ── Computed: Node Selectbox Options ──────────────────────────────────────────
const nodeSelectOptions = computed<SelectOption[]>(() => {
  if (!snapshot.value) return []
  return snapshot.value.node_rows.map((n) => ({
    label: `${n.node_name} (${n.protocol_type})`,
    value: n.xboard_node_id,
  }))
})

// ── Computed: Manual Operation Options ───────────────────────────────────────
const manualOpOptions = computed<SelectOption[]>(() => {
  if (!selectedNode.value) return []
  const assetType = selectedNode.value.asset_type
  if (assetType === 'aws') {
    return [
      { label: t('fleet.forceHeal'), value: 'force_heal' },
      { label: t('fleet.decommissionNode'), value: 'decommission_node' },
      { label: t('fleet.reprobeNode'), value: 'reprobe_node' },
      { label: t('fleet.markManualReview'), value: 'mark_manual_review' },
    ]
  }
  return [
    { label: t('fleet.forceHealCf'), value: 'force_heal' },
    { label: t('fleet.decommissionNode'), value: 'decommission_node' },
    { label: t('fleet.reprobeNode'), value: 'reprobe_node' },
    { label: t('fleet.markManualReview'), value: 'mark_manual_review' },
  ]
})

const forceStrategyOptions: SelectOption[] = [
  { label: t('fleet.keepStrategy'), value: 'keep' },
  { label: t('fleet.replaceStrategy'), value: 'replace' },
]

// ── Computed: Fleet Summary Metrics ──────────────────────────────────────────
const totalNodes = computed(() => snapshot.value?.node_rows.length ?? 0)
const onlineNodes = computed(() => snapshot.value?.node_rows.filter((n) => n.status === 'online').length ?? 0)
const offlineNodes = computed(() => snapshot.value?.node_rows.filter((n) => n.status === 'offline').length ?? 0)
const healingNodes = computed(() => snapshot.value?.node_rows.filter((n) => n.status === 'healing').length ?? 0)
const failedNodes = computed(() => snapshot.value?.node_rows.filter((n) => n.status === 'failed').length ?? 0)
const anomalyNodes = computed(() => snapshot.value?.node_rows.filter((n) => ['offline', 'failed', 'healing'].includes(n.status) || n.last_error !== null).length ?? 0)

// ── Data Fetching ────────────────────────────────────────────────────────────
async function fetchSnapshot() {
  try {
    const { data } = await apiClient.get<DashboardSnapshotResponse>('/dashboard/snapshot')
    snapshot.value = data
    errorMsg.value = null
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string }; status?: number }; message?: string }
    errorMsg.value = axiosErr.response?.data?.error || axiosErr.message || t('fleet.loadFailed')
  } finally {
    loading.value = false
  }
}

async function fetchEvents(nodeId: number) {
  eventsLoading.value = true
  events.value = []
  try {
    const { data } = await apiClient.get<NodeEventResponse[]>(`/nodes/${nodeId}/events?limit=10`)
    events.value = data
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.response?.data?.message || axiosErr.message || t('fleet.loadEventsFailed'))
  } finally {
    eventsLoading.value = false
  }
}

async function submitManualTask() {
  if (!selectedNodeId.value || !formTaskType.value) return
  submitting.value = true
  try {
    await apiClient.post('/manual-tasks', {
      task_type: formTaskType.value,
      xboard_node_id: selectedNodeId.value,
      operator_name: formOperatorName.value || undefined,
      reason: formReason.value || undefined,
      force_strategy: formForceStrategy.value || undefined,
    })
    message.success(t('fleet.taskSubmitted'))
    formOperatorName.value = ''
    formTaskType.value = null
    formReason.value = ''
    formForceStrategy.value = null
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.response?.data?.message || axiosErr.message || t('fleet.submitTaskFailed'))
  } finally {
    submitting.value = false
  }
}

// ── Delete Node ─────────────────────────────────────────────────────────────────
async function deleteNode(xboardNodeId: number) {
  deletingNodeId.value = xboardNodeId
  try {
    await apiClient.delete(`/nodes/${xboardNodeId}`)
    message.success(`节点 #${xboardNodeId} 已删除`)
    await fetchSnapshot()
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.response?.data?.message || axiosErr.message || '删除失败')
  } finally {
    deletingNodeId.value = null
  }
}

// ── Sync with Xboard ────────────────────────────────────────────────────────────
async function syncWithXboard() {
  syncing.value = true
  try {
    const { data } = await apiClient.post<{ created: number; orphan_local_deleted: number; already_synced: number }>('/nodes/sync')
    message.success(`同步完成：新建 ${data.created}，删除本地孤立节点 ${data.orphan_local_deleted}，已同步 ${data.already_synced}`)
    await fetchSnapshot()
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.response?.data?.message || axiosErr.message || '同步失败')
  } finally {
    syncing.value = false
  }
}

// ── Watchers ──────────────────────────────────────────────────────────────────
function onSelectedNodeChange(val: number | null) {
  selectedNodeId.value = val
  formTaskType.value = null
  formReason.value = ''
  formForceStrategy.value = null
  if (val !== null) {
    fetchEvents(val)
  } else {
    events.value = []
  }
}

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtTs(value: string | null | undefined): string {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return value
  }
}

function maskAwsAccount(id: string | null): string {
  if (!id) return '—'
  return id.slice(0, 4) + '...'
}

function statusTagType(status: string): 'success' | 'error' | 'warning' | 'info' | 'default' {
  switch (status) {
    case 'online': return 'success'
    case 'offline': return 'error'
    case 'failed': return 'error'
    case 'deleted': return 'error'
    case 'healing': return 'warning'
    case 'provisioning': return 'info'
    default: return 'default'
  }
}

// ── Table Columns ────────────────────────────────────────────────────────────
const nodeTableColumns = [
  { title: t('fleet.nodeName'), key: 'node_name', ellipsis: { tooltip: true } },
  { title: t('fleet.protocol'), key: 'protocol_type' },
  { title: t('fleet.assetType'), key: 'asset_type' },
  { title: t('fleet.region'), key: 'region', render: (row: FleetNodeDashboardRowResponse) => row.region ?? '—' },
  {
    title: t('fleet.status'),
    key: 'status',
    render: (row: FleetNodeDashboardRowResponse) =>
      h(NTag, { type: statusTagType(row.status), size: 'small' }, { default: () => row.status }),
  },
  { title: t('fleet.lastHealed'), key: 'last_healed_at', render: (row: FleetNodeDashboardRowResponse) => fmtTs(row.last_healed_at) },
  {
    title: t('fleet.lastError'),
    key: 'last_error',
    ellipsis: { tooltip: true },
    render: (row: FleetNodeDashboardRowResponse) => row.last_error ?? '—',
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render: (row: FleetNodeDashboardRowResponse) =>
      row.status !== 'deleted' ? h(NPopconfirm, {
        onPositiveClick: () => deleteNode(row.xboard_node_id),
      }, {
        trigger: () => h(NButton, {
          size: 'small',
          type: 'error',
          loading: deletingNodeId.value === row.xboard_node_id,
        }, { default: () => '删除' }),
        default: () => `确认删除节点 ${row.node_name}？`,
      }) : null,
  },
]

const eventsColumns = [
  { title: t('fleet.eventId'), key: 'event_id', align: 'center' as const },
  { title: t('fleet.eventType'), key: 'event_type' },
  { title: t('fleet.from'), key: 'from_status', render: (row: NodeEventResponse) => row.from_status ?? '—' },
  { title: t('fleet.to'), key: 'to_status', render: (row: NodeEventResponse) => row.to_status ?? '—' },
  { title: t('fleet.message'), key: 'message', ellipsis: { tooltip: true } },
  { title: t('fleet.correlationId'), key: 'correlation_id', ellipsis: { tooltip: true } },
  { title: t('fleet.createdAt'), key: 'created_at', render: (row: NodeEventResponse) => fmtTs(row.created_at) },
]

// ── Lifecycle ─────────────────────────────────────────────────────────────────
const { connect, disconnect, connected: sseConnected } = useSSE({
  onSnapshotUpdated: () => fetchSnapshot(),
  onNodeStatusChanged: () => fetchSnapshot(),
})

onMounted(() => {
  fetchSnapshot()
  refreshTimer = setInterval(fetchSnapshot, 30_000)
  connect()
})

onUnmounted(() => {
  if (refreshTimer !== null) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  disconnect()
})
</script>

<template>
  <div class="fleet-page">
    <!-- ── Page Header ──────────────────────────────────────────────────────── -->
    <div class="fleet-header">
      <div class="fleet-header-icon">
        <IconFleet />
      </div>
      <div class="fleet-header-text">
        <h1 class="fleet-title">{{ t('fleet.title') }}</h1>
        <p class="fleet-subtitle">{{ t('fleet.headerDesc') }}</p>
      </div>
      <div class="fleet-header-actions">
        <NButton type="info" :loading="syncing" @click="syncWithXboard">
          {{ syncing ? '同步中...' : '同步 Xboard' }}
        </NButton>
        <div :class="['fleet-sse-badge', sseConnected ? 'fleet-sse-live' : 'fleet-sse-offline']">
          <span class="fleet-sse-dot"></span>
          {{ sseConnected ? t('fleet.sseConnected') : t('fleet.sseDisconnected') }}
        </div>
      </div>
    </div>

    <NSpin :show="loading" :description="t('fleet.loadingFleet')">
      <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px" closable @close="errorMsg = null" />

      <template v-if="snapshot">
        <!-- ── Metric Cards ──────────────────────────────────────────────────── -->
        <div class="fleet-metrics-grid">
          <div class="fleet-metric-card fleet-metric-total">
            <div class="metric-icon-wrap">
              <IconFleet />
            </div>
            <div class="metric-body">
              <div class="metric-label">{{ t('fleet.totalNodes') }}</div>
              <div class="metric-value">{{ totalNodes }}</div>
            </div>
          </div>

          <div class="fleet-metric-card fleet-metric-online">
            <div class="metric-icon-wrap">
              <IconCheck />
            </div>
            <div class="metric-body">
              <div class="metric-label">{{ t('fleet.online') }}</div>
              <div class="metric-value">{{ onlineNodes }}</div>
            </div>
          </div>

          <div class="fleet-metric-card fleet-metric-offline">
            <div class="metric-icon-wrap">
              <IconError />
            </div>
            <div class="metric-body">
              <div class="metric-label">{{ t('fleet.offline') }}</div>
              <div class="metric-value">{{ offlineNodes }}</div>
            </div>
          </div>

          <div class="fleet-metric-card fleet-metric-healing">
            <div class="metric-icon-wrap">
              <IconHeart />
            </div>
            <div class="metric-body">
              <div class="metric-label">{{ t('fleet.healing') }}</div>
              <div class="metric-value">{{ healingNodes }}</div>
            </div>
          </div>

          <div class="fleet-metric-card fleet-metric-failed">
            <div class="metric-icon-wrap">
              <IconWarn />
            </div>
            <div class="metric-body">
              <div class="metric-label">{{ t('fleet.failed') }}</div>
              <div class="metric-value">{{ failedNodes }}</div>
            </div>
          </div>

          <div class="fleet-metric-card fleet-metric-anomaly">
            <div class="metric-icon-wrap">
              <IconWarn />
            </div>
            <div class="metric-body">
              <div class="metric-label">{{ t('fleet.anomaly') }}</div>
              <div class="metric-value">{{ anomalyNodes }}</div>
            </div>
          </div>
        </div>

        <!-- ── Filter Row ──────────────────────────────────────────────────────── -->
        <div class="fleet-section">
          <div class="fleet-section-header">
            <div class="fleet-section-icon" style="background:#e0f2fe;color:#0284c7">
              <IconFilter />
            </div>
            <span class="fleet-section-title">{{ t('fleet.filters') }}</span>
            <span class="fleet-section-sub">{{ t('fleet.showNodes', { shown: filteredNodes.length, total: snapshot.node_rows.length }) }}</span>
          </div>
          <div class="fleet-filter-row">
            <NSelect
              v-model:value="filterRegion"
              :options="regionOptions"
              :placeholder="t('fleet.filterRegion')"
              clearable
              size="small"
              class="fleet-filter-select"
            />
            <NSelect
              v-model:value="filterProtocol"
              :options="protocolOptions"
              :placeholder="t('fleet.filterProtocol')"
              clearable
              size="small"
              class="fleet-filter-select"
            />
            <NSelect
              v-model:value="filterAssetType"
              :options="assetTypeOptions"
              :placeholder="t('fleet.filterAssetType')"
              clearable
              size="small"
              class="fleet-filter-select"
            />
            <NSelect
              v-model:value="filterStatus"
              :options="statusOptions"
              :placeholder="t('fleet.filterStatus')"
              clearable
              size="small"
              class="fleet-filter-select"
            />
            <NCheckbox v-model:checked="onlyAnomalies" class="fleet-anomaly-checkbox">
              <span class="fleet-anomaly-label">{{ t('fleet.onlyAnomalies') }}</span>
            </NCheckbox>
          </div>
        </div>

        <!-- ── Node Table ──────────────────────────────────────────────────────── -->
        <div class="fleet-section">
          <div class="fleet-section-header">
            <div class="fleet-section-icon" style="background:#f0fdf4;color:#16a34a">
              <IconNode />
            </div>
            <span class="fleet-section-title">{{ t('fleet.nodes') }}</span>
          </div>
          <div class="fleet-table-wrap">
            <NDataTable
              :columns="nodeTableColumns"
              :data="filteredNodes"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 15 }"
              :row-key="(row: any) => row.xboard_node_id"
            />
          </div>
        </div>

        <!-- ── Node Detail + Manual Operation ────────────────────────────────────── -->
        <div class="fleet-detail-grid">
          <!-- Node Detail Panel -->
          <div class="fleet-section fleet-section--detail">
            <div class="fleet-section-header">
              <div class="fleet-section-icon" style="background:#fef3c7;color:#d97706">
                <IconDetail />
              </div>
              <span class="fleet-section-title">{{ t('fleet.nodeDetail') }}</span>
            </div>

            <div class="fleet-node-selector-wrap">
              <NSelect
                v-model:value="selectedNodeId"
                :options="nodeSelectOptions"
                :placeholder="t('fleet.selectNode')"
                filterable
                clearable
                size="small"
                class="fleet-node-selector"
                @update:value="onSelectedNodeChange"
              />
            </div>

            <template v-if="selectedNode">
              <!-- Status Banner -->
              <div :class="['fleet-status-banner', `fleet-status-banner--${selectedNode.status}`]">
                <div class="fleet-status-indicator">
                  <span class="fleet-status-dot-large"></span>
                  <span class="fleet-status-text">{{ selectedNode.status.toUpperCase() }}</span>
                </div>
                <div v-if="selectedNode.last_error" class="fleet-status-error-msg">
                  {{ selectedNode.last_error }}
                </div>
              </div>

              <!-- Detail Grid -->
              <div class="fleet-detail-grid-inner">
                <div class="fleet-detail-item">
                  <span class="fleet-detail-label">
                    <IconNode style="width:14px;height:14px;fill:currentColor;vertical-align:middle;margin-right:4px" />
                    {{ t('fleet.nodeName') }}
                  </span>
                  <span class="fleet-detail-value">{{ selectedNode.node_name }}</span>
                </div>
                <div class="fleet-detail-item">
                  <span class="fleet-detail-label">{{ t('fleet.protocol') }}</span>
                  <span class="fleet-detail-value">{{ selectedNode.protocol_type }}</span>
                </div>
                <div class="fleet-detail-item">
                  <span class="fleet-detail-label">{{ t('fleet.assetType') }}</span>
                  <span class="fleet-detail-value">{{ selectedNode.asset_type }}</span>
                </div>
                <div class="fleet-detail-item">
                  <span class="fleet-detail-label">
                    <IconRegion style="width:14px;height:14px;fill:currentColor;vertical-align:middle;margin-right:4px" />
                    {{ t('fleet.region') }}
                  </span>
                  <span class="fleet-detail-value">{{ selectedNode.region ?? '—' }}</span>
                </div>
                <div class="fleet-detail-item fleet-detail-item--wide">
                  <span class="fleet-detail-label">{{ t('fleet.instanceId') }}</span>
                  <span class="fleet-detail-value fleet-detail-value--mono">{{ selectedNode.instance_id ?? '—' }}</span>
                </div>
                <div class="fleet-detail-item fleet-detail-item--wide">
                  <span class="fleet-detail-label">{{ t('fleet.domain') }}</span>
                  <span class="fleet-detail-value fleet-detail-value--mono">{{ selectedNode.domain_name ?? '—' }}</span>
                </div>
                <div class="fleet-detail-item fleet-detail-item--wide">
                  <span class="fleet-detail-label">{{ t('fleet.ipv6') }}</span>
                  <span class="fleet-detail-value fleet-detail-value--mono" style="font-size:11px">{{ selectedNode.ipv6_address ?? '—' }}</span>
                </div>
                <div class="fleet-detail-item">
                  <span class="fleet-detail-label">{{ t('fleet.awsAccount') }}</span>
                  <span class="fleet-detail-value fleet-detail-value--mono">{{ maskAwsAccount(selectedNode.aws_account_id) }}</span>
                </div>
                <div class="fleet-detail-item">
                  <span class="fleet-detail-label">
                    <IconHeart style="width:14px;height:14px;fill:currentColor;vertical-align:middle;margin-right:4px" />
                    {{ t('fleet.lastHealed') }}
                  </span>
                  <span class="fleet-detail-value">{{ fmtTs(selectedNode.last_healed_at) }}</span>
                </div>
              </div>

              <NDivider style="margin: 12px 0" />

              <!-- Raw JSON -->
              <div class="fleet-raw-label">{{ t('fleet.rawNodeData') }}</div>
              <NCode :code="JSON.stringify(selectedNode, null, 2)" language="json" style="max-height: 260px; overflow: auto" />

              <!-- Recent Events -->
              <NDivider style="margin: 16px 0" />
              <div class="fleet-events-header">
                <IconEvent />
                <span>{{ t('fleet.recentEvents') }}</span>
                <span class="fleet-events-count">{{ events.length }}</span>
              </div>
              <NSpin :show="eventsLoading" :description="t('tasks.loadingEvents')">
                <div class="fleet-table-wrap fleet-table-wrap--sm">
                  <NDataTable
                    :columns="eventsColumns"
                    :data="events"
                    :bordered="false"
                    :single-line="false"
                    size="small"
                    :pagination="{ pageSize: 5 }"
                  />
                </div>
              </NSpin>
            </template>

            <div v-else class="fleet-empty-state">
              <IconDetail />
              <span>{{ t('fleet.selectNode') }}</span>
            </div>
          </div>

          <!-- Manual Operation Panel -->
          <div class="fleet-section fleet-section--operation">
            <div class="fleet-section-header">
              <div class="fleet-section-icon" style="background:#fce7f3;color:#db2777">
                <IconSend />
              </div>
              <span class="fleet-section-title">{{ t('fleet.manualOperation') }}</span>
            </div>

            <template v-if="selectedNode">
              <!-- Node Badge -->
              <div class="fleet-op-node-badge">
                <div class="fleet-op-node-info">
                  <span class="fleet-op-node-name">{{ selectedNode.node_name }}</span>
                  <span class="fleet-op-node-meta">
                    {{ selectedNode.region ?? '—' }} / {{ selectedNode.protocol_type }}
                  </span>
                </div>
                <NTag :type="statusTagType(selectedNode.status)" size="small">{{ selectedNode.status }}</NTag>
              </div>

              <!-- Form -->
              <div class="fleet-op-form-wrap">
                <NForm label-placement="left" label-width="100" size="small" class="fleet-op-form">
                  <NFormItem :label="t('fleet.operatorName')">
                    <NInput v-model:value="formOperatorName" :placeholder="t('fleet.yourName')" />
                  </NFormItem>
                  <NFormItem :label="t('fleet.operation')" :required="!formTaskType">
                    <NSelect
                      v-model:value="formTaskType"
                      :options="manualOpOptions"
                      :placeholder="t('fleet.selectOperation')"
                    />
                  </NFormItem>
                  <NFormItem :label="t('fleet.reason')">
                    <NInput v-model:value="formReason" type="textarea" :placeholder="t('fleet.reason')" :rows="3" />
                  </NFormItem>
                  <NFormItem v-if="formTaskType === 'force_heal'" :label="t('fleet.forceStrategy')">
                    <NSelect
                      v-model:value="formForceStrategy"
                      :options="forceStrategyOptions"
                      :placeholder="t('fleet.forceStrategy')"
                    />
                  </NFormItem>
                </NForm>
              </div>

              <!-- Submit Button -->
              <div class="fleet-op-actions">
                <NButton
                  type="primary"
                  size="small"
                  :loading="submitting"
                  :disabled="!formTaskType"
                  @click="submitManualTask"
                >
                  <template #icon>
                    <IconSend />
                  </template>
                  {{ t('fleet.submitTask') }}
                </NButton>
              </div>
            </template>

            <div v-else class="fleet-empty-state">
              <IconSend />
              <span>{{ t('fleet.selectNodeToOperate') }}</span>
            </div>
          </div>
        </div>
      </template>
    </NSpin>
  </div>
</template>

<style scoped>
/* ── Page ──────────────────────────────────────────────────────────────────── */
.fleet-page {
  padding: 20px 24px;
  max-width: 1600px;
  margin: 0 auto;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── Page Header ───────────────────────────────────────────────────────────── */
.fleet-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.fleet-header-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  background: linear-gradient(135deg, #18a058, #36ad6a);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 22px;
  box-shadow: 0 4px 12px rgba(24, 160, 88, 0.35);
  flex-shrink: 0;
}

.fleet-header-icon svg {
  width: 26px;
  height: 26px;
}

.fleet-header-text {
  flex: 1;
}

.fleet-title {
  margin: 0 0 2px;
  font-size: 22px;
  font-weight: 800;
  color: #1a1a2e;
  letter-spacing: -0.01em;
}

.fleet-subtitle {
  margin: 0;
  font-size: 13px;
  color: #64748b;
}

.fleet-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* SSE Badge */
.fleet-sse-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
}

.fleet-sse-live {
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #bbf7d0;
}

.fleet-sse-offline {
  background: #fefce8;
  color: #a16207;
  border: 1px solid #fef08a;
}

.fleet-sse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.fleet-sse-live .fleet-sse-dot {
  background: #22c55e;
  animation: pulse-green 2s infinite;
}

.fleet-sse-offline .fleet-sse-dot {
  background: #eab308;
}

@keyframes pulse-green {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.5); opacity: 0.7; }
}

/* ── Metric Cards Grid ─────────────────────────────────────────────────────── */
.fleet-metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.fleet-metric-card {
  background: #fff;
  border-radius: 10px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  cursor: default;
  position: relative;
  overflow: hidden;
}

.fleet-metric-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 6px rgba(0,0,0,0.07), 0 2px 4px rgba(0,0,0,0.06);
}

.fleet-metric-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
}

.fleet-metric-total::before { background: linear-gradient(90deg, #6366f1, #818cf8); }
.fleet-metric-online::before { background: linear-gradient(90deg, #18a058, #36ad6a); }
.fleet-metric-offline::before { background: linear-gradient(90deg, #ef4444, #f87171); }
.fleet-metric-healing::before { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.fleet-metric-failed::before { background: linear-gradient(90deg, #dc2626, #ef4444); }
.fleet-metric-anomaly::before { background: linear-gradient(90deg, #f97316, #fb923c); }

.metric-icon-wrap {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.fleet-metric-total .metric-icon-wrap { background: #eef2ff; color: #6366f1; }
.fleet-metric-online .metric-icon-wrap { background: #f0fdf4; color: #18a058; }
.fleet-metric-offline .metric-icon-wrap { background: #fef2f2; color: #ef4444; }
.fleet-metric-healing .metric-icon-wrap { background: #fffbeb; color: #f59e0b; }
.fleet-metric-failed .metric-icon-wrap { background: #fef2f2; color: #dc2626; }
.fleet-metric-anomaly .metric-icon-wrap { background: #fff7ed; color: #f97316; }

.metric-body {
  flex: 1;
  min-width: 0;
}

.metric-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  margin-bottom: 3px;
  white-space: nowrap;
}

.metric-value {
  font-size: 26px;
  font-weight: 800;
  color: #1a1a2e;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

/* ── Section Cards ─────────────────────────────────────────────────────────── */
.fleet-section {
  background: #fff;
  border-radius: 10px;
  padding: 18px;
  margin-bottom: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06);
}

.fleet-section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.fleet-section-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 16px;
}

.fleet-section-icon svg {
  width: 16px;
  height: 16px;
}

.fleet-section-title {
  font-size: 15px;
  font-weight: 700;
  color: #1a1a2e;
  letter-spacing: -0.01em;
}

.fleet-section-sub {
  margin-left: auto;
  font-size: 12px;
  color: #64748b;
}

/* ── Filter Row ────────────────────────────────────────────────────────────── */
.fleet-filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.fleet-filter-select {
  min-width: 160px;
  flex: 1;
}

.fleet-anomaly-checkbox {
  flex-shrink: 0;
}

.fleet-anomaly-label {
  font-size: 13px;
  color: #475569;
}

/* ── Table Wrap ────────────────────────────────────────────────────────────── */
.fleet-table-wrap {
  border-radius: 8px;
  overflow: hidden;
}

.fleet-table-wrap--sm {
  margin-top: 8px;
}

/* ── Node Selector ─────────────────────────────────────────────────────────── */
.fleet-node-selector-wrap {
  margin-bottom: 14px;
}

.fleet-node-selector {
  width: 100%;
  max-width: 420px;
}

/* ── Status Banner ────────────────────────────────────────────────────────── */
.fleet-status-banner {
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.fleet-status-banner--online { background: #f0fdf4; border: 1px solid #bbf7d0; }
.fleet-status-banner--offline { background: #fef2f2; border: 1px solid #fecaca; }
.fleet-status-banner--failed { background: #fef2f2; border: 1px solid #fecaca; }
.fleet-status-banner--healing { background: #fffbeb; border: 1px solid #fef08a; }
.fleet-status-banner--provisioning { background: #eff6ff; border: 1px solid #bfdbfe; }
.fleet-status-banner--deleted { background: #f8fafc; border: 1px solid #e2e8f0; }

.fleet-status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
}

.fleet-status-dot-large {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.fleet-status-banner--online .fleet-status-dot-large { background: #22c55e; }
.fleet-status-banner--offline .fleet-status-dot-large { background: #ef4444; }
.fleet-status-banner--failed .fleet-status-dot-large { background: #dc2626; }
.fleet-status-banner--healing .fleet-status-dot-large { background: #eab308; }
.fleet-status-banner--provisioning .fleet-status-dot-large { background: #3b82f6; }

.fleet-status-text {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
}

.fleet-status-banner--online .fleet-status-text { color: #15803d; }
.fleet-status-banner--offline .fleet-status-text { color: #b91c1c; }
.fleet-status-banner--failed .fleet-status-text { color: #991b1b; }
.fleet-status-banner--healing .fleet-status-text { color: #a16207; }
.fleet-status-banner--provisioning .fleet-status-text { color: #1d4ed8; }

.fleet-status-error-msg {
  font-size: 12px;
  color: #b91c1c;
  font-family: 'Courier New', monospace;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Detail Grid ───────────────────────────────────────────────────────────── */
.fleet-detail-grid-inner {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
  margin-bottom: 4px;
}

.fleet-detail-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.fleet-detail-item--wide {
  grid-column: 1 / -1;
}

.fleet-detail-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
}

.fleet-detail-value {
  font-size: 13px;
  font-weight: 500;
  color: #1a1a2e;
}

.fleet-detail-value--mono {
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
  color: #334155;
}

/* ── Raw Label ─────────────────────────────────────────────────────────────── */
.fleet-raw-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
  margin-bottom: 6px;
}

/* ── Events Header ─────────────────────────────────────────────────────────── */
.fleet-events-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #1a1a2e;
  margin-bottom: 8px;
}

.fleet-events-count {
  background: #f1f5f9;
  border-radius: 10px;
  padding: 1px 7px;
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  margin-left: 2px;
}

/* ── Empty State ───────────────────────────────────────────────────────────── */
.fleet-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: #94a3b8;
  font-size: 13px;
  text-align: center;
}

.fleet-empty-state svg {
  width: 32px;
  height: 32px;
  fill: currentColor;
  opacity: 0.4;
}

/* ── Detail Grid Layout ────────────────────────────────────────────────────── */
.fleet-detail-grid {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 14px;
  align-items: start;
}

.fleet-section--detail {
  border: 1px solid #f0fdf4;
  background: linear-gradient(180deg, #fafafa 0%, #ffffff 100%);
}

@media (max-width: 1100px) {
  .fleet-detail-grid {
    grid-template-columns: 1fr;
  }
  .fleet-metrics-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .fleet-page {
    padding: 12px;
  }
  .fleet-metrics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .fleet-detail-grid-inner {
    grid-template-columns: 1fr;
  }
}

/* ── Operation Panel ──────────────────────────────────────────────────────── */
.fleet-section--operation {
  position: sticky;
  top: 20px;
}

.fleet-op-node-badge {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #fdf2f8, #fce7f3);
  border: 1px solid #f9a8d4;
  border-radius: 10px;
  margin-bottom: 14px;
}

.fleet-op-node-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.fleet-op-node-name {
  font-size: 14px;
  font-weight: 700;
  color: #831843;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fleet-op-node-meta {
  font-size: 11px;
  color: #be185d;
  opacity: 0.7;
}

.fleet-op-node-badge .n-tag {
  flex-shrink: 0;
}

.fleet-op-form-wrap {
  background: #fafafa;
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 12px;
}

.fleet-op-form {
  margin-bottom: 0;
}

.fleet-op-form :deep(.n-form-item) {
  margin-bottom: 10px;
}

.fleet-op-form :deep(.n-form-item:last-child) {
  margin-bottom: 0;
}

.fleet-op-form :deep(.n-form-item-label) {
  color: #64748b;
  font-size: 12px;
}

.fleet-op-form :deep(.n-input),
.fleet-op-form :deep(.n-select) {
  width: 100%;
}

.fleet-op-actions {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px;
  background: linear-gradient(135deg, #fdf2f8, #fce7f3);
  border: 1px solid #f9a8d4;
  border-radius: 10px;
}

/* ── NDataTable overrides ─────────────────────────────────────────────────── */
:deep(.n-data-table) {
  font-size: 13px;
}

:deep(.n-data-table-th) {
  background: #f8fafc !important;
  font-weight: 600 !important;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 11px !important;
  color: #64748b !important;
  padding: 8px 12px !important;
}

:deep(.n-data-table-td) {
  padding: 7px 12px !important;
  font-size: 13px !important;
}

:deep(.n-data-table-tr:hover .n-data-table-td) {
  background: #f8fafc !important;
}

:deep(.n-data-table-pagination) {
  padding: 8px 12px !important;
}
</style>
