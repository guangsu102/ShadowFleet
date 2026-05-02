<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import {
  NGrid,
  NGi,
  NDataTable,
  NTag,
  NSpin,
  NAlert,
  NCard,
  NTabs,
  NTab,
  NButton,
  NSpace,
  NText,
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
import type { AssetResponse, AWSAssetCreateRequest, SelfHostedAssetCreateRequest } from '@/types/api'

// ── Helpers ────────────────────────────────────────────────────────────────────
function statusTagType(status: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  switch (status) {
    case 'active':    return 'success'
    case 'full':      return 'warning'
    case 'offline':   return 'error'
    case 'deploying': return 'info'
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

// Delete confirmation
const deleteTarget = ref<AssetResponse | null>(null)
const deleting = ref(false)

function confirmDelete(asset: AssetResponse) {
  dialog.warning({
    title: '确认删除资产',
    content: `确定要删除资产 "${asset.asset_name}" (ID: ${asset.asset_id}) 吗？此操作不可恢复。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: () => doDelete(asset),
  })
}

async function doDelete(asset: AssetResponse) {
  deleting.value = true
  try {
    await apiClient.delete(`/assets/${asset.asset_id}`)
    message.success(`资产 "${asset.asset_name}" 已删除`)
    deleteTarget.value = null
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.message || '删除失败')
  } finally {
    deleting.value = false
  }
}

// ── Computed: filtered assets ─────────────────────────────────────────────────
const awsAssets   = computed(() => assets.value.filter(a => a.asset_type === 'aws'))
const selfAssets  = computed(() => assets.value.filter(a => a.asset_type === 'self-hosted'))

// ── Table columns ──────────────────────────────────────────────────────────────
function buildColumns(onDelete: (asset: AssetResponse) => void): DataTableColumns<AssetResponse> {
  return [
    { title: 'Asset ID',      key: 'asset_id',      width: 90,  align: 'center' },
    { title: 'Name',          key: 'asset_name',    ellipsis: { tooltip: true } },
    {
      title: 'Type', key: 'asset_type', width: 80,
      render: (row) => h(NTag, { size: 'small', type: row.asset_type === 'aws' ? 'info' : 'warning' },
        { default: () => row.asset_type === 'aws' ? 'AWS' : '自建' }),
    },
    { title: 'Region',  key: 'region',  render: (r) => r.region ?? '—' },
    {
      title: 'Status', key: 'status', width: 100,
      render: (row) => h(NTag, { type: statusTagType(row.status), size: 'small' },
        { default: () => row.status }),
    },
    {
      title: 'AWS Account', key: 'aws_account_id',
      render: (row) => maskAccountId(row.aws_account_id),
    },
    {
      title: 'vCPU', key: 'account_total_vcpu', width: 70,
      render: (r) => r.account_total_vcpu ?? r.cpu_cores ?? '—',
    },
    {
      title: 'Memory (GB)', key: 'memory_gb', width: 100,
      render: (r) => r.memory_gb ?? '—',
    },
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
    {
      title: 'Updated', key: 'updated_at', width: 160,
      render: (r) => fmtTs(r.updated_at),
    },
    {
      title: 'Actions', key: 'actions', width: 80, align: 'center',
      render: (row) =>
        h(NButton, { size: 'small', type: 'error', quaternary: true, onClick: () => onDelete(row) },
          { default: () => '删除' }),
    },
  ]
}

const allColumns    = buildColumns((a) => confirmDelete(a))
const awsColumns    = buildColumns((a) => confirmDelete(a))
const selfColumns   = buildColumns((a) => confirmDelete(a))

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
// AMI query
const queryingAmi = ref(false)
const amiResults = ref<SelectOption[]>([])
const amiNameFilter = ref('debian')

// ── AWS Registration Form ──────────────────────────────────────────────────────
const awsForm = ref({
  asset_name: '',
  region: 'us-east-1',
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
  'us-east-1','us-west-1','us-west-2','eu-west-1','eu-west-2',
  'eu-central-1','ap-northeast-1','ap-southeast-1','ap-southeast-2',
].map(r => ({ label: r, value: r }))

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

// Current AMI asset_id for AMI query — stored after creation (not applicable here, we query before)
// Actually, AMI query requires an existing asset. For new assets, we can't query AMI until after creation.
// Show a placeholder button that explains this.
function handleQueryAmi() {
  message.info('AMI 查询需要在资产创建后进行，或通过 AWS Console / CLI 查看。')
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
    awsForm.value = {
      asset_name: '', region: 'us-east-1', account_total_vcpu: 8,
      aws_access_key: '', aws_secret_key: '', aws_account_id: '',
      remarks: '', protocol_types: ['AnyTLS'], target_count: 1,
      priority: 100, allow_cdn_proxy: false, auto_create_sg: false,
      vpc_id: '', sg_name: '', sg_ports_raw: '', ami_id: '',
    }
    amiResults.value = []
    await fetchAssets()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string }; message?: string } }
    message.error(e.response?.data?.error || e.response?.data?.message || '注册失败')
  } finally {
    submittingAws.value = false
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

async function probeHardware() {
  if (!selfForm.value.host.trim()) {
    message.warning('请先填写主机地址再探测硬件')
    return
  }
  probingHw.value = true
  try {
    // Try POST /assets/self-hosted/probe-hardware if available
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
    selfForm.value = {
      asset_name: '', region: '', host: '', ssh_port: 22,
      ssh_username: 'root', ssh_password: '', ssh_private_key: '',
      remarks: '', protocol_types: ['AnyTLS'], target_count: 1,
      max_count: 10, priority: 100, cpu_cores: null, memory_gb: null,
    }
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
  <div style="padding: 16px; max-width: 1400px; margin: 0 auto">
    <NSpin :show="loading" description="加载资产列表…">
      <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px"
        closable @close="errorMsg = null" />

      <!-- ── Section 1: Asset Tables ─────────────────────────────────────────── -->
      <NCard title="账号与资产池" style="margin-bottom: 16px">
        <NTabs type="line" animated>
          <NTab name="all" title="全部">
            <NDataTable
              :columns="allColumns"
              :data="assets"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 15 }"
              :row-key="(row: AssetResponse) => row.asset_id"
              style="margin-top: 8px"
            />
          </NTab>

          <NTab name="aws" title="AWS">
            <NDataTable
              :columns="awsColumns"
              :data="awsAssets"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 15 }"
              :row-key="(row: AssetResponse) => row.asset_id"
              style="margin-top: 8px"
            />
          </NTab>

          <NTab name="self" title="自建">
            <NDataTable
              :columns="selfColumns"
              :data="selfAssets"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 15 }"
              :row-key="(row: AssetResponse) => row.asset_id"
              style="margin-top: 8px"
            />
          </NTab>
        </NTabs>

        <template #footer>
          <NText depth="3" style="font-size: 13px">
            共 {{ assets.length }} 个资产 &nbsp;|&nbsp;
            AWS: {{ awsAssets.length }} &nbsp;|&nbsp;
            自建: {{ selfAssets.length }}
          </NText>
        </template>
      </NCard>

      <!-- ── Section 2: Registration ─────────────────────────────────────────── -->
      <NCard title="注册新资产">
        <NTabs type="line" animated>
          <!-- ── AWS Registration Tab ──────────────────────────────────────── -->
          <NTab name="aws-reg" title="AWS 资产">
            <div style="padding: 16px 0; max-width: 800px">
              <!-- Fields outside the form block -->
              <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="1">
                  <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">资产名称 *</NText>
                  <NInput v-model:value="awsForm.asset_name" placeholder="my-aws-asset-01" />
                </NGi>
                <NGi span="1">
                  <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">Region *</NText>
                  <NSelect v-model:value="awsForm.region" :options="awsRegions" placeholder="选择 Region" />
                </NGi>
                <NGi span="1">
                  <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">账户总 vCPU</NText>
                  <NInputNumber v-model:value="awsForm.account_total_vcpu" :min="1" :max="256" style="width: 100%" />
                </NGi>
                <NGi span="1">
                  <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">AWS Account ID (可选)</NText>
                  <NInput v-model:value="awsForm.aws_account_id" placeholder="12 位数字或别名" />
                </NGi>
                <NGi span="2">
                  <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">AWS Access Key *</NText>
                  <NInput v-model:value="awsForm.aws_access_key" placeholder="AKIA..." />
                </NGi>
                <NGi span="2">
                  <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">AWS Secret Key *</NText>
                  <NInput v-model:value="awsForm.aws_secret_key" type="password" placeholder="Secret Key" show-password-on="click" />
                </NGi>
                <NGi span="2">
                  <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">备注</NText>
                  <NInput v-model:value="awsForm.remarks" type="textarea" placeholder="可选备注信息" :rows="2" />
                </NGi>
              </NGrid>

              <!-- AMI Query -->
              <NDivider>AMI 查询</NDivider>
              <NGrid :cols="3" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                <NGi span="2">
                  <NInput
                    v-model:value="amiNameFilter"
                    placeholder="AMI 名称过滤关键词，如 debian"
                  />
                </NGi>
                <NGi span="1">
                  <NButton :loading="queryingAmi" block @click="handleQueryAmi">查询 AMI</NButton>
                </NGi>
              </NGrid>
              <NSelect
                v-if="amiResults.length > 0"
                v-model:value="awsForm.ami_id"
                :options="amiResults"
                placeholder="选择 AMI (结果来自资产创建后查询)"
                clearable
                style="margin-top: 8px; max-width: 600px"
              />
              <NText depth="3" style="font-size: 12px; display: block; margin-top: 6px">
                AMI 查询功能需要资产先创建。下方可手动填写 AMI ID。
              </NText>
              <NInput
                v-model:value="awsForm.ami_id"
                placeholder="手动填写 AMI ID (可选)"
                style="margin-top: 8px; max-width: 600px"
              />

              <!-- Form section -->
              <NDivider>协议与容量配置</NDivider>
              <NForm label-placement="left" label-width="140" size="medium">
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
                  <NCollapseItem title="网络与安全组配置 (可选)" name="net">
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

                <NSpace style="margin-top: 16px">
                  <NButton type="primary" :loading="submittingAws" @click="submitAwsForm">
                    注册 AWS 资产
                  </NButton>
                </NSpace>
              </NForm>
            </div>
          </NTab>

          <!-- ── Self-Hosted Registration Tab ──────────────────────────────── -->
          <NTab name="self-reg" title="自建资产">
            <div style="padding: 16px 0; max-width: 800px">
              <NForm label-placement="left" label-width="140" size="medium">
                <NGrid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                  <NGi span="1">
                    <NFormItem label="资产名称 *">
                      <NInput v-model:value="selfForm.asset_name" placeholder="my-self-hosted-01" />
                    </NFormItem>
                  </NGi>
                  <NGi span="1">
                    <NFormItem label="Region *">
                      <NInput v-model:value="selfForm.region" placeholder="hk, us-west, eu-central..." />
                    </NFormItem>
                  </NGi>
                  <NGi span="2">
                    <NFormItem label="主机地址 *">
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

                  <!-- SSH Private Key expand -->
                  <NGi span="2">
                    <NCollapse>
                      <NCollapseItem title="SSH 私钥 (可选)" name="ssh-key">
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

                <!-- Hardware probe -->
                <NDivider>硬件配置</NDivider>
                <NGrid :cols="3" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
                  <NGi span="1">
                    <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">CPU 核心数</NText>
                    <NInputNumber
                      v-model:value="selfForm.cpu_cores"
                      :min="1" :max="256"
                      placeholder="自动或手动填写"
                      style="width: 100%"
                    />
                  </NGi>
                  <NGi span="1">
                    <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">内存 (GB)</NText>
                    <NInputNumber
                      v-model:value="selfForm.memory_gb"
                      :min="1" :max="1024"
                      placeholder="自动或手动填写"
                      style="width: 100%"
                    />
                  </NGi>
                  <NGi span="1">
                    <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 4px">硬件探测</NText>
                    <NButton :loading="probingHw" block @click="probeHardware">
                      探测硬件
                    </NButton>
                  </NGi>
                </NGrid>
                <NText depth="3" style="font-size: 12px; display: block; margin-top: 6px">
                  硬件探测需要通过 SSH 连接目标主机，成功后会自动填入 CPU 核心数和内存大小。
                </NText>

                <NSpace style="margin-top: 16px">
                  <NButton type="primary" :loading="submittingSelf" @click="submitSelfForm">
                    注册自建资产
                  </NButton>
                </NSpace>
              </NForm>
            </div>
          </NTab>
        </NTabs>
      </NCard>
    </NSpin>
  </div>
</template>
