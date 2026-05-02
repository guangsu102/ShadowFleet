import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import App from './App.vue'
import router from './router'
import './styles/global.css'
import { setLocale } from './composables/useI18n'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(naive)
app.mount('#app')

// Initialize locale
const saved = localStorage.getItem('shadowfleet_locale')
if (saved === 'en' || saved === 'zh') setLocale(saved as 'en' | 'zh')
else setLocale('zh')
