<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import {
  NDataTable,
  NTag,
  NSpin,
  NAlert,
  NButton,
  NSpace,
  NText,
  NModal,
  NTabs,
  NTabPane,
  NGrid,
  NGi,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSwitch,
  NCheckbox,
  NCheckboxGroup,
  NCollapse,
  NCollapseItem,
  NDivider,
  useMessage,
  useDialog,
} from 'naive-ui'
import type { SelectOption, DataTableColumns } from 'naive-ui'
import apiClient from '@/api/client'
import type { AssetResponse, AWSAssetCreateRequest, SelfHostedAssetCreateRequest, AmiQueryResponse, AmiInfo } from '@/types/api'

// ── Helpers ────────────────────────────────────────────────────────────────────
function statusTagType(status: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  switch (status) {
    case 'active':    return 'success'
    case 'full':      return 'warning'
    case 'offline':   return 'error'
    case 'deploying':  return 'info'
    case 'banned':    return 'error'
    default:          return 'default'
  }
}

function fmtTs(value: string | null | undefined): string {
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

function maskAccountId(id: string | null): string {
  if (!id) return '—'
  return id.slice(0, 4) + '...'
}

// ── State ──────────────────────────────────────────────────────────────────────
const message = useMessage()
const dialog = useDialog()

const assets = ref<AssetResponse[]>([])
const loading = ref(true)
const errorMsg = ref<string | null>(null)
const selectedAssetIds = ref<number[]>([])
const batchDeleting = ref(false)

// ── Modal ──────────────────────────────────────────────────────────────────────
const showModal = ref(false)
const modalTab = ref<'aws' | 'self'>('aws')

function openModal(tab: 'aws' | 'self' = 'aws') {
  modalTab.value = tab
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

// ── Delete ─────────────────────────────────────────────────────────────────────
function confirmDelete(asset: AssetResponse) {
  dialog.warning({
    title: '确认删除资产',
    content: `确定要删除资产 "${asset.asset_name}" (ID: ${asset.asset_id}) 吗？此操作不可恢复。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: () => doDelete(asset),
  })
}

const deleting = ref(false)

async function doDelete(asset: AssetResponse) {
  deleting.value = true
  try {
    await apiClient.delete(`/assets/${asset.asset_id}`)
    message.success(`资产 "${asset.asset_name}" 已删除`)
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.message || '删除失败')
  } finally {
    deleting.value = false
  }
}

// ── Batch Delete Assets ────────────────────────────────────────────────────────
async function batchDeleteAssets() {
  if (selectedAssetIds.value.length === 0) {
    message.warning('请先选择要删除的资产')
    return
  }

  dialog.warning({
    title: '确认批量删除',
    content: `确定要删除选中的 ${selectedAssetIds.value.length} 个资产吗？此操作不可恢复。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      batchDeleting.value = true
      try {
        const deletePromises = selectedAssetIds.value.map(id => apiClient.delete(`/assets/${id}`))
        await Promise.all(deletePromises)
        message.success(`已删除 ${selectedAssetIds.value.length} 个资产`)
        selectedAssetIds.value = []
        await fetchAssets()
      } catch (err: unknown) {
        const e = err as { response?: { data?: { error?: string; message?: string } } }
        message.error(e.response?.data?.error || e.response?.data?.message || '批量删除失败')
      } finally {
        batchDeleting.value = false
      }
    },
  })
}

// ── Computed: filtered assets ─────────────────────────────────────────────────
const awsAssets  = computed(() => assets.value.filter(a => a.asset_type === 'aws'))
const selfAssets = computed(() => assets.value.filter(a => a.asset_type === 'self_hosted'))

// ── Table columns ──────────────────────────────────────────────────────────────
function buildColumns(onDelete: (asset: AssetResponse) => void): DataTableColumns<AssetResponse> {
  return [
    {
      type: 'selection' as const,
    },
    { title: 'Asset ID', key: 'asset_id', width: 90, align: 'center' },
    { title: 'Name', key: 'asset_name', ellipsis: { tooltip: true } },
    {
      title: 'Type', key: 'asset_type', width: 80,
      render: (row) => h(NTag, { size: 'small', type: row.asset_type === 'aws' ? 'info' : 'warning' },
        { default: () => row.asset_type === 'aws' ? 'AWS' : '自建' }),
    },
    { title: 'Region', key: 'region', render: (r) => r.region ?? '—' },
    {
      title: 'Status', key: 'status', width: 100,
      render: (row) => h(NTag, { type: statusTagType(row.status), size: 'small' },
        { default: () => row.status }),
    },
    { title: 'AWS Account', key: 'aws_account_id', render: (row) => maskAccountId(row.aws_account_id) },
    {
      title: 'vCPU', key: 'account_total_vcpu', width: 70,
      render: (r) => r.account_total_vcpu ?? r.cpu_cores ?? '—',
    },
    { title: 'Memory (GB)', key: 'memory_gb', width: 100, render: (r) => r.memory_gb ?? '—' },
    {
      title: 'Allocated', key: 'allocated', width: 100,
      render: (r) => `${r.allocated_count} / ${r.target_count}`,
    },
    { title: 'Max', key: 'max_count', width: 70, align: 'center' },
    {
      title: 'Protocols', key: 'supported_protocols',
      ellipsis: { tooltip: true },
      render: (r) =>
        h('div', { style: 'display:flex;flex-wrap:wrap;gap:4px' },
          r.supported_protocols.map(p =>
            h(NTag, { key: p, size: 'tiny', bordered: false }, { default: () => p })
          )
        ),
    },
    {
      title: 'Remarks', key: 'remarks',
      ellipsis: { tooltip: true },
      render: (r) => r.remarks ?? '—',
    },
    { title: 'Updated', key: 'updated_at', width: 160, render: (r) => fmtTs(r.updated_at) },
    {
      title: 'Actions', key: 'actions', width: 80, align: 'center',
      render: (row) =>
        h(NButton, { size: 'small', type: 'error', quaternary: true, onClick: () => onDelete(row) },
          { default: () => '删除' }),
    },
  ]
}

const allColumns = buildColumns(a => confirmDelete(a))

// ── Data fetching ─────────────────────────────────────────────────────────────
async function fetchAssets() {
  try {
    const { data } = await apiClient.get<AssetResponse[]>('/assets')
    assets.value = data
    errorMsg.value = null
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string }; status?: number }; message?: string }
    errorMsg.value = e.response?.data?.error || e.response?.data?.message || 'Failed to load assets'
  } finally {
    loading.value = false
  }
}

// ── AWS Registration Form ──────────────────────────────────────────────────────
const awsForm = ref({
  asset_name: '',
  region: 'ap-northeast-1',
  account_total_vcpu: 8,
  aws_access_key: '',
  aws_secret_key: '',
  aws_account_id: '',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  priority: 100,
  allow_cdn_proxy: false,
  auto_create_sg: false,
  vpc_id: '',
  sg_name: '',
  sg_ports_raw: '',
  ami_id: '',
})

const awsRegions: SelectOption[] = [
  { label: '美东 (us-east-1)', value: 'us-east-1' },
  { label: '美西 (us-west-1)', value: 'us-west-1' },
  { label: '美西2 (us-west-2)', value: 'us-west-2' },
  { label: '伦敦 (eu-west-1)', value: 'eu-west-1' },
  { label: '巴黎 (eu-west-2)', value: 'eu-west-2' },
  { label: '法兰克福 (eu-central-1)', value: 'eu-central-1' },
  { label: '东京 (ap-northeast-1)', value: 'ap-northeast-1' },
  { label: '新加坡 (ap-southeast-1)', value: 'ap-southeast-1' },
  { label: '悉尼 (ap-southeast-2)', value: 'ap-southeast-2' },
]

const awsProtocolOptions: SelectOption[] = [
  { label: 'AnyTLS', value: 'AnyTLS' },
  { label: 'Trojan', value: 'Trojan' },
  { label: 'vless',  value: 'vless' },
  { label: 'vmess',  value: 'vmess' },
]

const sgPortsHint = computed(() => {
  const ports = new Set<number>([22, 80, 443])
  if (awsForm.value.protocol_types.includes('AnyTLS') ||
      awsForm.value.protocol_types.includes('Trojan') ||
      awsForm.value.protocol_types.includes('vless') ||
      awsForm.value.protocol_types.includes('vmess')) {
    ports.add(443)
  }
  return '计算端口: ' + [...ports].sort((a, b) => a - b).join(', ')
})

const sgPorts = computed<number[]>(() => {
  const ports = new Set<number>([22, 80, 443])
  if (awsForm.value.protocol_types.includes('AnyTLS') ||
      awsForm.value.protocol_types.includes('Trojan') ||
      awsForm.value.protocol_types.includes('vless') ||
      awsForm.value.protocol_types.includes('vmess')) {
    ports.add(443)
  }
  return [...ports]
})

const submittingAws = ref(false)

function resetAwsForm() {
  awsForm.value = {
    asset_name: '', region: 'ap-northeast-1', account_total_vcpu: 8,
    aws_access_key: '', aws_secret_key: '', aws_account_id: '',
    remarks: '', protocol_types: ['AnyTLS'], target_count: 1,
    priority: 100, allow_cdn_proxy: false, auto_create_sg: false,
    vpc_id: '', sg_name: '', sg_ports_raw: '', ami_id: '',
  }
}

async function submitAwsForm() {
  if (!awsForm.value.asset_name.trim()) { message.warning('请填写资产名称'); return }
  if (!awsForm.value.region)           { message.warning('请选择 Region');   return }
  if (!awsForm.value.aws_access_key)  { message.warning('请填写 AWS Access Key'); return }
  if (!awsForm.value.aws_secret_key)  { message.warning('请填写 AWS Secret Key'); return }

  submittingAws.value = true
  try {
    const body: AWSAssetCreateRequest = {
      asset_name:         awsForm.value.asset_name.trim(),
      region:             awsForm.value.region,
      aws_access_key:     awsForm.value.aws_access_key,
      aws_secret_key:     awsForm.value.aws_secret_key,
      account_total_vcpu: awsForm.value.account_total_vcpu,
      remarks:           awsForm.value.remarks || undefined,
      protocol_type:     awsForm.value.protocol_types[0] ?? null,
      additional_protocol_types: awsForm.value.protocol_types.slice(1),
      target_count:      awsForm.value.target_count,
      priority:          awsForm.value.priority,
      allow_cdn_proxy:   awsForm.value.allow_cdn_proxy,
      auto_create_security_group: awsForm.value.auto_create_sg,
      vpc_id:            awsForm.value.vpc_id || undefined,
      security_group_name: awsForm.value.sg_name || undefined,
      security_group_ports: sgPorts.value,
      ami_id:            awsForm.value.ami_id || undefined,
      aws_account_id:    awsForm.value.aws_account_id || undefined,
    }
    await apiClient.post<AssetResponse>('/assets', body)
    message.success('AWS 资产注册成功')
    closeModal()
    resetAwsForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string }; message?: string } }
    message.error(e.response?.data?.error || e.response?.data?.message || '注册失败')
  } finally {
    submittingAws.value = false
  }
}

// ── AMI Query ──────────────────────────────────────────────────────────────────
const queryingAmi = ref(false)
const fetchingAccountId = ref(false)
const amiResults = ref<AmiInfo[]>([])
const amiError = ref<string | null>(null)

async function queryAmi() {
  if (!awsForm.value.aws_access_key) {
    message.warning('请先填写 AWS Access Key')
    return
  }
  if (!awsForm.value.aws_secret_key) {
    message.warning('请先填写 AWS Secret Key')
    return
  }
  queryingAmi.value = true
  amiError.value = null
  amiResults.value = []
  try {
    const { data } = await apiClient.post<AmiQueryResponse>('/assets/query-amis', {
      aws_access_key: awsForm.value.aws_access_key,
      aws_secret_key: awsForm.value.aws_secret_key,
      region: awsForm.value.region,
    })
    amiResults.value = data.amis
    if (data.amis.length === 0) {
      message.info('该账号/区域未找到 Debian ARM64 AMI')
    }
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string }; message?: string } }
    amiError.value = e.response?.data?.error || e.response?.data?.detail || '查询失败'
    message.error(amiError.value)
  } finally {
    queryingAmi.value = false
  }
}

function selectAmi(ami: AmiInfo) {
  awsForm.value.ami_id = ami.ami_id
  amiResults.value = []
  message.success(`已选择: ${ami.name} (${ami.ami_id})`)
}

async function fetchAccountId() {
  if (!awsForm.value.aws_access_key) {
    message.warning('请先填写 AWS Access Key')
    return
  }
  if (!awsForm.value.aws_secret_key) {
    message.warning('请先填写 AWS Secret Key')
    return
  }
  fetchingAccountId.value = true
  try {
    const { data } = await apiClient.post<{ aws_account_id: string; arn: string; user_id: string }>(
      '/assets/resolve-aws-account-id',
      {
        aws_access_key: awsForm.value.aws_access_key,
        aws_secret_key: awsForm.value.aws_secret_key,
        region: awsForm.value.region,
      }
    )
    awsForm.value.aws_account_id = data.aws_account_id
    message.success(`Account ID 已获取: ${data.aws_account_id}`)
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; detail?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.detail || '获取 Account ID 失败')
  } finally {
    fetchingAccountId.value = false
  }
}

// ── Self-Hosted Registration Form ──────────────────────────────────────────────
const selfForm = ref({
  asset_name: '',
  region: '',
  host: '',
  ssh_port: 22,
  ssh_username: 'root',
  ssh_password: '',
  ssh_private_key: '',
  remarks: '',
  protocol_types: ['AnyTLS'] as string[],
  target_count: 1,
  max_count: 10,
  priority: 100,
  cpu_cores: null as number | null,
  memory_gb: null as number | null,
})

const selfProtocolOptions: SelectOption[] = [
  { label: 'AnyTLS',   value: 'AnyTLS' },
  { label: 'Trojan',   value: 'Trojan' },
  { label: 'vless',    value: 'vless' },
  { label: 'vmess',    value: 'vmess' },
  { label: 'Hysteria2', value: 'Hysteria2' },
]

const submittingSelf = ref(false)
const probingHw = ref(false)

function resetSelfForm() {
  selfForm.value = {
    asset_name: '', region: '', host: '', ssh_port: 22,
    ssh_username: 'root', ssh_password: '', ssh_private_key: '',
    remarks: '', protocol_types: ['AnyTLS'], target_count: 1,
    max_count: 10, priority: 100, cpu_cores: null, memory_gb: null,
  }
}

async function probeHardware() {
  if (!selfForm.value.host.trim()) {
    message.warning('请先填写主机地址再探测硬件')
    return
  }
  probingHw.value = true
  try {
    const { data } = await apiClient.post<{ cpu_cores: number; memory_gb: number }>(
      '/assets/self-hosted/probe-hardware',
      {
        host: selfForm.value.host,
        ssh_port: selfForm.value.ssh_port,
        ssh_username: selfForm.value.ssh_username,
        ssh_password: selfForm.value.ssh_password || undefined,
        ssh_private_key: selfForm.value.ssh_private_key || undefined,
      }
    )
    selfForm.value.cpu_cores = data.cpu_cores
    selfForm.value.memory_gb = data.memory_gb
    message.success('硬件探测成功')
  } catch {
    message.info('硬件探测需要通过 SSH 连接，请手动填写 CPU 核心数和内存大小')
  } finally {
    probingHw.value = false
  }
}

async function submitSelfForm() {
  if (!selfForm.value.asset_name.trim()) { message.warning('请填写资产名称'); return }
  if (!selfForm.value.region.trim())     { message.warning('请填写 Region');   return }
  if (!selfForm.value.host.trim())       { message.warning('请填写主机地址');   return }

  submittingSelf.value = true
  try {
    const body: SelfHostedAssetCreateRequest = {
      asset_name:      selfForm.value.asset_name.trim(),
      region:          selfForm.value.region.trim(),
      host:            selfForm.value.host.trim(),
      ssh_port:        selfForm.value.ssh_port,
      ssh_username:    selfForm.value.ssh_username || undefined,
      ssh_password:    selfForm.value.ssh_password || undefined,
      ssh_private_key: selfForm.value.ssh_private_key || undefined,
      remarks:        selfForm.value.remarks || undefined,
      protocol_type:   selfForm.value.protocol_types[0] ?? null,
      additional_protocol_types: selfForm.value.protocol_types.slice(1),
      target_count:   selfForm.value.target_count,
      max_count:      selfForm.value.max_count,
      priority:       selfForm.value.priority,
      cpu_cores:      selfForm.value.cpu_cores ?? undefined,
      memory_gb:      selfForm.value.memory_gb ?? undefined,
    }
    await apiClient.post<AssetResponse>('/assets/self-hosted', body)
    message.success('自建资产注册成功')
    closeModal()
    resetSelfForm()
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string }; message?: string } }
    message.error(e.response?.data?.error || e.response?.data?.message || '注册失败')
  } finally {
    submittingSelf.value = false
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(fetchAssets)
</script>

<template>
  <div class="assets-page">
    <!-- ── Header ──────────────────────────────────────────────────────────── -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">账号与资产池</h1>
        <p class="page-subtitle">管理 AWS 账号与自建资产，统一调度节点配额与协议</p>
      </div>
      <div class="header-right">
        <NSpace>
          <NButton v-if="selectedAssetIds.length > 0" type="error" size="large" :loading="batchDeleting" @click="batchDeleteAssets">
            批量删除 ({{ selectedAssetIds.length }})
          </NButton>
          <NButton type="primary" size="large" @click="openModal('aws')">
            <template #icon>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor">
                <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
              </svg>
            </template>
            新增资产
          </NButton>
        </NSpace>
      </div>
    </div>

    <!-- ── Summary Stats ──────────────────────────────────────────────────── -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ assets.length }}</div>
        <div class="stat-label">全部资产</div>
      </div>
      <div class="stat-card stat-aws">
        <div class="stat-value">{{ awsAssets.length }}</div>
        <div class="stat-label">AWS 资产</div>
      </div>
      <div class="stat-card stat-self">
        <div class="stat-value">{{ selfAssets.length }}</div>
        <div class="stat-label">自建资产</div>
      </div>
      <div class="stat-card stat-active">
        <div class="stat-value">{{ assets.filter(a => a.status === 'active').length }}</div>
        <div class="stat-label">在线</div>
      </div>
      <div class="stat-card stat-full">
        <div class="stat-value">{{ assets.filter(a => a.status === 'full').length }}</div>
        <div class="stat-label">配额满</div>
      </div>
    </div>

    <!-- ── Asset Table ─────────────────────────────────────────────────────── -->
    <div class="table-card">
      <NSpin :show="loading" description="加载资产列表…">
        <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px"
          closable @close="errorMsg = null" />

        <!-- ── Filter Tabs ────────────────────────────────────────────────── -->
        <div class="tab-bar">
          <button
            class="tab-btn active"
            @click="() => {}"
          >
            全部
            <span class="tab-badge">{{ assets.length }}</span>
          </button>
          <button class="tab-btn">
            AWS
            <span class="tab-badge tab-badge-aws">{{ awsAssets.length }}</span>
          </button>
          <button class="tab-btn">
            自建
            <span class="tab-badge tab-badge-self">{{ selfAssets.length }}</span>
          </button>
        </div>

        <!-- ── Data Table ──────────────────────────────────────────────────── -->
        <NDataTable
          :columns="allColumns"
          :data="assets"
          :bordered="false"
          :single-line="false"
          size="small"
          :pagination="{ pageSize: 15 }"
          :row-key="(row: AssetResponse) => row.asset_id"
          v-model:checked-row-keys="selectedAssetIds"
          class="assets-table"
        />
      </NSpin>
    </div>

    <!-- ── Add Asset Modal ─────────────────────────────────────────────────── -->
    <NModal
      v-model:show="showModal"
      preset="card"
      class="asset-modal"
      :style="{ width: '860px', maxWidth: '95vw' }"
      :title="modalTab === 'aws' ? '新增 AWS 资产' : '新增自建资产'"
      :mask-closable="false"
      :segmented="{ content: true, footer: 'soft' }"
    >
      <NTabs v-model:value="modalTab" type="line" animated>
        <!-- ── AWS Tab ───────────────────────────────────────────────────── -->
        <NTabPane name="aws" tab="AWS 资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="140" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="awsForm.asset_name" placeholder="my-aws-asset-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Region" required>
                    <NSelect v-model:value="awsForm.region" :options="awsRegions" placeholder="选择 Region" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="账户总 vCPU">
                    <NInputNumber v-model:value="awsForm.account_total_vcpu" :min="1" :max="256" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="AWS Account ID">
                    <NSpace vertical>
                      <NSpace>
                        <NInput v-model:value="awsForm.aws_account_id" placeholder="12 位数字或别名" style="width: 200px" />
                        <NButton
                          :loading="fetchingAccountId"
                          :disabled="!awsForm.aws_access_key || !awsForm.aws_secret_key"
                          @click="fetchAccountId"
                        >
                          自动获取
                        </NButton>
                      </NSpace>
                      <NText depth="3" style="font-size: 12px">
                        填写 Access Key 和 Secret Key 后点击自动获取
                      </NText>
                    </NSpace>
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="AWS Access Key" required>
                    <NInput v-model:value="awsForm.aws_access_key" placeholder="AKIA..." />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="AWS Secret Key" required>
                    <NInput v-model:value="awsForm.aws_secret_key" type="password" placeholder="Secret Key" show-password-on="click" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="备注">
                    <NInput v-model:value="awsForm.remarks" type="textarea" placeholder="可选备注信息" :rows="2" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>AMI 配置（可选）</NDivider>
              <NGrid :cols="1" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="AMI ID">
                    <NSpace vertical>
                      <NSpace>
                        <NInput v-model:value="awsForm.ami_id" placeholder="ami-xxxxxxxx 或留空" style="width: 300px" />
                        <NButton :loading="queryingAmi" @click="queryAmi" :disabled="!awsForm.aws_access_key || !awsForm.aws_secret_key">
                          自动获取 Debian ARM64 AMI
                        </NButton>
                      </NSpace>
                      <NSpin v-if="queryingAmi" description="正在查询 AWS..." />
                      <NAlert v-if="amiError" type="error" :title="amiError" style="margin-top: 4px" closable @close="amiError = null" />
                      <NAlert v-if="amiResults.length > 0" type="info" title="查询到以下 AMI，点击选择" style="margin-top: 4px">
                        <NSpace vertical>
                          <div v-for="ami in amiResults" :key="ami.ami_id" style="cursor: pointer; padding: 4px 0; border-bottom: 1px solid #eee" @click="selectAmi(ami)">
                            <NText strong style="font-size: 12px">{{ ami.name }}</NText>
                            <NText depth="3" style="font-size: 11px; margin-left: 8px">{{ ami.ami_id }}</NText>
                            <NText depth="3" style="font-size: 11px; display: block">{{ ami.description || '' }}</NText>
                          </div>
                        </NSpace>
                      </NAlert>
                    </NSpace>
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="协议类型">
                    <NCheckboxGroup v-model:value="awsForm.protocol_types">
                      <NSpace>
                        <NCheckbox v-for="opt in awsProtocolOptions" :key="String(opt.value)" :value="opt.value" :label="String(opt.label)" />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="awsForm.target_count" :min="1" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="优先级">
                    <NInputNumber v-model:value="awsForm.priority" :min="1" :max="1000" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="允许 CDN Proxy">
                    <NSwitch v-model:value="awsForm.allow_cdn_proxy" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <!-- Network / Security Group expand -->
              <NCollapse>
                <NCollapseItem title="网络与安全组配置（可选）" name="net">
                  <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                    <NGi span="2">
                      <NFormItem label="自动创建安全组">
                        <NSwitch v-model:value="awsForm.auto_create_sg" />
                      </NFormItem>
                    </NGi>
                    <NGi span="1">
                      <NFormItem label="VPC ID">
                        <NInput v-model:value="awsForm.vpc_id" placeholder="vpc-xxxxxxxx" />
                      </NFormItem>
                    </NGi>
                    <NGi span="1">
                      <NFormItem label="安全组名称">
                        <NInput v-model:value="awsForm.sg_name" placeholder="shadowfleet-sg" />
                      </NFormItem>
                    </NGi>
                    <NGi span="2">
                      <NFormItem label="计算端口">
                        <NText depth="3" style="font-size: 13px">{{ sgPortsHint }}</NText>
                      </NFormItem>
                    </NGi>
                  </NGrid>
                </NCollapseItem>
              </NCollapse>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton type="primary" :loading="submittingAws" @click="submitAwsForm">
                  注册 AWS 资产
                </NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>

        <!-- ── Self-Hosted Tab ───────────────────────────────────────────── -->
        <NTabPane name="self" tab="自建资产">
          <div class="modal-form">
            <NForm label-placement="left" label-width="140" size="medium">
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="资产名称" required>
                    <NInput v-model:value="selfForm.asset_name" placeholder="my-self-hosted-01" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="Region" required>
                    <NInput v-model:value="selfForm.region" placeholder="hk, us-west, eu-central..." />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NFormItem label="主机地址" required>
                    <NInput v-model:value="selfForm.host" placeholder="1.2.3.4 或域名" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="SSH 端口">
                    <NInputNumber v-model:value="selfForm.ssh_port" :min="1" :max="65535" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="SSH 用户名">
                    <NInput v-model:value="selfForm.ssh_username" placeholder="root" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="SSH 密码">
                    <NInput v-model:value="selfForm.ssh_password" type="password" placeholder="密码或留空使用私钥" show-password-on="click" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="备注">
                    <NInput v-model:value="selfForm.remarks" placeholder="可选备注信息" />
                  </NFormItem>
                </NGi>
                <NGi span="2">
                  <NCollapse>
                    <NCollapseItem title="SSH 私钥（可选）" name="ssh-key">
                      <NInput
                        v-model:value="selfForm.ssh_private_key"
                        type="textarea"
                        placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                        :rows="6"
                        style="font-family: monospace; font-size: 12px"
                      />
                    </NCollapseItem>
                  </NCollapse>
                </NGi>
              </NGrid>

              <NDivider>协议与容量配置</NDivider>
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NFormItem label="协议类型">
                    <NCheckboxGroup v-model:value="selfForm.protocol_types">
                      <NSpace>
                        <NCheckbox v-for="opt in selfProtocolOptions" :key="String(opt.value)" :value="opt.value" :label="String(opt.label)" />
                      </NSpace>
                    </NCheckboxGroup>
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="目标节点数">
                    <NInputNumber v-model:value="selfForm.target_count" :min="1" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="最大节点数">
                    <NInputNumber v-model:value="selfForm.max_count" :min="1" :max="9999" style="width: 100%" />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="优先级">
                    <NInputNumber v-model:value="selfForm.priority" :min="1" :max="1000" style="width: 100%" />
                  </NFormItem>
                </NGi>
              </NGrid>

              <NDivider>硬件配置</NDivider>
              <NGrid :cols="3" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NFormItem label="CPU 核心数">
                    <NInputNumber
                      v-model:value="selfForm.cpu_cores"
                      :min="1" :max="256"
                      placeholder="自动或手动填写"
                      style="width: 100%"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label="内存 (GB)">
                    <NInputNumber
                      v-model:value="selfForm.memory_gb"
                      :min="1" :max="1024"
                      placeholder="自动或手动填写"
                      style="width: 100%"
                    />
                  </NFormItem>
                </NGi>
                <NGi span="1">
                  <NFormItem label=" ">
                    <NButton :loading="probingHw" block @click="probeHardware">
                      探测硬件
                    </NButton>
                  </NFormItem>
                </NGi>
              </NGrid>
              <NText depth="3" style="font-size: 12px; display: block; margin-top: 4px">
                硬件探测需要通过 SSH 连接目标主机，成功后会自动填入 CPU 核心数和内存大小。
              </NText>
            </NForm>

            <div class="modal-footer">
              <NSpace>
                <NButton @click="closeModal">取消</NButton>
                <NButton type="primary" :loading="submittingSelf" @click="submitSelfForm">
                  注册自建资产
                </NButton>
              </NSpace>
            </div>
          </div>
        </NTabPane>
      </NTabs>
    </NModal>
  </div>
</template>

<style scoped>
/* ── Page Layout ────────────────────────────────────────────────────────────── */
.assets-page {
  padding: 24px 28px;
  max-width: 1400px;
  margin: 0 auto;
  min-height: 100%;
  background: transparent;
}

/* ── Header ─────────────────────────────────────────────────────────────────── */
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
  gap: 16px;
}

.header-left {
  flex: 1;
}

.page-title {
  margin: 0 0 6px 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--n-text-color-1, #18181b);
  letter-spacing: -0.3px;
}

.page-subtitle {
  margin: 0;
  font-size: 14px;
  color: var(--n-text-color-3, #a1a1aa);
}

.header-right {
  flex-shrink: 0;
}

/* ── Stats Row ──────────────────────────────────────────────────────────────── */
.stats-row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.stat-card {
  flex: 1;
  background: white;
  border-radius: 12px;
  padding: 16px 20px;
  border: 1px solid var(--n-border-color, #e5e7eb);
  transition: box-shadow 0.2s ease;
}

.stat-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 6px;
  color: var(--n-text-color-1, #18181b);
}

.stat-label {
  font-size: 12px;
  color: var(--n-text-color-3, #a1a1aa);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-aws .stat-value  { color: #f59e0b; }
.stat-self .stat-value { color: #8b5cf6; }
.stat-active .stat-value { color: #10b981; }
.stat-full .stat-value  { color: #f97316; }

/* ── Table Card ─────────────────────────────────────────────────────────────── */
.table-card {
  background: white;
  border-radius: 14px;
  border: 1px solid var(--n-border-color, #e5e7eb);
  padding: 20px 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

/* ── Tab Bar ─────────────────────────────────────────────────────────────────── */
.tab-bar {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--n-border-color, #e5e7eb);
  padding-bottom: 0;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  color: var(--n-text-color-3, #71717a);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  border-radius: 6px 6px 0 0;
  transition: color 0.15s ease, background 0.15s ease;
}

.tab-btn:hover {
  color: var(--n-text-color-1, #18181b);
  background: rgba(0, 0, 0, 0.03);
}

.tab-btn.active {
  color: #6366f1;
  border-bottom-color: #6366f1;
  background: rgba(99, 102, 241, 0.04);
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 10px;
  background: var(--n-color-pressed, #f4f4f5);
  color: var(--n-text-color-3, #71717a);
}

.tab-btn.active .tab-badge {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.tab-badge-aws  { background: rgba(245, 158, 11, 0.1); color: #f59e0b; }
.tab-badge-self { background: rgba(139, 92, 246, 0.1); color: #8b5cf6; }

/* ── Table ──────────────────────────────────────────────────────────────────── */
.assets-table {
  font-size: 13px;
}

/* ── Modal Form ─────────────────────────────────────────────────────────────── */
.modal-form {
  padding: 8px 4px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--n-border-color, #e5e7eb);
}
</style>
