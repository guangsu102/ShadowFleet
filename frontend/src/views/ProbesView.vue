<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import {
  NDataTable,
  NTag,
  NSpin,
  NAlert,
  NButton,
  NSpace,
  NText,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NCode,
  NEmpty,
  NPopconfirm,
  useMessage,
  useDialog,
} from 'naive-ui'
import type { SelectOption, DataTableColumns } from 'naive-ui'
import apiClient from '@/api/client'
import { t as i18n } from '@/composables/useI18n'
import type { ProbeResponse, ProbeTokenResponse, ProbeStatusUpdateRequest } from '@/types/api'

// ── Helpers ────────────────────────────────────────────────────────────────────
function statusTagType(status: string): 'success' | 'error' | 'warning' | 'info' | 'default' {
  switch (status) {
    case 'active':   return 'success'
    case 'offline':  return 'error'
    case 'disabled': return 'warning'
    default:         return 'default'
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

function maskToken(token: string): string {
  if (token.length <= 16) return token.slice(0, 4) + '...' + token.slice(-4)
  return token.slice(0, 8) + '...' + token.slice(-4)
}

// ── State ──────────────────────────────────────────────────────────────────────
const message = useMessage()
const dialog = useDialog()

const probes = ref<ProbeResponse[]>([])
const tokens = ref<ProbeTokenResponse[]>([])
const loading = ref(true)
const tokensLoading = ref(true)
const errorMsg = ref<string | null>(null)
const actionLoading = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

// ── Filter ─────────────────────────────────────────────────────────────────────
type FilterTab = 'all' | 'active' | 'offline' | 'disabled'
const filterTab = ref<FilterTab>('all')
const searchQuery = ref<string>('')

const filteredProbes = computed(() => {
  let result = probes.value
  if (filterTab.value !== 'all') {
    result = result.filter(p => p.status === filterTab.value)
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    result = result.filter(
      p => p.probe_name.toLowerCase().includes(q) ||
           p.probe_id.toLowerCase().includes(q) ||
           (p.region?.toLowerCase().includes(q)) ||
           (p.isp?.toLowerCase().includes(q))
    )
  }
  return result
})

// ── Stats ──────────────────────────────────────────────────────────────────────
const stats = computed(() => ({
  total:   probes.value.length,
  active:  probes.value.filter(p => p.status === 'active').length,
  offline: probes.value.filter(p => p.status === 'offline').length,
  disabled:probes.value.filter(p => p.status === 'disabled').length,
}))

// ── Modal ──────────────────────────────────────────────────────────────────────
const showModal = ref(false)

function openModal() { showModal.value = true }
function closeModal() {
  showModal.value = false
  resetForm()
}

// ── Add Probe Form ──────────────────────────────────────────────────────────────
const probeForm = ref({
  probe_name: '',
  region: '',
  isp: '',
  tags: '',
  daemon_host: '',
})

const regionOptions: SelectOption[] = [
  'us-east-1','us-west-1','us-west-2','eu-west-1','eu-west-2',
  'eu-central-1','ap-northeast-1','ap-southeast-1','ap-southeast-2',
  'hk','tw','jp','kr','sg','de','uk','ca','au',
].map(r => ({ label: r, value: r }))

const registrationCommand = computed(() => {
  const name  = probeForm.value.probe_name || '<probe_name>'
  const region = probeForm.value.region   || '<region>'
  const isp   = probeForm.value.isp      || '<isp>'
  const tags  = probeForm.value.tags
    ? probeForm.value.tags.split(',').map(t => `"${t.trim()}"`).join(', ')
    : '"<tag1>", "<tag2>"'
  const host  = probeForm.value.daemon_host || '<your-daemon-host>'
  return [
    `curl -X POST http://${host}:8787/register \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d '{`,
    `    "probe_name": "${name}",`,
    `    "region": "${region}",`,
    `    "isp": "${isp}",`,
    `    "tags": [${tags}]`,
    `  }'`,
  ].join('\n')
})

function resetForm() {
  probeForm.value = { probe_name: '', region: '', isp: '', tags: '', daemon_host: '' }
}

// ── Token ──────────────────────────────────────────────────────────────────────
const showTokenModal = ref(false)
const newTokenNote = ref<string>('')
const generatingToken = ref(false)
const generatedToken = ref<string | null>(null)

function openTokenModal() { showTokenModal.value = true }
function closeTokenModal() {
  showTokenModal.value = false
  newTokenNote.value = ''
  generatedToken.value = null
}

async function generateToken() {
  generatingToken.value = true
  generatedToken.value = null
  try {
    const body = newTokenNote.value.trim() ? { note: newTokenNote.value.trim() } : {}
    const { data } = await apiClient.post<ProbeTokenResponse>('/probe-tokens', body)
    generatedToken.value = data.token
    await fetchTokens()
    message.success(i18n('probes.tokenGenerated'))
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string } } }
    message.error(e.response?.data?.error || e.response?.data?.message || i18n('probes.generationFailed'))
  } finally {
    generatingToken.value = false
  }
}

// ── Data fetching ──────────────────────────────────────────────────────────────
async function fetchProbes() {
  try {
    const { data } = await apiClient.get<ProbeResponse[]>('/probes')
    probes.value = data
    errorMsg.value = null
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    errorMsg.value = e.response?.data?.error || e.message || i18n('probes.loadFailed')
  } finally {
    loading.value = false
  }
}

async function fetchTokens() {
  tokensLoading.value = true
  try {
    const { data } = await apiClient.get<ProbeTokenResponse[]>('/probe-tokens')
    tokens.value = data
  } catch {
    // silently ignore
  } finally {
    tokensLoading.value = false
  }
}

// ── Actions ────────────────────────────────────────────────────────────────────
async function updateProbeStatus(probeId: string, newStatus: 'active' | 'disabled') {
  actionLoading.value = true
  try {
    const body: ProbeStatusUpdateRequest = { status: newStatus }
    await apiClient.put<ProbeResponse>(`/probes/${probeId}/status`, body)
    message.success(newStatus === 'active' ? i18n('probes.probeEnabled') : i18n('probes.probeDisabled'))
    await fetchProbes()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(e.response?.data?.error || e.message || i18n('probes.updateFailed'))
  } finally {
    actionLoading.value = false
  }
}

function confirmDelete(probe: ProbeResponse) {
  dialog.warning({
    title: i18n('probes.confirmDeleteTitle'),
    content: `${i18n('probes.confirmDeleteBody')} "${probe.probe_name}"?`,
    positiveText: i18n('probes.deleteProbe'),
    negativeText: i18n('app.cancel'),
    onPositiveClick: () => doDelete(probe),
  })
}

async function doDelete(probe: ProbeResponse) {
  try {
    await apiClient.delete(`/probes/${probe.probe_id}`)
    message.success(i18n('probes.probeDeleted'))
    await fetchProbes()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(e.response?.data?.error || e.message || i18n('probes.deleteFailed'))
  }
}

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success(i18n('probes.copiedSuccess'))
  } catch {
    message.error(i18n('probes.copyFailed'))
  }
}

// ── Table columns ──────────────────────────────────────────────────────────────
function buildColumns(): DataTableColumns<ProbeResponse> {
  return [
    { title: i18n('probes.probeId'), key: 'probe_id', width: 120, ellipsis: { tooltip: true } },
    { title: i18n('probes.name'), key: 'probe_name', ellipsis: { tooltip: true } },
    {
      title: i18n('probes.status'), key: 'status', width: 90,
      render: (row) => h(NTag, { type: statusTagType(row.status), size: 'small' },
        { default: () => row.status }),
    },
    { title: i18n('dashboard.region'), key: 'region', render: (r) => r.region ?? '—', width: 100 },
    { title: i18n('probes.isp'), key: 'isp', render: (r) => r.isp ?? '—', width: 100 },
    { title: i18n('probes.publicIp'), key: 'public_ip', render: (r) => r.public_ip ?? '—', ellipsis: { tooltip: true } },
    {
      title: i18n('probes.lastSeen'), key: 'last_seen_at', width: 160,
      render: (r) => fmtTs(r.last_seen_at),
    },
    {
      title: i18n('probes.tags'), key: 'tags',
      render: (r) => (r.tags ?? []).join(', ') || '—',
      ellipsis: { tooltip: true },
    },
    {
      title: i18n('dashboard.actions'), key: 'actions', width: 160, align: 'center',
      render: (row) =>
        h(NSpace, { size: 4, style: 'flex-wrap: nowrap' }, {
          default: () => [
            row.status === 'active' || row.status === 'offline'
              ? h(NButton, {
                  size: 'tiny', type: 'warning', quaternary: true,
                  loading: actionLoading.value,
                  onClick: (e: Event) => { e.stopPropagation(); updateProbeStatus(row.probe_id, 'disabled') },
                }, { default: () => i18n('probes.disable') })
              : row.status === 'disabled'
              ? h(NButton, {
                  size: 'tiny', type: 'success', quaternary: true,
                  loading: actionLoading.value,
                  onClick: (e: Event) => { e.stopPropagation(); updateProbeStatus(row.probe_id, 'active') },
                }, { default: () => i18n('probes.enable') })
              : null,
            h(NPopconfirm, {
              onPositiveClick: () => confirmDelete(row),
            }, {
              trigger: () => h(NButton, {
                size: 'tiny', type: 'error', quaternary: true,
              }, { default: () => i18n('app.delete') }),
              content: () => `${i18n('probes.confirmDeleteBody')} "${row.probe_name}"?`,
            }),
          ],
        }),
    },
  ]
}

const probeColumns = buildColumns()

// ── Token columns ──────────────────────────────────────────────────────────────
const tokenColumns: DataTableColumns<ProbeTokenResponse> = [
  { title: 'Token', key: 'token', render: (r) => maskToken(r.token) },
  { title: i18n('probes.note'), key: 'note', render: (r) => r.note ?? '—' },
  {
    title: i18n('probes.created'), key: 'created_at', width: 160,
    render: (r) => fmtTs(r.created_at),
  },
  {
    title: i18n('probes.expires'), key: 'expires_at', width: 160,
    render: (r) => r.expires_at ? fmtTs(r.expires_at) : '—',
  },
  {
    title: i18n('dashboard.actions'), key: 'actions', width: 80, align: 'center',
    render: (row) =>
      h(NButton, {
        size: 'small', quaternary: true,
        onClick: () => copyToClipboard(row.token),
      }, { default: () => i18n('probes.copy') }),
  },
]

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  fetchProbes()
  fetchTokens()
  pollTimer = setInterval(() => {
    fetchProbes()
    fetchTokens()
  }, 30_000)
})

onUnmounted(() => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <div class="probes-page">
    <!-- ── Header ──────────────────────────────────────────────────────────────── -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">{{ i18n('nav.probes') }}</h1>
        <p class="page-subtitle">{{ i18n('probes.headerDesc') }}</p>
      </div>
      <div class="header-right">
        <NButton type="primary" size="large" @click="openModal">
          <template #icon>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor">
              <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
            </svg>
          </template>
          {{ i18n('probes.newProbe') }}
        </NButton>
        <NButton size="large" @click="openTokenModal">
          <template #icon>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor">
              <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/>
            </svg>
          </template>
          {{ i18n('probes.manageTokens') }}
        </NButton>
      </div>
    </div>

    <!-- ── Summary Stats ──────────────────────────────────────────────────────── -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-label">{{ i18n('probes.total') }}</div>
      </div>
      <div class="stat-card stat-active">
        <div class="stat-value">{{ stats.active }}</div>
        <div class="stat-label">{{ i18n('probes.active') }}</div>
      </div>
      <div class="stat-card stat-offline">
        <div class="stat-value">{{ stats.offline }}</div>
        <div class="stat-label">{{ i18n('probes.offline') }}</div>
      </div>
      <div class="stat-card stat-disabled">
        <div class="stat-value">{{ stats.disabled }}</div>
        <div class="stat-label">{{ i18n('probes.disabled') }}</div>
      </div>
    </div>

    <!-- ── Table Card ─────────────────────────────────────────────────────────── -->
    <div class="table-card">
      <NSpin :show="loading" :description="i18n('probes.loadingProbes')">
        <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px"
          closable @close="errorMsg = null" />

        <!-- ── Filter Tab Bar ────────────────────────────────────────────────── -->
        <div class="tab-bar">
          <button
            class="tab-btn"
            :class="{ active: filterTab === 'all' }"
            @click="filterTab = 'all'"
          >
            {{ i18n('app.all') }}
            <span class="tab-badge" :class="{ 'tab-badge-active': filterTab === 'all' }">
              {{ stats.total }}
            </span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: filterTab === 'active' }"
            @click="filterTab = 'active'"
          >
            {{ i18n('probes.active') }}
            <span class="tab-badge tab-badge-active-status">
              {{ stats.active }}
            </span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: filterTab === 'offline' }"
            @click="filterTab = 'offline'"
          >
            {{ i18n('probes.offline') }}
            <span class="tab-badge tab-badge-offline">
              {{ stats.offline }}
            </span>
          </button>
          <button
            class="tab-btn"
            :class="{ active: filterTab === 'disabled' }"
            @click="filterTab = 'disabled'"
          >
            {{ i18n('probes.disabled') }}
            <span class="tab-badge tab-badge-disabled">
              {{ stats.disabled }}
            </span>
          </button>

          <!-- Search box on the right -->
          <div class="tab-search">
            <NInput
              v-model:value="searchQuery"
              :placeholder="i18n('probes.searchNameId')"
              clearable
              size="small"
              style="width: 200px"
            >
              <template #prefix>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" style="width:14px;height:14px;fill:#a1a1aa">
                  <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
                </svg>
              </template>
            </NInput>
          </div>
        </div>

        <!-- ── Data Table ────────────────────────────────────────────────────── -->
        <NDataTable
          :columns="probeColumns"
          :data="filteredProbes"
          :bordered="false"
          :single-line="false"
          size="small"
          :pagination="{ pageSize: 15 }"
          :row-key="(row: ProbeResponse) => row.probe_id"
          class="probes-table"
        />

        <NText depth="3" style="font-size: 12px; display: block; margin-top: 8px; text-align: right">
          {{ i18n('probes.totalProbes', { count: filteredProbes.length }) }}
        </NText>
      </NSpin>
    </div>

    <!-- ── Add Probe Modal ────────────────────────────────────────────────────── -->
    <NModal
      v-model:show="showModal"
      preset="card"
      class="probe-modal"
      :style="{ width: '700px', maxWidth: '95vw' }"
      :title="i18n('probes.newProbe')"
      :mask-closable="false"
      :segmented="{ content: true, footer: 'soft' }"
    >
      <div class="modal-form">
        <NAlert type="info" :title="i18n('probes.modalAlertTitle')" style="margin-bottom: 20px">
          <NText depth="3">{{ i18n('probes.modalAlertNote') }}</NText>
        </NAlert>

        <NForm label-placement="left" label-width="140" size="medium">
          <NFormItem :label="i18n('probes.name')" required>
            <NInput v-model:value="probeForm.probe_name" :placeholder="i18n('probes.namePlaceholder')" />
          </NFormItem>

          <NFormItem :label="i18n('dashboard.region')">
            <NSelect
              v-model:value="probeForm.region"
              :options="regionOptions"
              :placeholder="i18n('probes.regionPlaceholder')"
              filterable
              clearable
            />
          </NFormItem>

          <NFormItem :label="i18n('probes.isp')">
            <NInput v-model:value="probeForm.isp" :placeholder="i18n('probes.ispPlaceholder')" />
          </NFormItem>

          <NFormItem :label="i18n('probes.tags')">
            <NInput v-model:value="probeForm.tags" :placeholder="i18n('probes.tagsPlaceholder')" />
          </NFormItem>

          <NFormItem :label="i18n('probes.daemonHost')">
            <NInput v-model:value="probeForm.daemon_host" :placeholder="i18n('probes.daemonHostPlaceholder')" />
          </NFormItem>
        </NForm>

        <div class="reg-command-section">
          <NText depth="3" style="font-size: 13px; display: block; margin-bottom: 8px">
            {{ i18n('probes.registrationCommand') }}
          </NText>
          <div class="reg-command-box">
            <NCode :code="registrationCommand" language="bash" style="font-size: 12px" />
            <NButton
              size="tiny"
              style="position: absolute; top: 8px; right: 8px"
              @click="copyToClipboard(registrationCommand)"
            >
              {{ i18n('app.copy') }}
            </NButton>
          </div>
          <NText depth="3" style="font-size: 12px; display: block; margin-top: 6px">
            {{ i18n('probes.commandHint') }}
          </NText>
        </div>

        <div class="modal-footer">
          <NSpace>
            <NButton @click="closeModal">{{ i18n('app.cancel') }}</NButton>
            <NButton type="primary" @click="closeModal">
              {{ i18n('app.close') }}
            </NButton>
          </NSpace>
        </div>
      </div>
    </NModal>

    <!-- ── Token Management Modal ─────────────────────────────────────────────── -->
    <NModal
      v-model:show="showTokenModal"
      preset="card"
      class="probe-modal"
      :style="{ width: '700px', maxWidth: '95vw' }"
      :title="i18n('probes.manageTokens')"
      :mask-closable="false"
      :segmented="{ content: true, footer: 'soft' }"
    >
      <div class="modal-form">
        <NAlert type="warning" :title="i18n('probes.securityWarning')" style="margin-bottom: 20px">
          <NText depth="3">{{ i18n('probes.tokenSecurityNote') }}</NText>
        </NAlert>

        <!-- Generate new token -->
        <NCard :title="i18n('probes.generateNewToken')" size="small" style="margin-bottom: 16px">
          <NSpace vertical>
            <NInput
              v-model:value="newTokenNote"
              :placeholder="i18n('probes.tokenNotePlaceholder')"
              style="width: 400px"
            />
            <NButton
              type="primary"
              :loading="generatingToken"
              @click="generateToken"
            >
              {{ i18n('probes.createToken') }}
            </NButton>
          </NSpace>
        </NCard>

        <!-- Show newly generated token -->
        <NCard v-if="generatedToken" :title="i18n('probes.newToken')" size="small" style="margin-bottom: 16px">
          <div class="generated-token-row">
            <NCode :code="generatedToken" language="text" style="font-size: 13px; flex: 1; max-width: 500px; word-break: break-all" />
            <NButton size="small" type="primary" @click="copyToClipboard(generatedToken!)">
              {{ i18n('app.copy') }}
            </NButton>
          </div>
          <NText depth="3" style="font-size: 12px; display: block; margin-top: 8px">
            {{ i18n('probes.copyNowHint') }}
          </NText>
        </NCard>

        <!-- Existing tokens table -->
        <NCard :title="i18n('probes.existingTokens')" size="small">
          <NSpin :show="tokensLoading">
            <NDataTable
              v-if="tokens.length > 0"
              :columns="tokenColumns"
              :data="tokens"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="false"
            />
            <NEmpty v-else :description="i18n('probes.noTokens')" />
          </NSpin>
        </NCard>

        <div class="modal-footer">
          <NButton @click="closeTokenModal">{{ i18n('app.close') }}</NButton>
        </div>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
/* ── Page Layout ────────────────────────────────────────────────────────────── */
.probes-page {
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
  display: flex;
  gap: 8px;
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

.stat-active   .stat-value { color: #10b981; }
.stat-offline  .stat-value { color: #ef4444; }
.stat-disabled .stat-value { color: #f59e0b; }

/* ── Table Card ─────────────────────────────────────────────────────────────── */
.table-card {
  background: white;
  border-radius: 14px;
  border: 1px solid var(--n-border-color, #e5e7eb);
  padding: 20px 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

/* ── Tab Bar ────────────────────────────────────────────────────────────────── */
.tab-bar {
  display: flex;
  align-items: center;
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

.tab-badge-active-status { background: rgba(16, 185, 129, 0.1); color: #10b981; }
.tab-badge-offline       { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
.tab-badge-disabled      { background: rgba(245, 158, 11, 0.1); color: #f59e0b; }

.tab-search {
  margin-left: auto;
  margin-bottom: -1px;
}

/* ── Table ──────────────────────────────────────────────────────────────────── */
.probes-table {
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

/* ── Registration Command ──────────────────────────────────────────────────── */
.reg-command-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed var(--n-border-color, #e5e7eb);
}

.reg-command-box {
  position: relative;
  background: #1e1e1e;
  border-radius: 8px;
  padding: 12px 16px;
}

/* ── Generated Token ────────────────────────────────────────────────────────── */
.generated-token-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
</style>
