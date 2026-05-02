<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NCard,
  NGrid,
  NGi,
  NCollapse,
  NCollapseItem,
  NSpin,
  NAlert,
  NInput,
  NInputNumber,
  NSwitch,
  NButton,
  NSpace,
  NText,
  NDataTable,
  NSelect,
  NTag,
  NDivider,
  useMessage,
  useDialog,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import apiClient from '@/api/client'
import type {
  ConfigResponse,
  FleetMatrixUpdateRequest,
  SentinelUpdateRequest,
  DashboardUpdateRequest,
} from '@/types/api'

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
const savingSentinel = ref(false)
const savingDashboard = ref(false)
const resettingFleetMatrix = ref(false)

// ---------------------------------------------------------------------------
// Fleet Matrix Editor State
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
      form[region][protocol] = {
        desired_count: existing?.desired_count ?? 0,
        min_alert_threshold: existing?.min_alert_threshold ?? 0,
      }
    }
  }
  fleetMatrixForm.value = form
}

// ---------------------------------------------------------------------------
// Sentinel Form State
// ---------------------------------------------------------------------------
const sentinelEnabled = ref(false)
const sentinelPollInterval = ref(180)
const sentinelConfirmCycles = ref(2)
const sentinelHealCooldown = ref(900)
const sentinelMinCnProbe = ref(2)
const sentinelSuccessRatio = ref(0.5)

function buildSentinelForm() {
  if (!config.value) return
  const app = config.value.app ?? {}
  sentinelEnabled.value = (app.sentinel_enabled as boolean) ?? false
  sentinelPollInterval.value = (app.sentinel_poll_interval_seconds as number) ?? 180
  sentinelConfirmCycles.value = (app.sentinel_probe_confirm_cycles as number) ?? 2
  sentinelHealCooldown.value = (app.sentinel_heal_cooldown_seconds as number) ?? 900
  sentinelMinCnProbe.value = (app.sentinel_probe_min_cn_probe_count as number) ?? 2
  sentinelSuccessRatio.value = (app.sentinel_probe_required_success_ratio as number) ?? 0.5
}

// ---------------------------------------------------------------------------
// Dashboard Form State
// ---------------------------------------------------------------------------
const dashboardRequirePassword = ref(false)
const dashboardPassword = ref('')

function buildDashboardForm() {
  if (!config.value) return
  const app = config.value.app ?? {}
  dashboardRequirePassword.value = (app.dashboard_require_password as boolean) ?? false
  dashboardPassword.value = (app.dashboard_password as string) ?? ''
}

// ---------------------------------------------------------------------------
// Fleet Matrix Table
// ---------------------------------------------------------------------------
interface MatrixRow {
  region: string
  protocol: string
  desired_count: number
  alert_threshold: number
}

const matrixTableData = computed<MatrixRow[]>(() => {
  const rows: MatrixRow[] = []
  const raw = config.value?.fleet_matrix ?? {}
  for (const region of Object.keys(raw).sort()) {
    const protocols = raw[region] as Record<string, unknown>
    for (const protocol of PROTOCOLS) {
      const p = protocols?.[protocol] as { desired_count?: number; min_alert_threshold?: number } | undefined
      if (p) {
        rows.push({
          region,
          protocol,
          desired_count: p.desired_count ?? 0,
          alert_threshold: p.min_alert_threshold ?? 0,
        })
      }
    }
  }
  return rows
})

const matrixTableColumns: DataTableColumns<MatrixRow> = [
  { title: '区域', key: 'region', width: 160 },
  { title: '协议', key: 'protocol', width: 120 },
  { title: '期望数量', key: 'desired_count', width: 120 },
  { title: '告警阈值', key: 'alert_threshold', width: 120 },
]

const deleteRegionOptions = computed<{ label: string; value: string }[]>(() =>
  Object.keys(config.value?.fleet_matrix ?? {}).map((r) => ({ label: r, value: r }))
)
const regionToDelete = ref<string | null>(null)

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
    buildSentinelForm()
    buildDashboardForm()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string; message?: string } }; status?: number; message?: string }
    error.value = axiosErr.response?.data?.error || axiosErr.message || '加载配置失败'
  } finally {
    loading.value = false
  }
}

async function saveFleetMatrix() {
  const region = activeRegion.value
  if (!region) {
    message.warning('请输入或选择要保存的区域')
    return
  }

  savingFleetMatrix.value = true
  try {
    // Merge the edited region into current fleet_matrix
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

    const body: FleetMatrixUpdateRequest = { fleet_matrix: currentMatrix }
    await apiClient.put<FleetMatrixUpdateRequest, never>('/config/fleet-matrix', body)
    message.success(`区域 "${region}" 保存成功`)
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || '保存失败')
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

    const body: FleetMatrixUpdateRequest = { fleet_matrix: currentMatrix }
    await apiClient.put<FleetMatrixUpdateRequest, never>('/config/fleet-matrix', body)
    message.success(`区域 "${region}" 已删除`)
    regionToDelete.value = null
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || '删除失败')
  } finally {
    savingFleetMatrix.value = false
  }
}

async function saveSentinel() {
  savingSentinel.value = true
  try {
    const body: SentinelUpdateRequest = {
      sentinel_enabled: sentinelEnabled.value,
      sentinel_poll_interval_seconds: sentinelPollInterval.value,
      sentinel_probe_confirm_cycles: sentinelConfirmCycles.value,
      sentinel_heal_cooldown_seconds: sentinelHealCooldown.value,
    }
    await apiClient.put<SentinelUpdateRequest, never>('/config/sentinel', body)
    message.success('Sentinel 配置已保存')
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || '保存失败')
  } finally {
    savingSentinel.value = false
  }
}

async function saveDashboard() {
  savingDashboard.value = true
  try {
    const body: DashboardUpdateRequest = {
      dashboard_require_password: dashboardRequirePassword.value,
      dashboard_password: dashboardPassword.value || null,
    }
    await apiClient.put<DashboardUpdateRequest, never>('/config/dashboard', body)
    message.success('Dashboard 配置已保存')
    await fetchConfig()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || '保存失败')
  } finally {
    savingDashboard.value = false
  }
}

function confirmResetFleetMatrix() {
  dialog.warning({
    title: '确认重置',
    content: '确定要清空整个舰队矩阵配置吗？此操作不可逆。',
    positiveText: '确认重置',
    negativeText: '取消',
    onPositiveClick: async () => {
      resettingFleetMatrix.value = true
      try {
        const body: FleetMatrixUpdateRequest = { fleet_matrix: {} }
        await apiClient.put<FleetMatrixUpdateRequest, never>('/config/fleet-matrix', body)
        message.success('舰队矩阵已重置')
        await fetchConfig()
      } catch (e: unknown) {
        const axiosErr = e as { response?: { data?: { error?: string; message?: string } }; message?: string }
        message.error(axiosErr.response?.data?.error || axiosErr.message || '重置失败')
      } finally {
        resettingFleetMatrix.value = false
      }
    },
  })
}

function restoreDefaults() {
  dialog.warning({
    title: '确认恢复默认配置',
    content: '此操作将把 Sentinel 和 Dashboard 配置恢复为默认值。舰队矩阵不会被清空（需单独操作）。',
    positiveText: '确认恢复',
    negativeText: '取消',
    onPositiveClick: async () => {
      savingDashboard.value = true
      try {
        const sentinelBody: SentinelUpdateRequest = {
          sentinel_enabled: false,
          sentinel_poll_interval_seconds: 180.0,
          sentinel_probe_timeout_seconds: 10,
          sentinel_heal_cooldown_seconds: 900.0,
          sentinel_probe_confirm_cycles: 2,
        }
        const dashboardBody: DashboardUpdateRequest = {
          dashboard_require_password: false,
          dashboard_password: null,
        }
        await Promise.all([
          apiClient.put<SentinelUpdateRequest, never>('/config/sentinel', sentinelBody),
          apiClient.put<DashboardUpdateRequest, never>('/config/dashboard', dashboardBody),
        ])
        message.success('配置已恢复默认值')
        await fetchConfig()
      } catch (e: unknown) {
        const axiosErr = e as { response?: { data?: { error?: string } } }
        message.error(axiosErr.response?.data?.error || '恢复默认配置失败')
      } finally {
        savingDashboard.value = false
      }
    },
  })
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
  fetchConfig()
})
</script>

<template>
  <NSpin :show="loading" description="加载配置…" style="padding: 16px; max-width: 1100px; margin: 0 auto">
    <NAlert v-if="error" type="error" :title="error" style="margin-bottom: 16px" closable @close="error = null" />

    <template v-if="!loading && config">
      <!-- ── Fleet Matrix ────────────────────────────────────────────────────── -->
      <NCard title="舰队矩阵 (Fleet Matrix)" style="margin-bottom: 16px">
        <NText depth="3" style="display: block; margin-bottom: 16px">
          配置每个区域每个协议的期望节点数和告警阈值。
        </NText>

        <!-- Editor -->
        <NCollapse :default-expanded-names="['editor']">
          <NCollapseItem title="编辑舰队矩阵配置" name="editor">
            <NGrid :cols="2" :x-gap="16" :y-gap="12" style="margin-bottom: 16px">
              <NGi>
                <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">新区域名称</NText>
                <NInput
                  v-model:value="newRegionName"
                  placeholder="例如 ap-northeast-1"
                  clearable
                  @update:value="selectedRegion = null"
                />
              </NGi>
              <NGi>
                <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">选择已有区域</NText>
                <NSelect
                  v-model:value="selectedRegion"
                  :options="regionOptions"
                  placeholder="选择区域以编辑"
                  clearable
                  @update:value="newRegionName = ''"
                />
              </NGi>
            </NGrid>

            <template v-if="activeRegion">
              <NDivider>{{ activeRegion }}</NDivider>

              <NGrid
                v-for="protocol in PROTOCOLS"
                :key="protocol"
                :cols="4"
                :x-gap="12"
                :y-gap="8"
                style="margin-bottom: 12px; align-items: center"
              >
                <NGi>
                  <NTag size="small" type="info">{{ protocol }}</NTag>
                </NGi>
                <NGi>
                  <NText depth="3" style="font-size: 12px">期望节点数</NText>
                  <NInputNumber
                    :model-value="fleetDesired(activeRegion, protocol).value"
                    :min="0"
                    :default-value="0"
                    style="width: 100%"
                    @update:value="(v: number | null) => { if (activeRegion) fleetDesired(activeRegion, protocol).value = v ?? 0 }"
                  />
                </NGi>
                <NGi>
                  <NText depth="3" style="font-size: 12px">告警阈值</NText>
                  <NInputNumber
                    :model-value="fleetThreshold(activeRegion, protocol).value"
                    :min="0"
                    :default-value="0"
                    style="width: 100%"
                    @update:value="(v: number | null) => { if (activeRegion) fleetThreshold(activeRegion, protocol).value = v ?? 0 }"
                  />
                </NGi>
                <NGi />
              </NGrid>

              <NButton
                type="primary"
                :loading="savingFleetMatrix"
                @click="saveFleetMatrix"
              >
                保存区域 {{ activeRegion }}
              </NButton>
            </template>
            <NText v-else depth="3">请输入新区域名称或选择已有区域进行编辑</NText>
          </NCollapseItem>
        </NCollapse>

        <NDivider />

        <!-- Current Table -->
        <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">当前舰队矩阵配置</NText>
        <NDataTable
          v-if="matrixTableData.length > 0"
          :columns="matrixTableColumns"
          :data="matrixTableData"
          :bordered="false"
          size="small"
          :pagination="false"
          style="margin-bottom: 16px"
        />
        <NAlert v-else type="info" title="暂无舰队矩阵配置" :show-icon="false">
          <NText depth="3">当前尚未配置舰队矩阵</NText>
        </NAlert>

        <!-- Delete Region -->
        <NGrid v-if="deleteRegionOptions.length > 0" :cols="2" :x-gap="12" :y-gap="8" style="align-items: end">
          <NGi>
            <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">删除区域配置</NText>
            <NSelect
              v-model:value="regionToDelete"
              :options="deleteRegionOptions"
              placeholder="选择要删除的区域"
              clearable
            />
          </NGi>
          <NGi>
            <NButton
              type="warning"
              :loading="savingFleetMatrix"
              :disabled="!regionToDelete"
              @click="deleteRegion"
            >
              删除选中区域
            </NButton>
          </NGi>
        </NGrid>
      </NCard>

      <!-- ── Sentinel Settings ──────────────────────────────────────────────── -->
      <NCard title="应用运行时配置" style="margin-bottom: 16px">
        <NCollapse>
          <NCollapseItem title="Sentinel 监控设置" name="sentinel">
            <NGrid :cols="2" :x-gap="16" :y-gap="12">
              <NGi>
                <NSpace vertical>
                  <NText depth="3" style="font-size: 12px">启用 Sentinel</NText>
                  <NSwitch v-model:value="sentinelEnabled" />
                </NSpace>
              </NGi>
              <NGi>
                <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">
                  轮询间隔（秒）
                </NText>
                <NInputNumber
                  v-model:value="sentinelPollInterval"
                  :min="1"
                  :default-value="180"
                  style="width: 100%"
                />
              </NGi>
              <NGi>
                <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">
                  确认周期数
                </NText>
                <NInputNumber
                  v-model:value="sentinelConfirmCycles"
                  :min="1"
                  :default-value="2"
                  style="width: 100%"
                />
              </NGi>
              <NGi>
                <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">
                  自愈冷却时间（秒）
                </NText>
                <NInputNumber
                  v-model:value="sentinelHealCooldown"
                  :min="60"
                  :default-value="900"
                  style="width: 100%"
                />
              </NGi>
              <NGi>
                <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">
                  最小国内探针数
                </NText>
                <NInputNumber
                  v-model:value="sentinelMinCnProbe"
                  :min="1"
                  :default-value="2"
                  style="width: 100%"
                />
              </NGi>
              <NGi>
                <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">
                  探测成功率阈值（0–1）
                </NText>
                <NInputNumber
                  v-model:value="sentinelSuccessRatio"
                  :min="0"
                  :max="1"
                  :step="0.1"
                  :default-value="0.5"
                  style="width: 100%"
                />
              </NGi>
            </NGrid>
            <NButton
              type="primary"
              :loading="savingSentinel"
              style="margin-top: 16px"
              @click="saveSentinel"
            >
              保存应用配置
            </NButton>
          </NCollapseItem>
        </NCollapse>
      </NCard>

      <!-- ── Dashboard Settings ───────────────────────────────────────────── -->
      <NCard title="Dashboard 设置" style="margin-bottom: 16px">
        <NCollapse>
          <NCollapseItem title="Dashboard 配置" name="dashboard">
            <NSpace vertical>
              <NSpace align="center">
                <NText depth="3">需要密码访问</NText>
                <NSwitch v-model:value="dashboardRequirePassword" />
              </NSpace>

              <template v-if="dashboardRequirePassword">
                <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">
                  访问密码
                </NText>
                <NInput
                  v-model:value="dashboardPassword"
                  type="password"
                  placeholder="输入密码，留空则保持不变"
                  style="max-width: 320px"
                  show-password-on="click"
                />
              </template>
            </NSpace>
            <NButton
              type="primary"
              :loading="savingDashboard"
              style="margin-top: 16px"
              @click="saveDashboard"
            >
              保存 Dashboard 配置
            </NButton>
          </NCollapseItem>
        </NCollapse>
      </NCard>

      <!-- ── Danger Zone ──────────────────────────────────────────────────── -->
      <NCard title="危险操作">
        <NCollapse>
          <NCollapseItem title="危险操作区" name="danger">
            <NAlert type="warning" title="以下操作不可逆，请谨慎操作" style="margin-bottom: 16px">
              <NText depth="3">执行前请确认操作后果。</NText>
            </NAlert>

            <NGrid :cols="2" :x-gap="16" :y-gap="12">
              <NGi>
                <NText depth="3" style="display: block; margin-bottom: 4px; font-size: 12px">
                  重置 Fleet Matrix
                </NText>
                <NText depth="3" style="display: block; margin-bottom: 8px; font-size: 12px">
                  清空整个 fleet_matrix 配置（删除所有区域）
                </NText>
                <NButton
                  type="warning"
                  :loading="resettingFleetMatrix"
                  @click="confirmResetFleetMatrix"
                >
                  重置 Fleet Matrix
                </NButton>
              </NGi>
              <NGi>
                <NText depth="3" style="display: block; margin-bottom: 4px; font-size: 12px">
                  恢复默认配置
                </NText>
                <NText depth="3" style="display: block; margin-bottom: 8px; font-size: 12px">
                  恢复出厂默认配置
                </NText>
                <NButton type="warning" @click="restoreDefaults">
                  恢复默认配置
                </NButton>
              </NGi>
            </NGrid>
          </NCollapseItem>
        </NCollapse>
      </NCard>
    </template>
  </NSpin>
</template>
