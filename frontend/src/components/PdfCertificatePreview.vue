<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getDocument, GlobalWorkerOptions, version, type PDFDocumentLoadingTask, type PDFDocumentProxy, type RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?worker&url'

const props = defineProps<{ blob: Blob }>()
GlobalWorkerOptions.workerSrc = workerUrl
const resourceBase = new URL(import.meta.env.DEV
  ? `${import.meta.env.BASE_URL}node_modules/pdfjs-dist/`
  : `${import.meta.env.BASE_URL}assets/pdfjs-${version}/`, document.baseURI).href
const canvas = ref<HTMLCanvasElement>()
const stage = ref<HTMLDivElement>()
const pageNumber = ref(1)
const pageCount = ref(0)
const zoom = ref(1)
const busy = ref(true)
const error = ref('')
let loadingTask: PDFDocumentLoadingTask | null = null
let pdfDocument: PDFDocumentProxy | null = null
let renderTask: RenderTask | null = null
let canvasReady: Promise<void> = Promise.resolve()
let documentGeneration = 0
let renderGeneration = 0
let resizeObserver: ResizeObserver | null = null
let animationFrame = 0

function disposeDocument() {
  ++documentGeneration
  ++renderGeneration
  renderTask?.cancel()
  renderTask = null
  pdfDocument = null
  const previous = loadingTask
  loadingTask = null
  void previous?.destroy().catch(() => {})
}

async function loadDocument() {
  disposeDocument()
  const generation = documentGeneration
  busy.value = true
  error.value = ''
  pageCount.value = 0
  pageNumber.value = 1
  zoom.value = 1
  try {
    const data = new Uint8Array(await props.blob.arrayBuffer())
    if (generation !== documentGeneration) return
    const task = getDocument({ data, cMapUrl: `${resourceBase}cmaps/`, cMapPacked: true,
      standardFontDataUrl: `${resourceBase}standard_fonts/`, wasmUrl: `${resourceBase}wasm/`,
      // Render glyphs in canvas so strict CSP does not need blob fonts or eval.
      disableFontFace: true, useSystemFonts: false, useWasm: false })
    loadingTask = task
    const loaded = await task.promise
    if (generation !== documentGeneration) return
    pdfDocument = loaded
    pageCount.value = loaded.numPages
    await nextTick()
    await renderPage()
  } catch (cause) {
    if (generation !== documentGeneration) return
    error.value = (cause as Error).name === 'PasswordException'
      ? '该 PDF 有密码保护，请下载原文件后打开'
      : 'PDF 无法预览，请下载原文件查看或重新上传完整的 PDF'
    busy.value = false
  }
}

async function renderPage() {
  if (!pdfDocument || !canvas.value || !stage.value) return
  const generation = ++renderGeneration
  const currentDocument = pdfDocument
  const previous = renderTask
  previous?.cancel()
  renderTask = null
  busy.value = true
  error.value = ''
  try {
    // A cancelled render must release the canvas before the next render starts.
    await canvasReady
    const page = await currentDocument.getPage(pageNumber.value)
    if (generation !== renderGeneration || currentDocument !== pdfDocument) return
    const original = page.getViewport({ scale: 1 })
    const availableWidth = Math.max(200, stage.value.clientWidth - 32)
    const viewport = page.getViewport({ scale: availableWidth / original.width * zoom.value })
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(16_000_000 / (viewport.width * viewport.height)))
    const target = canvas.value
    target.width = Math.max(1, Math.floor(viewport.width * pixelRatio))
    target.height = Math.max(1, Math.floor(viewport.height * pixelRatio))
    target.style.width = `${Math.floor(viewport.width)}px`
    target.style.height = `${Math.floor(viewport.height)}px`
    const context = target.getContext('2d')
    if (!context) throw new Error('Canvas unavailable')
    const task = page.render({ canvas: target, canvasContext: context, viewport,
      transform: pixelRatio === 1 ? undefined : [pixelRatio, 0, 0, pixelRatio, 0, 0] })
    renderTask = task
    canvasReady = task.promise.then(() => {}, () => {})
    await task.promise
    if (generation === renderGeneration) stage.value.scrollTo({ top: 0, left: 0 })
  } catch (cause) {
    if (generation === renderGeneration && (cause as Error).name !== 'RenderingCancelledException') {
      error.value = '这一页无法预览，请下载原文件查看'
    }
  } finally {
    if (generation === renderGeneration) { busy.value = false; renderTask = null }
  }
}

function scheduleRender() {
  cancelAnimationFrame(animationFrame)
  animationFrame = requestAnimationFrame(() => { void renderPage() })
}

watch(() => props.blob, loadDocument)
watch([pageNumber, zoom], scheduleRender)
onMounted(() => {
  resizeObserver = new ResizeObserver(scheduleRender)
  if (stage.value) resizeObserver.observe(stage.value)
  void loadDocument()
})
onBeforeUnmount(() => {
  cancelAnimationFrame(animationFrame)
  resizeObserver?.disconnect()
  disposeDocument()
})
</script>

<template>
  <div class="pdf-certificate-preview">
    <div class="pdf-preview-toolbar">
      <el-button size="small" :disabled="busy || pageNumber <= 1" @click="pageNumber--">上一页</el-button>
      <span aria-live="polite">第 {{ pageCount ? pageNumber : '—' }} / {{ pageCount || '—' }} 页</span>
      <el-button size="small" :disabled="busy || pageNumber >= pageCount" @click="pageNumber++">下一页</el-button>
      <el-button size="small" :disabled="busy || !pageCount || zoom <= 0.5" @click="zoom = Math.max(0.5, zoom - 0.25)">缩小</el-button>
      <el-button size="small" :disabled="busy || !pageCount" @click="zoom = 1">适合宽度</el-button>
      <el-button size="small" :disabled="busy || !pageCount || zoom >= 2" @click="zoom = Math.min(2, zoom + 0.25)">放大</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <div ref="stage" v-loading="busy" class="pdf-preview-stage" :aria-busy="busy">
      <canvas ref="canvas" v-show="pageCount && !error" :aria-label="`PDF 证书第 ${pageNumber} 页`" role="img" />
    </div>
  </div>
</template>
