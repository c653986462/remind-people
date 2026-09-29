import { createApp } from 'vue'
import App from './App.vue'
// Programmatic components are explicitly imported, so the component resolver
// does not automatically include their styles.
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import './style.css'

const app = createApp(App)
app.mount('#app')

