<script setup lang="ts">
import { NSpace, NResult } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
</script>
<template>
  <div style="padding: 16px; max-width: 1400px; margin: 0 auto">
    <NCard>
      <NSpace vertical align="center" justify="center" style="padding: 80px 0; text-align: center">
        <NResult status="info" title="Sentinel" :description="t('sentinel.comingSoon')" />
      </NSpace>
    </NCard>
  </div>
</template>
