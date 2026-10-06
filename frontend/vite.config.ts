import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { readFileSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'

const pdfPackageRoot = dirname(createRequire(import.meta.url).resolve('pdfjs-dist/package.json'))
const pdfVersion = JSON.parse(readFileSync(join(pdfPackageRoot, 'package.json'), 'utf8')).version

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    base: './',
    worker: { format: 'es' },
    plugins: [
      vue(),
      {
        name: 'pdf-preview-resources',
        apply: 'build',
        generateBundle() {
          // Ship Chinese character maps, fallback fonts and image decoders locally.
          for (const directory of ['cmaps', 'standard_fonts', 'wasm']) {
            for (const filename of readdirSync(join(pdfPackageRoot, directory))) {
              this.emitFile({ type: 'asset', fileName: `assets/pdfjs-${pdfVersion}/${directory}/${filename}`,
                source: readFileSync(join(pdfPackageRoot, directory, filename)) })
            }
          }
        },
      },
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
