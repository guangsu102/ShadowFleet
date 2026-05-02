<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import {
  NDataTable,
  NTag,
  NSpin,
  NText,
  NDivider,
  NButton,
  NCollapse,
  NCollapseItem,
} from 'naive-ui'
import apiClient from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import type {
  DashboardSnapshotResponse,
  RegionProtocolHealthRowResponse,
  AssetHealthRowResponse,
  FleetNodeDashboardRowResponse,
} from '@/types/api'

const { t } = useI18n()

// ── State ────────────────────────────────────────────────────────────────────
const snapshot = ref<DashboardSnapshotResponse | null>(null)
const loading = ref(true)
const errorMsg = ref<string | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | null = null
const lastRefresh = ref<Date>(new Date())

// ── Icon helpers (inline SVG) ────────────────────────────────────────────────
function makeIcon(paths: string) {
  return () => h('svg', {
    xmlns: 'http://www.w3.org/2000/svg',
    viewBox: '0 0 24 24',
    style: 'width:18px;height:18px;fill:currentColor',
  }, [h('path', { d: paths })])
}

const IconDashboard = makeIcon('M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3z')
const IconSentinel = makeIcon('M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z')
const IconTable = makeIcon('M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z')
const IconError = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z')
const IconHeart = makeIcon('M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z')
const IconRefresh = makeIcon('M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z')

// ── Data Fetching ────────────────────────────────────────────────────────────
async function fetchSnapshot() {
  try {
    const { data } = await apiClient.get<DashboardSnapshotResponse>('/dashboard/snapshot')
    snapshot.value = data
    lastRefresh.value = new Date()
    errorMsg.value = null
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string }; status?: number }; message?: string }
    errorMsg.value = axiosErr.response?.data?.error || axiosErr.message || t('dashboard.loadFailed')
  } finally {
    loading.value = false
  }
}

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtPct(value: number | undefined): string {
  if (value === undefined || value === null) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function fmtNum(value: number | undefined): string {
  if (value === undefined || value === null) return '—'
  return value.toLocaleString()
}

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

function fmtTime(date: Date): string {
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// ── Donut Chart helpers ───────────────────────────────────────────────────────
interface DonutSegment {
  label: string
  value: number
  color: string
  bgColor: string
}

function nodeHealthDonut() {
  if (!snapshot.value) return []
  const o = snapshot.value.overview
  return [
    { label: t('dashboard.online'), value: o.online_node_count, color: '#18a058', bgColor: '#e8f5e9' },
    { label: t('dashboard.healing'), value: o.healing_node_count, color: '#f59e0b', bgColor: '#fffbeb' },
    { label: t('dashboard.offline'), value: o.offline_or_failed_node_count, color: '#ef4444', bgColor: '#fef2f2' },
  ].filter(s => s.value > 0)
}

function assetStatusDonut() {
  if (!snapshot.value) return []
  const o = snapshot.value.overview
  const segs: DonutSegment[] = [
    { label: t('dashboard.active'), value: o.active_asset_count, color: '#18a058', bgColor: '#e8f5e9' },
    { label: t('dashboard.full'), value: o.full_asset_count, color: '#f59e0b', bgColor: '#fffbeb' },
    { label: t('dashboard.banned'), value: o.banned_asset_count, color: '#ef4444', bgColor: '#fef2f2' },
    { label: t('dashboard.offline'), value: o.offline_asset_count, color: '#94a3b8', bgColor: '#f1f5f9' },
  ]
  return segs.filter(s => s.value > 0)
}

function probeStatusDonut() {
  if (!snapshot.value) return []
  const o = snapshot.value.overview
  const segs: DonutSegment[] = [
    { label: t('dashboard.active'), value: o.active_probe_count, color: '#18a058', bgColor: '#e8f5e9' },
    { label: t('dashboard.offline'), value: o.offline_probe_count, color: '#ef4444', bgColor: '#fef2f2' },
    { label: t('dashboard.disabled'), value: o.disabled_probe_count, color: '#94a3b8', bgColor: '#f1f5f9' },
  ]
  return segs.filter(s => s.value > 0)
}

function calcDonut(segments: DonutSegment[], total: number, size: number) {
  const r = size / 2
  const circumference = 2 * Math.PI * r
  const strokeWidth = size * 0.22
  let offset = 0
  return segments.map((seg) => {
    const pct = total > 0 ? seg.value / total : 0
    const dashLen = circumference * pct
    const gapLen = circumference - dashLen
    const seg2 = {
      ...seg,
      dashArray: `${dashLen} ${gapLen}`,
      dashOffset: -offset,
      circumference,
      r,
      cx: r,
      cy: r,
      strokeWidth,
      pct,
    }
    offset += dashLen
    return seg2
  })
}

function nodeHealthTotal() {
  return snapshot.value?.overview.total_node_count || 0
}

function assetTotal() {
  return snapshot.value?.overview.total_asset_count || 0
}

function probeTotal() {
  return snapshot.value?.overview.total_probe_count || 0
}

const nodeDonutSegments = computed(() => calcDonut(nodeHealthDonut(), nodeHealthTotal(), 160))
const assetDonutSegments = computed(() => calcDonut(assetStatusDonut(), assetTotal(), 160))
const probeDonutSegments = computed(() => calcDonut(probeStatusDonut(), probeTotal(), 160))

// ── Color helpers ────────────────────────────────────────────────────────────
function survivalColor(rate: number | undefined): string {
  if (rate === undefined) return 'gray'
  const pct = rate * 100
  if (pct >= 90) return 'green'
  if (pct >= 70) return 'orange'
  return 'red'
}

function utilClass(rate: number | undefined): string {
  if (rate === undefined) return 'util-bar-fill-low'
  const pct = rate * 100
  if (pct >= 85) return 'util-bar-fill-high'
  if (pct >= 65) return 'util-bar-fill-mid'
  return 'util-bar-fill-low'
}

function utilColor(rate: number | undefined): string {
  if (rate === undefined) return '#18a058'
  const pct = rate * 100
  if (pct >= 85) return '#ef4444'
  if (pct >= 65) return '#f59e0b'
  return '#18a058'
}

function alertTagType(level: 'healthy' | 'warning' | 'critical'): 'success' | 'warning' | 'error' {
  return level === 'healthy' ? 'success' : level === 'warning' ? 'warning' : 'error'
}

function alertTagLabel(level: 'healthy' | 'warning' | 'critical'): string {
  const map: Record<string, string> = {
    healthy: t('dashboard.healthy'),
    warning: t('dashboard.warning'),
    critical: t('dashboard.critical'),
  }
  return map[level] || level
}

function statusBadgeClass(status: string): string {
  const s = status?.toLowerCase()
  if (s === 'online' || s === 'running' || s === 'active' || s === 'succeeded') return 'status-badge-success'
  if (s === 'warning' || s === 'healing') return 'status-badge-warning'
  if (s === 'offline' || s === 'failed' || s === 'error' || s === 'banned') return 'status-badge-error'
  if (s === 'queued' || s === 'pending') return 'status-badge-purple'
  if (s === 'disabled') return 'status-badge-gray'
  return 'status-badge-info'
}

function statusBadgeDot(status: string): string {
  const s = status?.toLowerCase()
  if (s === 'online' || s === 'running' || s === 'active' || s === 'succeeded') return '#18a058'
  if (s === 'warning' || s === 'healing') return '#f59e0b'
  if (s === 'offline' || s === 'failed' || s === 'error' || s === 'banned') return '#ef4444'
  return '#64748b'
}

// ── Capacity bar ─────────────────────────────────────────────────────────────
const capacityPct = computed(() => {
  const rate = snapshot.value?.overview.aws_capacity_utilization_rate
  return rate !== undefined ? Math.round(rate * 100) : 0
})

// ── Region × Protocol Table ───────────────────────────────────────────────────
const regionProtocolColumns = [
  { title: t('dashboard.region'), key: 'region' },
  { title: t('dashboard.protocol'), key: 'protocol_type' },
  { title: t('dashboard.desired'), key: 'desired_count', align: 'center' as const },
  { title: t('dashboard.online'), key: 'online_count', align: 'center' as const },
  { title: t('dashboard.total'), key: 'total_count', align: 'center' as const },
  {
    title: t('dashboard.gap'),
    key: 'gap_count',
    align: 'center' as const,
    render: (row: RegionProtocolHealthRowResponse) => {
      const gap = row.gap_count
      const cls = gap > 0 ? 'status-badge-error' : gap === 0 ? 'status-badge-success' : 'status-badge-gray'
      const dot = gap > 0 ? '#ef4444' : gap === 0 ? '#18a058' : '#64748b'
      return h('span', { class: `status-badge ${cls}` }, [
        h('span', { class: 'status-dot', style: `background:${dot}` }),
        gap,
      ])
    },
  },
  {
    title: t('dashboard.survivalRate'),
    key: 'survival_rate',
    align: 'center' as const,
    render: (row: RegionProtocolHealthRowResponse) => {
      const rate = row.survival_rate
      return h('span', { style: `font-weight:700;color:${rate >= 0.9 ? '#18a058' : rate >= 0.7 ? '#f59e0b' : '#ef4444'}` },
        fmtPct(rate))
    },
  },
  {
    title: t('dashboard.alert'),
    key: 'alert_level',
    align: 'center' as const,
    render: (row: RegionProtocolHealthRowResponse) =>
      h(NTag, { type: alertTagType(row.alert_level), size: 'small', round: true }, { default: () => alertTagLabel(row.alert_level) }),
  },
]

// ── Asset Table ────────────────────────────────────────────────────────────────
const assetColumns = [
  { title: t('assets.name'), key: 'asset_name' },
  { title: t('dashboard.type'), key: 'asset_type' },
  { title: t('dashboard.region'), key: 'region' },
  {
    title: t('dashboard.status'),
    key: 'status',
    render: (row: AssetHealthRowResponse) => {
      const s = row.status?.toLowerCase() || ''
      const badge = statusBadgeClass(s)
      const dot = statusBadgeDot(s)
      return h('span', { class: `status-badge ${badge}` }, [
        h('span', { class: 'status-dot', style: `background:${dot}` }),
        row.status || '—',
      ])
    },
  },
  { title: t('dashboard.allocated'), key: 'allocated_count', align: 'center' as const },
  { title: 'Target', key: 'target_count', align: 'center' as const },
  { title: t('dashboard.max'), key: 'max_count', align: 'center' as const },
  { title: t('dashboard.awsAccount'), key: 'aws_account_id', ellipsis: { tooltip: true } },
]

// ── Fleet Node Table ──────────────────────────────────────────────────────────
const nodeColumns = [
  { title: t('dashboard.nodeName'), key: 'node_name' },
  { title: t('dashboard.protocol'), key: 'protocol_type' },
  { title: t('dashboard.type'), key: 'asset_type' },
  { title: t('dashboard.region'), key: 'region' },
  {
    title: t('dashboard.status'),
    key: 'status',
    render: (row: FleetNodeDashboardRowResponse) => {
      const s = row.status?.toLowerCase() || ''
      const badge = statusBadgeClass(s)
      const dot = statusBadgeDot(s)
      return h('span', { class: `status-badge ${badge}` }, [
        h('span', { class: 'status-dot', style: `background:${dot}` }),
        row.status || '—',
      ])
    },
  },
  { title: t('dashboard.instanceId'), key: 'instance_id', ellipsis: { tooltip: true } },
  { title: t('dashboard.lastHealed'), key: 'last_healed_at', render: (row: FleetNodeDashboardRowResponse) => fmtTs(row.last_healed_at) },
]

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  fetchSnapshot()
  refreshTimer = setInterval(fetchSnapshot, 30_000)
})

onUnmounted(() => {
  if (refreshTimer !== null) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<template>
  <div class="dashboard-page">

    <!-- ── Page Header ──────────────────────────────────────────────────── -->
    <div class="dashboard-header">
      <div class="dashboard-header-left">
        <div class="dashboard-header-icon">
          <IconDashboard />
        </div>
        <div class="dashboard-header-title">
          <h1>{{ t('dashboard.title') }}</h1>
          <p>{{ t('dashboard.autoRefresh') }}</p>
        </div>
      </div>
      <div class="dashboard-header-actions">
        <div class="refresh-badge">
          <span class="refresh-badge-dot"></span>
          <span>{{ t('dashboard.lastUpdated') }}: {{ fmtTime(lastRefresh) }}</span>
        </div>
        <NButton size="small" quaternary circle @click="fetchSnapshot" :loading="loading">
          <template #icon>
            <IconRefresh />
          </template>
        </NButton>
      </div>
    </div>

    <!-- ── Error Alert ─────────────────────────────────────────────────── -->
    <div v-if="errorMsg" class="alert-banner alert-banner-error">
      <IconError />
      {{ errorMsg }}
      <NButton size="tiny" quaternary style="margin-left:auto" @click="errorMsg = null">
        {{ t('app.close') }}
      </NButton>
    </div>

    <NSpin :show="loading">
      <template v-if="snapshot">

        <!-- ══ Health Summary ═══════════════════════════════════════════════ -->
        <div class="dashboard-section-header">
          <div class="dashboard-section-icon" style="background:#e8f5e9;color:#18a058">
            <IconDashboard />
          </div>
          <span class="dashboard-section-title">{{ t('dashboard.healthSummary') }}</span>
        </div>
        <div class="health-summary-grid">
          <!-- Node Health Donut -->
          <div class="donut-card">
            <div class="donut-title">{{ t('dashboard.nodeHealth') }}</div>
            <div class="donut-wrapper">
              <svg viewBox="0 0 160 160" class="donut-svg">
                <circle class="donut-track" cx="80" cy="80" r="62" />
                <circle
                  v-for="(seg, i) in nodeDonutSegments"
                  :key="i"
                  class="donut-segment"
                  cx="80"
                  cy="80"
                  r="62"
                  :stroke="seg.color"
                  :stroke-dasharray="seg.dashArray"
                  :stroke-dashoffset="seg.dashOffset"
                />
              </svg>
              <div class="donut-center">
                <div class="donut-total">{{ fmtNum(nodeHealthTotal()) }}</div>
                <div class="donut-total-label">{{ t('dashboard.totalNodes') }}</div>
              </div>
            </div>
            <div class="donut-legend">
              <div v-for="seg in nodeDonutSegments" :key="seg.label" class="donut-legend-item">
                <span class="donut-legend-dot" :style="`background:${seg.color}`"></span>
                <span class="donut-legend-label">{{ seg.label }}</span>
                <span class="donut-legend-value">{{ fmtNum(seg.value) }}</span>
              </div>
            </div>
          </div>

          <!-- Asset Capacity Donut -->
          <div class="donut-card">
            <div class="donut-title">{{ t('dashboard.assetCapacity') }}</div>
            <div class="donut-wrapper">
              <svg viewBox="0 0 160 160" class="donut-svg">
                <circle class="donut-track" cx="80" cy="80" r="62" />
                <circle
                  v-for="(seg, i) in assetDonutSegments"
                  :key="i"
                  class="donut-segment"
                  cx="80"
                  cy="80"
                  r="62"
                  :stroke="seg.color"
                  :stroke-dasharray="seg.dashArray"
                  :stroke-dashoffset="seg.dashOffset"
                />
              </svg>
              <div class="donut-center">
                <div class="donut-total">{{ fmtNum(assetTotal()) }}</div>
                <div class="donut-total-label">{{ t('dashboard.assetShort') }}</div>
              </div>
            </div>
            <div class="donut-legend">
              <div v-for="seg in assetDonutSegments" :key="seg.label" class="donut-legend-item">
                <span class="donut-legend-dot" :style="`background:${seg.color}`"></span>
                <span class="donut-legend-label">{{ seg.label }}</span>
                <span class="donut-legend-value">{{ fmtNum(seg.value) }}</span>
              </div>
            </div>
          </div>

          <!-- Probe Status Donut -->
          <div class="donut-card">
            <div class="donut-title">{{ t('dashboard.probeStatus') }}</div>
            <div class="donut-wrapper">
              <svg viewBox="0 0 160 160" class="donut-svg">
                <circle class="donut-track" cx="80" cy="80" r="62" />
                <circle
                  v-for="(seg, i) in probeDonutSegments"
                  :key="i"
                  class="donut-segment"
                  cx="80"
                  cy="80"
                  r="62"
                  :stroke="seg.color"
                  :stroke-dasharray="seg.dashArray"
                  :stroke-dashoffset="seg.dashOffset"
                />
              </svg>
              <div class="donut-center">
                <div class="donut-total">{{ fmtNum(probeTotal()) }}</div>
                <div class="donut-total-label">{{ t('dashboard.probeShort') }}</div>
              </div>
            </div>
            <div class="donut-legend">
              <div v-for="seg in probeDonutSegments" :key="seg.label" class="donut-legend-item">
                <span class="donut-legend-dot" :style="`background:${seg.color}`"></span>
                <span class="donut-legend-label">{{ seg.label }}</span>
                <span class="donut-legend-value">{{ fmtNum(seg.value) }}</span>
              </div>
            </div>
          </div>

          <!-- Capacity Bar -->
          <div class="capacity-card">
            <div class="donut-title">{{ t('dashboard.awsUtilization') }}</div>
            <div class="capacity-numbers">
              <div class="capacity-num">
                <span class="capacity-val" style="color:#3b82f6">{{ fmtNum(snapshot.overview.allocated_aws_node_count) }}</span>
                <span class="capacity-lbl">{{ t('dashboard.allocated') }}</span>
              </div>
              <div class="capacity-sep">/</div>
              <div class="capacity-num">
                <span class="capacity-val" style="color:#18a058">{{ fmtNum(snapshot.overview.target_aws_capacity) }}</span>
                <span class="capacity-lbl">{{ t('dashboard.target') }}</span>
              </div>
              <div class="capacity-sep">/</div>
              <div class="capacity-num">
                <span class="capacity-val" style="color:#94a3b8">{{ fmtNum(snapshot.overview.max_aws_capacity) }}</span>
                <span class="capacity-lbl">{{ t('dashboard.maxCap') }}</span>
              </div>
            </div>
            <div class="capacity-bar-track">
              <div
                class="capacity-bar-fill"
                :class="utilClass(snapshot.overview.aws_capacity_utilization_rate)"
                :style="`width:${Math.min(capacityPct, 100)}%;background:${utilColor(snapshot.overview.aws_capacity_utilization_rate)}`"
              ></div>
            </div>
            <div class="capacity-pct-row">
              <span class="capacity-pct-label">{{ t('dashboard.utilizationRate') }}</span>
              <span
                class="capacity-pct-val"
                :style="`color:${utilColor(snapshot.overview.aws_capacity_utilization_rate)}`"
              >{{ fmtPct(snapshot.overview.aws_capacity_utilization_rate) }}</span>
            </div>
            <!-- Survival rate -->
            <div class="survival-row">
              <IconHeart />
              <span class="survival-lbl">{{ t('dashboard.survivalRate') }}</span>
              <span
                class="survival-val"
                :style="`color:${survivalColor(snapshot.overview.overall_survival_rate) === 'green' ? '#18a058' : survivalColor(snapshot.overview.overall_survival_rate) === 'orange' ? '#f59e0b' : '#ef4444'}`"
              >{{ fmtPct(snapshot.overview.overall_survival_rate) }}</span>
              <div class="survival-bar-track">
                <div
                  class="survival-bar-fill"
                  :style="`width:${Math.min((snapshot.overview.overall_survival_rate || 0) * 100, 100)}%;background:${survivalColor(snapshot.overview.overall_survival_rate) === 'green' ? '#18a058' : survivalColor(snapshot.overview.overall_survival_rate) === 'orange' ? '#f59e0b' : '#ef4444'}`"
                ></div>
              </div>
            </div>
            <div class="healing-row">
              <IconHeart />
              <span class="healing-lbl">{{ t('dashboard.healings') }}</span>
              <span class="healing-val">{{ fmtNum(snapshot.overview.monthly_healing_count) }}</span>
              <span class="healing-unit">{{ t('dashboard.thisMonth') }}</span>
            </div>
          </div>
        </div>

        <!-- ══ Region × Protocol Matrix ══════════════════════════════════ -->
        <div class="dashboard-section-header">
          <div class="dashboard-section-icon" style="background:#e0f2fe;color:#0284c7">
            <IconTable />
          </div>
          <span class="dashboard-section-title">{{ t('dashboard.regionProtocolHealth') }}</span>
          <span class="dashboard-section-sub text-muted">
            {{ snapshot.region_protocol_rows?.length || 0 }} rows
          </span>
        </div>
        <div class="dashboard-card">
          <div class="dashboard-table">
            <NDataTable
              :columns="regionProtocolColumns"
              :data="snapshot.region_protocol_rows || []"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 10 }"
              :row-key="(row: RegionProtocolHealthRowResponse) => `${row.region}-${row.protocol_type}`"
            />
          </div>
        </div>

        <!-- ══ Sentinel Latest Cycle ══════════════════════════════════════ -->
        <div class="dashboard-section-header">
          <div class="dashboard-section-icon" style="background:#e8f5e9;color:#18a058">
            <IconSentinel />
          </div>
          <span class="dashboard-section-title">{{ t('dashboard.sentinelLatestCycle') }}</span>
        </div>
        <div class="dashboard-card sentinel-card">
          <template v-if="snapshot.latest_monitor_cycle">
            <div class="sentinel-metrics">
              <div class="sentinel-metric">
                <div class="sentinel-metric-val" style="font-family:monospace">{{ snapshot.latest_monitor_cycle.cycle_id }}</div>
                <div class="sentinel-metric-lbl">{{ t('dashboard.cycleId') }}</div>
              </div>
              <div class="sentinel-metric">
                <div class="sentinel-metric-val" :style="`color:${snapshot.latest_monitor_cycle.status?.toLowerCase() === 'succeeded' ? '#18a058' : snapshot.latest_monitor_cycle.status?.toLowerCase() === 'running' ? '#3b82f6' : '#ef4444'}`">
                  {{ snapshot.latest_monitor_cycle.status }}
                </div>
                <div class="sentinel-metric-lbl">{{ t('dashboard.status') }}</div>
              </div>
              <div class="sentinel-metric">
                <div class="sentinel-metric-val">{{ fmtNum(snapshot.latest_monitor_cycle.candidate_count) }}</div>
                <div class="sentinel-metric-lbl">{{ t('dashboard.candidates') }}</div>
              </div>
              <div class="sentinel-metric">
                <div class="sentinel-metric-val" style="color:#18a058">{{ fmtNum(snapshot.latest_monitor_cycle.confirmed_count) }}</div>
                <div class="sentinel-metric-lbl">{{ t('dashboard.confirmed') }}</div>
              </div>
              <div class="sentinel-metric">
                <div class="sentinel-metric-val" style="color:#8b5cf6">{{ fmtNum(snapshot.latest_monitor_cycle.healed_count) }}</div>
                <div class="sentinel-metric-lbl">{{ t('dashboard.healed') }}</div>
              </div>
              <div class="sentinel-metric">
                <div class="sentinel-metric-val" :style="`color:${snapshot.latest_monitor_cycle.failed_count > 0 ? '#ef4444' : '#94a3b8'}`">{{ fmtNum(snapshot.latest_monitor_cycle.failed_count) }}</div>
                <div class="sentinel-metric-lbl">{{ t('tasks.failed') }}</div>
              </div>
            </div>
            <NDivider style="margin: 12px 0" />
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
              <div>
                <span class="text-muted text-small">{{ t('dashboard.startedAt') }}</span>
                <NText style="display:block;font-weight:600;font-size:13px">{{ fmtTs(snapshot.latest_monitor_cycle.started_at) }}</NText>
              </div>
              <div>
                <span class="text-muted text-small">{{ t('dashboard.finishedAt') }}</span>
                <NText style="display:block;font-weight:600;font-size:13px">{{ fmtTs(snapshot.latest_monitor_cycle.finished_at) }}</NText>
              </div>
            </div>
            <template v-if="snapshot.latest_monitor_cycle.error_message">
              <NDivider style="margin: 12px 0" />
              <div style="display:flex;align-items:flex-start;gap:8px;padding:10px;background:#fef2f2;border-radius:6px;border:1px solid #fecaca">
                <IconError style="width:16px;height:16px;color:#ef4444;flex-shrink:0;margin-top:2px" />
                <div>
                  <div style="font-size:12px;font-weight:600;color:#b91c1c;margin-bottom:4px">{{ t('dashboard.error') }}</div>
                  <div style="font-size:12px;color:#991b1b;word-break:break-all">{{ snapshot.latest_monitor_cycle.error_message }}</div>
                </div>
              </div>
            </template>
          </template>
          <NText v-else depth="3" style="font-size:13px">{{ t('dashboard.noMonitorData') }}</NText>
        </div>

        <!-- ══ Collapsible Detail Tables ══════════════════════════════════ -->
        <NCollapse>
          <!-- Fleet Nodes -->
          <NCollapseItem :title="`${t('dashboard.fleetNodeSummary')} (${snapshot.node_rows?.length || 0})`" name="nodes">
            <template #header-extra>
              <span class="collapse-extra-text">{{ snapshot.node_rows?.length || 0 }} nodes</span>
            </template>
            <div class="dashboard-table">
              <NDataTable
                :columns="nodeColumns"
                :data="snapshot.node_rows || []"
                :bordered="false"
                :single-line="false"
                size="small"
                :pagination="(snapshot.node_rows?.length || 0) > 100 ? false : { pageSize: 10 }"
                :virtual-scroll="(snapshot.node_rows?.length || 0) > 100"
                :height="(snapshot.node_rows?.length || 0) > 100 ? 400 : undefined"
                :row-key="(row: FleetNodeDashboardRowResponse) => row.xboard_node_id"
              />
            </div>
          </NCollapseItem>

          <!-- Asset Details -->
          <NCollapseItem :title="`${t('dashboard.assetDetails')} (${snapshot.asset_rows?.length || 0})`" name="assets">
            <template #header-extra>
              <span class="collapse-extra-text">{{ snapshot.asset_rows?.length || 0 }} assets</span>
            </template>
            <div class="dashboard-table">
              <NDataTable
                :columns="assetColumns"
                :data="snapshot.asset_rows || []"
                :bordered="false"
                :single-line="false"
                size="small"
                :pagination="{ pageSize: 10 }"
                :row-key="(row: AssetHealthRowResponse) => row.asset_id"
              />
            </div>
          </NCollapseItem>
        </NCollapse>

      </template>
    </NSpin>
  </div>
</template>
