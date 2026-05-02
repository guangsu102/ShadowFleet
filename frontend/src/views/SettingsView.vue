<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard,
  NSpin,
  NAlert,
  NInput,
  NInputNumber,
  NSwitch,
  NButton,
  NText,
  NDataTable,
  NSelect,
  NTag,
  NDivider,
  useMessage,
  useDialog,
} from 'naive-ui'
import type { SelectOption } from 'naive-ui'
import apiClient from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import type {
  ConfigResponse,
  FleetMatrixUpdateRequest,
  SentinelUpdateRequest,
  AppUpdateRequest,
  LoggingUpdateRequest,
  DashboardUpdateRequest,
} from '@/types/api'

const { t } = useI18n()

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const PROTOCOLS = ['AnyTLS', 'Trojan', 'vless', 'vmess', 'Hysteria2']

function fleetDesired(region: string | null, protocol: string) {
  return computed({
    get: () => (region ? fleetMatrixForm.value[region]?.[protocol]?.desired_count ?? 0 : 0),
    set: (v: number) => {
      if (!region) return
      if (!fleetMatrixForm.value[region]) fleetMatrixForm.value[region] = {}
      if (!fleetMatrixForm.value[region][protocol]) fleetMatrixForm.value[region][protocol] = { desired_count: 0, min_alert_threshold: 0 }
      fleetMatrixForm.value[region][protocol].desired_count = v
    },
  })
}
function fleetThreshold(region: string | null, protocol: string) {
  return computed({
    get: () => (region ? fleetMatrixForm.value[region]?.[protocol]?.min_alert_threshold ?? 0 : 0),
    set: (v: number) => {
      if (!region) return
      if (!fleetMatrixForm.value[region]) fleetMatrixForm.value[region] = {}
      if (!fleetMatrixForm.value[region][protocol]) fleetMatrixForm.value[region][protocol] = { desired_count: 0, min_alert_threshold: 0 }
      fleetMatrixForm.value[region][protocol].min_alert_threshold = v
    },
  })
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const message = useMessage()
const dialog = useDialog()

const loading = ref(true)
const error = ref<string | null>(null)
const config = ref<ConfigResponse | null>(null)
const savingFleetMatrix = ref(false)
const savingApp = ref(false)
const savingSentinel = ref(false)
const savingLogging = ref(false)
const savingDashboard = ref(false)
const resettingFleetMatrix = ref(false)

// ---------------------------------------------------------------------------
// Fleet Matrix
// ---------------------------------------------------------------------------
const newRegionName = ref('')
const selectedRegion = ref<string | null>(null)
const fleetMatrixForm = ref<Record<string, Record<string, { desired_count: number; min_alert_threshold: number }>>>({})

const regionOptions = computed<{ label: string; value: string }[]>(() => {
  const regions = config.value ? Object.keys(config.value.fleet_matrix ?? {}) : []
  return regions.map((r) => ({ label: r, value: r }))
})

const activeRegion = computed<string | null>(() => {
  if (selectedRegion.value) return selectedRegion.value
  if (newRegionName.value.trim()) return newRegionName.value.trim()
  return null
})

const deleteRegionOptions = computed<{ label: string; value: string }[]>(() =>
  Object.keys(config.value?.fleet_matrix ?? {}).map((r) => ({ label: r, value: r }))
)
const regionToDelete = ref<string | null>(null)

interface MatrixRow { region: string; protocol: string; desired_count: number; alert_threshold: number }

const matrixTableData = computed<MatrixRow[]>(() => {
  const rows: MatrixRow[] = []
  const raw = config.value?.fleet_matrix ?? {}
  for (const region of Object.keys(raw).sort()) {
    const protocols = raw[region] as Record<string, unknown>
    for (const protocol of PROTOCOLS) {
      const p = protocols?.[protocol] as { desired_count?: number; min_alert_threshold?: number } | undefined
      if (p) {
        rows.push({ region, protocol, desired_count: p.desired_count ?? 0, alert_threshold: p.min_alert_threshold ?? 0 })
      }
    }
  }
  return rows
})

const matrixTableColumns = [
  { title: 'Region', key: 'region', width: 160 },
  { title: 'Protocol', key: 'protocol', width: 120 },
  { title: 'Desired', key: 'desired_count', width: 100 },
  { title: 'Threshold', key: 'alert_threshold', width: 100 },
]

function buildMatrixForm() {
  if (!config.value) return
  const raw = config.value.fleet_matrix ?? {}
  const form: Record<string, Record<string, { desired_count: number; min_alert_threshold: number }>> = {}
  for (const region of Object.keys(raw)) {
    form[region] = {}
    for (const protocol of PROTOCOLS) {
      const existing = (raw[region] as Record<string, unknown>)?.[protocol] as
        | { desired_count?: number; min_alert_threshold?: number }
        | undefined
      form[region][protocol] = { desired_count: existing?.desired_count ?? 0, min_alert_threshold: existing?.min_alert_threshold ?? 0 }
    }
  }
  fleetMatrixForm.value = form
}

// ---------------------------------------------------------------------------
// Daemon Form
// ---------------------------------------------------------------------------
const daemonIdlePoll = ref(5.0)
const daemonFailureBackoff = ref(5.0)
const daemonStaleRecovery = ref(30.0)
const daemonTaskTimeout = ref(900.0)
const daemonRetryDelay = ref(10.0)

function buildDaemonForm() {
  if (!config.value) return
  const app = config.value.app ?? {}
  daemonIdlePoll.value = (app.daemon_idle_poll_interval_seconds as number) ?? 5.0
  daemonFailureBackoff.value = (app.daemon_failure_backoff_seconds as number) ?? 5.0
  daemonStaleRecovery.value = (app.daemon_stale_task_recovery_interval_seconds as number) ?? 30.0
  daemonTaskTimeout.value = (app.daemon_running_task_timeout_seconds as number) ?? 900.0
  daemonRetryDelay.value = (app.daemon_recovered_task_retry_delay_seconds as number) ?? 10.0
}

// ---------------------------------------------------------------------------
// Phone-Home Form
// ---------------------------------------------------------------------------
const phoneHomeBaseUrl = ref('')
const phoneHomeListenHost = ref('::')
const phoneHomeListenPort = ref(8787)
const phoneHomeReadyTimeout = ref(300.0)
const phoneHomePollInterval = ref(5.0)

function buildPhoneHomeForm() {
  if (!config.value) return
  const app = config.value.app ?? {}
  phoneHomeBaseUrl.value = (app.phone_home_base_url as string) ?? ''
  phoneHomeListenHost.value = (app.phone_home_listen_host as string) ?? '::'
  phoneHomeListenPort.value = (app.phone_home_listen_port as number) ?? 8787
  phoneHomeReadyTimeout.value = (app.phone_home_ready_timeout_seconds as number) ?? 300.0
  phoneHomePollInterval.value = (app.phone_home_poll_interval_seconds as number) ?? 5.0
}

// ---------------------------------------------------------------------------
// Artifact Cache Form
// ---------------------------------------------------------------------------
const artifactCacheEnabled = ref(false)
const artifactCacheListenPort = ref(8080)
const artifactCacheBaseUrl = ref('')

function buildArtifactCacheForm() {
  if (!config.value) return
  const app = config.value.app ?? {}
  artifactCacheEnabled.value = (app.artifact_cache_enabled as boolean) ?? false
  artifactCacheListenPort.value = (app.artifact_cache_listen_port as number) ?? 8080
  artifactCacheBaseUrl.value = (app.artifact_cache_base_url_override as string) ?? ''
}

// ---------------------------------------------------------------------------
// Probe Server Form
// ---------------------------------------------------------------------------
const probeServerEnabled = ref(false)
const probePollInterval = ref(5.0)
const probeHeartbeatTimeout = ref(60.0)

function buildProbeServerForm() {
  if (!config.value) return
  const app = config.value.app ?? {}
  probeServerEnabled.value = (app.probe_server_enabled as boolean) ?? false
  probePollInterval.value = (app.probe_poll_interval_seconds as number) ?? 5.0
  probeHeartbeatTimeout.value = (app.probe_heartbeat_timeout_seconds as number) ?? 60.0
}

// ---------------------------------------------------------------------------
// Sentinel Form
// ---------------------------------------------------------------------------
const sentinelEnabled = ref(false)
const sentinelPollInterval = ref(180.0)
const sentinelProbeTimeout = ref(10)
const sentinelRetryCooldown = ref(300.0)
const sentinelSuspiciousLookback = ref(60)
const sentinelZeroUplinkWindow = ref(3)
const sentinelProbeMode = ref('cn_probe_mesh')
const sentinelConfirmCycles = ref(2)
const sentinelMinCnProbe = ref(2)
const sentinelSuccessRatio = ref(0.5)
const sentinelAllowAutoHealHy2 = ref(false)

const sentinelProbeModeOptions: SelectOption[] = [
  { label: 'local_active_probe', value: 'local_active_probe' },
  { label: 'cn_probe_mesh', value: 'cn_probe_mesh' },
]

function buildSentinelForm() {
  if (!config.value) return
  const app = config.value.app ?? {}
  sentinelEnabled.value = (app.sentinel_enabled as boolean) ?? false
  sentinelPollInterval.value = (app.sentinel_poll_interval_seconds as number) ?? 180.0
  sentinelProbeTimeout.value = (app.sentinel_probe_timeout_seconds as number) ?? 10
  sentinelRetryCooldown.value = (app.sentinel_probe_retry_cooldown_seconds as number) ?? 300.0
  sentinelSuspiciousLookback.value = (app.sentinel_suspicious_lookback_minutes as number) ?? 60
  sentinelZeroUplinkWindow.value = (app.sentinel_zero_uplink_window_minutes as number) ?? 3
  sentinelProbeMode.value = (app.sentinel_probe_mode as string) ?? 'cn_probe_mesh'
  sentinelConfirmCycles.value = (app.sentinel_probe_confirm_cycles as number) ?? 2
  sentinelMinCnProbe.value = (app.sentinel_probe_min_cn_probe_count as number) ?? 2
  sentinelSuccessRatio.value = (app.sentinel_probe_required_success_ratio as number) ?? 0.5
  sentinelAllowAutoHealHy2.value = (app.sentinel_probe_allow_auto_heal_hy2 as boolean) ?? false
}

// ---------------------------------------------------------------------------
// Logging Form
// ---------------------------------------------------------------------------
const logLevel = ref('INFO')
const logRetentionDays = ref(30)

const logLevelOptions: SelectOption[] = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
  { label: 'CRITICAL', value: 'CRITICAL' },
]

function buildLoggingForm() {
  if (!config.value) return
  const logging = config.value.logging ?? {}
  logLevel.value = (logging.level as string) ?? 'INFO'
  logRetentionDays.value = (logging.log_retention_days as number) ?? 30
}

// ---------------------------------------------------------------------------
// Dashboard Form
// ---------------------------------------------------------------------------
const dashboardRequirePassword = ref(true)
const dashboardPassword = ref('')

function buildDashboardForm() {
  if (!config.value) return
  const app = config.value.app ?? {}
  dashboardRequirePassword.value = (app.dashboard_require_password as boolean) ?? true
  dashboardPassword.value = ''
}

// ---------------------------------------------------------------------------
// API Actions
// ---------------------------------------------------------------------------
async function fetchConfig() {
  loading.value = true
  error.value = null
  try {
    const { data } = await apiClient.get<ConfigResponse>('/config')
    config.value = data
    buildMatrixForm()
    buildDaemonForm()
    buildPhoneHomeForm()
    buildArtifactCacheForm()
    buildProbeServerForm()
    buildSentinelForm()
    buildLoggingForm()
    buildDashboardForm()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string } }; message?: string }
    error.value = axiosErr.response?.data?.error || axiosErr.message || t('settings.loadFailed')
  } finally {
    loading.value = false
  }
}

async function saveFleetMatrix() {
  const region = activeRegion.value
  if (!region) { message.warning(t('settings.inputNewRegion')); return }

  savingFleetMatrix.value = true
  try {
    const currentMatrix = JSON.parse(JSON.stringify(config.value?.fleet_matrix ?? {})) as Record<string, unknown>
    const formRegion = fleetMatrixForm.value[region]
    if (!formRegion) return

    const merged: Record<string, unknown> = {}
    for (const p of PROTOCOLS) {
      merged[p] = {
        desired_count: formRegion[p]?.desired_count ?? 0,
        min_alert_threshold: formRegion[p]?.min_alert_threshold ?? 0,
      }
    }
    currentMatrix[region] = merged

    await apiClient.put<FleetMatrixUpdateRequest, never>('/config/fleet-matrix', { fleet_matrix: currentMatrix })
    message.success(t('settings.regionSaved'))
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('settings.saveFailed'))
  } finally {
    savingFleetMatrix.value = false
  }
}

async function deleteRegion() {
  const region = regionToDelete.value
  if (!region) return

  savingFleetMatrix.value = true
  try {
    const currentMatrix = JSON.parse(JSON.stringify(config.value?.fleet_matrix ?? {})) as Record<string, unknown>
    delete currentMatrix[region]
    await apiClient.put<FleetMatrixUpdateRequest, never>('/config/fleet-matrix', { fleet_matrix: currentMatrix })
    message.success(t('settings.regionDeleted'))
    regionToDelete.value = null
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('settings.deleteFailed'))
  } finally {
    savingFleetMatrix.value = false
  }
}

async function saveApp() {
  savingApp.value = true
  try {
    const body: AppUpdateRequest = {
      daemon_idle_poll_interval_seconds: daemonIdlePoll.value,
      daemon_failure_backoff_seconds: daemonFailureBackoff.value,
      daemon_stale_task_recovery_interval_seconds: daemonStaleRecovery.value,
      daemon_running_task_timeout_seconds: daemonTaskTimeout.value,
      daemon_recovered_task_retry_delay_seconds: daemonRetryDelay.value,
      phone_home_base_url: phoneHomeBaseUrl.value || null,
      phone_home_listen_host: phoneHomeListenHost.value,
      phone_home_listen_port: phoneHomeListenPort.value,
      phone_home_ready_timeout_seconds: phoneHomeReadyTimeout.value,
      phone_home_poll_interval_seconds: phoneHomePollInterval.value,
      artifact_cache_enabled: artifactCacheEnabled.value,
      artifact_cache_listen_port: artifactCacheListenPort.value,
      artifact_cache_base_url_override: artifactCacheBaseUrl.value || null,
      probe_server_enabled: probeServerEnabled.value,
      probe_poll_interval_seconds: probePollInterval.value,
      probe_heartbeat_timeout_seconds: probeHeartbeatTimeout.value,
    }
    await apiClient.put<AppUpdateRequest, never>('/config/app', body)
    message.success(t('settings.daemonSaved'))
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('settings.saveFailed'))
  } finally {
    savingApp.value = false
  }
}

async function saveSentinel() {
  savingSentinel.value = true
  try {
    const body: SentinelUpdateRequest = {
      sentinel_enabled: sentinelEnabled.value,
      sentinel_poll_interval_seconds: sentinelPollInterval.value,
      sentinel_probe_timeout_seconds: sentinelProbeTimeout.value,
      sentinel_heal_cooldown_seconds: sentinelRetryCooldown.value,
      sentinel_suspicious_lookback_minutes: sentinelSuspiciousLookback.value,
      sentinel_zero_uplink_window_minutes: sentinelZeroUplinkWindow.value,
      sentinel_probe_mode: sentinelProbeMode.value,
      sentinel_probe_confirm_cycles: sentinelConfirmCycles.value,
      sentinel_probe_min_cn_probe_count: sentinelMinCnProbe.value,
      sentinel_probe_required_success_ratio: sentinelSuccessRatio.value,
      sentinel_probe_allow_auto_heal_hy2: sentinelAllowAutoHealHy2.value,
    }
    await apiClient.put<SentinelUpdateRequest, never>('/config/sentinel', body)
    message.success(t('settings.sentinelSaved'))
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('settings.saveFailed'))
  } finally {
    savingSentinel.value = false
  }
}

async function saveLogging() {
  savingLogging.value = true
  try {
    const body: LoggingUpdateRequest = { level: logLevel.value, log_retention_days: logRetentionDays.value }
    await apiClient.put<LoggingUpdateRequest, never>('/config/logging', body)
    message.success(t('settings.loggingSaved'))
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('settings.saveFailed'))
  } finally {
    savingLogging.value = false
  }
}

async function saveDashboard() {
  savingDashboard.value = true
  try {
    const body: DashboardUpdateRequest = { dashboard_require_password: dashboardRequirePassword.value }
    if (dashboardPassword.value.trim()) {
      body.dashboard_password = dashboardPassword.value.trim()
    }
    await apiClient.put<DashboardUpdateRequest, never>('/config/dashboard', body)
    message.success(t('settings.dashboardSaved'))
    dashboardPassword.value = ''
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('settings.saveFailed'))
  } finally {
    savingDashboard.value = false
  }
}

function confirmResetFleetMatrix() {
  dialog.warning({
    title: t('settings.confirmReset'),
    content: t('settings.confirmResetContent'),
    positiveText: t('settings.confirmReset'),
    negativeText: 'Cancel',
    onPositiveClick: async () => {
      resettingFleetMatrix.value = true
      try {
        await apiClient.put<FleetMatrixUpdateRequest, never>('/config/fleet-matrix', { fleet_matrix: {} })
        message.success(t('settings.resetFleetMatrix'))
        await fetchConfig()
      } catch (e: unknown) {
        const axiosErr = e as { response?: { data?: { error?: string } }; message?: string }
        message.error(axiosErr.response?.data?.error || axiosErr.message || t('settings.resetFailed'))
      } finally {
        resettingFleetMatrix.value = false
      }
    },
  })
}

onMounted(() => { fetchConfig() })
</script>

<template>
  <NSpin :show="loading" :description="t('settings.loading')" style="padding: 16px; max-width: 1100px; margin: 0 auto">
    <NAlert v-if="error" type="error" :title="error" style="margin-bottom: 16px" closable @close="error = null" />

    <template v-if="!loading && config">

      <!-- ══ 1. Fleet Matrix ═══════════════════════════════════════════════════ -->
      <NCard :title="t('settings.fleetMatrix')" style="margin-bottom: 16px">
        <NText depth="3" style="display:block; margin-bottom: 16px">{{ t('settings.fleetMatrixDesc') }}</NText>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.newRegionName') }}</NText>
            <NInput v-model:value="newRegionName" :placeholder="t('settings.regionPlaceholder')" clearable @update:value="selectedRegion = null" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.selectExistingRegion') }}</NText>
            <NSelect v-model:value="selectedRegion" :options="regionOptions" :placeholder="t('settings.selectRegionEdit')" clearable @update:value="newRegionName = ''" />
          </div>
        </div>

        <template v-if="activeRegion">
          <NDivider>{{ activeRegion }}</NDivider>
          <div v-for="protocol in PROTOCOLS" :key="protocol" style="display: grid; grid-template-columns: 120px 1fr 1fr 48px; gap: 12px; margin-bottom: 12px; align-items: end">
            <NTag size="small" type="info">{{ protocol }}</NTag>
            <div>
              <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.desiredCount') }}</NText>
              <NInputNumber :model-value="fleetDesired(activeRegion, protocol).value" :min="0" style="width: 100%"
                @update:value="(v: number | null) => { if (activeRegion) fleetDesired(activeRegion, protocol).value = v ?? 0 }" />
            </div>
            <div>
              <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.alertThreshold') }}</NText>
              <NInputNumber :model-value="fleetThreshold(activeRegion, protocol).value" :min="0" style="width: 100%"
                @update:value="(v: number | null) => { if (activeRegion) fleetThreshold(activeRegion, protocol).value = v ?? 0 }" />
            </div>
            <div />
          </div>
          <NButton type="primary" :loading="savingFleetMatrix" @click="saveFleetMatrix">{{ t('settings.saveRegion') }}</NButton>
        </template>
        <NText v-else depth="3">{{ t('settings.inputOrSelectRegion') }}</NText>

        <NDivider />
        <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 8px">{{ t('settings.currentMatrix') }}</NText>
        <NDataTable v-if="matrixTableData.length > 0" :columns="matrixTableColumns" :data="matrixTableData" :bordered="false" size="small" :pagination="false" style="margin-bottom: 16px" />
        <NAlert v-else type="info" style="margin-bottom: 16px"><NText depth="3">{{ t('settings.noMatrixConfig') }}</NText></NAlert>

        <div v-if="deleteRegionOptions.length > 0" style="display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: end">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.deleteRegion') }}</NText>
            <NSelect v-model:value="regionToDelete" :options="deleteRegionOptions" :placeholder="t('settings.selectDeleteRegion')" clearable />
          </div>
          <NButton type="warning" :loading="savingFleetMatrix" :disabled="!regionToDelete" @click="deleteRegion">{{ t('settings.deleteSelectedRegion') }}</NButton>
        </div>
      </NCard>

      <!-- ══ 2. Daemon ═════════════════════════════════════════════════════════ -->
      <NCard :title="t('settings.daemonSettings')" style="margin-bottom: 16px">
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.daemonIdlePoll') }}</NText>
            <NInputNumber v-model:value="daemonIdlePoll" :min="0.1" :step="0.5" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.daemonFailureBackoff') }}</NText>
            <NInputNumber v-model:value="daemonFailureBackoff" :min="0.1" :step="0.5" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.daemonStaleRecovery') }}</NText>
            <NInputNumber v-model:value="daemonStaleRecovery" :min="1" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.daemonTaskTimeout') }}</NText>
            <NInputNumber v-model:value="daemonTaskTimeout" :min="60" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.daemonRetryDelay') }}</NText>
            <NInputNumber v-model:value="daemonRetryDelay" :min="1" style="width: 100%" />
          </div>
        </div>
        <NButton type="primary" :loading="savingApp" style="margin-top: 16px" @click="saveApp">{{ t('settings.saveAppConfig') }}</NButton>
      </NCard>

      <!-- ══ 3. Phone-Home ══════════════════════════════════════════════════════ -->
      <NCard :title="t('settings.phoneHomeSettings')" style="margin-bottom: 16px">
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.phoneHomeEnabled') }}</NText>
            <NInput v-model:value="phoneHomeBaseUrl" placeholder="http://host:8787" clearable />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.phoneHomeListenHost') }}</NText>
            <NInput v-model:value="phoneHomeListenHost" placeholder="::" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.phoneHomeListenPort') }}</NText>
            <NInputNumber v-model:value="phoneHomeListenPort" :min="1" :max="65535" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.phoneHomeReadyTimeout') }}</NText>
            <NInputNumber v-model:value="phoneHomeReadyTimeout" :min="1" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.phoneHomePollInterval') }}</NText>
            <NInputNumber v-model:value="phoneHomePollInterval" :min="1" style="width: 100%" />
          </div>
        </div>
        <NButton type="primary" :loading="savingApp" style="margin-top: 16px" @click="saveApp">{{ t('settings.phoneHomeSaved') }}</NButton>
      </NCard>

      <!-- ══ 4. Artifact Cache ══════════════════════════════════════════════════ -->
      <NCard :title="t('settings.artifactCacheSettings')" style="margin-bottom: 16px">
        <div style="display: grid; grid-template-columns: auto 1fr 1fr; gap: 16px; align-items: end">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.artifactCacheEnabled') }}</NText>
            <NSwitch v-model:value="artifactCacheEnabled" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.artifactCacheListenPort') }}</NText>
            <NInputNumber v-model:value="artifactCacheListenPort" :min="1" :max="65535" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.artifactCacheBaseUrl') }}</NText>
            <NInput v-model:value="artifactCacheBaseUrl" :placeholder="t('settings.artifactCacheBaseUrlHint')" clearable />
          </div>
        </div>
        <NButton type="primary" :loading="savingApp" style="margin-top: 16px" @click="saveApp">{{ t('settings.artifactCacheSaved') }}</NButton>
      </NCard>

      <!-- ══ 5. Probe Server ════════════════════════════════════════════════════ -->
      <NCard :title="t('settings.probeServerSettings')" style="margin-bottom: 16px">
        <div style="display: grid; grid-template-columns: auto 1fr 1fr; gap: 16px; align-items: end">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.probeServerEnabled') }}</NText>
            <NSwitch v-model:value="probeServerEnabled" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.probePollInterval') }}</NText>
            <NInputNumber v-model:value="probePollInterval" :min="1" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.probeHeartbeatTimeout') }}</NText>
            <NInputNumber v-model:value="probeHeartbeatTimeout" :min="1" style="width: 100%" />
          </div>
        </div>
        <NButton type="primary" :loading="savingApp" style="margin-top: 16px" @click="saveApp">{{ t('settings.probeServerSaved') }}</NButton>
      </NCard>

      <!-- ══ 6. Sentinel (expanded) ═══════════════════════════════════════════ -->
      <NCard :title="t('settings.sentinelSettings')" style="margin-bottom: 16px">
        <div style="display: grid; grid-template-columns: auto 1fr; gap: 16px; align-items: end; margin-bottom: 16px">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.enableSentinel') }}</NText>
            <NSwitch v-model:value="sentinelEnabled" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.sentinelProbeMode') }}</NText>
            <NSelect v-model:value="sentinelProbeMode" :options="sentinelProbeModeOptions" style="width: 100%" />
          </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.sentinelPollIntervalSecs') }}</NText>
            <NInputNumber v-model:value="sentinelPollInterval" :min="1" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.sentinelProbeTimeoutSecs') }}</NText>
            <NInputNumber v-model:value="sentinelProbeTimeout" :min="1" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.healCooldown') }}</NText>
            <NInputNumber v-model:value="sentinelRetryCooldown" :min="1" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.sentinelSuspiciousLookback') }}</NText>
            <NInputNumber v-model:value="sentinelSuspiciousLookback" :min="1" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.sentinelZeroUplinkWindow') }}</NText>
            <NInputNumber v-model:value="sentinelZeroUplinkWindow" :min="1" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.confirmCycles') }}</NText>
            <NInputNumber v-model:value="sentinelConfirmCycles" :min="1" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.minCnProbe') }}</NText>
            <NInputNumber v-model:value="sentinelMinCnProbe" :min="2" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.probeSuccessThreshold') }}</NText>
            <NInputNumber v-model:value="sentinelSuccessRatio" :min="0" :max="1" :step="0.1" style="width: 100%" />
          </div>
          <div style="display: flex; align-items: center; padding-bottom: 8px; gap: 8px">
            <NSwitch v-model:value="sentinelAllowAutoHealHy2" />
            <NText depth="3" style="font-size: 13px">{{ t('settings.sentinelAllowAutoHealHy2') }}</NText>
          </div>
        </div>
        <NButton type="primary" :loading="savingSentinel" style="margin-top: 16px" @click="saveSentinel">{{ t('settings.sentinelSaved') }}</NButton>
      </NCard>

      <!-- ══ 7. Logging ═════════════════════════════════════════════════════════ -->
      <NCard :title="t('settings.loggingSettings')" style="margin-bottom: 16px">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.logLevel') }}</NText>
            <NSelect v-model:value="logLevel" :options="logLevelOptions" style="width: 100%" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.logRetentionDays') }}</NText>
            <NInputNumber v-model:value="logRetentionDays" :min="1" style="width: 100%" />
          </div>
        </div>
        <NButton type="primary" :loading="savingLogging" style="margin-top: 16px" @click="saveLogging">{{ t('settings.loggingSaved') }}</NButton>
      </NCard>

      <!-- ══ 8. Dashboard Security ════════════════════════════════════════════ -->
      <NCard :title="t('settings.dashboardSettings')" style="margin-bottom: 16px">
        <div style="display: grid; grid-template-columns: auto 1fr; gap: 16px; align-items: end">
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.requirePassword') }}</NText>
            <NSwitch v-model:value="dashboardRequirePassword" />
          </div>
          <div>
            <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.accessPassword') }}</NText>
            <NInput v-model:value="dashboardPassword" type="password" :placeholder="t('settings.passwordHint')" show-password-on="mousedown" />
          </div>
        </div>
        <NButton type="primary" :loading="savingDashboard" style="margin-top: 16px" @click="saveDashboard">{{ t('settings.saveDashboardConfig') }}</NButton>
      </NCard>

      <!-- ══ 9. Danger Zone ═══════════════════════════════════════════════════ -->
      <NCard :title="t('settings.dangerZone')" style="margin-bottom: 16px">
        <NAlert type="warning" :title="t('settings.dangerWarning')" style="margin-bottom: 16px" />
        <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 4px">{{ t('settings.resetFleetMatrix') }}</NText>
        <NText depth="3" style="font-size: 12px; display:block; margin-bottom: 8px">{{ t('settings.resetFleetMatrixDesc') }}</NText>
        <NButton type="warning" :loading="resettingFleetMatrix" @click="confirmResetFleetMatrix">{{ t('settings.resetFleetMatrixBtn') }}</NButton>
      </NCard>

    </template>
  </NSpin>
</template>
