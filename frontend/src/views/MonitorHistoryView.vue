<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { h } from 'vue'
import {
  NSpin,
  NAlert,
  NStatistic,
  NDataTable,
  NTabs,
  NTab,
  NSelect,
  NTag,
  NCard,
  NSpace,
  NText,
  NEmpty,
} from 'naive-ui'
import type { SelectOption } from 'naive-ui'
import apiClient from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import type {
  MonitorCycleResponse,
  DetectionRecordResponse,
} from '@/types/api'

const { t } = useI18n()

// ── State ────────────────────────────────────────────────────────────────────
const cycles = ref<MonitorCycleResponse[]>([])
const detections = ref<DetectionRecordResponse[]>([])
const loadingCycles = ref(true)
const loadingDetections = ref(false)
const fetchError = ref<string | null>(null)
const detectionError = ref<string | null>(null)

let pollTimer: ReturnType<typeof setInterval> | null = null

const selectedCycleId = ref<number | null>(null)
const statusFilter = ref<string>('全部')
const detectionStatusFilter = ref<string>('全部')
const cycleLimit = ref<number>(100)

// ── Computed ─────────────────────────────────────────────────────────────────
const succeededCycles = computed(() => cycles.value.filter(c => c.status === 'succeeded').length)
const failedCycles = computed(() => cycles.value.filter(c => c.status === 'failed').length)
const runningCycles = computed(() => cycles.value.filter(c => c.status === 'running').length)
const totalCandidates = computed(() => cycles.value.reduce((s, c) => s + c.candidate_count, 0))
const totalHealed = computed(() => cycles.value.reduce((s, c) => s + c.healed_count, 0))

const statusOptions: SelectOption[] = [
  { label: t('monitor.all'), value: '全部' },
  { label: 'succeeded', value: 'succeeded' },
  { label: 'failed', value: 'failed' },
  { label: 'running', value: 'running' },
]

const limitOptions: SelectOption[] = [
  { label: '10', value: 10 },
  { label: '20', value: 20 },
  { label: '50', value: 50 },
  { label: '100', value: 100 },
]

const detectionStatusOptions: SelectOption[] = [
  { label: t('monitor.all'), value: '全部' },
  { label: 'confirmed_blocked_by_gfw', value: 'confirmed_blocked_by_gfw' },
  { label: 'candidate', value: 'candidate' },
  { label: t('monitor.other'), value: 'other' },
]

const filteredCycles = computed(() => {
  let list = cycles.value
  if (statusFilter.value !== '全部') {
    list = list.filter(c => c.status === statusFilter.value)
  }
  return list.slice(0, cycleLimit.value)
})

const selectedCycle = computed(() =>
  cycles.value.find(c => c.cycle_id === selectedCycleId.value) ?? null
)

const confirmedBlockedDetections = computed(() =>
  detections.value.filter(d => d.detection_status === 'confirmed_blocked_by_gfw')
)

const confirmedCount = computed(() => confirmedBlockedDetections.value.length)
const candidateCount = computed(() => detections.value.filter(d => d.detection_status === 'candidate').length)
const otherCount = computed(() =>
  detections.value.filter(d => d.detection_status !== 'confirmed_blocked_by_gfw' && d.detection_status !== 'candidate').length
)

const filteredDetections = computed(() => {
  if (detectionStatusFilter.value === '全部') return detections.value
  if (detectionStatusFilter.value === 'other') {
    return detections.value.filter(d => d.detection_status !== 'confirmed_blocked_by_gfw' && d.detection_status !== 'candidate')
  }
  return detections.value.filter(d => d.detection_status === detectionStatusFilter.value)
})

interface ConfirmedNodeRow {
  node_id: number
  confirm_count: number
  latest_cycle: number
  triggered_healing: 'Yes' | 'No'
}

const confirmedNodeRows = computed<ConfirmedNodeRow[]>(() => {
  const groups: Record<number, { count: number; latest_cycle: number }> = {}
  for (const d of confirmedBlockedDetections.value) {
    if (!groups[d.xboard_node_id]) {
      groups[d.xboard_node_id] = { count: 0, latest_cycle: d.cycle_id }
    }
    groups[d.xboard_node_id].count++
    if (d.cycle_id > groups[d.xboard_node_id].latest_cycle) {
      groups[d.xboard_node_id].latest_cycle = d.cycle_id
    }
  }
  return Object.entries(groups).map(([nodeId, g]) => ({
    node_id: Number(nodeId),
    confirm_count: g.count,
    latest_cycle: g.latest_cycle,
    triggered_healing: g.count >= 2 ? 'Yes' : 'No',
  }))
})

const cycleSelectOptions = computed<SelectOption[]>(() =>
  cycles.value.map(c => ({ label: `Cycle #${c.cycle_id} (${c.status})`, value: c.cycle_id }))
)

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtTs(value: string | null): string {
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

function statusTagType(status: string): 'success' | 'error' | 'info' | 'warning' | 'default' {
  if (status === 'succeeded') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'running') return 'info'
  return 'default'
}

function detectionTagType(status: string): 'error' | 'warning' | 'default' {
  if (status === 'confirmed_blocked_by_gfw') return 'error'
  if (status === 'candidate') return 'warning'
  return 'default'
}

function detectionTagLabel(status: string): string {
  if (status === 'confirmed_blocked_by_gfw') return t('monitor.gfwBlocked')
  if (status === 'candidate') return t('monitor.candidate')
  return status
}

function healingTagType(val: 'Yes' | 'No'): 'success' | 'error' {
  return val === 'Yes' ? 'success' : 'error'
}

// ── Data Fetching ─────────────────────────────────────────────────────────────
async function fetchCycles() {
  loadingCycles.value = true
  fetchError.value = null
  try {
    const { data } = await apiClient.get<MonitorCycleResponse[]>('/monitor/cycles', { params: { limit: 100 } })
    cycles.value = data
    if (data.length > 0) {
      selectedCycleId.value = data[0].cycle_id
    }
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string }; status?: number }; message?: string }
    fetchError.value = axiosErr.response?.data?.error || axiosErr.message || t('monitor.loadCyclesFailed')
  } finally {
    loadingCycles.value = false
  }
}

async function fetchDetections(cycleId: number) {
  loadingDetections.value = true
  detectionError.value = null
  try {
    const { data } = await apiClient.get<DetectionRecordResponse[]>('/monitor/detections', {
      params: { cycle_id: cycleId },
    })
    detections.value = data
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string }; status?: number }; message?: string }
    detectionError.value = axiosErr.response?.data?.error || axiosErr.message || t('monitor.loadDetectionsFailed')
    detections.value = []
  } finally {
    loadingDetections.value = false
  }
}

// ── Column Definitions ────────────────────────────────────────────────────────
const cycleColumns = [
  { title: t('monitor.cycleId'), key: 'cycle_id', align: 'center' as const, width: 90 },
  {
    title: t('monitor.status'),
    key: 'status',
    align: 'center' as const,
    width: 110,
    render: (row: MonitorCycleResponse) =>
      h(NTag, { type: statusTagType(row.status), size: 'small' }, { default: () => row.status }),
  },
  { title: t('monitor.candidates'), key: 'candidate_count', align: 'center' as const, width: 100 },
  { title: t('monitor.confirmed'), key: 'confirmed_count', align: 'center' as const, width: 100 },
  { title: t('monitor.healed'), key: 'healed_count', align: 'center' as const, width: 80 },
  { title: t('monitor.failed'), key: 'failed_count', align: 'center' as const, width: 80 },
  { title: t('monitor.startedAt'), key: 'started_at', render: (row: MonitorCycleResponse) => fmtTs(row.started_at) },
  { title: t('monitor.finishedAt'), key: 'finished_at', render: (row: MonitorCycleResponse) => fmtTs(row.finished_at) },
]

const detectionColumns = [
  { title: t('monitor.nodeIdShort'), key: 'xboard_node_id', align: 'center' as const, width: 90 },
  { title: t('monitor.detectionType'), key: 'detection_type', width: 140 },
  {
    title: t('monitor.detectionStatus'),
    key: 'detection_status',
    width: 140,
    render: (row: DetectionRecordResponse) =>
      h(NTag, { type: detectionTagType(row.detection_status), size: 'small' }, { default: () => detectionTagLabel(row.detection_status) }),
  },
  { title: t('monitor.reason'), key: 'reason', ellipsis: { tooltip: true } },
  { title: t('monitor.probeProvider'), key: 'probe_provider', width: 140 },
  { title: t('monitor.createdAt'), key: 'created_at', render: (row: DetectionRecordResponse) => fmtTs(row.created_at) },
]

const confirmedNodeColumns = [
  { title: t('monitor.nodeId'), key: 'node_id', align: 'center' as const, width: 100 },
  { title: t('monitor.confirmCount'), key: 'confirm_count', align: 'center' as const, width: 140 },
  { title: t('monitor.latestCycle'), key: 'latest_cycle', align: 'center' as const, width: 130 },
  {
    title: t('monitor.triggeredHealing'),
    key: 'triggered_healing',
    align: 'center' as const,
    width: 160,
    render: (row: ConfirmedNodeRow) =>
      h(NTag, { type: healingTagType(row.triggered_healing), size: 'small' }, { default: () => row.triggered_healing }),
  },
]

// ── Watchers ──────────────────────────────────────────────────────────────────
function onCycleSelect(val: number | null) {
  if (val !== null) {
    selectedCycleId.value = val
  } else {
    detections.value = []
  }
}

// Auto-fetch detections whenever a cycle is selected (works across all tabs)
watch(selectedCycleId, (newId, oldId) => {
  if (newId !== null && newId !== oldId) {
    fetchDetections(newId)
  }
})

// ── Lifecycle ────────────────────────────────────────────────────────────────
onMounted(() => {
  fetchCycles()
  pollTimer = setInterval(() => {
    if (!loadingCycles.value) {
      fetchCycles()
    }
  }, 30_000)
})

onUnmounted(() => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <div style="padding: 16px; max-width: 1400px; margin: 0 auto">
    <NSpin :show="loadingCycles" :description="t('app.loading')">
      <NAlert v-if="fetchError" type="error" :title="fetchError" style="margin-bottom: 16px" closable @close="fetchError = null" />

      <NTabs type="line" animated>
        <!-- ══ Tab 1: Scan Cycle List ═══════════════════════════════════════════════ -->
        <NTab name="cycles" :tab="t('monitor.scanCycleList')">
          <NCard style="margin-top: 12px">
            <!-- Stats row -->
            <div class="stats-row" style="display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 16px">
              <NStatistic :label="t('monitor.totalCycles')" :value="cycles.length" />
              <NStatistic :label="t('monitor.succeeded')" :value="succeededCycles" />
              <NStatistic :label="t('monitor.failed')" :value="failedCycles" />
              <NStatistic :label="t('monitor.running')" :value="runningCycles" />
              <NStatistic :label="t('monitor.totalCandidates')" :value="totalCandidates" />
              <NStatistic :label="t('monitor.totalHealed')" :value="totalHealed" />
            </div>

            <!-- Controls -->
            <NSpace :size="12" style="margin-bottom: 12px">
              <NSelect
                v-model:value="statusFilter"
                :options="statusOptions"
                style="width: 160px"
                :placeholder="t('monitor.filterStatus')"
              />
              <NSelect
                v-model:value="cycleLimit"
                :options="limitOptions"
                style="width: 100px"
                :placeholder="t('monitor.limit')"
              />
            </NSpace>

            <!-- Cycle table with row-click to select -->
            <NDataTable
              :columns="cycleColumns"
              :data="filteredCycles"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 10 }"
              :row-key="(row: any) => row.cycle_id"
              :row-props="(row: any) => ({
                style: 'cursor: pointer',
                onClick: () => onCycleSelect(row.cycle_id),
              })"
              :highlight-row="selectedCycleId !== null"
            />

            <!-- Cycle detail + detections (always shown when a cycle is selected) -->
            <template v-if="selectedCycle">
              <div style="margin: 20px 0 12px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px">
                <div style="padding: 10px 12px; background: #f5f5f5; border-radius: 6px; text-align: center">
                  <div style="font-size: 12px; color: #888">{{ t('monitor.status') }}</div>
                  <NTag :type="statusTagType(selectedCycle.status)" size="small" style="margin-top: 4px">{{ selectedCycle.status }}</NTag>
                </div>
                <div style="padding: 10px 12px; background: #f5f5f5; border-radius: 6px; text-align: center">
                  <div style="font-size: 12px; color: #888">{{ t('monitor.candidates') }}</div>
                  <div style="font-size: 18px; font-weight: 600; margin-top: 4px">{{ selectedCycle.candidate_count }}</div>
                </div>
                <div style="padding: 10px 12px; background: #f5f5f5; border-radius: 6px; text-align: center">
                  <div style="font-size: 12px; color: #888">{{ t('monitor.confirmed') }}</div>
                  <div style="font-size: 18px; font-weight: 600; margin-top: 4px">{{ selectedCycle.confirmed_count }}</div>
                </div>
                <div style="padding: 10px 12px; background: #f5f5f5; border-radius: 6px; text-align: center">
                  <div style="font-size: 12px; color: #888">{{ t('monitor.healed') }}</div>
                  <div style="font-size: 18px; font-weight: 600; margin-top: 4px">{{ selectedCycle.healed_count }}</div>
                </div>
                <div style="padding: 10px 12px; background: #f5f5f5; border-radius: 6px; text-align: center; grid-column: span 2">
                  <div style="font-size: 12px; color: #888">{{ t('monitor.startedAt') }}</div>
                  <div style="font-size: 13px; font-weight: 500; margin-top: 4px">{{ fmtTs(selectedCycle.started_at) }}</div>
                </div>
                <div style="padding: 10px 12px; background: #f5f5f5; border-radius: 6px; text-align: center; grid-column: span 2">
                  <div style="font-size: 12px; color: #888">{{ t('monitor.finishedAt') }}</div>
                  <div style="font-size: 13px; font-weight: 500; margin-top: 4px">{{ fmtTs(selectedCycle.finished_at) }}</div>
                </div>
              </div>
              <NAlert v-if="selectedCycle.error_message" type="error" style="margin-bottom: 12px">
                {{ selectedCycle.error_message }}
              </NAlert>

              <NSpin :show="loadingDetections" :description="t('monitor.loadingDetections')">
                <NAlert v-if="detectionError" type="error" :title="detectionError" style="margin-bottom: 12px" closable @close="detectionError = null" />

                <NText depth="3" style="font-size: 13px; display: block; margin-bottom: 8px">
                  {{ t('monitor.detectionsForCycle', { id: selectedCycleId ?? '?' }) }}
                </NText>

                <template v-if="detections.length === 0 && !loadingDetections && !detectionError">
                  <NEmpty :description="t('monitor.noDetections')" style="margin: 24px 0" />
                </template>

                <template v-else>
                  <NDataTable
                    :columns="detectionColumns"
                    :data="detections"
                    :bordered="false"
                    :single-line="false"
                    size="small"
                    :pagination="{ pageSize: 10 }"
                    :row-key="(row: any) => row.id"
                  >
                    <template #empty>
                      <NEmpty :description="t('monitor.noDetections')" />
                    </template>
                  </NDataTable>
                </template>
              </NSpin>
            </template>
          </NCard>
        </NTab>

        <!-- ══ Tab 2: Detection Records ═══════════════════════════════════════════ -->
        <NTab name="detections" :tab="t('monitor.nodeDetectionRecords')">
          <NCard style="margin-top: 12px">
            <NSpace :size="12" style="margin-bottom: 16px" align="center">
              <NSelect
                v-model:value="selectedCycleId"
                :options="cycleSelectOptions"
                style="width: 280px"
                :placeholder="t('monitor.selectCycle')"
                @update:value="onCycleSelect"
              />
              <NSelect
                v-model:value="detectionStatusFilter"
                :options="detectionStatusOptions"
                style="width: 200px"
                :placeholder="t('monitor.filterStatus')"
              />
            </NSpace>

            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px">
              <NStatistic :label="t('monitor.gfwBlocked')" :value="confirmedCount">
                <template #suffix>
                  <NTag type="error" size="small" style="margin-left: 6px">GFW Blocked</NTag>
                </template>
              </NStatistic>
              <NStatistic :label="t('monitor.candidate')" :value="candidateCount">
                <template #suffix>
                  <NTag type="warning" size="small" style="margin-left: 6px">Candidate</NTag>
                </template>
              </NStatistic>
              <NStatistic :label="t('monitor.other')" :value="otherCount" />
            </div>

            <NSpin :show="loadingDetections" :description="t('monitor.loadingDetections')">
              <NAlert v-if="detectionError" type="error" :title="detectionError" style="margin-bottom: 12px" closable @close="detectionError = null" />

              <template v-if="selectedCycleId === null">
                <NEmpty :description="t('monitor.selectCycleAbove')" style="margin: 24px 0" />
              </template>
              <template v-else-if="filteredDetections.length === 0 && !loadingDetections && !detectionError">
                <NEmpty :description="t('monitor.noDetectionsMatch')" style="margin: 24px 0" />
              </template>
              <template v-else>
                <NDataTable
                  :columns="detectionColumns"
                  :data="filteredDetections"
                  :bordered="false"
                  :single-line="false"
                  size="small"
                  :pagination="{ pageSize: 10 }"
                  :row-key="(row: any) => row.id"
                >
                  <template #empty>
                    <NEmpty :description="t('monitor.noDetections')" />
                  </template>
                </NDataTable>
              </template>
            </NSpin>
          </NCard>
        </NTab>

        <!-- ══ Tab 3: Block Confirmation Summary ══════════════════════════════════ -->
        <NTab name="confirmation" :tab="t('monitor.blockConfirmationProgress')">
          <NCard style="margin-top: 12px">
            <NAlert type="info" :title="t('monitor.blockConfirmation')" style="margin-bottom: 16px">
              {{ t('monitor.blockConfirmationDesc') }}
            </NAlert>

            <!-- Aggregate confirmed nodes across ALL cycles -->
            <NSpin :show="loadingCycles || loadingDetections" :description="t('monitor.loadingDetections')">
              <NAlert v-if="detectionError" type="error" :title="detectionError" style="margin-bottom: 12px" closable @close="detectionError = null" />

              <NText depth="3" style="font-size: 13px; display: block; margin-bottom: 8px">
                {{ t('monitor.confirmedNodesAcrossAllCycles') || 'GFW 阻断确认节点汇总（所有周期）' }}
              </NText>

              <template v-if="confirmedNodeRows.length === 0 && !loadingCycles && !loadingDetections">
                <NEmpty :description="t('monitor.noConfirmations')" style="margin: 24px 0" />
              </template>
              <template v-else>
                <NDataTable
                  :columns="confirmedNodeColumns"
                  :data="confirmedNodeRows"
                  :bordered="false"
                  :single-line="false"
                  size="small"
                  :pagination="{ pageSize: 10 }"
                  :row-key="(row: any) => row.node_id"
                />
              </template>
            </NSpin>
          </NCard>
        </NTab>
      </NTabs>
    </NSpin>
  </div>
</template>
