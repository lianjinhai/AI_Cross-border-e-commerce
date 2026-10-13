import { createApp } from 'vue'
import * as Icons from '@element-plus/icons-vue'
import App from './App.vue'
import router from './app/router'
import './styles/tokens.css'
import './styles.css'

const app = createApp(App)
for (const [name, comp] of Object.entries(Icons)) app.component(name, comp)
app.use(router)
app.mount('#app')
