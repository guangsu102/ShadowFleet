<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { h } from 'vue'
import {
  NSpin,
  NAlert,
  NDataTable,
  NTabs,
  NTab,
  NSelect,
  NTag,
  NText,
  NEmpty,
  NIcon,
} from 'naive-ui'
import type { SelectOption } from 'naive-ui'
import apiClient from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import type {
  MonitorCycleResponse,
  DetectionRecordResponse,
} from '@/types/api'

const { t } = useI18n()

// ── Icon factories ───────────────────────────────────────────────────────────
function makeIcon(paths: string) {
  return () => h(NIcon, null, {
    default: () => h('svg', { xmlns: 'http://www.w3.org/2000/svg', viewBox: '0 0 24 24', style: 'width:18px;height:18px;fill:currentColor' }, [
      h('path', { d: paths }),
    ]),
  })
}

const IconCycle   = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z')
const IconCheck   = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z')
const IconFail    = makeIcon('M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z')
const IconRun     = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z')
const IconCands   = makeIcon('M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z')
const IconHeal    = makeIcon('M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z')
const IconBlock   = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8 0-1.85.63-3.55 1.69-4.9L16.9 18.31C15.55 19.37 13.85 20 12 20zm6.31-3.1L7.1 5.69C8.45 4.63 10.15 4 12 4c4.42 0 8 3.58 8 8 0 1.85-.63 3.55-1.69 4.9z')
const IconCand2   = makeIcon('M11 15h2v2h-2zm0-8h2v6h-2zm.99-5C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z')
const IconOther   = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z')

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
    const d = new Date(value)
    const now = Date.now()
    const diff = now - d.getTime()
    const m = Math.floor(diff / 60000)
    const h = Math.floor(diff / 3600000)
    const D = Math.floor(diff / 86400000)
    if (m < 1) return '刚刚'
    if (m < 60) return `${m}m 前`
    if (h < 24) return `${h}h 前`
    if (D < 7) return `${D}d 前`
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
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
  { title: '#', key: '_index', width: 50, align: 'center' as const,
    render: (_: any, i: number) => h('span', { style: 'color:#94a3b8;font-size:12px;font-weight:500' }, i + 1) },
  { title: t('monitor.cycleId'), key: 'cycle_id', align: 'center' as const, width: 80 },
  {
    title: t('monitor.status'),
    key: 'status',
    align: 'center' as const,
    width: 100,
    render: (row: MonitorCycleResponse) =>
      h(NTag, { type: statusTagType(row.status), size: 'small', round: true }, { default: () => row.status }),
  },
  { title: t('monitor.candidates'), key: 'candidate_count', align: 'center' as const, width: 90 },
  { title: t('monitor.confirmed'), key: 'confirmed_count', align: 'center' as const, width: 90 },
  { title: t('monitor.healed'), key: 'healed_count', align: 'center' as const, width: 80 },
  { title: t('monitor.failed'), key: 'failed_count', align: 'center' as const, width: 80 },
  { title: t('monitor.startedAt'), key: 'started_at', width: 170, render: (row: MonitorCycleResponse) => fmtTs(row.started_at) },
  { title: t('monitor.finishedAt'), key: 'finished_at', width: 170, render: (row: MonitorCycleResponse) => fmtTs(row.finished_at) },
]

const detectionColumns = [
  { title: '#', key: '_index', width: 50, align: 'center' as const,
    render: (_: any, i: number) => h('span', { style: 'color:#94a3b8;font-size:12px;font-weight:500' }, i + 1) },
  { title: t('monitor.nodeIdShort'), key: 'xboard_node_id', align: 'center' as const, width: 80 },
  { title: t('monitor.detectionType'), key: 'detection_type', width: 130, ellipsis: { tooltip: true } },
  {
    title: t('monitor.detectionStatus'),
    key: 'detection_status',
    width: 130,
    render: (row: DetectionRecordResponse) =>
      h(NTag, { type: detectionTagType(row.detection_status), size: 'small', round: true }, { default: () => detectionTagLabel(row.detection_status) }),
  },
  { title: t('monitor.reason'), key: 'reason', ellipsis: { tooltip: true } },
  { title: t('monitor.probeProvider'), key: 'probe_provider', width: 130, ellipsis: { tooltip: true } },
  { title: t('monitor.createdAt'), key: 'created_at', width: 170, render: (row: DetectionRecordResponse) => fmtTs(row.created_at) },
]

const confirmedNodeColumns = [
  { title: '#', key: '_index', width: 50, align: 'center' as const,
    render: (_: any, i: number) => h('span', { style: 'color:#94a3b8;font-size:12px;font-weight:500' }, i + 1) },
  { title: t('monitor.nodeId'), key: 'node_id', align: 'center' as const, width: 80 },
  { title: t('monitor.confirmCount'), key: 'confirm_count', align: 'center' as const, width: 110 },
  { title: t('monitor.latestCycle'), key: 'latest_cycle', align: 'center' as const, width: 110 },
  {
    title: t('monitor.triggeredHealing'),
    key: 'triggered_healing',
    align: 'center' as const,
    width: 130,
    render: (row: ConfirmedNodeRow) =>
      h(NTag, { type: healingTagType(row.triggered_healing), size: 'small', round: true }, { default: () => row.triggered_healing }),
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
  <div class="monitor-history-page">
    <NSpin :show="loadingCycles" :description="t('app.loading')">
      <NAlert v-if="fetchError" type="error" :title="fetchError" style="margin-bottom: 16px" closable @close="fetchError = null" />

      <NTabs type="line" animated>
        <!-- ══ Tab 1: Scan Cycle List ═══════════════════════════════════════════════ -->
        <NTab name="cycles" :tab="t('monitor.scanCycleList')">
          <div class="tab-card">
            <!-- Stats row -->
            <div class="stats-row">
              <div class="stat-item stat-all">
                <div class="stat-icon"><NIcon :component="IconCycle" /></div>
                <div class="stat-body">
                  <div class="stat-value">{{ cycles.length }}</div>
                  <div class="stat-label">{{ t('monitor.totalCycles') }}</div>
                </div>
              </div>
              <div class="stat-item stat-success">
                <div class="stat-icon"><NIcon :component="IconCheck" /></div>
                <div class="stat-body">
                  <div class="stat-value">{{ succeededCycles }}</div>
                  <div class="stat-label">{{ t('monitor.succeeded') }}</div>
                </div>
              </div>
              <div class="stat-item stat-error">
                <div class="stat-icon"><NIcon :component="IconFail" /></div>
                <div class="stat-body">
                  <div class="stat-value">{{ failedCycles }}</div>
                  <div class="stat-label">{{ t('monitor.failed') }}</div>
                </div>
              </div>
              <div class="stat-item stat-info">
                <div class="stat-icon"><NIcon :component="IconRun" /></div>
                <div class="stat-body">
                  <div class="stat-value">{{ runningCycles }}</div>
                  <div class="stat-label">{{ t('monitor.running') }}</div>
                </div>
              </div>
              <div class="stat-item stat-warn">
                <div class="stat-icon"><NIcon :component="IconCands" /></div>
                <div class="stat-body">
                  <div class="stat-value">{{ totalCandidates }}</div>
                  <div class="stat-label">{{ t('monitor.totalCandidates') }}</div>
                </div>
              </div>
              <div class="stat-item stat-heal">
                <div class="stat-icon"><NIcon :component="IconHeal" /></div>
                <div class="stat-body">
                  <div class="stat-value">{{ totalHealed }}</div>
                  <div class="stat-label">{{ t('monitor.totalHealed') }}</div>
                </div>
              </div>
            </div>

            <!-- Controls -->
            <div class="section-label">{{ t('monitor.filter') || '筛选与控制' }}</div>
            <div class="controls-row">
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
            </div>

            <!-- Cycle table with row-click to select -->
            <div class="table-wrapper">
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
            </div>

            <!-- Cycle detail + detections (always shown when a cycle is selected) -->
            <template v-if="selectedCycle">
              <div class="cycle-detail-grid">
                <div class="detail-item">
                  <div class="detail-label">{{ t('monitor.status') }}</div>
                  <NTag :type="statusTagType(selectedCycle.status)" size="small" style="margin-top: 4px">{{ selectedCycle.status }}</NTag>
                </div>
                <div class="detail-item">
                  <div class="detail-label">{{ t('monitor.candidates') }}</div>
                  <div class="detail-value">{{ selectedCycle.candidate_count }}</div>
                </div>
                <div class="detail-item">
                  <div class="detail-label">{{ t('monitor.confirmed') }}</div>
                  <div class="detail-value">{{ selectedCycle.confirmed_count }}</div>
                </div>
                <div class="detail-item">
                  <div class="detail-label">{{ t('monitor.healed') }}</div>
                  <div class="detail-value">{{ selectedCycle.healed_count }}</div>
                </div>
                <div class="detail-item detail-wide">
                  <div class="detail-label">{{ t('monitor.startedAt') }}</div>
                  <div class="detail-value">{{ fmtTs(selectedCycle.started_at) }}</div>
                </div>
                <div class="detail-item detail-wide">
                  <div class="detail-label">{{ t('monitor.finishedAt') }}</div>
                  <div class="detail-value">{{ fmtTs(selectedCycle.finished_at) }}</div>
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
                  <div class="table-wrapper">
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
                  </div>
                </template>
              </NSpin>
            </template>
          </div>
        </NTab>

        <!-- ══ Tab 2: Detection Records ═══════════════════════════════════════════ -->
        <NTab name="detections" :tab="t('monitor.nodeDetectionRecords')">
          <div class="tab-card">
            <div class="section-label">{{ t('monitor.filter') || '筛选与控制' }}</div>
            <div class="controls-row">
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
            </div>

            <NSpin :show="loadingDetections" :description="t('monitor.loadingDetections')">
              <NAlert v-if="detectionError" type="error" :title="detectionError" style="margin-bottom: 12px" closable @close="detectionError = null" />

              <template v-if="selectedCycleId === null">
                <NEmpty :description="t('monitor.selectCycleAbove')" style="margin: 24px 0" />
              </template>
              <template v-else>
                <div class="table-wrapper">
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
                </div>
              </template>
            </NSpin>

            <template v-if="selectedCycleId !== null">
              <div class="stats-row stats-row-3" style="margin-top: 16px">
                <div class="stat-item stat-error">
                  <div class="stat-icon"><NIcon :component="IconBlock" /></div>
                  <div class="stat-body">
                    <div class="stat-value">{{ confirmedCount }}</div>
                    <div class="stat-label">{{ t('monitor.gfwBlocked') }}</div>
                  </div>
                  <NTag type="error" size="small" round>GFW Blocked</NTag>
                </div>
                <div class="stat-item stat-warn">
                  <div class="stat-icon"><NIcon :component="IconCand2" /></div>
                  <div class="stat-body">
                    <div class="stat-value">{{ candidateCount }}</div>
                    <div class="stat-label">{{ t('monitor.candidate') }}</div>
                  </div>
                  <NTag type="warning" size="small" round>Candidate</NTag>
                </div>
                <div class="stat-item stat-neutral">
                  <div class="stat-icon"><NIcon :component="IconOther" /></div>
                  <div class="stat-body">
                    <div class="stat-value">{{ otherCount }}</div>
                    <div class="stat-label">{{ t('monitor.other') }}</div>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </NTab>

        <!-- ══ Tab 3: Block Confirmation Summary ══════════════════════════════════ -->
        <NTab name="confirmation" :tab="t('monitor.blockConfirmationProgress')">
          <div class="tab-card">
            <NAlert type="info" :title="t('monitor.blockConfirmation')" style="margin-bottom: 16px">
              {{ t('monitor.blockConfirmationDesc') }}
            </NAlert>

            <NSpin :show="loadingCycles || loadingDetections" :description="t('monitor.loadingDetections')">
              <NAlert v-if="detectionError" type="error" :title="detectionError" style="margin-bottom: 12px" closable @close="detectionError = null" />

              <template v-if="confirmedNodeRows.length > 0">
                <div class="stats-row stats-row-3">
                  <div class="stat-item stat-error">
                    <div class="stat-icon"><NIcon :component="IconBlock" /></div>
                    <div class="stat-body">
                      <div class="stat-value">{{ confirmedNodeRows.length }}</div>
                      <div class="stat-label">{{ t('monitor.confirmedNodesTotal') || '确认阻断节点' }}</div>
                    </div>
                  </div>
                  <div class="stat-item stat-success">
                    <div class="stat-icon"><NIcon :component="IconHeal" /></div>
                    <div class="stat-body">
                      <div class="stat-value">{{ confirmedNodeRows.filter(r => r.triggered_healing === 'Yes').length }}</div>
                      <div class="stat-label">{{ t('monitor.triggeredHealing') || '已触发自愈' }}</div>
                    </div>
                  </div>
                  <div class="stat-item stat-warn">
                    <div class="stat-icon"><NIcon :component="IconRun" /></div>
                    <div class="stat-body">
                      <div class="stat-value">{{ confirmedNodeRows.filter(r => r.triggered_healing === 'No').length }}</div>
                      <div class="stat-label">{{ t('monitor.pendingHealing') || '等待自愈' }}</div>
                    </div>
                  </div>
                </div>
              </template>

              <NText depth="3" style="font-size: 13px; display: block; margin-bottom: 8px">
                {{ t('monitor.confirmedNodesAcrossAllCycles') || 'GFW 阻断确认节点汇总（所有周期）' }}
              </NText>

              <template v-if="confirmedNodeRows.length === 0 && !loadingCycles && !loadingDetections">
                <NEmpty :description="t('monitor.noConfirmations')" style="margin: 24px 0" />
              </template>
              <template v-else>
                <div class="table-wrapper">
                  <NDataTable
                    :columns="confirmedNodeColumns"
                    :data="confirmedNodeRows"
                    :bordered="false"
                    :single-line="false"
                    size="small"
                    :pagination="{ pageSize: 10 }"
                    :row-key="(row: any) => row.node_id"
                  />
                </div>
              </template>
            </NSpin>
          </div>
        </NTab>
      </NTabs>
    </NSpin>
  </div>
</template>

<style scoped>
.monitor-history-page {
  height: 100%;
  overflow-y: auto;
}

.tab-card {
  padding: 8px 0 20px;
}

/* ── Stats Row ────────────────────────────────────────────────────────────── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.stats-row-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.stats-row-3 .stat-item {
  padding: 8px 10px;
  gap: 8px;
}

.stat-item {
  background: #fff;
  border: 1px solid #e8ecf0;
  border-radius: 10px;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: box-shadow 0.2s ease, transform 0.2s ease;
  position: relative;
  overflow: hidden;
}

.stat-item::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  border-radius: 10px 10px 0 0;
}

.stat-all::before   { background: linear-gradient(90deg, #6366f1, #818cf8); }
.stat-success::before { background: linear-gradient(90deg, #18a058, #36ad6a); }
.stat-error::before   { background: linear-gradient(90deg, #ef4444, #f87171); }
.stat-info::before    { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
.stat-warn::before    { background: linear-gradient(90deg, #d97706, #fbbf24); }
.stat-heal::before    { background: linear-gradient(90deg, #8b5cf6, #a78bfa); }
.stat-neutral::before { background: linear-gradient(90deg, #64748b, #94a3b8); }

.stat-item:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  transform: translateY(-1px);
}

.stat-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-all .stat-icon    { background: #eef2ff; color: #6366f1; }
.stat-success .stat-icon { background: #ecfdf5; color: #18a058; }
.stat-error .stat-icon   { background: #fef2f2; color: #ef4444; }
.stat-info .stat-icon    { background: #eff6ff; color: #3b82f6; }
.stat-warn .stat-icon    { background: #fffbeb; color: #d97706; }
.stat-heal .stat-icon    { background: #f5f3ff; color: #8b5cf6; }
.stat-neutral .stat-icon { background: #f8fafc; color: #64748b; }

.stat-body {
  flex: 1;
  min-width: 0;
}

.stat-value {
  font-size: 15px;
  font-weight: 800;
  color: #1a1a2e;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: 9px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-top: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Controls ────────────────────────────────────────────────────────────── */
.controls-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
  align-items: center;
}

/* ── Table Wrapper ───────────────────────────────────────────────────────── */
.table-wrapper {
  overflow-x: auto;
  border-radius: 12px;
  border: 1px solid #e8ecf0;
  background: #fff;
}

.table-wrapper :deep(.n-data-table) {
  border-radius: 12px;
}

.table-wrapper :deep(.n-data-table-th) {
  background: #f8fafc !important;
  font-weight: 600;
  font-size: 11px !important;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b !important;
  border-bottom: 1px solid #e8ecf0 !important;
}

.table-wrapper :deep(.n-data-table-td) {
  font-size: 13px;
  color: #334155;
  border-bottom: 1px solid #f1f5f9 !important;
}

.table-wrapper :deep(.n-data-table-tr:hover .n-data-table-td) {
  background: #f8fafc !important;
}

.table-wrapper :deep(.n-data-table-tr:last-child .n-data-table-td) {
  border-bottom: none !important;
}

.table-wrapper :deep(.n-data-table-thead .n-data-table-th) {
  padding: 10px 12px;
}

.table-wrapper :deep(.n-data-table-tbody .n-data-table-td) {
  padding: 9px 12px;
}

.table-wrapper :deep(.n-data-table-pagination) {
  padding: 10px 12px;
  border-top: 1px solid #f1f5f9;
}

/* Row highlight */
.table-wrapper :deep(.n-data-table-tr--highlighted) {
  background: #eff6ff !important;
}

.table-wrapper :deep(.n-data-table-tr--highlighted .n-data-table-td) {
  background: #eff6ff !important;
}

/* ── Cycle Detail Grid ────────────────────────────────────────────────────── */
.cycle-detail-grid {
  display: flex;
  gap: 10px;
  margin: 18px 0 14px;
  flex-wrap: wrap;
}

.detail-item {
  flex: 1;
  min-width: 110px;
  background: #fff;
  border: 1px solid #e8ecf0;
  border-radius: 10px;
  padding: 12px 14px;
  text-align: center;
}

.detail-wide {
  flex: 2;
}

.detail-label {
  font-size: 10px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}

.detail-value {
  font-size: 16px;
  font-weight: 700;
  color: #1a1a2e;
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}

/* ── Section Label ───────────────────────────────────────────────────────── */
.section-label {
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.section-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #f1f5f9;
}

/* ── Tab Transitions ─────────────────────────────────────────────────────── */
:deep(.n-tab-pane) {
  animation: tabFadeIn 0.25s ease;
}

@keyframes tabFadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Responsive ─────────────────────────────────────────────────────────── */
@media (max-width: 1200px) {
  .stats-row {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 480px) {
  .stats-row-3 {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .stats-row-3 {
    grid-template-columns: 1fr;
  }
  .stat-value {
    font-size: 16px;
  }
  .cycle-detail-grid {
    gap: 8px;
  }
  .detail-item {
    min-width: calc(50% - 8px);
  }
  .detail-wide {
    flex: 1;
  }
}
</style>
