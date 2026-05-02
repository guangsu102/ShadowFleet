<script setup lang="ts">
import { ref, onMounted, onUnmounted, h } from 'vue'
import {
  NGrid,
  NGi,
  NStatistic,
  NDataTable,
  NTag,
  NSpin,
  NAlert,
  NText,
  NCard,
  NDivider,
} from 'naive-ui'
import apiClient from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import type {
  DashboardSnapshotResponse,
  RegionProtocolHealthRowResponse,
  ProbeHealthRowResponse,
  ProbeMeasurementRowResponse,
  AssetHealthRowResponse,
  FleetNodeDashboardRowResponse,
} from '@/types/api'

const { t } = useI18n()

// ── State ────────────────────────────────────────────────────────────────────
const snapshot = ref<DashboardSnapshotResponse | null>(null)
const loading = ref(true)
const errorMsg = ref<string | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | null = null

// ── Data Fetching ────────────────────────────────────────────────────────────
async function fetchSnapshot() {
  try {
    const { data } = await apiClient.get<DashboardSnapshotResponse>('/dashboard/snapshot')
    snapshot.value = data
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
  return `${value.toFixed(1)}%`
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

function alertTagType(level: 'healthy' | 'warning' | 'critical'): 'success' | 'warning' | 'error' {
  return level === 'healthy' ? 'success' : level === 'warning' ? 'warning' : 'error'
}

function alertTagLabel(level: 'healthy' | 'warning' | 'critical'): string {
  return level.charAt(0).toUpperCase() + level.slice(1)
}

// ── Region × Protocol Table ───────────────────────────────────────────────────
const regionProtocolColumns = [
  { title: t('dashboard.region'), key: 'region' },
  { title: t('dashboard.protocol'), key: 'protocol_type' },
  { title: t('dashboard.desired'), key: 'desired_count', align: 'center' as const },
  { title: t('dashboard.online'), key: 'online_count', align: 'center' as const },
  { title: t('dashboard.total'), key: 'total_count', align: 'center' as const },
  { title: t('dashboard.gap'), key: 'gap_count', align: 'center' as const },
  {
    title: t('dashboard.survivalRate'),
    key: 'survival_rate',
    align: 'center' as const,
    render: (row: RegionProtocolHealthRowResponse) => fmtPct(row.survival_rate),
  },
  {
    title: t('dashboard.alert'),
    key: 'alert_level',
    align: 'center' as const,
    render: (row: RegionProtocolHealthRowResponse) =>
      h(NTag, { type: alertTagType(row.alert_level), size: 'small' }, { default: () => alertTagLabel(row.alert_level) }),
  },
]

// ── Probe Status Table ────────────────────────────────────────────────────────
const probeColumns = [
  { title: t('probes.name'), key: 'probe_name' },
  { title: t('probes.status'), key: 'status' },
  { title: t('probes.publicIp'), key: 'public_ip' },
  { title: t('dashboard.region'), key: 'region' },
  { title: t('probes.isp'), key: 'isp' },
  { title: t('probes.lastSeen'), key: 'last_seen_at', render: (row: ProbeHealthRowResponse) => fmtTs(row.last_seen_at) },
  { title: t('assets.updated'), key: 'updated_at', render: (row: ProbeHealthRowResponse) => fmtTs(row.updated_at) },
]

// ── Probe Measurement Table ──────────────────────────────────────────────────
const probeMeasurementColumns = [
  { title: 'Measurement ID', key: 'measurement_id' },
  { title: 'Node ID', key: 'xboard_node_id', align: 'center' as const },
  { title: 'Final Status', key: 'final_status' },
  { title: 'Reason', key: 'reason' },
  { title: 'Created', key: 'created_at', render: (row: ProbeMeasurementRowResponse) => fmtTs(row.created_at) },
  { title: 'Finished', key: 'finished_at', render: (row: ProbeMeasurementRowResponse) => fmtTs(row.finished_at) },
]

// ── Asset Table ────────────────────────────────────────────────────────────────
const assetColumns = [
  { title: t('assets.name'), key: 'asset_name' },
  { title: t('assets.type'), key: 'asset_type' },
  { title: t('dashboard.region'), key: 'region' },
  { title: t('assets.status'), key: 'status' },
  { title: t('assets.allocated'), key: 'allocated_count', align: 'center' as const },
  { title: 'Target', key: 'target_count', align: 'center' as const },
  { title: t('assets.max'), key: 'max_count', align: 'center' as const },
  { title: 'AWS Account', key: 'aws_account_id' },
  { title: t('assets.updated'), key: 'updated_at', render: (row: AssetHealthRowResponse) => fmtTs(row.updated_at) },
]

// ── Fleet Node Table ──────────────────────────────────────────────────────────
const nodeColumns = [
  { title: t('fleet.nodeName'), key: 'node_name' },
  { title: t('fleet.protocol'), key: 'protocol_type' },
  { title: t('fleet.assetType'), key: 'asset_type' },
  { title: t('fleet.region'), key: 'region' },
  { title: t('fleet.status'), key: 'status' },
  { title: t('fleet.instanceId'), key: 'instance_id' },
  { title: t('fleet.domain'), key: 'domain_name' },
  { title: t('fleet.lastHealed'), key: 'last_healed_at', render: (row: FleetNodeDashboardRowResponse) => fmtTs(row.last_healed_at) },
  { title: t('fleet.lastError'), key: 'last_error', ellipsis: { tooltip: true } },
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
  <div style="padding: 16px; max-width: 1400px; margin: 0 auto">
    <NSpin :show="loading" :description="t('app.loading')">
      <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px" closable @close="errorMsg = null" />

      <template v-if="snapshot">
        <!-- ── Overview Metrics ─────────────────────────────────────────────── -->
        <NCard :title="t('dashboard.overview')" style="margin-bottom: 16px">
          <NGrid :cols="6" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
            <NGi span="2 m:1">
              <NStatistic :label="t('dashboard.survivalRate')" :value="fmtPct(snapshot.overview.overall_survival_rate)" />
            </NGi>
            <NGi span="2 m:1">
              <NStatistic :label="t('dashboard.offlineFailed')" :value="fmtNum(snapshot.overview.offline_or_failed_node_count)" />
            </NGi>
            <NGi span="2 m:1">
              <NStatistic :label="t('dashboard.expectedNodes')" :value="fmtNum(snapshot.overview.expected_node_count)" />
            </NGi>
            <NGi span="2 m:1">
              <NStatistic :label="t('dashboard.onlineNodes')" :value="fmtNum(snapshot.overview.online_node_count)" />
            </NGi>
            <NGi span="2 m:1">
              <NStatistic :label="t('dashboard.healingNodes')" :value="fmtNum(snapshot.overview.healing_node_count)" />
            </NGi>
            <NGi span="2 m:1">
              <NStatistic :label="t('dashboard.monthlyHealings')" :value="fmtNum(snapshot.overview.monthly_healing_count)" />
            </NGi>
          </NGrid>
        </NCard>

        <!-- ── Asset Metrics ─────────────────────────────────────────────────── -->
        <NCard :title="t('dashboard.assetMetrics')" style="margin-bottom: 16px">
          <NGrid :cols="5" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
            <NGi span="1">
              <NStatistic :label="t('dashboard.awsAssets')" :value="fmtNum(snapshot.overview.aws_asset_count)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.activeAws')" :value="fmtNum(snapshot.overview.active_aws_asset_count)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.fullAws')" :value="fmtNum(snapshot.overview.full_aws_asset_count)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.bannedAws')" :value="fmtNum(snapshot.overview.banned_aws_asset_count)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.totalAssets')" :value="fmtNum(snapshot.overview.total_asset_count)" />
            </NGi>
          </NGrid>
        </NCard>

        <!-- ── Capacity Metrics ──────────────────────────────────────────────── -->
        <NCard :title="t('dashboard.awsCapacity')" style="margin-bottom: 16px">
          <NGrid :cols="4" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
            <NGi span="1">
              <NStatistic :label="t('dashboard.allocatedNodes')" :value="fmtNum(snapshot.overview.allocated_aws_node_count)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.targetCapacity')" :value="fmtNum(snapshot.overview.target_aws_capacity)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.maxCapacity')" :value="fmtNum(snapshot.overview.max_aws_capacity)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.utilizationRate')" :value="fmtPct(snapshot.overview.aws_capacity_utilization_rate)" />
            </NGi>
          </NGrid>
        </NCard>

        <!-- ── Probe Metrics ─────────────────────────────────────────────────── -->
        <NCard :title="t('dashboard.probeMetrics')" style="margin-bottom: 16px">
          <NGrid :cols="4" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
            <NGi span="1">
              <NStatistic :label="t('dashboard.totalProbes')" :value="fmtNum(snapshot.overview.total_probe_count)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.activeProbes')" :value="fmtNum(snapshot.overview.active_probe_count)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.offlineProbes')" :value="fmtNum(snapshot.overview.offline_probe_count)" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('dashboard.disabledProbes')" :value="fmtNum(snapshot.overview.disabled_probe_count)" />
            </NGi>
          </NGrid>
        </NCard>

        <!-- ── Region × Protocol Matrix ──────────────────────────────────────── -->
        <NCard :title="t('dashboard.regionProtocolHealth')" style="margin-bottom: 16px">
          <NDataTable
            :columns="regionProtocolColumns"
            :data="snapshot.region_protocol_rows"
            :bordered="false"
            :single-line="false"
            size="small"
            :pagination="{ pageSize: 10 }"
          />
        </NCard>

        <!-- ── Sentinel Summary ──────────────────────────────────────────────── -->
        <NCard :title="t('dashboard.sentinelLatestCycle')" style="margin-bottom: 16px">
          <template v-if="snapshot.latest_monitor_cycle">
            <NGrid :cols="4" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
              <NGi span="1">
                <NStatistic :label="t('dashboard.cycleId')" :value="snapshot.latest_monitor_cycle.cycle_id" />
              </NGi>
              <NGi span="1">
                <NStatistic :label="t('dashboard.status')" :value="snapshot.latest_monitor_cycle.status" />
              </NGi>
              <NGi span="1">
                <NStatistic :label="t('dashboard.candidates')" :value="fmtNum(snapshot.latest_monitor_cycle.candidate_count)" />
              </NGi>
              <NGi span="1">
                <NStatistic :label="t('dashboard.confirmed')" :value="fmtNum(snapshot.latest_monitor_cycle.confirmed_count)" />
              </NGi>
              <NGi span="1">
                <NStatistic :label="t('dashboard.healed')" :value="fmtNum(snapshot.latest_monitor_cycle.healed_count)" />
              </NGi>
              <NGi span="1">
                <NStatistic :label="t('tasks.failed')" :value="fmtNum(snapshot.latest_monitor_cycle.failed_count)" />
              </NGi>
              <NGi span="2">
                <NStatistic :label="t('dashboard.startedAt')" :value="fmtTs(snapshot.latest_monitor_cycle.started_at)" />
              </NGi>
              <NGi span="2">
                <NStatistic :label="t('dashboard.finishedAt')" :value="fmtTs(snapshot.latest_monitor_cycle.finished_at)" />
              </NGi>
            </NGrid>
            <template v-if="snapshot.latest_monitor_cycle.error_message">
              <NDivider />
              <NText depth="3" style="font-size: 13px">
                {{ t('dashboard.error') }}: {{ snapshot.latest_monitor_cycle.error_message }}
              </NText>
            </template>
          </template>
          <NText v-else depth="3">{{ t('dashboard.noMonitorData') }}</NText>
        </NCard>

        <!-- ── Probe Status Table ────────────────────────────────────────────── -->
        <NCard :title="t('dashboard.probeStatus')" style="margin-bottom: 16px">
          <NDataTable
            :columns="probeColumns"
            :data="snapshot.probe_rows"
            :bordered="false"
            :single-line="false"
            size="small"
            :pagination="{ pageSize: 10 }"
          />
        </NCard>

        <!-- ── Recent Probe Measurements ────────────────────────────────────── -->
        <NCard :title="t('dashboard.recentProbeMeasurements')" style="margin-bottom: 16px">
          <NDataTable
            :columns="probeMeasurementColumns"
            :data="snapshot.probe_measurement_rows"
            :bordered="false"
            :single-line="false"
            size="small"
            :pagination="{ pageSize: 10 }"
          />
        </NCard>

        <!-- ── Asset Rows ────────────────────────────────────────────────────── -->
        <NCard :title="t('dashboard.assetDetails')" style="margin-bottom: 16px">
          <NDataTable
            :columns="assetColumns"
            :data="snapshot.asset_rows"
            :bordered="false"
            :single-line="false"
            size="small"
            :pagination="{ pageSize: 10 }"
          />
        </NCard>

        <!-- ── Fleet Node Rows ───────────────────────────────────────────────── -->
        <NCard :title="t('dashboard.fleetNodeSummary')" style="margin-bottom: 16px">
          <NDataTable
            :columns="nodeColumns"
            :data="snapshot.node_rows"
            :bordered="false"
            :single-line="false"
            size="small"
            :pagination="snapshot.node_rows.length > 100 ? false : { pageSize: 10 }"
            :virtual-scroll="snapshot.node_rows.length > 100"
            :height="snapshot.node_rows.length > 100 ? 400 : undefined"
            :row-key="(row: any) => row.xboard_node_id"
          />
        </NCard>
      </template>
    </NSpin>
  </div>
</template>
