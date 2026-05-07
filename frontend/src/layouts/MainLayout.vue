<script setup lang="ts">
import { computed, h } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu, NButton, NText, NSpace, NIcon, NSelect } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useAuthStore } from '@/stores/authStore'
import { useI18n } from '@/composables/useI18n'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t, locale, setLocale, availableLocales, localeName } = useI18n()

// Icon factories (inline SVG-based naive-ui icons)
function renderIcon(iconPath: string) {
  return () => h(NIcon, null, {
    default: () => h('svg', { xmlns: 'http://www.w3.org/2000/svg', viewBox: '0 0 24 24', style: 'width:18px;height:18px;fill:currentColor' }, [
      h('path', { d: iconPath }),
    ]),
  })
}

const menuOptions = computed<MenuOption[]>(() => [
  { label: () => h(RouterLink, { to: '/' }, { default: () => t('nav.dashboard') }), key: '/', icon: renderIcon('M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3z') },
  { label: () => h(RouterLink, { to: '/assets' }, { default: () => t('nav.assets') }), key: '/assets', icon: renderIcon('M20 6h-8l-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2z') },
  { label: () => h(RouterLink, { to: '/fleet' }, { default: () => t('nav.fleet') }), key: '/fleet', icon: renderIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z') },
  { label: () => h(RouterLink, { to: '/provisioner' }, { default: () => t('nav.provisioner') }), key: '/provisioner', icon: renderIcon('M19.43 12.98c.04-.32.07-.64.07-.98 0-.34-.03-.66-.07-.98l2.11-1.65c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.39-.3-.61-.22l-2.49 1c-.52-.4-1.08-.73-1.69-.98l-.38-2.65C14.46 2.18 14.25 2 14 2h-4c-.25 0-.46.18-.49.42l-.38 2.65c-.61.25-1.17.59-1.69.98l-2.49-1c-.23-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64l2.11 1.65c-.04.32-.07.65-.07.98 0 .33.03.66.07.98l-2.11 1.65c-.19.15-.24.42-.12.64l2 3.46c.12.22.39.3.61.22l2.49-1c.52.4 1.08.73 1.69.98l.38 2.65c.03.24.24.42.49.42h4c.25 0 .46-.18.49-.42l.38-2.65c.61-.25 1.17-.59 1.69-.98l2.49 1c.23.09.49 0 .61-.22l2-3.46c.12-.22.07-.49-.12-.64l-2.11-1.65zM12 15.5c-1.93 0-3.5-1.57-3.5-3.5s1.57-3.5 3.5-3.5 3.5 1.57 3.5 3.5-1.57 3.5-3.5 3.5z') },
  { label: () => h(RouterLink, { to: '/probes' }, { default: () => t('nav.probes') }), key: '/probes', icon: renderIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z') },
  { label: () => h(RouterLink, { to: '/sentinel' }, { default: () => t('nav.sentinel') }), key: '/sentinel', icon: renderIcon('M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z') },
  { label: () => h(RouterLink, { to: '/system' }, { default: () => t('nav.system') }), key: '/system', icon: renderIcon('M20 18c1.1 0 1.99-.9 1.99-2L22 6c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2H0v2h24v-2h-4zM4 6h16v10H4V6z') },
  { label: () => h(RouterLink, { to: '/abandonment' }, { default: () => t('nav.abandonment') }), key: '/abandonment', icon: renderIcon('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z') },
  { label: () => h(RouterLink, { to: '/settings' }, { default: () => t('nav.settings') }), key: '/settings', icon: renderIcon('M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z') },
])

const localeOptions = computed(() => availableLocales.map(l => ({ label: localeName(l), value: l })))

function handleMenuUpdate(key: string) {
  router.push(key)
}

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <NLayout has-sider style="height: 100vh">
    <NLayoutSider
      bordered
      :width="200"
      :native-scrollbar="false"
      style="background: #fff"
    >
      <div style="padding: 16px; border-bottom: 1px solid #f0f0f0">
        <NText strong style="font-size: 16px">{{ t('app.title') }}</NText>
      </div>
      <NMenu
        :value="route.path"
        :options="menuOptions"
        @update:value="handleMenuUpdate"
      />
    </NLayoutSider>

    <NLayout>
      <NLayoutHeader bordered style="height: 56px; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; background: #fff">
        <NText strong>{{ route.meta?.title || route.name }}</NText>
        <NSpace>
          <NSelect
            :value="locale"
            :options="localeOptions"
            size="small"
            style="width: 100px"
            @update:value="setLocale"
          />
          <NText depth="3">{{ auth.currentUser?.username }}</NText>
          <NText depth="3" style="text-transform: capitalize">[{{ auth.currentUser?.role }}]</NText>
          <NButton size="small" @click="handleLogout">{{ t('auth.logout') }}</NButton>
        </NSpace>
      </NLayoutHeader>

      <NLayoutContent style="padding: 24px">
        <RouterView />
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>
