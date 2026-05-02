<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NForm, NFormItem, NInput, NButton, NCard, NText, NSpace, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/authStore'
import { useI18n } from '@/composables/useI18n'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const message = useMessage()
const { t } = useI18n()

const form = ref({ username: '', password: '' })
const loading = ref(false)

async function handleLogin() {
  if (!form.value.username || !form.value.password) {
    message.warning(t('auth.fillAllFields'))
    return
  }
  loading.value = true
  try {
    await auth.login(form.value)
    const redirect = route.query.redirect as string
    router.push(redirect || '/')
  } catch {
    message.error(t('auth.invalidCredentials'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="display: flex; align-items: center; justify-content: center; height: 100vh; background: #f5f5f5">
    <NCard style="width: 400px" :bordered="false" hoverable>
      <template #header>
        <NSpace vertical :size="4">
          <NText strong style="font-size: 20px">{{ t('app.title') }}</NText>
          <NText depth="3" style="font-size: 13px">{{ t('app.subtitle') }}</NText>
        </NSpace>
      </template>

      <NForm @submit.prevent="handleLogin">
        <NFormItem :label="t('auth.username')">
          <NInput v-model:value="form.username" placeholder="admin" />
        </NFormItem>
        <NFormItem :label="t('auth.password')">
          <NInput v-model:value="form.password" type="password" placeholder="••••••" @keydown.enter="handleLogin" />
        </NFormItem>
        <NButton type="primary" block :loading="loading" attr-type="submit">
          {{ t('auth.signIn') }}
        </NButton>
      </NForm>
    </NCard>
  </div>
</template>
