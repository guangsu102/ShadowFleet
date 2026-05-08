<script setup lang="ts">
import type { DetectionRecordResponse } from '@/types/api'

defineProps<{
  row: DetectionRecordResponse
}>()
</script>

<template>
  <div style="padding: 12px 16px; background: #f8fafc; border-radius: 8px; margin: 8px 0;">
    <div style="font-weight: 600; margin-bottom: 8px; color: #334155; display: flex; align-items: center; gap: 8px;">
      探测详情
      <span v-if="!row.selected_probe_ids?.length" style="font-size: 11px; background: #dbeafe; color: #1d4ed8; padding: 2px 8px; border-radius: 10px; font-weight: 500;">本地探测模式</span>
      <span v-else style="font-size: 11px; background: #fce7f3; color: #be185d; padding: 2px 8px; border-radius: 10px; font-weight: 500;">探针网格模式</span>
    </div>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px;">
      <div><span style="color: #64748b;">探测状态:</span> {{ row.probe_status ?? '—' }}</div>
      <div><span style="color: #64748b;">失败阶段:</span> {{ row.probe_failure_stage ?? '—' }}</div>
      <div><span style="color: #64748b;">解析IP:</span> {{ row.probe_resolved_ip ?? '—' }}</div>
      <div><span style="color: #64748b;">延迟:</span> {{ row.probe_latency_ms !== null ? row.probe_latency_ms + 'ms' : '—' }}</div>
      <div><span style="color: #64748b;">成功区域:</span> {{ row.probe_success_region_count ?? '—' }}</div>
      <div><span style="color: #64748b;">失败区域:</span> {{ row.probe_failed_region_count ?? '—' }}</div>
      <div><span style="color: #64748b;">Measurement ID:</span> <code style="font-size: 11px;">{{ row.measurement_id ?? '—' }}</code></div>
      <div><span style="color: #64748b;">探针节点:</span> {{ row.selected_probe_ids?.length ? row.selected_probe_ids.join(', ') : '—' }}</div>
      <div style="grid-column: 1 / -1;"><span style="color: #64748b;">结论:</span> <strong>{{ row.reason ?? '—' }}</strong></div>
    </div>
    <div v-if="!row.selected_probe_ids?.length" style="margin-top: 8px; padding: 8px; background: #eff6ff; border-radius: 6px; font-size: 12px; color: #1e40af;">
      <strong>本地探测模式说明：</strong>仅使用海外控制面对节点进行探测，不依赖国内探针。判定规则：可达=正常，DNS失败/源站不可达/TLS失败=源站故障。
    </div>
    <div v-else style="margin-top: 8px; padding: 8px; background: #fdf4ff; border-radius: 6px; font-size: 12px; color: #86198f;">
      <strong>探针网格模式说明：</strong>使用海外控制面+国内多个探针联合探测。需要国内探针全部失败且失败比例达到阈值才判定为 GFW 封锁。
    </div>
  </div>
</template>
