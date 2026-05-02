<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { h } from 'vue'
import {
  NSpin, NAlert, NTabs, NTab, NDataTable, NTag, NButton,
  NCard, NSpace, NGrid, NGi, NStatistic, NForm,
  NFormItem, NInput, NSelect, NSwitch, NProgress,
  NDescriptions, NDescriptionsItem,
  NEmpty, useMessage, useDialog,
} from 'naive-ui'
import apiClient from '@/api/client'
import type {
  AssetResponse,
  AbandonmentResultResponse,
  QuotaRowResponse,
} from '@/types/api'

const message = useMessage()
const dialog = useDialog()

const loading = ref(false)
const error = ref<string | null>(null)

// ── Data ──────────────────────────────────────────────────────────────────────
const allAssets = ref<AssetResponse[]>([])
const quotas = ref<QuotaRowResponse[]>([])

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
        prev.updated_at > curr.updated_at ? prev : curr, assets[0])
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
  { title: 'AWS 账号', key: 'aws_account_id', width: 180 },
  { title: '废弃资产数', key: 'count', width: 120, render: (row: BannedGroup) => h(NTag, { type: 'error', bordered: false }, { default: () => row.count }) },
  { title: '区域', key: 'region', width: 140, render: (row: BannedGroup) => row.region || '-' },
  { title: '备注', key: 'remarks', ellipsis: { tooltip: true } },
  { title: '最近更新', key: 'updated_at', width: 160, render: (row: BannedGroup) => fmtTs(row.updated_at) },
]

const bannedDetailColumns = [
  { title: '资产ID', key: 'asset_id', width: 90 },
  { title: '名称', key: 'asset_name', ellipsis: { tooltip: true } },
  { title: '区域', key: 'region', width: 120, render: (r: AssetResponse) => r.region || '-' },
  { title: '状态', key: 'status', width: 90, render: (r: AssetResponse) => h(NTag, { type: 'error', bordered: false }, { default: () => r.status }) },
  { title: '备注', key: 'remarks', ellipsis: { tooltip: true }, render: (r: AssetResponse) => r.remarks || '-' },
]

// ── Tab 2: Quota tracking ───────────────────────────────────────────────────
const quotaColumns = [
  { title: 'AWS 账号', key: 'aws_account_id', width: 180, ellipsis: { tooltip: true } },
  { title: '区域', key: 'region', width: 140, render: (r: QuotaRowResponse) => r.region || '-' },
  { title: 'Active', key: 'active_count', width: 90, render: (r: QuotaRowResponse) => h(NTag, { type: 'success', bordered: false }, { default: () => r.active_count }) },
  { title: 'Full', key: 'full_count', width: 80, render: (r: QuotaRowResponse) => h(NTag, { type: 'warning', bordered: false }, { default: () => r.full_count }) },
  { title: 'Banned', key: 'banned_count', width: 90, render: (r: QuotaRowResponse) => h(NTag, { type: 'error', bordered: false }, { default: () => r.banned_count }) },
  { title: '总计', key: 'total', width: 80 },
]

function quotaProgress(row: QuotaRowResponse) {
  if (row.total === 0) return 0
  return ((row.active_count + row.full_count) / row.total) * 100
}

function quotaText(row: QuotaRowResponse) {
  return `Active: ${row.active_count} | Full: ${row.full_count} | Banned: ${row.banned_count}`
}

// ── Tab 3: Manual abandonment form ─────────────────────────────────────────
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
    message.warning('请输入 AWS 账号 ID')
    return
  }
  if (!form.value.error_code) {
    message.warning('请选择错误代码')
    return
  }
  if (!form.value.error_message.trim()) {
    message.warning('请输入错误描述')
    return
  }
  if (confirmText.value !== 'CONFIRM') {
    message.warning('请输入 CONFIRM 确认此危险操作')
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
      `账号 ${result.data.aws_account_id} 已废弃 — 删除了 ${result.data.deleted_node_count} 个节点，处理了 ${result.data.asset_count} 个资产`
    )
    resetForm()
    await fetchData()
  } catch (err) {
    const e = err as { response?: { data?: { error?: string } } }
    message.error(e.response?.data?.error || '废弃操作失败，请检查输入')
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

// ── Stats ────────────────────────────────────────────────────────────────────
const stats = {
  active: 0, full: 0, banned: 0, offline: 0, total: 0,
}

function calcStats(assets: AssetResponse[]) {
  stats.active = assets.filter(a => a.status === 'active').length
  stats.full = assets.filter(a => a.status === 'full').length
  stats.banned = assets.filter(a => a.status === 'banned').length
  stats.offline = assets.filter(a => a.status === 'offline').length
  stats.total = assets.length
}

// ── Fetch ────────────────────────────────────────────────────────────────────
async function fetchData() {
  loading.value = true
  error.value = null
  try {
    const [assetsRes, quotaRes] = await Promise.all([
      apiClient.get<AssetResponse[]>('/assets'),
      apiClient.get<QuotaRowResponse[]>('/abandonment/quota'),
    ])
    allAssets.value = assetsRes.data
    quotas.value = quotaRes.data
    calcStats(allAssets.value)
    buildBannedGroups(allAssets.value)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载数据失败'
  } finally {
    loading.value = false
  }
}

function fmtTs(ts: string) {
  if (!ts) return '-'
  try { return new Date(ts).toLocaleString('zh-CN') } catch { return ts }
}

onMounted(fetchData)
</script>

<template>
  <NSpin :show="loading">
    <NAlert v-if="error" type="error" :title="error" style="margin-bottom: 16px" />

    <!-- Stats row -->
    <NCard title="账号状态概览" size="small" style="margin-bottom: 16px">
      <NGrid :cols="5" :x-gap="12" :y-gap="12">
        <NGi><NStatistic label="Active" :value="stats.active" /></NGi>
        <NGi><NStatistic label="Full" :value="stats.full" /></NGi>
        <NGi><NStatistic label="Banned" :value="stats.banned" /></NGi>
        <NGi><NStatistic label="Offline" :value="stats.offline" /></NGi>
        <NGi><NStatistic label="总计" :value="stats.total" /></NGi>
      </NGrid>
    </NCard>

    <NCard title="账号废弃管理" size="small">
      <NTabs type="line" animated>
        <!-- Tab 1: Banned accounts -->
        <NTab name="banned" title="废弃账号列表">
          <div v-if="bannedGroups.length === 0" style="padding: 24px 0">
            <NEmpty description="当前没有废弃的账号" />
          </div>
          <div v-else>
            <div style="margin-bottom: 16px">
              <NAlert type="info">
                共 {{ bannedGroups.length }} 个废弃 AWS 账号
              </NAlert>
            </div>
            <NDataTable
              :columns="bannedGroupColumns"
              :data="bannedGroups"
              :bordered="false"
              size="small"
              style="margin-bottom: 16px"
            />

            <NCollapse>
              <NCollapseItem
                v-for="group in bannedGroups"
                :key="group.aws_account_id"
                :title="`AWS 账号: ${group.aws_account_id} (${group.count} 个资产)`"
                :name="group.aws_account_id"
              >
                <template #header-extra>
                  <NTag type="error" bordered>{{ group.count }}</NTag>
                </template>
                <NDataTable
                  :columns="bannedDetailColumns"
                  :data="group.assets"
                  :bordered="false"
                  size="small"
                />
              </NCollapseItem>
            </NCollapse>
          </div>
        </NTab>

        <!-- Tab 2: Quota tracking -->
        <NTab name="quota" title="配额追踪">
          <div v-if="quotas.length === 0" style="padding: 24px 0">
            <NEmpty description="当前没有 AWS 账号数据" />
          </div>
          <div v-else>
            <NDataTable
              :columns="quotaColumns"
              :data="quotas"
              :bordered="false"
              size="small"
              style="margin-bottom: 24px"
            />

            <h4 style="margin: 16px 0 12px">配额使用概览</h4>
            <NCard
              v-for="row in quotas.slice(0, 10)"
              :key="row.aws_account_id"
              size="small"
              style="margin-bottom: 12px"
            >
              <div style="font-weight: 600; margin-bottom: 8px">
                {{ row.aws_account_id }}
                <span style="font-weight: normal; color: #888; margin-left: 8px">区域: {{ row.region || '-' }}</span>
              </div>
              <NProgress
                type="line"
                :percentage="Math.round(quotaProgress(row))"
                :indicator-text="quotaText(row)"
                status="default"
                :height="20"
              />
            </NCard>
          </div>
        </NTab>

        <!-- Tab 3: Manual abandonment -->
        <NTab name="abandon" title="手动废弃账号">
          <NAlert type="error" title="危险操作" style="margin-bottom: 16px">
            此操作会立即将账号下所有节点从 Xboard 删除，且不可恢复！
          </NAlert>

          <NForm
            label-placement="top"
            :show-feedback="true"
            style="max-width: 640px"
          >
            <NGrid :cols="2" :x-gap="16" :y-gap="12">
              <NGi>
                <NFormItem label="AWS 账号 ID *" required>
                  <NInput
                    v-model:value="form.aws_account_id"
                    placeholder="12位数字账号ID"
                    :disabled="submitting"
                  />
                </NFormItem>
              </NGi>
              <NGi>
                <NFormItem label="触发节点 ID (可选)">
                  <NInput
                    v-model:value="form.source_xboard_node_id"
                    placeholder="触发废弃操作的节点ID"
                    :disabled="submitting"
                  />
                </NFormItem>
              </NGi>
              <NGi>
                <NFormItem label="错误代码 *" required>
                  <NSelect
                    v-model:value="form.error_code"
                    :options="errorCodeOptions"
                    :disabled="submitting"
                  />
                </NFormItem>
              </NGi>
            </NGrid>

            <NFormItem label="错误描述 *" required>
              <NInput
                v-model:value="form.error_message"
                type="textarea"
                placeholder="详细的错误描述"
                :rows="3"
                :disabled="submitting"
              />
            </NFormItem>

            <NFormItem label="危险操作二次确认 *" required>
              <div>
                <div style="margin-bottom: 8px">
                  <NSpace>
                    <NSwitch v-model:value="acknowledged" :disabled="submitting" />
                    <span>我确认已了解此操作的风险，并确认要废弃此账号</span>
                  </NSpace>
                </div>
                <div v-if="acknowledged">
                  <NInput
                    v-model:value="confirmText"
                    placeholder="请输入 CONFIRM 确认此危险操作"
                    :disabled="submitting"
                  />
                </div>
              </div>
            </NFormItem>

            <NFormItem>
              <NButton
                type="error"
                :disabled="acknowledged && confirmText === 'CONFIRM' ? false : true"
                :loading="submitting"
                @click="showDangerConfirm"
              >
                执行废弃操作
              </NButton>
            </NFormItem>
          </NForm>

          <NCollapse style="margin-top: 24px">
            <NCollapseItem title="废弃原因代码说明" name="reason-codes">
              <NDescriptions :column="2" bordered size="small">
                <NDescriptionsItem label="AccountBanned">AWS 账号被封禁</NDescriptionsItem>
                <NDescriptionsItem label="QuotaExceeded">AWS 账号配额耗尽</NDescriptionsItem>
                <NDescriptionsItem label="SecurityViolation">安全违规</NDescriptionsItem>
                <NDescriptionsItem label="PaymentFailed">支付失败</NDescriptionsItem>
                <NDescriptionsItem label="ComplianceViolation">合规违规</NDescriptionsItem>
                <NDescriptionsItem label="ManualAbandonment">手动废弃</NDescriptionsItem>
              </NDescriptions>
              <h4 style="margin: 12px 0 8px">废弃操作影响</h4>
              <ol style="padding-left: 20px; color: #d03050">
                <li>所有关联资产状态更新为 <code>banned</code></li>
                <li>所有节点从 Xboard 删除</li>
                <li>资产分配记录释放</li>
                <li>Telegram 通知发送</li>
              </ol>
            </NCollapseItem>
          </NCollapse>
        </NTab>
      </NTabs>
    </NCard>
  </NSpin>
</template>
