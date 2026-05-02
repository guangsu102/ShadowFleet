<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import {
  NDataTable,
  NTag,
  NSpin,
  NButton,
  NProgress,
  NEmpty,
  NCollapse,
  NCollapseItem,
  useMessage,
  useDialog,
} from 'naive-ui'
import apiClient from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import type {
  AssetResponse,
  AbandonmentResultResponse,
  QuotaRowResponse,
} from '@/types/api'

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()

const loading = ref(false)
const errorMsg = ref<string | null>(null)
const lastRefresh = ref<Date>(new Date())

// ── Inline SVG icon helpers ──────────────────────────────────────────────────
function makeIcon(paths: string) {
  return () => h('svg', {
    xmlns: 'http://www.w3.org/2000/svg',
    viewBox: '0 0 24 24',
    style: 'width:18px;height:18px;fill:currentColor',
  }, [h('path', { d: paths })])
}

const IconShield = makeIcon('M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z')
const IconTrash = makeIcon('M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z')
const IconNode = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z')
const IconChart = makeIcon('M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z')
const IconRefresh = makeIcon('M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z')
const IconWarn = makeIcon('M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z')
const IconError = makeIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z')
const IconCheck = makeIcon('M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z')

// ── Data ──────────────────────────────────────────────────────────────────────
const allAssets = ref<AssetResponse[]>([])
const quotas = ref<QuotaRowResponse[]>([])

// ── Stats ────────────────────────────────────────────────────────────────────
const stats = computed(() => ({
  active: allAssets.value.filter(a => a.status === 'active').length,
  full: allAssets.value.filter(a => a.status === 'full').length,
  banned: allAssets.value.filter(a => a.status === 'banned').length,
  offline: allAssets.value.filter(a => a.status === 'offline').length,
  total: allAssets.value.length,
}))

const statCards = computed(() => {
  const s = stats.value
  return [
    { label: t('abandonment.active'), value: s.active, colorClass: 'metric-card-green', iconColor: 'green', icon: IconCheck },
    { label: t('abandonment.full'), value: s.full, colorClass: 'metric-card-orange', iconColor: 'orange', icon: IconWarn },
    { label: t('abandonment.banned'), value: s.banned, colorClass: s.banned > 0 ? 'metric-card-red' : 'metric-card-gray', iconColor: s.banned > 0 ? 'red' : 'gray', icon: IconError },
    { label: t('abandonment.offline'), value: s.offline, colorClass: s.offline > 0 ? 'metric-card-gray' : 'metric-card-gray', iconColor: 'gray', icon: IconWarn },
    { label: t('abandonment.total'), value: s.total, colorClass: 'metric-card-blue', iconColor: 'blue', icon: IconNode },
  ]
})

// ── Tab 1: Banned accounts ───────────────────────────────────────────────────
interface BannedGroup {
  aws_account_id: string
  count: number
  region: string | null
  remarks: string
  updated_at: string
  assets: AssetResponse[]
}

const bannedGroups = ref<BannedGroup[]>([])

function buildBannedGroups(assets: AssetResponse[]) {
  const map = new Map<string, AssetResponse[]>()
  for (const a of assets) {
    if (a.status === 'banned') {
      const id = a.aws_account_id || 'Unknown'
      if (!map.has(id)) map.set(id, [])
      map.get(id)!.push(a)
    }
  }
  bannedGroups.value = Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([aws_account_id, assets]) => {
      const latest = assets.reduce((prev, curr) =>
        prev.updated_at > curr.updated_at ? prev : assets[0])
      return {
        aws_account_id,
        count: assets.length,
        region: latest.region,
        remarks: latest.remarks || '-',
        updated_at: latest.updated_at,
        assets,
      }
    })
}

const bannedGroupColumns = [
  {
    title: 'AWS 账号',
    key: 'aws_account_id',
    render: (row: BannedGroup) => h('span', { class: 'text-mono', style: 'font-weight:600' }, row.aws_account_id),
  },
  {
    title: '废弃资产数',
    key: 'count',
    align: 'center' as const,
    render: (row: BannedGroup) => h(NTag, { type: row.count > 0 ? 'error' : 'default', size: 'small', bordered: false }, { default: () => row.count }),
  },
  { title: '区域', key: 'region', render: (row: BannedGroup) => row.region || h('span', { style: 'color:#94a3b8' }, '—') },
  { title: '备注', key: 'remarks', ellipsis: { tooltip: true } },
  {
    title: '最近更新',
    key: 'updated_at',
    render: (row: BannedGroup) => h('span', { style: 'font-size:12px;color:#64748b' }, fmtTs(row.updated_at)),
  },
]

const bannedDetailColumns = [
  { title: '资产ID', key: 'asset_id', render: (r: AssetResponse) => h('span', { class: 'text-mono', style: 'font-size:12px' }, r.asset_id) },
  { title: '名称', key: 'asset_name', ellipsis: { tooltip: true } },
  { title: '区域', key: 'region', render: (r: AssetResponse) => r.region || h('span', { style: 'color:#94a3b8' }, '—') },
  {
    title: '状态',
    key: 'status',
    render: () => h(NTag, { type: 'error', size: 'small', bordered: false }, { default: () => 'banned' }),
  },
  { title: '备注', key: 'remarks', ellipsis: { tooltip: true }, render: (r: AssetResponse) => r.remarks || h('span', { style: 'color:#94a3b8' }, '—') },
]

// ── Tab 2: Quota tracking ───────────────────────────────────────────────────
const quotaColumns = [
  {
    title: 'AWS 账号',
    key: 'aws_account_id',
    render: (r: QuotaRowResponse) => h('span', { class: 'text-mono', style: 'font-weight:600' }, r.aws_account_id),
  },
  { title: '区域', key: 'region', render: (r: QuotaRowResponse) => r.region || h('span', { style: 'color:#94a3b8' }, '—') },
  {
    title: 'Active',
    key: 'active_count',
    align: 'center' as const,
    render: (r: QuotaRowResponse) => h(NTag, { type: 'success', size: 'small', bordered: false }, { default: () => r.active_count }),
  },
  {
    title: 'Full',
    key: 'full_count',
    align: 'center' as const,
    render: (r: QuotaRowResponse) => h(NTag, { type: 'warning', size: 'small', bordered: false }, { default: () => r.full_count }),
  },
  {
    title: 'Banned',
    key: 'banned_count',
    align: 'center' as const,
    render: (r: QuotaRowResponse) => h(NTag, { type: 'error', size: 'small', bordered: false }, { default: () => r.banned_count }),
  },
  {
    title: '总计',
    key: 'total',
    align: 'center' as const,
    render: (r: QuotaRowResponse) => h('span', { style: 'font-weight:700' }, r.total),
  },
]

function quotaProgress(row: QuotaRowResponse) {
  if (row.total === 0) return 0
  return ((row.active_count + row.full_count) / row.total) * 100
}

// ── Tab 3: Manual abandonment form ────────────────────────────────────────
const form = ref({
  aws_account_id: '',
  error_code: '',
  error_message: '',
  source_xboard_node_id: '',
})
const submitting = ref(false)
const acknowledged = ref(false)
const confirmText = ref('')

const errorCodeOptions = [
  { label: '-- 选择错误代码 --', value: '' },
  { label: 'AccountBanned (账号被封禁)', value: 'AccountBanned' },
  { label: 'QuotaExceeded (配额耗尽)', value: 'QuotaExceeded' },
  { label: 'SecurityViolation (安全违规)', value: 'SecurityViolation' },
  { label: 'PaymentFailed (支付失败)', value: 'PaymentFailed' },
  { label: 'ComplianceViolation (合规违规)', value: 'ComplianceViolation' },
  { label: 'ManualAbandonment (手动废弃)', value: 'ManualAbandonment' },
]

function resetForm() {
  form.value = { aws_account_id: '', error_code: '', error_message: '', source_xboard_node_id: '' }
  acknowledged.value = false
  confirmText.value = ''
}

async function submitAbandonment() {
  if (!form.value.aws_account_id.trim()) {
    message.warning(t('abandonment.fillAwsAccount'))
    return
  }
  if (!form.value.error_code) {
    message.warning(t('abandonment.selectErrorCode'))
    return
  }
  if (!form.value.error_message.trim()) {
    message.warning(t('abandonment.fillErrorDesc'))
    return
  }
  if (confirmText.value !== 'CONFIRM') {
    message.warning(t('abandonment.inputConfirmWord'))
    return
  }

  submitting.value = true
  try {
    const result = await apiClient.post<AbandonmentResultResponse>('/abandonment', {
      aws_account_id: form.value.aws_account_id.trim(),
      error_code: form.value.error_code,
      error_message: form.value.error_message.trim(),
      source_xboard_node_id: form.value.source_xboard_node_id.trim()
        ? parseInt(form.value.source_xboard_node_id)
        : null,
    })
    message.success(
      `账号 ${result.data.aws_account_id} 已废弃 — ${t('abandonment.deletedNodes', { count: result.data.deleted_node_count, count2: result.data.asset_count })}`
    )
    resetForm()
    await fetchData()
  } catch (err) {
    const e = err as { response?: { data?: { error?: string } } }
    message.error(e.response?.data?.error || t('abandonment.abandonmentFailed'))
  } finally {
    submitting.value = false
  }
}

function showDangerConfirm() {
  dialog.warning({
    title: '确认废弃 AWS 账号',
    content: () =>
      h('div', {}, [
        h('p', { style: { color: '#d03050', fontWeight: 'bold' } },
          '警告：此操作会立即将账号下所有节点从 Xboard 删除，且不可恢复！'),
        h('p', { style: { marginTop: '8px' } },
          `AWS 账号 ID: ${form.value.aws_account_id || '-'}`),
        h('p', { style: { marginTop: '4px' } },
          `错误代码: ${form.value.error_code}`),
      ]),
    positiveText: '确认废弃',
    negativeText: '取消',
    onPositiveClick: submitAbandonment,
  })
}

// ── Formatters ──────────────────────────────────────────────────────────────
function fmtTs(ts: string) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ts
  }
}

// ── Fetch ────────────────────────────────────────────────────────────────────
async function fetchData() {
  loading.value = true
  errorMsg.value = null
  try {
    const [assetsRes, quotaRes] = await Promise.all([
      apiClient.get<AssetResponse[]>('/assets'),
      apiClient.get<QuotaRowResponse[]>('/abandonment/quota'),
    ])
    allAssets.value = assetsRes.data
    quotas.value = quotaRes.data
    buildBannedGroups(allAssets.value)
    lastRefresh.value = new Date()
  } catch (e: unknown) {
    const axiosErr = e as { response?: { data?: { error?: string }; status?: number }; message?: string }
    errorMsg.value = axiosErr.response?.data?.error || axiosErr.message || t('abandonment.loadDataFailed')
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
</script>

<template>
  <div class="abandonment-page">

    <!-- ── Page Header ──────────────────────────────────────────────────────── -->
    <div class="dashboard-header">
      <div class="dashboard-header-left">
        <div class="dashboard-header-icon" style="background: linear-gradient(135deg, #ef4444, #f87171); box-shadow: 0 4px 12px rgba(239, 68, 68, 0.35);">
          <IconShield />
        </div>
        <div class="dashboard-header-title">
          <h1>{{ t('abandonment.title') }}</h1>
          <p>{{ t('abandonment.accountStatusOverview') }}</p>
        </div>
      </div>
      <div class="dashboard-header-actions">
        <div class="refresh-badge">
          <span class="refresh-badge-dot"></span>
          <span>{{ t('dashboard.lastUpdated') }}: {{ lastRefresh.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }}</span>
        </div>
        <NButton size="small" quaternary circle @click="fetchData" :loading="loading">
          <template #icon>
            <IconRefresh />
          </template>
        </NButton>
      </div>
    </div>

    <!-- ── Error Banner ────────────────────────────────────────────────────── -->
    <div v-if="errorMsg" class="alert-banner alert-banner-error">
      <IconError />
      {{ errorMsg }}
      <NButton size="tiny" quaternary style="margin-left:auto" @click="errorMsg = null">
        {{ t('app.close') }}
      </NButton>
    </div>

    <NSpin :show="loading">

      <!-- ── Stats Row ────────────────────────────────────────────────────── -->
      <div class="dashboard-section-header">
        <div class="dashboard-section-icon" style="background:#fef2f2;color:#ef4444">
          <IconShield />
        </div>
          <span class="dashboard-section-title">{{ t('abandonment.accountStatusOverview') }}</span>
      </div>
      <div class="metrics-grid">
        <div
          v-for="(card, idx) in statCards"
          :key="idx"
          :class="['metric-card', card.colorClass]"
        >
          <div :class="['metric-card-icon', `metric-card-icon-${card.iconColor}`]">
            <component :is="card.icon" />
          </div>
          <div class="metric-card-label">{{ card.label }}</div>
          <div class="metric-card-value">{{ card.value }}</div>
        </div>
      </div>

      <!-- ── Banned Accounts Section ──────────────────────────────────────── -->
      <div class="dashboard-section-header">
        <div class="dashboard-section-icon" style="background:#fef2f2;color:#ef4444">
          <IconShield />
        </div>
        <span class="dashboard-section-title">{{ t('abandonment.bannedAccountList') }}</span>
        <span class="dashboard-section-sub text-muted">
          {{ t('abandonment.bannedAccountCount', { count: bannedGroups.length }) }}
        </span>
      </div>

      <div v-if="bannedGroups.length === 0" class="dashboard-card">
        <NEmpty :description="t('abandonment.noBannedAccounts')" />
      </div>
      <template v-else>
        <div class="dashboard-card">
          <div class="dashboard-table">
            <NDataTable
              :columns="bannedGroupColumns"
              :data="bannedGroups"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 10 }"
              :row-key="(row: BannedGroup) => row.aws_account_id"
            />
          </div>
        </div>

        <div class="dashboard-section-header" style="margin-top:8px">
          <span class="dashboard-section-title" style="font-size:13px">{{ t('abandonment.bannedAccountList') }}</span>
        </div>
        <div v-for="group in bannedGroups" :key="group.aws_account_id" class="dashboard-card abandonment-detail-card">
          <div class="abandonment-detail-header">
            <div class="abandonment-detail-meta">
              <IconNode style="width:16px;height:16px;color:#ef4444;flex-shrink:0" />
              <span class="text-mono" style="font-weight:700;font-size:14px">{{ group.aws_account_id }}</span>
              <NTag type="error" size="small" bordered>{{ group.count }} {{ t('assets.name') }}</NTag>
              <span v-if="group.region" class="text-muted" style="font-size:12px">{{ group.region }}</span>
            </div>
            <div class="abandonment-detail-meta" style="margin-top:6px">
              <span class="text-muted" style="font-size:12px">{{ t('dashboard.lastUpdated') }}: {{ fmtTs(group.updated_at) }}</span>
              <span v-if="group.remarks !== '-'" class="text-muted" style="font-size:12px;margin-left:12px">{{ group.remarks }}</span>
            </div>
          </div>
          <div class="dashboard-table">
            <NDataTable
              :columns="bannedDetailColumns"
              :data="group.assets"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="group.assets.length > 5 ? { pageSize: 5 } : false"
              :row-key="(r: AssetResponse) => String(r.asset_id)"
            />
          </div>
        </div>
      </template>

      <!-- ── Quota Section ─────────────────────────────────────────────────── -->
      <div class="dashboard-section-header" style="margin-top:20px">
        <div class="dashboard-section-icon" style="background:#eff6ff;color:#3b82f6">
          <IconChart />
        </div>
        <span class="dashboard-section-title">{{ t('abandonment.quotaTracking') }}</span>
        <span class="dashboard-section-sub text-muted">
          {{ quotas.length }} 条记录
        </span>
      </div>

      <div v-if="quotas.length === 0" class="dashboard-card">
        <NEmpty :description="t('abandonment.noAccountData')" />
      </div>
      <template v-else>
        <div class="dashboard-card">
          <div class="dashboard-table">
            <NDataTable
              :columns="quotaColumns"
              :data="quotas"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 10 }"
              :row-key="(r: QuotaRowResponse) => r.aws_account_id"
            />
          </div>
        </div>

        <div class="dashboard-section-header" style="margin-top:8px">
          <span class="dashboard-section-title" style="font-size:13px">{{ t('abandonment.quotaOverview') }}</span>
        </div>
        <div class="quota-cards-grid">
          <div
            v-for="row in quotas"
            :key="row.aws_account_id"
            class="dashboard-card quota-card"
          >
            <div class="quota-card-header">
              <span class="text-mono" style="font-weight:700;font-size:13px">{{ row.aws_account_id }}</span>
              <span class="text-muted" style="font-size:12px">{{ row.region || '—' }}</span>
            </div>
            <div class="quota-card-body">
              <NProgress
                type="line"
                :percentage="Math.round(quotaProgress(row))"
                :height="8"
                :border-radius="4"
                :fill-border-radius="4"
                :color="quotaProgress(row) >= 85 ? '#ef4444' : quotaProgress(row) >= 65 ? '#f59e0b' : '#18a058'"
                :rail-color="'#e2e8f0'"
                status="default"
              />
              <div class="quota-card-labels">
                <span class="quota-stat-success">Active {{ row.active_count }}</span>
                <span class="quota-stat-warning">Full {{ row.full_count }}</span>
                <span class="quota-stat-error">Banned {{ row.banned_count }}</span>
                <span class="text-muted">Total {{ row.total }}</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ── Manual Abandonment Section ────────────────────────────────────── -->
      <div class="dashboard-section-header" style="margin-top:20px">
        <div class="dashboard-section-icon" style="background:#fef2f2;color:#ef4444">
          <IconTrash />
        </div>
        <span class="dashboard-section-title">{{ t('abandonment.manualAbandonment') }}</span>
      </div>

      <div class="dashboard-card abandonment-form-card">
        <div class="danger-alert">
          <IconWarn style="width:18px;height:18px;flex-shrink:0" />
          <div>
            <div style="font-weight:700;font-size:13px;color:#b91c1c;margin-bottom:4px">{{ t('abandonment.dangerWarning') }}</div>
            <div style="font-size:12px;color:#991b1b">{{ t('abandonment.dangerWarningContent') }}</div>
          </div>
        </div>

        <div class="abandonment-form-grid">
          <div class="form-field">
            <label class="form-label">
              AWS 账号 ID <span class="form-required">*</span>
            </label>
            <NInput
              v-model:value="form.aws_account_id"
              placeholder="12位数字账号ID"
              :disabled="submitting"
            />
          </div>

          <div class="form-field">
            <label class="form-label">
              {{ t('abandonment.triggerNodeId') }} <span class="form-optional">(可选)</span>
            </label>
            <NInput
              v-model:value="form.source_xboard_node_id"
              placeholder="触发废弃操作的节点ID"
              :disabled="submitting"
            />
          </div>

          <div class="form-field">
            <label class="form-label">
              {{ t('abandonment.errorCode') }} <span class="form-required">*</span>
            </label>
            <NSelect
              v-model:value="form.error_code"
              :options="errorCodeOptions"
              :disabled="submitting"
            />
          </div>

          <div class="form-field form-field-full">
            <label class="form-label">
              {{ t('abandonment.errorDescription') }} <span class="form-required">*</span>
            </label>
            <NInput
              v-model:value="form.error_message"
              type="textarea"
              placeholder="详细的错误描述"
              :rows="3"
              :disabled="submitting"
            />
          </div>
        </div>

        <div class="abandonment-confirm-section">
          <div class="confirm-toggle">
            <label class="confirm-switch">
              <input type="checkbox" v-model="acknowledged" :disabled="submitting" />
              <span class="confirm-slider"></span>
            </label>
            <span class="confirm-label">{{ t('abandonment.acknowledged') }}</span>
          </div>
          <div v-if="acknowledged" class="confirm-input-row">
            <NInput
              v-model:value="confirmText"
              placeholder="请输入 CONFIRM 确认此危险操作"
              :disabled="submitting"
              size="large"
            />
          </div>
        </div>

        <div class="abandonment-actions">
          <NButton
            type="error"
            size="large"
            :disabled="!(acknowledged && confirmText === 'CONFIRM')"
            :loading="submitting"
            @click="showDangerConfirm"
          >
            <template #icon>
              <IconTrash />
            </template>
            {{ t('abandonment.executeAbandonment') }}
          </NButton>
          <NButton
            size="large"
            quaternary
            :disabled="submitting"
            @click="resetForm"
          >
            {{ t('app.reset') }}
          </NButton>
        </div>

        <NCollapse style="margin-top:24px">
          <NCollapseItem :title="t('abandonment.reasonCodes')" name="reason-codes">
            <div class="code-guide-grid">
              <div class="code-guide-item">
                <NTag type="error" size="small" bordered>AccountBanned</NTag>
                <span>AWS 账号被封禁</span>
              </div>
              <div class="code-guide-item">
                <NTag type="warning" size="small" bordered>QuotaExceeded</NTag>
                <span>AWS 账号配额耗尽</span>
              </div>
              <div class="code-guide-item">
                <NTag type="info" size="small" bordered>SecurityViolation</NTag>
                <span>安全违规</span>
              </div>
              <div class="code-guide-item">
                <NTag type="warning" size="small" bordered>PaymentFailed</NTag>
                <span>支付失败</span>
              </div>
              <div class="code-guide-item">
                <NTag type="error" size="small" bordered>ComplianceViolation</NTag>
                <span>合规违规</span>
              </div>
              <div class="code-guide-item">
                <NTag type="default" size="small" bordered>ManualAbandonment</NTag>
                <span>手动废弃</span>
              </div>
            </div>
            <div class="impact-list">
              <div class="impact-list-title">
                <IconWarn style="width:14px;height:14px;color:#ef4444;flex-shrink:0" />
                {{ t('abandonment.abandonmentImpact') }}
              </div>
              <ol>
                <li>所有关联资产状态更新为 <code>banned</code></li>
                <li>所有节点从 Xboard 删除</li>
                <li>资产分配记录释放</li>
                <li>Telegram 通知发送</li>
              </ol>
            </div>
          </NCollapseItem>
        </NCollapse>
      </div>

    </NSpin>
  </div>
</template>
