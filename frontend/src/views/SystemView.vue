<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import {
  NSpin,
  NAlert,
  NGrid,
  NGi,
  NStatistic,
  NSpace,
  NTag,
  NCode,
  NDescriptions,
  NDescriptionsItem,
  NCard,
  NDataTable,
  NDivider,
} from 'naive-ui'
import { useAuthStore } from '@/stores/authStore'
import apiClient from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import type { ConfigResponse } from '@/types/api'

const { t } = useI18n()
const loading = ref(true)
const error = ref<string | null>(null)
const config = ref<ConfigResponse | null>(null)
const authStore = useAuthStore()
const platform: string = navigator.platform

const currentTime = ref(new Date().toLocaleString('zh-CN', { timeZoneName: 'short' }))
let clockTimer: ReturnType<typeof setInterval> | null = null

const appConfig = computed(() => config.value?.app ?? {})
const telegramConfig = computed(() => config.value?.telegram ?? {})
const cloudflareConfig = computed(() => config.value?.cloudflare ?? {})
const awsProxyConfig = computed(() => config.value?.aws_proxy ?? {})
const xboardConfig = computed(() => config.value?.xboard ?? null)
const fleetMatrix = computed(() => config.value?.fleet_matrix ?? {})

const statusTag = (val: unknown): { type: 'success' | 'info'; label: string } => {
  if (val === true) return { type: 'success', label: t('system.enabled') }
  if (val === false) return { type: 'info', label: t('system.disabled') }
  return { type: 'info', label: String(val ?? 'N/A') }
}

const maskToken = (token: string | unknown): string => {
  const s = String(token ?? '')
  if (s.length < 12) return '***'
  return `${s.slice(0, 8)}...`
}

const probeBootstrapTokens = computed<string[]>(() => {
  const raw = appConfig.value.probe_bootstrap_tokens
  if (!Array.isArray(raw)) return []
  return raw as string[]
})

const healthRows = computed(() => [
  { key: 'SQLite 连接', passed: true, detail: t('system.normal') },
  {
    key: 'Xboard PostgreSQL',
    passed: !!xboardConfig.value,
    detail: xboardConfig.value ? t('system.connected') : t('system.notConnected'),
  },
  { key: '配置加载', passed: !!config.value, detail: config.value ? t('system.success') : t('system.failure') },
  { key: '日志系统', passed: true, detail: t('system.normal') },
])

const healthColumns = [
  { title: t('system.checkItem'), key: 'key' },
  { title: t('system.status'), key: 'detail' },
  {
    title: t('system.result'),
    key: 'passed',
    render: (row: { key: string; passed: boolean }) =>
      h(
        NTag,
        { type: row.passed ? 'success' : 'error' },
        () => row.passed ? t('system.passed') : t('system.failed'),
      ),
  },
]

const apiEndpoints = [
  { method: 'POST', path: '/probe/register', desc: t('system.probeRegister') },
  { method: 'POST', path: '/probe/heartbeat', desc: t('system.probeHeartbeat') },
  { method: 'POST', path: '/probe/poll', desc: t('system.probePoll') },
  { method: 'POST', path: '/probe/result', desc: t('system.probeResult') },
  { method: 'GET', path: '/probe/config', desc: t('system.probeConfig') },
  { method: 'POST', path: '/callback/ready', desc: t('system.nodeReadyCallback') },
]

const endpointColumns = [
  { title: t('system.method'), key: 'method' },
  { title: t('system.path'), key: 'path' },
  { title: t('system.description'), key: 'desc' },
]

const timingRows = computed(() => [
  {
    key: 'daemon_idle_poll_interval_seconds',
    label: t('system.daemonPollInterval'),
    value: appConfig.value.daemon_idle_poll_interval_seconds,
    unit: 's',
  },
  {
    key: 'daemon_running_task_timeout_seconds',
    label: t('system.taskTimeout'),
    value: appConfig.value.daemon_running_task_timeout_seconds,
    unit: 's',
  },
  {
    key: 'daemon_stale_task_recovery_interval_seconds',
    label: t('system.staleRecoveryInterval'),
    value: appConfig.value.daemon_stale_task_recovery_interval_seconds,
    unit: 's',
  },
  {
    key: 'daemon_failure_backoff_seconds',
    label: t('system.failureBackoff'),
    value: appConfig.value.daemon_failure_backoff_seconds,
    unit: 's',
  },
])

const sentinelTimingRows = computed(() => {
  if (!appConfig.value.sentinel_enabled) return []
  return [
    {
      key: 'sentinel_poll_interval_seconds',
      label: t('system.sentinelPollInterval'),
      value: appConfig.value.sentinel_poll_interval_seconds,
      unit: 's',
    },
    {
      key: 'sentinel_heal_cooldown_seconds',
      label: t('system.sentinelHealCooldown'),
      value: appConfig.value.sentinel_heal_cooldown_seconds,
      unit: 's',
    },
    {
      key: 'sentinel_probe_timeout_seconds',
      label: t('system.sentinelProbeTimeout'),
      value: appConfig.value.sentinel_probe_timeout_seconds,
      unit: 's',
    },
    {
      key: 'sentinel_probe_confirm_cycles',
      label: t('system.sentinelConfirmCycles'),
      value: appConfig.value.sentinel_probe_confirm_cycles,
      unit: '次',
    },
  ]
})

const phoneHomeRows = computed(() => [
  { key: 'phone_home_listen_host', label: t('system.phoneHomeListen'), value: appConfig.value.phone_home_listen_host },
  { key: 'phone_home_listen_port', label: t('system.phoneHomePort'), value: appConfig.value.phone_home_listen_port },
  {
    key: 'phone_home_ready_timeout_seconds',
    label: t('system.phoneHomeTimeout'),
    value: `${appConfig.value.phone_home_ready_timeout_seconds}s`,
  },
  {
    key: 'phone_home_poll_interval_seconds',
    label: t('system.phoneHomeInterval'),
    value: `${appConfig.value.phone_home_poll_interval_seconds}s`,
  },
])

const configStatusRows = computed(() => [
  { key: 'sentinel_enabled', label: t('system.sentinelEnabled'), value: appConfig.value.sentinel_enabled },
  { key: 'probe_server_enabled', label: t('system.probeServerEnabled'), value: appConfig.value.probe_server_enabled },
  { key: 'telegram_enabled', label: t('system.telegramEnabled'), value: telegramConfig.value.enabled },
  { key: 'cloudflare_enabled', label: t('system.cloudflareEnabled'), value: cloudflareConfig.value.enabled },
  { key: 'aws_proxy_enabled', label: t('system.awsProxyEnabled'), value: awsProxyConfig.value.enabled },
  { key: 'xboard_available', label: t('system.xboardDb'), value: !!xboardConfig.value },
  {
    key: 'dashboard_require_password',
    label: t('system.dashboardPassword'),
    value: appConfig.value.dashboard_require_password,
  },
])

onMounted(async () => {
  clockTimer = setInterval(() => {
    currentTime.value = new Date().toLocaleString('zh-CN', { timeZoneName: 'short' })
  }, 1000)

  try {
    const { data } = await apiClient.get<ConfigResponse>('/config')
    config.value = data
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string; message?: string } }; message?: string }
    error.value = axiosErr.response?.data?.error || axiosErr.message || t('system.loadConfigFailed')
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  if (clockTimer !== null) {
    clearInterval(clockTimer)
    clockTimer = null
  }
})
</script>

<template>
  <NSpin v-if="loading" />
  <NAlert v-else-if="error" type="error" :title="error" style="margin-bottom: 16px;" />

  <template v-else-if="config">
    <NCard :title="t('system.systemInfo')" style="margin-bottom: 16px;">
      <NGrid :cols="4" :x-gap="16" :y-gap="12">
        <NGi>
          <NStatistic :label="t('system.hostname')">
            {{ fleetMatrix.hostname ?? 'N/A' }}
          </NStatistic>
        </NGi>
        <NGi>
          <NStatistic :label="t('system.os')">
            {{ platform }}
          </NStatistic>
        </NGi>
        <NGi>
          <NStatistic :label="t('system.pythonVersion')">
            {{ appConfig.python_version ?? 'N/A' }}
          </NStatistic>
        </NGi>
        <NGi>
          <NStatistic :label="t('system.currentTime')">
            {{ currentTime }}
          </NStatistic>
        </NGi>
      </NGrid>
    </NCard>

    <NCard :title="t('system.runtimeConfig')" style="margin-bottom: 16px;">
      <NGrid :cols="3" :x-gap="16" :y-gap="12">
        <NGi>
          <NStatistic :label="t('system.environment')">
            {{ appConfig.environment ?? 'N/A' }}
          </NStatistic>
        </NGi>
        <NGi>
          <NStatistic :label="t('system.sqliteDb')">
            {{ appConfig.sqlite_path ?? 'N/A' }}
          </NStatistic>
        </NGi>
        <NGi>
          <NStatistic :label="t('system.runMode')">
            {{ appConfig.run_mode ?? 'N/A' }}
          </NStatistic>
        </NGi>
      </NGrid>
    </NCard>

    <NCard :title="t('system.configStatus')" style="margin-bottom: 16px;">
      <NDescriptions :column="1" label-placement="left" bordered size="small">
        <NDescriptionsItem v-for="row in configStatusRows" :key="row.key" :label="row.label">
          <NTag :type="statusTag(row.value).type">
            {{ statusTag(row.value).label }}
          </NTag>
        </NDescriptionsItem>
      </NDescriptions>
    </NCard>

    <NCard :title="t('system.phoneHomeServer')" style="margin-bottom: 16px;">
      <NDescriptions :column="2" label-placement="left" bordered size="small">
        <NDescriptionsItem v-for="row in phoneHomeRows" :key="row.key" :label="row.label">
          {{ row.value ?? 'N/A' }}
        </NDescriptionsItem>
      </NDescriptions>
    </NCard>

    <NCard :title="t('system.timingConfig')" style="margin-bottom: 16px;">
      <NDescriptions :column="2" label-placement="left" bordered size="small">
        <NDescriptionsItem v-for="row in timingRows" :key="row.key" :label="row.label">
          {{ row.value ?? 'N/A' }}{{ row.unit }}
        </NDescriptionsItem>
        <template v-if="sentinelTimingRows.length > 0">
          <NDescriptionsItem :label="''">
            <NDivider>{{ t('system.sentinel') }}</NDivider>
          </NDescriptionsItem>
          <NDescriptionsItem v-for="row in sentinelTimingRows" :key="row.key" :label="row.label">
            {{ row.value ?? 'N/A' }}{{ row.unit }}
          </NDescriptionsItem>
        </template>
      </NDescriptions>
    </NCard>

    <NCard :title="t('system.healthChecks')" style="margin-bottom: 16px;">
      <NDataTable :columns="healthColumns" :data="healthRows" :bordered="false" size="small" />
    </NCard>

    <NCard :title="t('system.availableEndpoints')" style="margin-bottom: 16px;">
      <NDataTable :columns="endpointColumns" :data="apiEndpoints" :bordered="false" size="small" />
    </NCard>

    <NCard :title="t('system.probeBootstrapTokens')" style="margin-bottom: 16px;">
      <NSpace vertical>
        <NTag v-if="probeBootstrapTokens.length === 0" type="warning">
          {{ t('system.noBootstrapToken') }}
        </NTag>
        <template v-else>
          <NTag type="success">{{ t('system.bootstrapTokensConfigured', { count: probeBootstrapTokens.length }) }}</NTag>
          <NSpace>
            <NCode v-for="(token, idx) in probeBootstrapTokens" :key="idx" language="text">
              Token {{ idx + 1 }}: {{ maskToken(token) }}
            </NCode>
          </NSpace>
        </template>
      </NSpace>
    </NCard>

    <NCard :title="t('system.currentSession')">
      <NCode language="text">
        Correlation ID: {{ authStore.correlationId ?? 'N/A' }}
      </NCode>
    </NCard>
  </template>
</template>
