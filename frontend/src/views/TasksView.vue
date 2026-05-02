<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import {
  NGrid,
  NGi,
  NStatistic,
  NDataTable,
  NTabs,
  NTab,
  NTag,
  NSpin,
  NAlert,
  NCard,
  NSelect,
  NCode,
  NCollapse,
  NCollapseItem,
  NEmpty,
  NButton,
  NSpace,
  NDivider,
  useMessage,
} from 'naive-ui'
import apiClient from '@/api/client'
import { useSSE } from '@/composables/useSSE'
import { useI18n } from '@/composables/useI18n'
import type { TaskResponse, SubmitResult } from '@/types/api'

const { t } = useI18n()
const message = useMessage()
const tasks = ref<TaskResponse[]>([])
const loading = ref(true)
const errorMsg = ref<string | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | null = null

// Tab 3 state
const failedTaskId = ref<number | null>(null)
const retryingTaskId = ref<number | null>(null)
const fullFailedTask = ref<TaskResponse | null>(null)

// Tab 4 state
const selectedTaskId = ref<number | null>(null)
const fullTaskDetail = ref<TaskResponse | null>(null)
const loadingDetail = ref(false)

// Filters (Tab 1)
const filterStatus = ref<string | null>(null)
const filterLimit = ref<number>(50)
const filterTaskType = ref<string | null>(null)

// ── Computed ──────────────────────────────────────────────────────────────────
const totalCount = computed(() => tasks.value.length)
const queuedCount = computed(() => tasks.value.filter(t => t.status === 'queued').length)
const runningCount = computed(() => tasks.value.filter(t => t.status === 'running').length)
const succeededCount = computed(() => tasks.value.filter(t => t.status === 'succeeded').length)
const failedCount = computed(() => tasks.value.filter(t => t.status === 'failed').length)

const runningTasks = computed(() => tasks.value.filter(t => t.status === 'running'))
const failedTasks = computed(() => tasks.value.filter(t => t.status === 'failed'))

const filteredTasks = computed(() => {
  let result = tasks.value
  if (filterStatus.value) {
    result = result.filter(t => t.status === filterStatus.value)
  }
  if (filterTaskType.value) {
    result = result.filter(t => t.task_type === filterTaskType.value)
  }
  return result.slice(0, filterLimit.value)
})

const taskOptions = computed(() =>
  tasks.value.map(t => ({
    label: `#${t.id} — ${t.task_type}`,
    value: t.id,
  }))
)

// ── Data Fetching ────────────────────────────────────────────────────────────
async function fetchTasks() {
  try {
    const { data } = await apiClient.get<TaskResponse[]>('/tasks', { params: { limit: 100 } })
    tasks.value = data
    errorMsg.value = null
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    errorMsg.value = axiosErr.response?.data?.error || axiosErr.message || t('tasks.loadFailed')
  } finally {
    loading.value = false
  }
}

async function fetchTaskDetail(id: number) {
  loadingDetail.value = true
  try {
    const { data } = await apiClient.get<TaskResponse>(`/tasks/${id}`)
    fullTaskDetail.value = data
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('tasks.loadDetailFailed'))
  } finally {
    loadingDetail.value = false
  }
}

async function fetchFailedTaskDetail(id: number) {
  try {
    const { data } = await apiClient.get<TaskResponse>(`/tasks/${id}`)
    fullFailedTask.value = data
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('tasks.loadDetailFailed'))
  }
}

async function retryTask(id: number) {
  retryingTaskId.value = id
  try {
    const { data } = await apiClient.post<SubmitResult>(`/tasks/${id}/retry`)
    message.success(t('tasks.retrySuccess') + ` — Task #${data.task_id}, Correlation: ${data.correlation_id}`)
    await fetchTasks()
    if (failedTaskId.value === id) {
      fullFailedTask.value = null
      failedTaskId.value = null
    }
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('tasks.retryFailed'))
  } finally {
    retryingTaskId.value = null
  }
}

// ── Formatters ────────────────────────────────────────────────────────────────
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

function statusTagType(status: string): 'default' | 'info' | 'success' | 'error' | 'warning' {
  switch (status) {
    case 'queued': return 'default'
    case 'running': return 'info'
    case 'succeeded': return 'success'
    case 'failed': return 'error'
    default: return 'default'
  }
}

function truncateError(err: string | null, maxLen = 100): string {
  if (!err) return '—'
  return err.length > maxLen ? err.slice(0, maxLen) + '…' : err
}

// ── Task Type Label ──────────────────────────────────────────────────────────
function taskTypeLabel(tt: string): string {
  const map: Record<string, string> = {
    provision_node: t('tasks.provisionNode'),
    force_heal: t('tasks.forceHeal'),
    decommission_node: t('tasks.decommissionNode'),
    reprobe_node: t('tasks.reprobeNode'),
    mark_manual_review: t('tasks.manualReview'),
  }
  return map[tt] ?? tt
}

// ── Columns ───────────────────────────────────────────────────────────────────
const allTaskColumns = [
  { title: t('tasks.id'), key: 'id', align: 'center' as const, width: 70 },
  { title: t('tasks.taskType'), key: 'task_type', render: (row: TaskResponse) => taskTypeLabel(row.task_type) },
  {
    title: t('tasks.status'),
    key: 'status',
    width: 100,
    align: 'center' as const,
    render: (row: TaskResponse) => h(NTag, { type: statusTagType(row.status), size: 'small' }, { default: () => row.status }),
  },
  {
    title: t('tasks.attempts'),
    key: 'attempt_count',
    align: 'center' as const,
    width: 100,
    render: (row: TaskResponse) => `${row.attempt_count} / ${row.max_attempts}`,
  },
  { title: t('tasks.created'), key: 'created_at', render: (row: TaskResponse) => fmtTs(row.created_at) },
  { title: t('tasks.started'), key: 'started_at', render: (row: TaskResponse) => fmtTs(row.started_at) },
  { title: t('tasks.finished'), key: 'finished_at', render: (row: TaskResponse) => fmtTs(row.finished_at) },
  {
    title: t('tasks.lockedBy'),
    key: 'locked_by',
    ellipsis: { tooltip: true },
    render: (row: TaskResponse) => row.locked_by ?? '—',
  },
]

const runningTaskColumns = [
  { title: t('tasks.id'), key: 'id', align: 'center' as const, width: 70 },
  {
    title: t('tasks.attempts'),
    key: 'attempt_count',
    align: 'center' as const,
    width: 100,
    render: (row: TaskResponse) => `${row.attempt_count} / ${row.max_attempts}`,
  },
  { title: t('tasks.started'), key: 'started_at', render: (row: TaskResponse) => fmtTs(row.started_at) },
  { title: t('tasks.lockedBy'), key: 'locked_by', ellipsis: { tooltip: true } },
  {
    title: t('tasks.nextRun'),
    key: 'next_run_at',
    render: (row: TaskResponse) => fmtTs(row.next_run_at),
  },
]

const failedTaskColumns = [
  { title: t('tasks.id'), key: 'id', align: 'center' as const, width: 70 },
  {
    title: t('tasks.attempts'),
    key: 'attempt_count',
    align: 'center' as const,
    width: 100,
    render: (row: TaskResponse) => `${row.attempt_count} / ${row.max_attempts}`,
  },
  {
    title: t('tasks.error'),
    key: 'last_error',
    ellipsis: { tooltip: true },
    render: (row: TaskResponse) => truncateError(row.last_error),
  },
  { title: t('tasks.finished'), key: 'finished_at', render: (row: TaskResponse) => fmtTs(row.finished_at) },
  {
    title: t('tasks.actions'),
    key: 'actions',
    align: 'center' as const,
    width: 100,
    render: (row: TaskResponse) =>
      h(NButton, {
        size: 'small',
        type: 'warning',
        loading: retryingTaskId.value === row.id,
        disabled: retryingTaskId.value !== null,
        onClick: () => retryTask(row.id),
      }, { default: () => t('tasks.retry') }),
  },
]

// ── Watchers ──────────────────────────────────────────────────────────────────
function onFailedTaskSelect(id: number | null) {
  failedTaskId.value = id
  if (id !== null) {
    fetchFailedTaskDetail(id)
  } else {
    fullFailedTask.value = null
  }
}

function onTaskDetailSelect(id: number | null) {
  selectedTaskId.value = id
  if (id !== null) {
    fetchTaskDetail(id)
  } else {
    fullTaskDetail.value = null
  }
}

// ── Filter Options ────────────────────────────────────────────────────────────
const statusOptions = [
  { label: t('tasks.queued'), value: 'queued' },
  { label: t('tasks.running'), value: 'running' },
  { label: t('tasks.succeeded'), value: 'succeeded' },
  { label: t('tasks.failed'), value: 'failed' },
]

const limitOptions = [
  { label: '10', value: 10 },
  { label: '20', value: 20 },
  { label: '50', value: 50 },
  { label: '100', value: 100 },
]

const taskTypeOptions = [
  { label: t('tasks.provisionNode'), value: 'provision_node' },
  { label: t('tasks.forceHeal'), value: 'force_heal' },
  { label: t('tasks.decommissionNode'), value: 'decommission_node' },
  { label: t('tasks.reprobeNode'), value: 'reprobe_node' },
  { label: t('tasks.manualReview'), value: 'mark_manual_review' },
]

// ── Lifecycle ─────────────────────────────────────────────────────────────────
const { connect, disconnect, connected: sseConnected } = useSSE({
  onTaskCreated: () => fetchTasks(),
  onTaskStatusChanged: () => fetchTasks(),
})

onMounted(() => {
  fetchTasks()
  refreshTimer = setInterval(fetchTasks, 15_000)
  connect()
})

onUnmounted(() => {
  if (refreshTimer !== null) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  disconnect()
})
</script>

<template>
  <div style="padding: 16px; max-width: 1400px; margin: 0 auto">
    <!-- SSE status indicator -->
    <div style="position: fixed; top: 16px; right: 16px; z-index: 1000">
      <NTag :type="sseConnected ? 'success' : 'warning'" size="small">
        {{ sseConnected ? t('fleet.sseConnected') : t('fleet.sseDisconnected') }}
      </NTag>
    </div>

    <NSpin :show="loading" :description="t('tasks.loadingTasks')">
      <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px" closable @close="errorMsg = null" />

      <!-- ── Stat Cards ──────────────────────────────────────────────────────── -->
      <NCard style="margin-bottom: 16px">
        <NGrid :cols="5" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
          <NGi span="1">
            <NStatistic :label="t('tasks.total')" :value="totalCount" />
          </NGi>
          <NGi span="1">
            <NStatistic :label="t('tasks.queued')" :value="queuedCount" />
          </NGi>
          <NGi span="1">
            <NStatistic :label="t('tasks.running')" :value="runningCount" />
          </NGi>
          <NGi span="1">
            <NStatistic :label="t('tasks.succeeded')" :value="succeededCount" />
          </NGi>
          <NGi span="1">
            <NStatistic :label="t('tasks.failed')" :value="failedCount" />
          </NGi>
        </NGrid>
      </NCard>

      <!-- ── Tabs ───────────────────────────────────────────────────────────── -->
      <NCard>
        <NTabs type="line" animated>
          <!-- Tab 1: Task List -->
          <NTab name="list" :title="t('tasks.taskList')">
            <div style="margin-bottom: 12px">
              <NSpace>
                <NSelect v-model:value="filterStatus" :options="statusOptions" :placeholder="t('tasks.status')" clearable style="width: 140px" />
                <NSelect v-model:value="filterTaskType" :options="taskTypeOptions" :placeholder="t('tasks.taskType')" clearable style="width: 160px" />
                <NSelect v-model:value="filterLimit" :options="limitOptions" :placeholder="t('tasks.limit')" style="width: 100px" />
              </NSpace>
            </div>
            <NDataTable
              :columns="allTaskColumns"
              :data="filteredTasks"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 15 }"
            />
            <NEmpty v-if="filteredTasks.length === 0 && !loading" :description="t('tasks.noTasks')" style="margin-top: 24px" />
          </NTab>

          <!-- Tab 2: Running Tasks -->
          <NTab name="running" :title="t('tasks.runningTasks')">
            <NAlert v-if="runningCount > 0" type="warning" :title="t('tasks.runningTaskWarning')" style="margin-bottom: 12px">
              {{ t('tasks.runningTaskDesc') }}
            </NAlert>
            <NDataTable
              :columns="runningTaskColumns"
              :data="runningTasks"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 15 }"
            />
            <NEmpty v-if="runningTasks.length === 0 && !loading" :description="t('tasks.noRunningTasks')" style="margin-top: 24px" />
          </NTab>

          <!-- Tab 3: Failed Tasks -->
          <NTab name="failed" :title="t('tasks.failedTasks')">
            <NAlert v-if="failedCount > 0" type="error" :title="t('tasks.hasFailedTasks')" style="margin-bottom: 12px" />
            <NDataTable
              :columns="failedTaskColumns"
              :data="failedTasks"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 15 }"
            />
            <NEmpty v-if="failedTasks.length === 0 && !loading" :description="t('tasks.noFailedTasks')" style="margin-top: 24px" />

            <!-- Failed Task Detail -->
            <template v-if="failedTasks.length > 0">
              <NDivider />
              <h4 style="margin: 0 0 12px; font-weight: 600">{{ t('tasks.viewFailedDetail') }}</h4>
              <NSelect
                :value="failedTaskId"
                :options="taskOptions.filter(o => failedTasks.some(t => t.id === o.value))"
                :placeholder="t('tasks.selectFailedTask')"
                clearable
                @update:value="onFailedTaskSelect"
                style="margin-bottom: 12px; max-width: 400px"
              />
              <template v-if="fullFailedTask">
                <NAlert v-if="fullFailedTask.last_error" type="error" :title="fullFailedTask.last_error" />
              </template>
            </template>
          </NTab>

          <!-- Tab 4: Task Detail -->
          <NTab name="detail" :title="t('tasks.taskDetail')">
            <NSelect
              :value="selectedTaskId"
              :options="taskOptions"
              :placeholder="t('tasks.selectTask')"
              clearable
              @update:value="onTaskDetailSelect"
              style="margin-bottom: 16px; max-width: 400px"
            />
            <NSpin :show="loadingDetail">
              <template v-if="fullTaskDetail">
                <!-- Metrics -->
                <NCard :title="t('tasks.basicInfo')" style="margin-bottom: 12px">
                  <NGrid :cols="4" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
                    <NGi span="1">
                      <NStatistic label="ID" :value="fullTaskDetail.id" />
                    </NGi>
                    <NGi span="1">
                      <NStatistic :label="t('tasks.taskType')" :value="taskTypeLabel(fullTaskDetail.task_type)" />
                    </NGi>
                    <NGi span="1">
                      <NStatistic :label="t('tasks.status')">
                        <template #default>
                          <NTag :type="statusTagType(fullTaskDetail.status)" size="small">
                            {{ fullTaskDetail.status }}
                          </NTag>
                        </template>
                      </NStatistic>
                    </NGi>
                    <NGi span="1">
                      <NStatistic :label="t('tasks.attempts')" :value="`${fullTaskDetail.attempt_count} / ${fullTaskDetail.max_attempts}`" />
                    </NGi>
                    <NGi span="1">
                      <NStatistic :label="t('tasks.created')" :value="fmtTs(fullTaskDetail.created_at)" />
                    </NGi>
                    <NGi span="1">
                      <NStatistic :label="t('tasks.started')" :value="fmtTs(fullTaskDetail.started_at)" />
                    </NGi>
                    <NGi span="1">
                      <NStatistic :label="t('tasks.finished')" :value="fmtTs(fullTaskDetail.finished_at)" />
                    </NGi>
                    <NGi span="1">
                      <NStatistic :label="t('tasks.lockedBy')" :value="fullTaskDetail.locked_by ?? '—'" />
                    </NGi>
                  </NGrid>
                </NCard>

                <!-- Correlation ID -->
                <NCard :title="t('tasks.correlationId')" style="margin-bottom: 12px">
                  <NCode :code="fullTaskDetail.correlation_id" language="text" word-wrap />
                </NCard>

                <!-- Error Section -->
                <NCard v-if="fullTaskDetail.last_error" :title="t('tasks.error')" style="margin-bottom: 12px">
                  <NAlert type="error" :title="fullTaskDetail.last_error" />
                </NCard>

                <!-- Execution Timeline -->
                <NCard :title="t('tasks.executionTimeline')" style="margin-bottom: 12px">
                  <ul style="margin: 0; padding-left: 20px">
                    <li><strong>{{ t('tasks.created') }}:</strong> {{ fmtTs(fullTaskDetail.created_at) }}</li>
                    <li><strong>{{ t('tasks.startedExecution') }}:</strong> {{ fmtTs(fullTaskDetail.started_at) }}</li>
                    <li><strong>{{ t('tasks.finished') }}:</strong> {{ fmtTs(fullTaskDetail.finished_at) }}</li>
                  </ul>
                </NCard>

                <!-- Raw JSON -->
                <NCard :title="t('tasks.rawJson')">
                  <NCollapse>
                    <NCollapseItem :title="t('tasks.viewRawTask')" name="raw">
                      <NCode :code="JSON.stringify(fullTaskDetail, null, 2)" language="json" word-wrap />
                    </NCollapseItem>
                  </NCollapse>
                </NCard>
              </template>
              <NEmpty v-else-if="!loadingDetail && selectedTaskId === null" :description="t('tasks.noTaskSelected')" />
            </NSpin>
          </NTab>
        </NTabs>
      </NCard>
    </NSpin>
  </div>
</template>
