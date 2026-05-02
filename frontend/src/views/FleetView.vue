<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import {
  NGrid,
  NGi,
  NDataTable,
  NSelect,
  NCheckbox,
  NTag,
  NSpin,
  NAlert,
  NCard,
  NCode,
  NDivider,
  NSpace,
  NButton,
  NForm,
  NFormItem,
  NInput,
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

let refreshTimer: ReturnType<typeof setInterval> | null = null

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
  <div style="padding: 16px; max-width: 1400px; margin: 0 auto">
    <!-- SSE status indicator -->
    <div style="position: fixed; top: 16px; right: 16px; z-index: 1000">
      <NTag :type="sseConnected ? 'success' : 'warning'" size="small">
        {{ sseConnected ? t('fleet.sseConnected') : t('fleet.sseDisconnected') }}
      </NTag>
    </div>

    <NSpin :show="loading" :description="t('fleet.loadingFleet')">
      <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px" closable @close="errorMsg = null" />

      <template v-if="snapshot">
        <!-- ── Filter Row ──────────────────────────────────────────────────────── -->
        <NCard :title="t('fleet.filters')" style="margin-bottom: 16px">
          <NGrid :cols="5" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
            <NGi span="1">
              <NSelect
                v-model:value="filterRegion"
                :options="regionOptions"
                :placeholder="t('fleet.filterRegion')"
                clearable
                size="small"
              />
            </NGi>
            <NGi span="1">
              <NSelect
                v-model:value="filterProtocol"
                :options="protocolOptions"
                :placeholder="t('fleet.filterProtocol')"
                clearable
                size="small"
              />
            </NGi>
            <NGi span="1">
              <NSelect
                v-model:value="filterAssetType"
                :options="assetTypeOptions"
                :placeholder="t('fleet.filterAssetType')"
                clearable
                size="small"
              />
            </NGi>
            <NGi span="1">
              <NSelect
                v-model:value="filterStatus"
                :options="statusOptions"
                :placeholder="t('fleet.filterStatus')"
                clearable
                size="small"
              />
            </NGi>
            <NGi span="1">
              <NCheckbox v-model:checked="onlyAnomalies" style="margin-top: 4px">
                <span style="font-size: 13px">{{ t('fleet.onlyAnomalies') }}</span>
              </NCheckbox>
            </NGi>
          </NGrid>
        </NCard>

        <!-- ── Node Table ──────────────────────────────────────────────────────── -->
        <NCard :title="t('fleet.nodes')" style="margin-bottom: 16px">
          <NDataTable
            :columns="nodeTableColumns"
            :data="filteredNodes"
            :bordered="false"
            :single-line="false"
            size="small"
            :pagination="{ pageSize: 15 }"
            :row-key="(row: any) => row.xboard_node_id"
          />
          <template #footer>
            <NText depth="3" style="font-size: 13px">
              {{ t('fleet.showNodes', { shown: filteredNodes.length, total: snapshot.node_rows.length }) }}
            </NText>
          </template>
        </NCard>

        <!-- ── Node Detail ────────────────────────────────────────────────────── -->
        <NCard :title="t('fleet.nodeDetail')" style="margin-bottom: 16px">
          <NSelect
            v-model:value="selectedNodeId"
            :options="nodeSelectOptions"
            :placeholder="t('fleet.selectNode')"
            filterable
            clearable
            size="small"
            style="margin-bottom: 12px; max-width: 400px"
            @update:value="onSelectedNodeChange"
          />

          <template v-if="selectedNode">
            <NGrid :cols="4" :x-gap="16" :y-gap="12" responsive="screen" item-responsive style="margin-bottom: 16px">
              <NGi span="1">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.status') }}</div>
                <NTag :type="statusTagType(selectedNode.status)" size="small" style="margin-top: 4px">
                  {{ selectedNode.status }}
                </NTag>
              </NGi>
              <NGi span="1">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.protocol') }}</div>
                <div style="margin-top: 4px">{{ selectedNode.protocol_type }}</div>
              </NGi>
              <NGi span="1">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.assetType') }}</div>
                <div style="margin-top: 4px">{{ selectedNode.asset_type }}</div>
              </NGi>
              <NGi span="1">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.region') }}</div>
                <div style="margin-top: 4px">{{ selectedNode.region ?? '—' }}</div>
              </NGi>
              <NGi span="1">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.instanceId') }}</div>
                <div style="margin-top: 4px">{{ selectedNode.instance_id ?? '—' }}</div>
              </NGi>
              <NGi span="1">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.domain') }}</div>
                <div style="margin-top: 4px">{{ selectedNode.domain_name ?? '—' }}</div>
              </NGi>
              <NGi span="1">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.ipv6') }}</div>
                <div style="margin-top: 4px; font-size: 12px; word-break: break-all">{{ selectedNode.ipv6_address ?? '—' }}</div>
              </NGi>
              <NGi span="1">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.awsAccount') }}</div>
                <div style="margin-top: 4px">{{ maskAwsAccount(selectedNode.aws_account_id) }}</div>
              </NGi>
              <NGi span="1">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.lastHealed') }}</div>
                <div style="margin-top: 4px">{{ fmtTs(selectedNode.last_healed_at) }}</div>
              </NGi>
              <NGi span="3">
                <div style="font-size: 12px; color: var(--n-text-color-3)">{{ t('fleet.lastError') }}</div>
                <div style="margin-top: 4px; color: var(--n-color-error); font-size: 13px">
                  {{ selectedNode.last_error ?? '—' }}
                </div>
              </NGi>
            </NGrid>

            <NDivider />
            <div style="font-size: 12px; color: var(--n-text-color-3); margin-bottom: 8px">{{ t('fleet.rawNodeData') }}</div>
            <NCode :code="JSON.stringify(selectedNode, null, 2)" language="json" style="max-height: 300px; overflow: auto" />

            <!-- ── Recent Events ─────────────────────────────────────────────── -->
            <NDivider />
            <div style="font-size: 14px; font-weight: 500; margin-bottom: 8px">{{ t('fleet.recentEvents') }}</div>
            <NSpin :show="eventsLoading" :description="t('tasks.loadingEvents')">
              <NDataTable
                :columns="eventsColumns"
                :data="events"
                :bordered="false"
                :single-line="false"
                size="small"
                :pagination="{ pageSize: 5 }"
              />
            </NSpin>

            <!-- ── Manual Operation Form ──────────────────────────────────────── -->
            <NDivider />
            <div style="font-size: 14px; font-weight: 500; margin-bottom: 12px">{{ t('fleet.manualOperation') }}</div>
            <NForm label-placement="left" label-width="120" size="small">
              <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem :label="t('fleet.operatorName')">
                    <NInput v-model:value="formOperatorName" :placeholder="t('fleet.yourName')" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem :label="t('fleet.operation')">
                    <NSelect
                      v-model:value="formTaskType"
                      :options="manualOpOptions"
                      :placeholder="t('fleet.selectOperation')"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem :label="t('fleet.reason')">
                    <NInput v-model:value="formReason" :placeholder="t('fleet.reason')" />
                  </NFormItem>
                </NGi>
                <NGi v-if="formTaskType === 'force_heal'" span="1">
                  <NFormItem :label="t('fleet.forceStrategy')">
                    <NSelect
                      v-model:value="formForceStrategy"
                      :options="forceStrategyOptions"
                      :placeholder="t('fleet.forceStrategy')"
                    />
                  </NFormItem>
                </NGi>
              </NGrid>
              <NSpace style="margin-top: 8px">
                <NButton
                  type="primary"
                  size="small"
                  :loading="submitting"
                  :disabled="!formTaskType"
                  @click="submitManualTask"
                >
                  {{ t('fleet.submitTask') }}
                </NButton>
              </NSpace>
            </NForm>
          </template>

          <NText v-else depth="3">{{ t('fleet.selectNode') }}</NText>
        </NCard>
      </template>
    </NSpin>
  </div>
</template>
