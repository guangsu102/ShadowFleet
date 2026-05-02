<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import {
  NDataTable,
  NTabs,
  NTab,
  NTag,
  NSpin,
  NAlert,
  NSelect,
  NCode,
  NCollapse,
  NCollapseItem,
  NEmpty,
  NButton,
  NSpace,
  NDivider,
  NThing,
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

function statusLabel(status: string): string {
  switch (status) {
    case 'queued': return t('tasks.queued')
    case 'running': return t('tasks.running')
    case 'succeeded': return t('tasks.succeeded')
    case 'failed': return t('tasks.failed')
    default: return status
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
  {
    title: t('tasks.taskType'),
    key: 'task_type',
    width: 150,
    render: (row: TaskResponse) => taskTypeLabel(row.task_type),
  },
  {
    title: t('tasks.status'),
    key: 'status',
    width: 100,
    align: 'center' as const,
    render: (row: TaskResponse) => h(NTag, { type: statusTagType(row.status), size: 'small' }, { default: () => statusLabel(row.status) }),
  },
  {
    title: t('tasks.attempts'),
    key: 'attempt_count',
    align: 'center' as const,
    width: 100,
    render: (row: TaskResponse) => `${row.attempt_count} / ${row.max_attempts}`,
  },
  { title: t('tasks.created'), key: 'created_at', width: 170, render: (row: TaskResponse) => fmtTs(row.created_at) },
  { title: t('tasks.started'), key: 'started_at', width: 170, render: (row: TaskResponse) => fmtTs(row.started_at) },
  { title: t('tasks.finished'), key: 'finished_at', width: 170, render: (row: TaskResponse) => fmtTs(row.finished_at) },
  {
    title: t('tasks.lockedBy'),
    key: 'locked_by',
    width: 120,
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
  { title: t('tasks.started'), key: 'started_at', width: 170, render: (row: TaskResponse) => fmtTs(row.started_at) },
  { title: t('tasks.lockedBy'), key: 'locked_by', width: 120, ellipsis: { tooltip: true } },
  {
    title: t('tasks.nextRun'),
    key: 'next_run_at',
    width: 170,
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
    width: 200,
    ellipsis: { tooltip: true },
    render: (row: TaskResponse) => truncateError(row.last_error),
  },
  { title: t('tasks.finished'), key: 'finished_at', width: 170, render: (row: TaskResponse) => fmtTs(row.finished_at) },
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
  <div class="dashboard-page">
    <!-- ── Page Header ──────────────────────────────────────────────────────── -->
    <div class="dashboard-header">
      <div class="dashboard-header-left">
        <div class="dashboard-header-icon">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>
        </div>
        <div class="dashboard-header-title">
          <h1>{{ t('nav.tasks') }}</h1>
          <p>{{ t('tasks.pageDesc') || '任务列表、实时状态监控、失败重试' }}</p>
        </div>
      </div>
      <div class="dashboard-header-actions">
        <div class="refresh-badge">
          <span class="refresh-badge-dot" :style="{ background: sseConnected ? 'var(--sf-green)' : 'var(--sf-orange)' }"></span>
          {{ sseConnected ? t('fleet.sseConnected') : t('fleet.sseDisconnected') }}
        </div>
      </div>
    </div>

    <NSpin :show="loading" :description="t('tasks.loadingTasks')">
      <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px" closable @close="errorMsg = null" />

      <!-- ── Metric Cards ─────────────────────────────────────────────────────── -->
      <div class="metrics-grid">
        <div class="metric-card metric-card-gray">
          <div class="metric-card-icon metric-card-icon-gray">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>
          </div>
          <div class="metric-card-label">{{ t('tasks.total') }}</div>
          <div class="metric-card-value">{{ totalCount }}</div>
        </div>
        <div class="metric-card metric-card-blue">
          <div class="metric-card-icon metric-card-icon-blue">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>
          </div>
          <div class="metric-card-label">{{ t('tasks.queued') }}</div>
          <div class="metric-card-value small">{{ queuedCount }}</div>
        </div>
        <div class="metric-card metric-card-orange">
          <div class="metric-card-icon metric-card-icon-orange">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0020 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 004 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/></svg>
          </div>
          <div class="metric-card-label">{{ t('tasks.running') }}</div>
          <div class="metric-card-value small">{{ runningCount }}</div>
        </div>
        <div class="metric-card metric-card-green">
          <div class="metric-card-icon metric-card-icon-green">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
          </div>
          <div class="metric-card-label">{{ t('tasks.succeeded') }}</div>
          <div class="metric-card-value small">{{ succeededCount }}</div>
        </div>
        <div class="metric-card metric-card-red">
          <div class="metric-card-icon metric-card-icon-red">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
          </div>
          <div class="metric-card-label">{{ t('tasks.failed') }}</div>
          <div class="metric-card-value small">{{ failedCount }}</div>
        </div>
      </div>

      <!-- ── Tabs ───────────────────────────────────────────────────────────── -->
      <div class="dashboard-card" style="padding: 0;">
        <NTabs type="line" animated style="padding: 0 20px">
          <!-- Tab 1: Task List -->
          <NTab name="list" :title="t('tasks.taskList')">
            <div style="padding: 16px 0 0">
              <div style="margin-bottom: 12px">
                <NSpace>
                  <NSelect v-model:value="filterStatus" :options="statusOptions" :placeholder="t('tasks.status')" clearable style="width: 140px" />
                  <NSelect v-model:value="filterTaskType" :options="taskTypeOptions" :placeholder="t('tasks.taskType')" clearable style="width: 160px" />
                  <NSelect v-model:value="filterLimit" :options="limitOptions" :placeholder="t('tasks.limit')" style="width: 100px" />
                </NSpace>
              </div>
              <div class="dashboard-table">
                <NDataTable
                  :columns="allTaskColumns"
                  :data="filteredTasks"
                  :bordered="false"
                  :single-line="false"
                  size="small"
                  :pagination="{ pageSize: 15 }"
                />
              </div>
              <NEmpty v-if="filteredTasks.length === 0 && !loading" :description="t('tasks.noTasks')" style="margin-top: 24px" />
            </div>
          </NTab>

          <!-- Tab 2: Running Tasks -->
          <NTab name="running" :title="t('tasks.runningTasks')">
            <div style="padding: 16px 0 0">
              <NAlert v-if="runningCount > 0" type="warning" :title="t('tasks.runningTaskWarning')" style="margin-bottom: 12px">
                {{ t('tasks.runningTaskDesc') }}
              </NAlert>
              <div class="dashboard-table">
                <NDataTable
                  :columns="runningTaskColumns"
                  :data="runningTasks"
                  :bordered="false"
                  :single-line="false"
                  size="small"
                  :pagination="{ pageSize: 15 }"
                />
              </div>
              <NEmpty v-if="runningTasks.length === 0 && !loading" :description="t('tasks.noRunningTasks')" style="margin-top: 24px" />
            </div>
          </NTab>

          <!-- Tab 3: Failed Tasks -->
          <NTab name="failed" :title="t('tasks.failedTasks')">
            <div style="padding: 16px 0 0">
              <NAlert v-if="failedCount > 0" type="error" :title="t('tasks.hasFailedTasks')" style="margin-bottom: 12px" />
              <div class="dashboard-table">
                <NDataTable
                  :columns="failedTaskColumns"
                  :data="failedTasks"
                  :bordered="false"
                  :single-line="false"
                  size="small"
                  :pagination="{ pageSize: 15 }"
                />
              </div>
              <NEmpty v-if="failedTasks.length === 0 && !loading" :description="t('tasks.noFailedTasks')" style="margin-top: 24px" />

              <!-- Failed Task Detail -->
              <template v-if="failedTasks.length > 0">
                <NDivider />
                <div class="dashboard-section-header">
                  <div class="dashboard-section-icon" style="background: var(--sf-red-bg); color: var(--sf-red)">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                  </div>
                  <span class="dashboard-section-title">{{ t('tasks.viewFailedDetail') }}</span>
                </div>
                <NSelect
                  :value="failedTaskId"
                  :options="taskOptions.filter(o => failedTasks.some(t => t.id === o.value))"
                  :placeholder="t('tasks.selectFailedTask')"
                  clearable
                  @update:value="onFailedTaskSelect"
                  style="margin-bottom: 16px; max-width: 400px"
                />
                <template v-if="fullFailedTask">
                  <div class="detail-info-grid">
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.id') }}</span>
                      <span class="detail-info-value">#{{ fullFailedTask.id }}</span>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.taskType') }}</span>
                      <span class="detail-info-value">{{ taskTypeLabel(fullFailedTask.task_type) }}</span>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.attempts') }}</span>
                      <span class="detail-info-value">{{ fullFailedTask.attempt_count }} / {{ fullFailedTask.max_attempts }}</span>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.finished') }}</span>
                      <span class="detail-info-value">{{ fmtTs(fullFailedTask.finished_at) }}</span>
                    </div>
                  </div>
                  <NAlert v-if="fullFailedTask.last_error" type="error" :title="fullFailedTask.last_error" style="margin-top: 12px" />
                  <div style="margin-top: 12px">
                    <span class="detail-info-label" style="display: block; margin-bottom: 4px">{{ t('tasks.correlationId') }}</span>
                    <NCode :code="fullFailedTask.correlation_id" language="text" word-wrap style="border-radius: 6px; padding: 8px 12px; background: #f8fafc; border: 1px solid var(--sf-border); font-size: 12px;" />
                  </div>
                </template>
              </template>
            </div>
          </NTab>

          <!-- Tab 4: Task Detail -->
          <NTab name="detail" :title="t('tasks.taskDetail')">
            <div style="padding: 16px 0 0">
              <NSelect
                :value="selectedTaskId"
                :options="taskOptions"
                :placeholder="t('tasks.selectTask')"
                clearable
                @update:value="onTaskDetailSelect"
                style="margin-bottom: 20px; max-width: 400px"
              />
              <NSpin :show="loadingDetail">
                <template v-if="fullTaskDetail">
                  <!-- Basic Info -->
                  <div class="dashboard-section-header">
                    <div class="dashboard-section-icon" style="background: var(--sf-blue-bg); color: var(--sf-blue)">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
                    </div>
                    <span class="dashboard-section-title">{{ t('tasks.basicInfo') }}</span>
                  </div>
                  <div class="detail-info-grid">
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.id') }}</span>
                      <span class="detail-info-value">#{{ fullTaskDetail.id }}</span>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.taskType') }}</span>
                      <span class="detail-info-value">{{ taskTypeLabel(fullTaskDetail.task_type) }}</span>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.status') }}</span>
                      <NTag :type="statusTagType(fullTaskDetail.status)" size="small">{{ statusLabel(fullTaskDetail.status) }}</NTag>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.attempts') }}</span>
                      <span class="detail-info-value">{{ fullTaskDetail.attempt_count }} / {{ fullTaskDetail.max_attempts }}</span>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.created') }}</span>
                      <span class="detail-info-value">{{ fmtTs(fullTaskDetail.created_at) }}</span>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.started') }}</span>
                      <span class="detail-info-value">{{ fmtTs(fullTaskDetail.started_at) }}</span>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.finished') }}</span>
                      <span class="detail-info-value">{{ fmtTs(fullTaskDetail.finished_at) }}</span>
                    </div>
                    <div class="detail-info-item">
                      <span class="detail-info-label">{{ t('tasks.lockedBy') }}</span>
                      <span class="detail-info-value">{{ fullTaskDetail.locked_by ?? '—' }}</span>
                    </div>
                  </div>

                  <!-- Correlation ID -->
                  <div class="dashboard-section-header" style="margin-top: 20px">
                    <div class="dashboard-section-icon" style="background: var(--sf-purple-bg); color: var(--sf-purple)">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M15 9H9v6h6V9zm-2 4h-2v-2h2v2zm8-2V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2zm-4 6H7V7h10v10z"/></svg>
                    </div>
                    <span class="dashboard-section-title">{{ t('tasks.correlationId') }}</span>
                  </div>
                  <NCode :code="fullTaskDetail.correlation_id" language="text" word-wrap style="border-radius: 6px; padding: 10px 14px; background: #f8fafc; border: 1px solid var(--sf-border); font-size: 12px; margin-bottom: 20px" />

                  <!-- Error -->
                  <template v-if="fullTaskDetail.last_error">
                    <div class="dashboard-section-header">
                      <div class="dashboard-section-icon" style="background: var(--sf-red-bg); color: var(--sf-red)">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                      </div>
                      <span class="dashboard-section-title">{{ t('tasks.error') }}</span>
                    </div>
                    <NAlert type="error" :title="fullTaskDetail.last_error" style="margin-bottom: 20px" />
                  </template>

                  <!-- Execution Timeline -->
                  <div class="dashboard-section-header">
                    <div class="dashboard-section-icon" style="background: var(--sf-green-bg); color: var(--sf-green)">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>
                    </div>
                    <span class="dashboard-section-title">{{ t('tasks.executionTimeline') }}</span>
                  </div>
                  <NThing v-if="fullTaskDetail.created_at" title-prefix="bar">{{ t('tasks.created') }}: {{ fmtTs(fullTaskDetail.created_at) }}</NThing>
                  <NThing v-if="fullTaskDetail.started_at" title-prefix="bar">{{ t('tasks.startedExecution') }}: {{ fmtTs(fullTaskDetail.started_at) }}</NThing>
                  <NThing v-if="fullTaskDetail.finished_at" title-prefix="bar">{{ t('tasks.finished') }}: {{ fmtTs(fullTaskDetail.finished_at) }}</NThing>

                  <!-- Raw JSON -->
                  <div class="dashboard-section-header" style="margin-top: 20px">
                    <div class="dashboard-section-icon" style="background: #f1f5f9; color: #64748b">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z"/></svg>
                    </div>
                    <span class="dashboard-section-title">{{ t('tasks.rawJson') }}</span>
                  </div>
                  <NCollapse>
                    <NCollapseItem :title="t('tasks.viewRawTask')" name="raw">
                      <NCode :code="JSON.stringify(fullTaskDetail, null, 2)" language="json" word-wrap />
                    </NCollapseItem>
                  </NCollapse>
                </template>
                <NEmpty v-else-if="!loadingDetail && selectedTaskId === null" :description="t('tasks.noTaskSelected')" />
              </NSpin>
            </div>
          </NTab>
        </NTabs>
      </div>
    </NSpin>
  </div>
</template>

<style scoped>
.detail-info-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 4px;
}

.detail-info-item {
  background: #f8fafc;
  border: 1px solid var(--sf-border);
  border-radius: var(--sf-radius-sm);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-info-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--sf-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.detail-info-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--sf-text);
}

@media (max-width: 1100px) {
  .detail-info-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .detail-info-grid {
    grid-template-columns: 1fr;
  }
}

/* ── Metrics Grid ──────────────────────────────────────────────────────────── */
@media (max-width: 1100px) {
  .metrics-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 700px) {
  .metrics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 480px) {
  .metrics-grid {
    grid-template-columns: 1fr;
  }
}

</style>
