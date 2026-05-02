<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import {
  NCard,
  NGrid,
  NGi,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NCheckbox,
  NButton,
  NSpace,
  NSpin,
  NAlert,
  NTag,
  NText,
  NDivider,
  NDataTable,
  NCollapse,
  NCollapseItem,
  NCode,
  useMessage,
} from 'naive-ui'
import type { SelectOption } from 'naive-ui'
import apiClient from '@/api/client'
import type {
  ProvisionTaskCreateRequest,
  SubmitResult,
  TaskResponse,
  XboardGroupResponse,
} from '@/types/api'

// ── Constants ─────────────────────────────────────────────────────────────────
const PROTOCOLS = ['AnyTLS', 'Trojan', 'vless', 'vmess', 'Hysteria2']
const REGION_MAP: Record<string, string> = {
  'ap-northeast-1': '东京',
  'ap-northeast-3': '大阪',
  'ap-northeast-2': '韩国',
  'ap-east-1': '香港',
  'us-west-1': '洛杉矶',
  'ap-southeast-1': '新加坡',
}
const REGIONS = Object.keys(REGION_MAP)

// ── State ─────────────────────────────────────────────────────────────────────
const message = useMessage()
const submitting = ref(false)
const submitError = ref<string | null>(null)
const submitSuccess = ref<SubmitResult | null>(null)

// Groups
const groups = ref<XboardGroupResponse[]>([])
const groupsLoading = ref(false)
const groupsError = ref<string | null>(null)

// Recent tasks
const recentTasks = ref<TaskResponse[]>([])
const tasksLoading = ref(true)
const tasksError = ref<string | null>(null)
let tasksTimer: ReturnType<typeof setInterval> | null = null

// Selected task for detail
const selectedTaskId = ref<number | null>(null)
const fullTaskDetail = ref<TaskResponse | null>(null)
const detailLoading = ref(false)
const retryingTaskId = ref<number | null>(null)

// ── Form ──────────────────────────────────────────────────────────────────────
const protocolType = ref('AnyTLS')
const assetType = ref('aws')
const nodeName = ref('')
const region = ref('ap-northeast-1')
const port = ref('443')
const serverPort = ref(443)
const rate = ref<number | null>(1.0)
const requireCdnProxy = ref(false)
const statusReason = ref('')
const parentId = ref<number | null>(null)
const routeIds = ref('')
const sortVal = ref<number | null>(null)
const showNode = ref(true)
const rateTimeEnable = ref(false)
const tagsJson = ref('')
const protocolSettingsJson = ref('')
const rateTimeRangesJson = ref('')

// ── Computed ──────────────────────────────────────────────────────────────────
const protocolOptions = computed<SelectOption[]>(() =>
  PROTOCOLS.map((p) => ({ label: p, value: p }))
)

const regionOptions = computed<SelectOption[]>(() =>
  REGIONS.map((r) => ({ label: `${REGION_MAP[r]} (${r})`, value: r }))
)

const assetTypeOptions: SelectOption[] = [
  { label: 'AWS', value: 'aws' },
  { label: 'Self-Hosted', value: 'self_hosted' },
]

const groupOptions = computed<SelectOption[]>(() =>
  groups.value.map((g) => ({ label: g.name, value: g.id }))
)

const runningCount = computed(() =>
  recentTasks.value.filter((t) => t.status === 'running').length
)

const filteredTasks = computed(() => recentTasks.value.slice(0, 20))

const taskSelectOptions = computed<SelectOption[]>(() =>
  recentTasks.value.map((t) => ({
    label: `#${t.id} — ${t.task_type}`,
    value: t.id,
  }))
)

// ── Auto-tags ─────────────────────────────────────────────────────────────────
const REGION_TAGS: Record<string, string> = {
  'ap-northeast-1': 'jp-tokyo',
  'ap-northeast-3': 'jp-osaka',
  'ap-northeast-2': 'kr-seoul',
  'ap-east-1': 'hk-hongkong',
  'us-west-1': 'us-losangeles',
  'ap-southeast-1': 'sg-singapore',
}

function buildDefaultTags() {
  const regionTag = REGION_TAGS[region.value] ?? region.value
  return JSON.stringify(
    { protocol: protocolType.value.toLowerCase(), region: regionTag, asset: 'aws' },
    null,
    2
  )
}

function onRegionChange() {
  tagsJson.value = buildDefaultTags()
}

// ── Data Fetching ─────────────────────────────────────────────────────────────
async function fetchGroups() {
  groupsLoading.value = true
  groupsError.value = null
  try {
    const { data } = await apiClient.get<XboardGroupResponse[]>('/xboard/groups')
    groups.value = data
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    groupsError.value = axiosErr.response?.data?.error || axiosErr.message || '加载分组失败'
  } finally {
    groupsLoading.value = false
  }
}

async function fetchRecentTasks() {
  try {
    const { data } = await apiClient.get<TaskResponse[]>('/tasks', { params: { limit: 20 } })
    recentTasks.value = data
    tasksError.value = null
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    tasksError.value = axiosErr.response?.data?.error || axiosErr.message || '加载任务失败'
  } finally {
    tasksLoading.value = false
  }
}

async function fetchTaskDetail(id: number) {
  detailLoading.value = true
  try {
    const { data } = await apiClient.get<TaskResponse>(`/tasks/${id}`)
    fullTaskDetail.value = data
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || '加载详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function retryTask(id: number) {
  retryingTaskId.value = id
  try {
    await apiClient.post<TaskResponse>(`/tasks/${id}/retry`)
    message.success(`任务 #${id} 已重置为 queued`)
    await fetchRecentTasks()
    if (selectedTaskId.value === id) {
      fullTaskDetail.value = null
      selectedTaskId.value = null
    }
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || '重试失败')
  } finally {
    retryingTaskId.value = null
  }
}

// ── Submit ────────────────────────────────────────────────────────────────────
async function handleSubmit() {
  if (!nodeName.value.trim()) {
    message.warning('节点名称不能为空')
    return
  }

  submitting.value = true
  submitError.value = null
  submitSuccess.value = null

  const body: ProvisionTaskCreateRequest = {
    protocol_type: protocolType.value,
    node_name: nodeName.value.trim(),
    port: port.value,
    server_port: assetType.value === 'aws' ? serverPort.value : 0,
    rate: rate.value ?? 1.0,
    asset_type: assetType.value,
    region: region.value,
    require_cdn_proxy: requireCdnProxy.value,
    group_ids: [],
    route_ids: routeIds.value
      ? routeIds.value.split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => !isNaN(n))
      : undefined,
    tags: tagsJson.value ? (() => { try { return JSON.parse(tagsJson.value) } catch { return undefined } })() : undefined,
    protocol_settings: protocolSettingsJson.value
      ? (() => { try { return JSON.parse(protocolSettingsJson.value) } catch { return undefined } })()
      : undefined,
    show: showNode.value,
    sort: sortVal.value,
    rate_time_enable: rateTimeEnable.value,
    rate_time_ranges: rateTimeRangesJson.value
      ? (() => { try { return JSON.parse(rateTimeRangesJson.value) } catch { return undefined } })()
      : undefined,
    status_reason: statusReason.value || undefined,
    parent_id: parentId.value,
  }

  try {
    const { data: resp } = await apiClient.post('/tasks', body)
    const respData = resp as SubmitResult
    submitSuccess.value = respData
    message.success(`任务已提交 — #${respData.task_id}, Correlation: ${respData.correlation_id}`)
    await fetchRecentTasks()
    resetForm()
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    submitError.value = axiosErr.response?.data?.error || axiosErr.message || '提交失败'
  } finally {
    submitting.value = false
  }
}

function resetForm() {
  nodeName.value = ''
  port.value = '443'
  serverPort.value = 443
  rate.value = 1.0
  requireCdnProxy.value = false
  statusReason.value = ''
  parentId.value = null
  routeIds.value = ''
  sortVal.value = null
  showNode.value = true
  rateTimeEnable.value = false
  tagsJson.value = buildDefaultTags()
  protocolSettingsJson.value = ''
  rateTimeRangesJson.value = ''
}

// ── Watchers ──────────────────────────────────────────────────────────────────
function onTaskSelect(id: number | null) {
  selectedTaskId.value = id
  if (id !== null) {
    fetchTaskDetail(id)
  } else {
    fullTaskDetail.value = null
  }
}

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtTs(value: string | null | undefined): string {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return String(value)
  }
}

function statusTagType(status: string): 'default' | 'info' | 'success' | 'error' | 'warning' {
  switch (status) {
    case 'queued': return 'default'
    case 'running': return 'info'
    case 'succeeded': return 'success'
    case 'failed': return 'error'
    default: return 'default'
  }
}

// ── Table Columns ─────────────────────────────────────────────────────────────
const taskColumns = [
  { title: 'ID', key: 'id', align: 'center' as const, width: 70 },
  { title: 'Type', key: 'task_type', ellipsis: { tooltip: true } },
  {
    title: 'Status', key: 'status', align: 'center' as const, width: 100,
    render: (row: TaskResponse) => h(NTag, { type: statusTagType(row.status), size: 'small' }, { default: () => row.status }),
  },
  {
    title: 'Attempts', key: 'attempt_count', align: 'center' as const, width: 100,
    render: (row: TaskResponse) => `${row.attempt_count} / ${row.max_attempts}`,
  },
  { title: 'Created', key: 'created_at', render: (row: TaskResponse) => fmtTs(row.created_at) },
  { title: 'Finished', key: 'finished_at', render: (row: TaskResponse) => fmtTs(row.finished_at) },
]

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  tagsJson.value = buildDefaultTags()
  fetchGroups()
  fetchRecentTasks()
  tasksTimer = setInterval(fetchRecentTasks, 15_000)
})

onUnmounted(() => {
  if (tasksTimer !== null) {
    clearInterval(tasksTimer)
    tasksTimer = null
  }
})
</script>

<template>
  <div style="padding: 16px; max-width: 1200px; margin: 0 auto">
    <!-- ── Header ──────────────────────────────────────────────────────────── -->
    <NCard style="margin-bottom: 16px">
      <NText depth="3" style="font-size: 14px">
        当前页面只负责提交任务到 SQLite 请求队列，不直接执行 AWS / Cloudflare / Xboard 开机流水线。
      </NText>
    </NCard>

    <NGrid :cols="2" :x-gap="16" style="margin-bottom: 16px">
      <!-- ── Left Column: Form ──────────────────────────────────────────────── -->
      <NGi>
        <NCard title="初始化任务请求表单">
          <NSpin :show="submitting">
            <NAlert v-if="submitError" type="error" :title="submitError" style="margin-bottom: 12px" closable
              @close="submitError = null" />
            <NAlert v-if="submitSuccess" type="success" :title="`任务已提交 #${submitSuccess.task_id}`"
              style="margin-bottom: 12px" closable @close="submitSuccess = null">
              <NText depth="3" style="font-size: 12px">Correlation: {{ submitSuccess.correlation_id }}</NText>
            </NAlert>

            <NForm label-placement="left" label-width="140" size="small">
              <NFormItem label="协议类型">
                <NSelect v-model:value="protocolType" :options="protocolOptions" />
              </NFormItem>
              <NFormItem label="资产类型">
                <NSelect v-model:value="assetType" :options="assetTypeOptions" />
              </NFormItem>
              <NFormItem label="节点名称" required>
                <NInput v-model:value="nodeName" placeholder="sf-xxx" clearable />
              </NFormItem>
              <NFormItem label="目标区域">
                <NSelect
                  v-model:value="region"
                  :options="regionOptions"
                  @update:value="onRegionChange"
                />
              </NFormItem>
              <NFormItem label="Xboard 节点端口">
                <NInput v-model:value="port" placeholder="443" />
              </NFormItem>
              <NFormItem v-if="assetType === 'aws'" label="服务监听端口">
                <NInputNumber v-model:value="serverPort" :min="1" :max="65535" style="width: 100%" />
              </NFormItem>
              <NFormItem v-else label="服务监听端口">
                <NInput value="自动分配 (40000-60000)" disabled />
              </NFormItem>
              <NFormItem label="倍率">
                <NInputNumber v-model:value="rate" :min="0" :step="0.1" style="width: 100%" />
              </NFormItem>
              <NFormItem label="Cloudflare CDN">
                <NCheckbox v-model:checked="requireCdnProxy">
                  启用 CDN 代理（灰色云，不走代理时保持关闭）
                </NCheckbox>
              </NFormItem>

              <NDivider />

              <NFormItem label="状态备注">
                <NInput v-model:value="statusReason" placeholder="可选" />
              </NFormItem>
              <NFormItem label="分组（多选）">
                <NSpin :show="groupsLoading">
                  <NSelect
                    v-model:value="parentId"
                    :options="groupOptions"
                    placeholder="选择分组"
                    multiple
                    clearable
                  />
                  <NText v-if="groupsError" depth="3" style="font-size: 12px; display: block; margin-top: 4px">
                    {{ groupsError }}
                  </NText>
                </NSpin>
              </NFormItem>
              <NFormItem label="父节点 ID">
                <NInputNumber v-model:value="parentId" placeholder="可选" clearable style="width: 100%" />
              </NFormItem>
              <NFormItem label="路由 ID（逗号分隔）">
                <NInput v-model:value="routeIds" placeholder="1,2,3" />
              </NFormItem>
              <NFormItem label="排序">
                <NInputNumber v-model:value="sortVal" placeholder="可选" clearable style="width: 100%" />
              </NFormItem>
              <NFormItem label="Xboard show">
                <NCheckbox v-model:checked="showNode">show=true</NCheckbox>
              </NFormItem>
              <NFormItem label="限速时段">
                <NCheckbox v-model:checked="rateTimeEnable">启用限速时段</NCheckbox>
              </NFormItem>

              <NDivider />

              <NFormItem label="标签 JSON">
                <NInput
                  v-model:value="tagsJson"
                  type="textarea"
                  placeholder="自动生成，可手动修改"
                  :autosize="{ minRows: 2, maxRows: 5 }"
                />
              </NFormItem>
              <NFormItem label="协议设置 JSON">
                <NInput
                  v-model:value="protocolSettingsJson"
                  type="textarea"
                  placeholder="可选"
                  :autosize="{ minRows: 2, maxRows: 6 }"
                />
              </NFormItem>
              <NFormItem label="限速时段 JSON">
                <NInput
                  v-model:value="rateTimeRangesJson"
                  type="textarea"
                  placeholder="可选"
                  :autosize="{ minRows: 2, maxRows: 5 }"
                />
              </NFormItem>
            </NForm>

            <NSpace style="margin-top: 16px">
              <NButton type="primary" :loading="submitting" @click="handleSubmit">
                执行初始化流水线
              </NButton>
              <NButton @click="resetForm">重置表单</NButton>
            </NSpace>
          </NSpin>
        </NCard>
      </NGi>

      <!-- ── Right Column: Recent Tasks ────────────────────────────────────── -->
      <NGi>
        <NCard title="最近初始化任务">
          <NSpin :show="tasksLoading" description="加载中…">
            <NAlert v-if="tasksError" type="error" :title="tasksError" style="margin-bottom: 12px" closable
              @close="tasksError = null" />
            <NAlert v-if="runningCount > 0" type="warning" style="margin-bottom: 12px">
              有 {{ runningCount }} 个执行中的任务
            </NAlert>

            <NDataTable
              :columns="taskColumns"
              :data="filteredTasks"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 10 }"
              :row-key="(row: TaskResponse) => row.id"
              style="margin-bottom: 16px"
            />

            <NCollapse>
              <NCollapseItem title="查看原始明细" name="detail">
                <NSelect
                  :value="selectedTaskId"
                  :options="taskSelectOptions"
                  placeholder="选择任务"
                  clearable
                  @update:value="onTaskSelect"
                  style="margin-bottom: 12px; max-width: 400px"
                />

                <NSpin :show="detailLoading">
                  <template v-if="fullTaskDetail">
                    <NCard title="基本信息" size="small" style="margin-bottom: 8px">
                      <NGrid :cols="2" :x-gap="8" :y-gap="4">
                        <NGi><NText depth="3">ID:</NText> {{ fullTaskDetail.id }}</NGi>
                        <NGi><NText depth="3">Type:</NText> {{ fullTaskDetail.task_type }}</NGi>
                        <NGi>
                          <NText depth="3">Status:</NText>
                          <NTag :type="statusTagType(fullTaskDetail.status)" size="small" style="margin-left: 4px">
                            {{ fullTaskDetail.status }}
                          </NTag>
                        </NGi>
                        <NGi>
                          <NText depth="3">Attempts:</NText>
                          {{ fullTaskDetail.attempt_count }} / {{ fullTaskDetail.max_attempts }}
                        </NGi>
                      </NGrid>
                    </NCard>

                    <NCard title="Correlation ID" size="small" style="margin-bottom: 8px">
                      <NCode :code="fullTaskDetail.correlation_id" language="text" word-wrap />
                    </NCard>

                    <NAlert v-if="fullTaskDetail.last_error" type="error" :title="fullTaskDetail.last_error"
                      style="margin-bottom: 8px" />

                    <NSpace>
                      <NButton
                        v-if="fullTaskDetail.status === 'failed'"
                        type="warning"
                        size="small"
                        :loading="retryingTaskId === fullTaskDetail.id"
                        :disabled="retryingTaskId !== null"
                        @click="retryTask(fullTaskDetail.id)"
                      >
                        重试此任务
                      </NButton>
                      <NButton
                        v-if="fullTaskDetail.status === 'succeeded'"
                        type="success"
                        size="small"
                      >
                        任务成功
                      </NButton>
                    </NSpace>
                  </template>
                </NSpin>
              </NCollapseItem>
            </NCollapse>
          </NSpin>
        </NCard>
      </NGi>
    </NGrid>
  </div>
</template>
