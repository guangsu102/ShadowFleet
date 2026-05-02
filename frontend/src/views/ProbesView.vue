<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import {
  NGrid,
  NGi,
  NStatistic,
  NDataTable,
  NTag,
  NSpin,
  NAlert,
  NCard,
  NTabs,
  NTab,
  NSelect,
  NInput,
  NButton,
  NSpace,
  NText,
  NCode,
  NEmpty,
  useMessage,
  useDialog,
} from 'naive-ui'
import apiClient from '@/api/client'
import { useI18n } from '@/composables/useI18n'
import type { ProbeResponse, ProbeTokenResponse, ProbeStatusUpdateRequest } from '@/types/api'

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()

const probes = ref<ProbeResponse[]>([])
const tokens = ref<ProbeTokenResponse[]>([])
const loading = ref(true)
const tokensLoading = ref(true)
const errorMsg = ref<string | null>(null)
const actionLoading = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

const statusFilter = ref<string | null>(null)
const regionFilter = ref<string>('')
const searchQuery = ref<string>('')

const selectedProbeId = ref<string | null>(null)

const newTokenNote = ref<string>('')
const generatingToken = ref(false)
const generatedToken = ref<string | null>(null)

const regProbeName = ref<string>('')
const regRegion = ref<string>('')
const regIsp = ref<string>('')
const regTags = ref<string>('')

const registrationCommand = computed(() => {
  const name = regProbeName.value || '<probe_name>'
  const region = regRegion.value || '<region>'
  const isp = regIsp.value || '<isp>'
  const tags = regTags.value
    ? regTags.value.split(',').map(t => `"${t.trim()}"`).join(', ')
    : '"<tag1>", "<tag2>"'
  return [
    t('probes.executeOnProbe'),
    `curl -X POST http://<your-daemon-host>:8787/register \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d '{`,
    `    "probe_name": "${name}",`,
    `    "region": "${region}",`,
    `    "isp": "${isp}",`,
    `    "tags": [${tags}]`,
    `  }'`,
  ].join('\n')
})

const statusOptions = [
  { label: t('probes.active'), value: 'active' },
  { label: t('probes.offline'), value: 'offline' },
  { label: t('probes.disabled'), value: 'disabled' },
  { label: t('probes.draining'), value: 'draining' },
]

const filteredProbes = computed(() => {
  let result = probes.value
  if (statusFilter.value) {
    result = result.filter((p) => p.status === statusFilter.value)
  }
  if (regionFilter.value.trim()) {
    const q = regionFilter.value.trim().toLowerCase()
    result = result.filter((p) => p.region?.toLowerCase().includes(q))
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    result = result.filter(
      (p) =>
        p.probe_name.toLowerCase().includes(q) ||
        p.probe_id.toLowerCase().includes(q)
    )
  }
  return result
})

const selectedProbe = computed(() =>
  probes.value.find((p) => p.probe_id === selectedProbeId.value) ?? null
)

const stats = computed(() => ({
  total: probes.value.length,
  active: probes.value.filter((p) => p.status === 'active').length,
  offline: probes.value.filter((p) => p.status === 'offline').length,
  disabled: probes.value.filter((p) => p.status === 'disabled').length,
}))

async function fetchProbes() {
  try {
    const { data } = await apiClient.get<ProbeResponse[]>('/probes')
    probes.value = data
    errorMsg.value = null
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    errorMsg.value = axiosErr.response?.data?.error || axiosErr.message || t('probes.loadFailed')
  } finally {
    loading.value = false
  }
}

async function fetchTokens() {
  try {
    const { data } = await apiClient.get<ProbeTokenResponse[]>('/probe-tokens')
    tokens.value = data
  } catch {
    tokensLoading.value = false
  } finally {
    tokensLoading.value = false
  }
}

async function updateProbeStatus(probeId: string, newStatus: 'active' | 'disabled') {
  actionLoading.value = true
  try {
    const body: ProbeStatusUpdateRequest = { status: newStatus }
    await apiClient.put<ProbeResponse>(`/probes/${probeId}/status`, body)
    message.success(newStatus === 'active' ? t('probes.probeEnabled') : t('probes.probeDisabled'))
    await fetchProbes()
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('probes.updateFailed'))
  } finally {
    actionLoading.value = false
  }
}

async function generateToken() {
  generatingToken.value = true
  generatedToken.value = null
  try {
    const body = newTokenNote.value.trim() ? { note: newTokenNote.value.trim() } : {}
    const { data } = await apiClient.post<ProbeTokenResponse>('/probe-tokens', body)
    generatedToken.value = data.token
    await fetchTokens()
    newTokenNote.value = ''
    message.success(t('probes.tokenGenerated'))
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { error?: string; message?: string } }; message?: string }
    message.error(axiosErr.response?.data?.error || axiosErr.message || t('probes.generationFailed'))
  } finally {
    generatingToken.value = false
  }
}

function confirmDisable(probe: ProbeResponse) {
  dialog.warning({
    title: t('probes.confirmDisableTitle'),
    content: `${t('probes.confirmDisableBody')} "${probe.probe_name}"?`,
    positiveText: t('probes.disableProbe'),
    negativeText: t('app.cancel'),
    onPositiveClick: () => updateProbeStatus(probe.probe_id, 'disabled'),
  })
}

function confirmEnable(probe: ProbeResponse) {
  dialog.warning({
    title: t('probes.confirmEnableTitle'),
    content: `${t('probes.confirmEnableBody')} "${probe.probe_name}"?`,
    positiveText: t('probes.enableProbe'),
    negativeText: t('app.cancel'),
    onPositiveClick: () => updateProbeStatus(probe.probe_id, 'active'),
  })
}

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success(t('probes.copiedSuccess'))
  } catch {
    message.error(t('probes.copyFailed'))
  }
}

function maskToken(token: string): string {
  if (token.length <= 16) return token.slice(0, 4) + '...' + token.slice(-4)
  return token.slice(0, 8) + '...' + token.slice(-4)
}

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

function statusTagType(status: string): 'success' | 'error' | 'warning' | 'default' {
  switch (status) {
    case 'active': return 'success'
    case 'offline': return 'error'
    case 'disabled': return 'warning'
    default: return 'default'
  }
}

function statusTagLabel(status: string): string {
  switch (status) {
    case 'active': return t('probes.active')
    case 'offline': return t('probes.offline')
    case 'disabled': return t('probes.disabled')
    case 'draining': return t('probes.draining')
    default: return status
  }
}

const probeColumns = [
  { title: t('probes.probeId'), key: 'probe_id', ellipsis: { tooltip: true } },
  { title: t('probes.name'), key: 'probe_name', ellipsis: { tooltip: true } },
  {
    title: t('probes.status'),
    key: 'status',
    width: 100,
    render: (row: ProbeResponse) =>
      h(NTag, { type: statusTagType(row.status), size: 'small' }, { default: () => statusTagLabel(row.status) }),
  },
  { title: t('dashboard.region'), key: 'region', render: (row: ProbeResponse) => row.region ?? '—' },
  { title: t('probes.isp'), key: 'isp', render: (row: ProbeResponse) => row.isp ?? '—' },
  { title: t('probes.publicIp'), key: 'public_ip', render: (row: ProbeResponse) => row.public_ip ?? '—', ellipsis: { tooltip: true } },
  {
    title: t('probes.lastSeen'),
    key: 'last_seen_at',
    render: (row: ProbeResponse) => fmtTs(row.last_seen_at),
    width: 160,
  },
  { title: t('probes.tags'), key: 'tags', render: (row: ProbeResponse) => (row.tags ?? []).join(', ') || '—', ellipsis: { tooltip: true } },
]

const tokenColumns = [
  { title: 'Token', key: 'token', render: (row: ProbeTokenResponse) => maskToken(row.token) },
  { title: t('probes.note'), key: 'note', render: (row: ProbeTokenResponse) => row.note ?? '—' },
  {
    title: t('probes.created'),
    key: 'created_at',
    render: (row: ProbeTokenResponse) => fmtTs(row.created_at),
    width: 160,
  },
  {
    title: t('probes.expires'),
    key: 'expires_at',
    render: (row: ProbeTokenResponse) => (row.expires_at ? fmtTs(row.expires_at) : '—'),
    width: 160,
  },
  {
    title: t('assets.actions'),
    key: 'actions',
    width: 80,
    render: (row: ProbeTokenResponse) =>
      h(
        NButton,
        { size: 'small', quaternary: true, onClick: () => copyToClipboard(row.token) },
        { default: () => t('probes.copyToken') }
      ),
  },
]

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
  <div style="padding: 16px; max-width: 1400px; margin: 0 auto">
    <NSpin :show="loading" :description="t('probes.loadingProbes')">
      <NAlert v-if="errorMsg" type="error" :title="errorMsg" style="margin-bottom: 16px" closable @close="errorMsg = null" />

      <template v-if="!loading">
        <!-- ── Stats Row ──────────────────────────────────────────────────────── -->
        <NCard :title="t('probes.probeOverview')" style="margin-bottom: 16px">
          <NGrid :cols="4" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
            <NGi span="1">
              <NStatistic :label="t('probes.total')" :value="stats.total" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('probes.active')" :value="stats.active" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('probes.offline')" :value="stats.offline" />
            </NGi>
            <NGi span="1">
              <NStatistic :label="t('probes.disabled')" :value="stats.disabled" />
            </NGi>
          </NGrid>
        </NCard>

        <!-- ── Tabs ────────────────────────────────────────────────────────────── -->
        <NCard>
          <NTabs type="line" animated>
            <!-- ── Tab 1: Probe List ─────────────────────────────────────────── -->
            <NTab name="list" :title="t('probes.probeList')">
              <div style="padding: 8px 0">
                <NSpace :wrap="false" style="margin-bottom: 12px">
                  <NSelect
                    v-model:value="statusFilter"
                    :options="statusOptions"
                    :placeholder="t('probes.filterStatus')"
                    clearable
                    style="width: 140px"
                  />
                  <NInput
                    v-model:value="regionFilter"
                    :placeholder="t('probes.filterRegion')"
                    clearable
                    style="width: 160px"
                  />
                  <NInput
                    v-model:value="searchQuery"
                    :placeholder="t('probes.searchNameId')"
                    clearable
                    style="width: 200px"
                  />
                  <NText depth="3" style="line-height: 34px; margin-left: auto">
                    {{ t('probes.totalProbes', { count: filteredProbes.length }) }}
                  </NText>
                </NSpace>

                <NDataTable
                  :columns="probeColumns"
                  :data="filteredProbes"
                  :bordered="false"
                  :single-line="false"
                  size="small"
                  :pagination="{ pageSize: 15 }"
                  :row-key="(row: ProbeResponse) => row.probe_id"
                  style="margin-bottom: 16px"
                />

                <NSelect
                  v-model:value="selectedProbeId"
                  :options="probes.map(p => ({ label: `${p.probe_name} (${p.probe_id})`, value: p.probe_id }))"
                  :placeholder="t('fleet.selectNode')"
                  clearable
                  filterable
                  style="margin-bottom: 12px; max-width: 400px"
                />

                <template v-if="selectedProbe">
                  <NCard :title="t('probes.probeDetails')" size="small" style="margin-bottom: 12px">
                    <NGrid :cols="3" :x-gap="16" :y-gap="8" responsive="screen" item-responsive>
                      <NGi span="1">
                        <NText depth="3" style="font-size: 12px">{{ t('probes.probeId') }}</NText>
                        <NText block style="word-break: break-all">{{ selectedProbe.probe_id }}</NText>
                      </NGi>
                      <NGi span="1">
                        <NText depth="3" style="font-size: 12px">{{ t('probes.status') }}</NText>
                        <div style="margin-top: 2px">
                          <NTag :type="statusTagType(selectedProbe.status)" size="small">
                            {{ statusTagLabel(selectedProbe.status) }}
                          </NTag>
                        </div>
                      </NGi>
                      <NGi span="1">
                        <NText depth="3" style="font-size: 12px">{{ t('dashboard.region') }}</NText>
                        <NText block>{{ selectedProbe.region ?? '—' }}</NText>
                      </NGi>
                      <NGi span="1">
                        <NText depth="3" style="font-size: 12px">{{ t('probes.isp') }}</NText>
                        <NText block>{{ selectedProbe.isp ?? '—' }}</NText>
                      </NGi>
                      <NGi span="1">
                        <NText depth="3" style="font-size: 12px">{{ t('probes.publicIp') }}</NText>
                        <NText block>{{ selectedProbe.public_ip ?? '—' }}</NText>
                      </NGi>
                      <NGi span="1">
                        <NText depth="3" style="font-size: 12px">{{ t('probes.lastSeen') }}</NText>
                        <NText block>{{ fmtTs(selectedProbe.last_seen_at) }}</NText>
                      </NGi>
                      <NGi span="1">
                        <NText depth="3" style="font-size: 12px">{{ t('probes.configVersion') }}</NText>
                        <NText block>{{ selectedProbe.config_version }}</NText>
                      </NGi>
                      <NGi span="1">
                        <NText depth="3" style="font-size: 12px">{{ t('probes.tags') }}</NText>
                        <NText block>{{ (selectedProbe.tags ?? []).join(', ') || '—' }}</NText>
                      </NGi>
                    </NGrid>
                  </NCard>

                  <NSpace>
                    <NButton
                      v-if="selectedProbe.status !== 'disabled'"
                      type="warning"
                      :loading="actionLoading"
                      @click="confirmDisable(selectedProbe)"
                    >
                      {{ t('probes.disableProbe') }}
                    </NButton>
                    <NButton
                      v-if="selectedProbe.status !== 'active'"
                      type="success"
                      :loading="actionLoading"
                      @click="confirmEnable(selectedProbe)"
                    >
                      {{ t('probes.enableProbe') }}
                    </NButton>
                  </NSpace>
                </template>
              </div>
            </NTab>

            <!-- ── Tab 2: Register New Probe ──────────────────────────────────── -->
            <NTab name="register" :title="t('probes.registerNewProbe')">
              <div style="padding: 8px 0; max-width: 700px">
                <NAlert type="info" :title="t('probes.registrationInstructions')" style="margin-bottom: 16px">
                  <NText depth="3">
                    {{ t('probes.registrationNote') }}
                  </NText>
                </NAlert>

                <NCard :title="t('probes.registrationParams')" size="small" style="margin-bottom: 16px">
                  <NSpace vertical>
                    <NSpace align="center">
                      <NText depth="3" style="width: 80px">{{ t('probes.name') }}</NText>
                      <NInput v-model:value="regProbeName" placeholder="my-probe-01" style="width: 260px" />
                    </NSpace>
                    <NSpace align="center">
                      <NText depth="3" style="width: 80px">{{ t('dashboard.region') }}</NText>
                      <NInput v-model:value="regRegion" placeholder="us-west-2" style="width: 260px" />
                    </NSpace>
                    <NSpace align="center">
                      <NText depth="3" style="width: 80px">{{ t('probes.isp') }}</NText>
                      <NInput v-model:value="regIsp" placeholder="Comcast" style="width: 260px" />
                    </NSpace>
                    <NSpace align="center">
                      <NText depth="3" style="width: 80px">{{ t('probes.tags') }}</NText>
                      <NInput
                        v-model:value="regTags"
                        placeholder="tag1, tag2"
                        style="width: 260px"
                      />
                    </NSpace>
                  </NSpace>
                </NCard>

                <NCard :title="t('probes.registrationCommand')" size="small">
                  <NCode
                    language="bash"
                    :code="registrationCommand"
                    style="font-size: 13px"
                  />
                </NCard>
              </div>
            </NTab>

            <!-- ── Tab 3: Token Management ────────────────────────────────────── -->
            <NTab name="tokens" :title="t('probes.bootstrapToken')">
              <div style="padding: 8px 0; max-width: 700px">
                <NAlert type="warning" :title="t('probes.securityWarning')" style="margin-bottom: 16px">
                  {{ t('probes.probeRegistrationNote') }}
                </NAlert>

                <NCard :title="t('probes.generateNewToken')" size="small" style="margin-bottom: 16px">
                  <NSpace vertical>
                    <NInput
                      v-model:value="newTokenNote"
                      :placeholder="t('probes.tokenNote')"
                      style="width: 400px"
                    />
                    <NButton
                      type="primary"
                      :loading="generatingToken"
                      @click="generateToken"
                    >
                      {{ t('probes.createToken') }}
                    </NButton>
                  </NSpace>
                </NCard>

                <NCard v-if="generatedToken" :title="t('probes.newToken')" size="small" style="margin-bottom: 16px">
                  <NSpace align="center" style="margin-bottom: 8px">
                    <NCode :code="generatedToken" language="text" style="font-size: 13px; max-width: 500px" />
                    <NButton size="small" @click="copyToClipboard(generatedToken!)">{{ t('probes.copyNow') }}</NButton>
                  </NSpace>
                  <NText depth="3" style="font-size: 12px">
                    {{ t('probes.copyNow') }}
                  </NText>
                </NCard>

                <NCard :title="t('probes.existingTokens')" size="small">
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
                    <NEmpty v-else :description="t('probes.noTokens')" />
                  </NSpin>
                </NCard>
              </div>
            </NTab>
          </NTabs>
        </NCard>
      </template>
    </NSpin>
  </div>
</template>
