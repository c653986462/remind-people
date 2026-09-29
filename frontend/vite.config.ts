import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    base: './',
    plugins: [
      vue(),
      AutoImport({ dts: 'src/auto-imports.d.ts', resolvers: [ElementPlusResolver()] }),
      Components({ dts: 'src/components.d.ts', resolvers: [ElementPlusResolver({ importStyle: 'css' })] }),
    ],
    server: {
      watch: {
        ignored: ['**/release/**', '**/desktop-release-*/**'],
      },
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
          rewrite: path => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})

