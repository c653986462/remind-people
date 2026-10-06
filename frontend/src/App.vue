<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import {
  ArrowLeft, ArrowRight, Bell, Calendar, Clock, Collection, Document, Lock, Message,
  Download, FolderOpened, House, Link, MoreFilled, Picture, Plus, Refresh, Search, Tickets, UploadFilled, User, UserFilled,
} from '@element-plus/icons-vue'
import { mockApi, type Certificate, type Person, type RecordAttachment, type RecordItem, type Reminder } from './mock'
import { type UploadUserFile } from 'element-plus'
import { exportXlsx } from './export-xlsx'

const PdfCertificatePreview = defineAsyncComponent(() => import('./components/PdfCertificatePreview.vue'))

type TabKey = 'dashboard' | 'records' | 'people' | 'certificates'
type DialogKind = 'person' | 'certificate' | 'record'
type AuthUser = { id: number; username: string }
type CertificateHolder = Person & { validityEndDates: string[] }
// Live API is the default; set VITE_USE_MOCK=true only for offline previews.
const mockMode = import.meta.env.DEV && import.meta.env.VITE_USE_MOCK === 'true'
let api = (import.meta.env.VITE_API_URL || '/api').replace(/\/+$/, '')
const desktopMode = Boolean(window.desktop)
const appVersion = ref('')
let reminderTimer = 0
let desktopPopupTimer = 0
let removeUpdateListener: (() => void) | undefined
let removeReminderActionListener: (() => void) | undefined
const activeDesktopReminderKeys = new Set<string>()
const authReady = ref(false)
const currentUser = ref<AuthUser | null>(null)
const csrfToken = ref('')
const loginForm = ref({ username: '', password: '' })
const loginError = ref('')
const loginLoading = ref(false)
const passwordDialogVisible = ref(false)
const passwordSaving = ref(false)
const passwordForm = ref({ current_password: '', new_password: '', confirm_password: '' })
type EmailSettings = { smtp_configured: boolean; email: string | null; verified: boolean; pending_email: string | null }
const emailSettingsVisible = ref(false)
const emailSettingsLoading = ref(false)
const emailActionLoading = ref(false)
const emailSettings = ref<EmailSettings>({ smtp_configured: false, email: null, verified: false, pending_email: null })
const emailForm = ref({ email: '', code: '' })
const tab = ref<TabKey>('dashboard')
const viewMode = ref<'list' | 'calendar'>('list')
const calendarDate = ref(new Date())
const people = ref<Person[]>([])
const certificates = ref<Certificate[]>([])
const records = ref<RecordItem[]>([])
const personCertificatesVisible = ref(false)
const selectedPersonId = ref<number | null>(null)
const selectedPerson = computed(() => people.value.find(person => person.id === selectedPersonId.value))
const recordsByPerson = computed(() => {
  const grouped = new Map<number, RecordItem[]>()
  for (const record of records.value) {
    const items = grouped.get(record.person_id) || []
    items.push(record)
    grouped.set(record.person_id, items)
  }
  return grouped
})
const selectedPersonCertificates = computed(() => selectedPersonId.value === null
  ? [] : recordsByPerson.value.get(selectedPersonId.value) || [])
const personDetailVisible = ref(false)
const detailPersonId = ref<number | null>(null)
const detailPerson = computed(() => people.value.find(person => person.id === detailPersonId.value))
const detailPersonCertificates = computed(() => detailPersonId.value === null
  ? [] : recordsByPerson.value.get(detailPersonId.value) || [])
const certificateHoldersVisible = ref(false)
const selectedCertificateId = ref<number | null>(null)
const selectedCertificate = computed(() => certificates.value.find(certificate => certificate.id === selectedCertificateId.value))
const holdersByCertificate = computed(() => {
  const grouped = new Map<number, Map<number, CertificateHolder>>()
  for (const record of records.value) {
    const holders = grouped.get(record.certificate_id) || new Map<number, CertificateHolder>()
    const holder = holders.get(record.person_id) || { ...record.person, validityEndDates: [] as string[] }
    const endDate = record.validity_end_date || ''
    if (!holder.validityEndDates.includes(endDate)) holder.validityEndDates.push(endDate)
    holders.set(record.person_id, holder)
    grouped.set(record.certificate_id, holders)
  }
  const holders = new Map<number, CertificateHolder[]>()
  for (const [certificateId, peopleById] of grouped) {
    holders.set(certificateId, Array.from(peopleById.values()))
  }
  return holders
})
const selectedCertificateHolders = computed(() => selectedCertificateId.value === null
  ? [] : holdersByCertificate.value.get(selectedCertificateId.value) || [])
const reminders = ref<Reminder[]>([])
const search = ref('')
const errorMessage = ref('')
const exportingRecords = ref(false)
const dialogVisible = ref(false)
const dialogKind = ref<DialogKind>('record')
const editingId = ref<number | null>(null)
const saving = ref(false)
const checking = ref(false)
const formRef = ref<FormInstance>()
const detailVisible = ref(false)
const detailRecord = ref<RecordItem | null>(null)
const previewVisible = ref(false)
const previewUrl = ref('')
const previewAttachment = ref<RecordAttachment | null>(null)
const previewBusy = ref(false)
const previewBlob = shallowRef<Blob | null>(null)
const previewError = ref('')
let previewRequest: AbortController | null = null
let previewGeneration = 0
const recordAttachments = ref<RecordAttachment[]>([])
const pendingPdfFiles = ref<UploadUserFile[]>([])
const pendingImageFiles = ref<UploadUserFile[]>([])
const removedAttachmentIds = ref(new Set<number>())
const personForm = ref({ name: '', phone: '', identity_number: '', email: '', department: '', notes: '' })
const certificateForm = ref({ name: '', issuer: '', description: '' })
const recordForm = ref({ person_id: 0, certificate_id: 0, certificate_no: '', validity_start_date: '', validity_end_date: '', expiry_date: '', continuing_education_date: '', renewal_date: '', certificate_url: '', education_url: '', renewal_url: '', remind_days: 30, active: true, notes: '' })
const validityRange = computed<[string, string] | null>({
  get: (): [string, string] | null => recordForm.value.validity_start_date || recordForm.value.validity_end_date
    ? [recordForm.value.validity_start_date, recordForm.value.validity_end_date]
    : null,
  set: (range: [string, string] | null) => {
    recordForm.value.validity_start_date = range?.[0] || ''
    recordForm.value.validity_end_date = range?.[1] || ''
  },
})

const personRules: FormRules = { name: [{ required: true, message: '请填写姓名', trigger: 'blur' }] }
const certificateRules: FormRules = { name: [{ required: true, message: '请填写证书名称', trigger: 'blur' }] }
const recordRules: FormRules = {
  person_id: [{ required: true, type: 'number', min: 1, message: '请选择持证人员', trigger: 'change' }],
  certificate_id: [{ required: true, type: 'number', min: 1, message: '请选择证书类型', trigger: 'change' }],
}
const dialogRules = computed(() => dialogKind.value === 'person' ? personRules : dialogKind.value === 'certificate' ? certificateRules : recordRules)
const dialogTitle = computed(() => {
  const action = editingId.value ? '编辑' : '新增'
  return dialogKind.value === 'person' ? `${action}人员档案` : dialogKind.value === 'certificate' ? `${action}证书类型` : `${action}持证记录`
})
const upcoming = computed(() => reminders.value.filter(item => item.days_left <= 30))
const monthTitle = computed(() => new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long' }).format(calendarDate.value))
const visiblePeople = computed(() => {
  const q = search.value.trim().toLowerCase()
  return people.value.filter(item => !q || `${item.name} ${item.phone || ''} ${item.identity_number || ''} ${item.email || ''} ${item.department || ''}`.toLowerCase().includes(q))
})
const visibleCertificates = computed(() => {
  const q = search.value.trim().toLowerCase()
  return certificates.value.filter(item => !q || `${item.name} ${item.issuer || ''} ${item.description || ''}`.toLowerCase().includes(q))
})
const visibleRecords = computed(() => {
  const q = search.value.trim().toLowerCase()
  return records.value.filter(item => !q || [item.person.name, item.certificate.name, item.certificate_no || '']
    .some(value => value.toLowerCase().includes(q)))
})

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (mockMode) {
    if (options.method && options.method !== 'GET') {
      return await mockApi.send<T>(path, options.method, options.body ? JSON.parse(String(options.body)) : undefined) as T
    }
    return mockApi.get<T>(path)
  }
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (options.method && !['GET', 'HEAD', 'OPTIONS'].includes(options.method.toUpperCase()) && csrfToken.value) {
    headers.set('X-CSRF-Token', csrfToken.value)
  }
  const response = await fetch(`${api}${path}`, { credentials: 'include', ...options, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '请求失败' }))
    if (response.status === 401 && !path.startsWith('/auth/')) {
      if (window.desktop && currentUser.value && !localStorage.getItem('certificate-session-expired-notice')) {
        window.desktop.showNotification('证事提醒已暂停', '登录会话已过期，请打开桌面客户端重新登录以恢复提醒。', 'session-expired')
        localStorage.setItem('certificate-session-expired-notice', '1')
      }
      currentUser.value = null
      csrfToken.value = ''
    }
    const detail = body.detail
    const message = Array.isArray(detail) ? detail.map((item: { msg?: string }) => item.msg || '').filter(Boolean).join('；') : detail
    throw new Error(typeof message === 'string' ? message : '请求失败')
  }
  return (response.status === 204 ? undefined : response.json()) as Promise<T>
}

async function initializeAuth() {
  if (window.desktop) {
    try {
      api = (await window.desktop.getApiUrl()).replace(/\/+$/, '')
      appVersion.value = await window.desktop.getAppVersion()
    } catch (error) {
      loginError.value = `桌面端初始化失败：${(error as Error).message}`
      authReady.value = true
      return
    }
  }
  if (mockMode) {
    currentUser.value = { id: 0, username: '演示模式' }
    authReady.value = true
    await load()
    return
  }
  try {
    const session = await request<{ user: AuthUser; csrf_token: string }>('/auth/me')
    currentUser.value = session.user
    localStorage.removeItem('certificate-session-expired-notice')
    csrfToken.value = session.csrf_token
    await load()
  } catch (error) {
    const message = (error as Error).message
    if (!message.includes('请先登录') && !message.includes('登录已过期')) loginError.value = `无法连接服务：${message}`
  } finally {
    authReady.value = true
  }
}

async function login() {
  loginError.value = ''
  loginLoading.value = true
  try {
    const session = await request<{ user: AuthUser; csrf_token: string }>('/auth/login', {
      method: 'POST', body: JSON.stringify(loginForm.value),
    })
    currentUser.value = session.user
    localStorage.removeItem('certificate-session-expired-notice')
    csrfToken.value = session.csrf_token
    loginForm.value.password = ''
    await load()
  } catch (error) {
    loginError.value = (error as Error).message
  } finally {
    loginLoading.value = false
  }
}

async function logout() {
  try {
    if (!mockMode) await request('/auth/logout', { method: 'POST' })
  } catch { /* The server may already have expired this session. */ }
  currentUser.value = null
  csrfToken.value = ''
  loginError.value = ''
  passwordDialogVisible.value = false
  loginForm.value.password = ''
}

async function changePassword() {
  if (passwordForm.value.new_password.length < 14) { ElMessage.error('新密码至少需要 14 个字符'); return }
  if (passwordForm.value.new_password !== passwordForm.value.confirm_password) { ElMessage.error('两次输入的新密码不一致'); return }
  passwordSaving.value = true
  try {
    await request('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: passwordForm.value.current_password, new_password: passwordForm.value.new_password }),
    })
    passwordDialogVisible.value = false
    passwordForm.value = { current_password: '', new_password: '', confirm_password: '' }
    await logout()
    ElMessage.success('密码已修改，请使用新密码重新登录')
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { passwordSaving.value = false }
}

async function openEmailSettings() {
  emailSettingsVisible.value = true
  emailSettingsLoading.value = true
  try {
    emailSettings.value = await request<EmailSettings>('/settings/email')
    emailForm.value.email = emailSettings.value.pending_email || emailSettings.value.email || ''
    emailForm.value.code = ''
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { emailSettingsLoading.value = false }
}

async function sendEmailCode() {
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailForm.value.email.trim())) {
    ElMessage.warning('请先填写有效的邮箱地址')
    return
  }
  emailActionLoading.value = true
  try {
    await request('/settings/email/send-code', { method: 'POST', body: JSON.stringify({ email: emailForm.value.email.trim() }) })
    ElMessage.success('验证码已发送，请检查邮箱（含垃圾邮件）')
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { emailActionLoading.value = false }
}

async function verifyEmail() {
  if (!/^\d{6}$/.test(emailForm.value.code.trim())) { ElMessage.warning('请输入邮件中的 6 位验证码'); return }
  emailActionLoading.value = true
  try {
    await request('/settings/email/verify', { method: 'POST', body: JSON.stringify({ code: emailForm.value.code.trim() }) })
    emailForm.value.code = ''
    await openEmailSettings()
    ElMessage.success('邮箱已绑定，证书提醒会发送到该邮箱')
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { emailActionLoading.value = false }
}

async function sendTestEmail() {
  emailActionLoading.value = true
  try { await request('/settings/email/test', { method: 'POST' }); ElMessage.success('测试邮件已发送，请检查收件箱') }
  catch (error) { ElMessage.error((error as Error).message) }
  finally { emailActionLoading.value = false }
}

async function unbindEmail() {
  try {
    await ElMessageBox.confirm('解除绑定后，将不再向此邮箱发送证书提醒。', '解除邮箱绑定', { type: 'warning', confirmButtonText: '解除绑定', cancelButtonText: '取消' })
    await request('/settings/email', { method: 'DELETE' })
    await openEmailSettings()
    ElMessage.success('邮箱已解除绑定')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error((error as Error).message) }
}

async function load() {
  errorMessage.value = ''
  try {
    ;[people.value, certificates.value, records.value, reminders.value] = await Promise.all([
      request<Person[]>('/people'), request<Certificate[]>('/certificates'),
      request<RecordItem[]>('/records'), request<Reminder[]>('/reminders/upcoming?days=365'),
    ])
    if (!recordForm.value.person_id && people.value[0]) recordForm.value.person_id = people.value[0].id
    if (!recordForm.value.certificate_id && certificates.value[0]) recordForm.value.certificate_id = certificates.value[0].id
    notifyUpcoming()
    void checkDesktopDueReminders()
  } catch (error) { errorMessage.value = `数据加载失败：${(error as Error).message}` }
}

async function exportRecords() {
  exportingRecords.value = true
  try {
    // Fetch with the current search term at click time so a pending debounce cannot export stale rows.
    const exportRows = await request<RecordItem[]>(`/records?q=${encodeURIComponent(search.value.trim())}`)
    const headers = [
      '持证人', '身份证号', '所属部门', '手机号', '邮箱', '人员备注', '证书类型', '发证机构', '证书说明',
      '证书编号', '证书有效期开始（不提醒）', '证书有效期截止（不提醒）', '更新日期', '延期日期', '继续教育日期', '更新网址', '延期网址',
      '继续教育网址', '状态', '提前提醒天数', '持证记录备注',
    ]
    const rows = exportRows.map(item => [
      item.person.name, item.person.identity_number, item.person.department, item.person.phone,
      item.person.email, item.person.notes, item.certificate.name, item.certificate.issuer,
      item.certificate.description, item.certificate_no, item.validity_start_date, item.validity_end_date,
      item.renewal_date, item.expiry_date, item.continuing_education_date, item.renewal_url, item.certificate_url,
      item.education_url, item.active === false ? '停用' : '有效', item.remind_days, item.notes,
    ])
    const date = chinaClock().date
    const searchSuffix = search.value.trim().replace(/[\\/:*?"<>|]/g, '_').slice(0, 30)
    exportXlsx(`持证记录_${searchSuffix || '全部'}_${date}.xlsx`, headers, rows)
    ElMessage.success(`已导出 ${rows.length} 条持证记录`)
  } catch (error) {
    ElMessage.error(`导出失败：${(error as Error).message}`)
  } finally {
    exportingRecords.value = false
  }
}

function notifyUpcoming() {
  if (window.desktop) {
    return
  }
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  for (const item of reminders.value.filter(item => item.days_left <= 7 && item.days_left >= 0)) {
    const key = `certificate-notice:${item.record_id}:${item.event_type}:${item.target_date}`
    if (!localStorage.getItem(key)) {
      new Notification('证书事项提醒', { body: `${item.person} · ${item.certificate}：${item.label} ${item.target_date}` })
      localStorage.setItem(key, '1')
    }
  }
}

function chinaClock() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return { date: `${values.year}-${values.month}-${values.day}`, hour: Number(values.hour) }
}

function reminderState(key: string): { dismissed?: boolean; snoozedUntil?: number } {
  try { return JSON.parse(localStorage.getItem(`certificate-desktop-reminder:${key}`) || '{}') }
  catch { return {} }
}

async function checkDesktopDueReminders() {
  if (!window.desktop || !currentUser.value || !window.desktop.showReminderPopup) return
  const { date, hour } = chinaClock()
  if (hour < 9 || activeDesktopReminderKeys.size > 0) return
  const due = reminders.value.find(item => {
    if (item.target_date !== date || item.days_left !== 0) return false
    const key = `${currentUser.value!.username}:${item.record_id}:${item.event_type}:${item.target_date}`
    if (activeDesktopReminderKeys.has(key)) return false
    const state = reminderState(key)
    return !state.dismissed && !(state.snoozedUntil && state.snoozedUntil > Date.now())
  })
  if (!due) return

  const key = `${currentUser.value.username}:${due.record_id}:${due.event_type}:${due.target_date}`

  activeDesktopReminderKeys.add(key)
  try {
    const opened = await window.desktop.showReminderPopup({
      key,
      person: due.person,
      certificate: due.certificate,
      label: due.label,
      targetDate: due.target_date,
    })
    if (!opened) activeDesktopReminderKeys.delete(key)
  } catch {
    activeDesktopReminderKeys.delete(key)
  }
}

function handleDesktopReminderAction(payload: { key: string; action: 'later' | 'dismiss' }) {
  activeDesktopReminderKeys.delete(payload.key)
  const stateKey = `certificate-desktop-reminder:${payload.key}`
  if (payload.action === 'dismiss') localStorage.setItem(stateKey, JSON.stringify({ dismissed: true }))
  else localStorage.setItem(stateKey, JSON.stringify({ snoozedUntil: Date.now() + 30 * 60 * 1000 }))
  void checkDesktopDueReminders()
}

async function enableNotification() {
  if (window.desktop) {
    void window.desktop.showReminderPopup?.({
      key: `test:${Date.now()}`,
      person: '测试人员',
      certificate: '桌面通知',
      label: '测试弹窗',
      targetDate: chinaClock().date,
    })
    ElMessage.success('桌面提醒已开启；关闭窗口后会继续在系统托盘运行')
    notifyUpcoming()
    return
  }
  if (!('Notification' in window)) { ElMessage.warning('当前浏览器不支持桌面通知'); return }
  const permission = await Notification.requestPermission()
  if (permission === 'granted') { ElMessage.success('桌面提醒已开启'); notifyUpcoming() }
  else ElMessage.info('未获得通知权限，可在浏览器设置中开启')
}

function openCreate(kind: DialogKind) {
  editingId.value = null
  dialogKind.value = kind
  if (kind === 'person') personForm.value = { name: '', phone: '', identity_number: '', email: '', department: '', notes: '' }
  if (kind === 'certificate') certificateForm.value = { name: '', issuer: '', description: '' }
  if (kind === 'record') {
    recordForm.value = { person_id: people.value[0]?.id || 0, certificate_id: certificates.value[0]?.id || 0, certificate_no: '', validity_start_date: '', validity_end_date: '', expiry_date: '', continuing_education_date: '', renewal_date: '', certificate_url: '', education_url: '', renewal_url: '', remind_days: 30, active: true, notes: '' }
    resetRecordAttachmentDraft()
  }
  dialogVisible.value = true
}

function openEdit(kind: DialogKind, item: Person | Certificate | RecordItem) {
  editingId.value = item.id
  dialogKind.value = kind
  if (kind === 'person') {
    const person = item as Person
    personForm.value = { name: person.name, phone: person.phone || '', identity_number: person.identity_number || '', email: person.email || '', department: person.department || '', notes: person.notes || '' }
  }
  if (kind === 'certificate') {
    const certificate = item as Certificate
    certificateForm.value = { name: certificate.name, issuer: certificate.issuer || '', description: certificate.description || '' }
  }
  if (kind === 'record') {
    const record = item as RecordItem
    recordForm.value = { person_id: record.person_id, certificate_id: record.certificate_id, certificate_no: record.certificate_no || '', validity_start_date: record.validity_start_date || '', validity_end_date: record.validity_end_date || '', expiry_date: record.expiry_date || '', continuing_education_date: record.continuing_education_date || '', renewal_date: record.renewal_date || '', certificate_url: record.certificate_url || '', education_url: record.education_url || '', renewal_url: record.renewal_url || '', remind_days: record.remind_days || 30, active: record.active !== false, notes: record.notes || '' }
    resetRecordAttachmentDraft(record.attachments || [])
  }
  dialogVisible.value = true
}

function resetRecordAttachmentDraft(attachments: RecordAttachment[] = []) {
  recordAttachments.value = [...attachments]
  pendingPdfFiles.value = []
  pendingImageFiles.value = []
  removedAttachmentIds.value = new Set()
}

function editPersonRow(item: unknown) { openEdit('person', item as Person) }
function editCertificateRow(item: unknown) { openEdit('certificate', item as Certificate) }
function editRecordRow(item: unknown) { openEdit('record', item as RecordItem) }

function openRecordDetail(item: unknown) {
  detailRecord.value = item as RecordItem
  detailVisible.value = true
}

function openPersonCertificates(item: unknown) {
  selectedPersonId.value = (item as Person).id
  personCertificatesVisible.value = true
}

function openPersonDetail(item: unknown) {
  detailPersonId.value = (item as Person).id
  personDetailVisible.value = true
}

function openCertificateHolders(item: unknown) {
  selectedCertificateId.value = (item as Certificate).id
  certificateHoldersVisible.value = true
}

function formatCertificateValidity(item: unknown) {
  const record = item as RecordItem
  if (!record.validity_start_date && !record.validity_end_date) return '未填写'
  return `${record.validity_start_date || '—'} 至 ${record.validity_end_date || '—'}`
}

function attachmentUrl(recordId: number, attachmentId: number) {
  return `${api}/records/${recordId}/attachments/${attachmentId}`
}

const detailPdfCount = computed(() => detailRecord.value?.attachments?.filter(item => item.kind === 'pdf').length || 0)
const detailImageCount = computed(() => detailRecord.value?.attachments?.filter(item => item.kind === 'image').length || 0)
const visibleRecordAttachments = computed(() => recordAttachments.value.filter(item => !removedAttachmentIds.value.has(item.id)))
const formPdfAttachments = computed(() => visibleRecordAttachments.value.filter(item => item.kind === 'pdf'))
const formImageAttachments = computed(() => visibleRecordAttachments.value.filter(item => item.kind === 'image'))
const pdfSelectionLimit = computed(() => Math.max(0, 9 - formPdfAttachments.value.length))
const imageSelectionLimit = computed(() => Math.max(0, 9 - formImageAttachments.value.length))

async function sendRecordAttachment(recordId: number, kind: 'pdf' | 'image', file: File) {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${api}/records/${recordId}/attachments/${kind}`, {
    method: 'POST', body: form, credentials: 'include', headers: { 'X-CSRF-Token': csrfToken.value },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: '上传失败' }))
    const detail = payload.detail
    throw new Error(Array.isArray(detail) ? detail.map((entry: { msg?: string }) => entry.msg || '').join('；') : detail || '上传失败')
  }
  return await response.json() as RecordAttachment
}

function attachmentLimitReached() { ElMessage.warning('每条持证记录的 PDF 和图片分别最多上传 9 个') }

async function showAttachmentPreview(attachment: RecordAttachment, recordId = detailRecord.value?.id) {
  if (!recordId) return
  closeAttachmentPreview()
  const generation = ++previewGeneration
  const controller = new AbortController()
  previewRequest = controller
  previewAttachment.value = attachment
  previewVisible.value = true
  previewBusy.value = true
  try {
    const response = await fetch(attachmentUrl(recordId, attachment.id), { credentials: 'include', signal: controller.signal })
    if (!response.ok) {
      if (response.status === 401) {
        currentUser.value = null
        csrfToken.value = ''
        throw new Error('登录已过期，请重新登录后查看附件')
      }
      const payload = await response.json().catch(() => ({}))
      throw new Error(typeof payload.detail === 'string' ? payload.detail : '附件读取失败，请稍后重试')
    }
    const blob = await response.blob()
    if (generation !== previewGeneration) return
    previewBlob.value = blob
    // Data URLs are permitted by the site's image policy; blob image URLs are not.
    if (attachment.kind === 'image') {
      const imageUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result))
        reader.onerror = () => reject(new Error('图片读取失败'))
        reader.readAsDataURL(blob)
      })
      if (generation === previewGeneration) previewUrl.value = imageUrl
    }
  } catch (error) {
    if (generation === previewGeneration && !controller.signal.aborted) previewError.value = (error as Error).message
  } finally {
    if (generation === previewGeneration) { previewBusy.value = false; previewRequest = null }
  }
}

function closeAttachmentPreview() {
  ++previewGeneration
  previewRequest?.abort()
  previewRequest = null
  previewVisible.value = false
  previewBusy.value = false
  previewUrl.value = ''
  previewBlob.value = null
  previewError.value = ''
  previewAttachment.value = null
}

function downloadPreviewAttachment() {
  if (!previewBlob.value || !previewAttachment.value) return
  const url = URL.createObjectURL(previewBlob.value)
  const link = document.createElement('a')
  link.href = url
  link.download = previewAttachment.value.filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function toggleAttachmentRemoval(attachmentId: number) {
  const next = new Set(removedAttachmentIds.value)
  if (next.has(attachmentId)) next.delete(attachmentId)
  else next.add(attachmentId)
  removedAttachmentIds.value = next
}

function removePendingAttachment(kind: 'pdf' | 'image', uid: number | undefined) {
  const pending = kind === 'pdf' ? pendingPdfFiles : pendingImageFiles
  pending.value = pending.value.filter(file => file.uid !== uid)
}

function formatAttachmentSize(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function clean<T extends Record<string, unknown>>(value: T) {
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, item === '' ? null : item]))
}

async function saveDialog() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().then(() => true).catch(() => false)
  if (!valid) return
  saving.value = true
  const wasEditing = Boolean(editingId.value)
  let recordSaved: RecordItem | null = null
  try {
    const path = dialogKind.value === 'person' ? '/people' : dialogKind.value === 'certificate' ? '/certificates' : '/records'
    const data = dialogKind.value === 'person' ? clean(personForm.value) : dialogKind.value === 'certificate' ? clean(certificateForm.value) : clean(recordForm.value)
    const result = await request<Person | Certificate | RecordItem>(`${path}${editingId.value ? `/${editingId.value}` : ''}`, { method: wasEditing ? 'PUT' : 'POST', body: JSON.stringify(data) })
    if (dialogKind.value === 'record') {
      recordSaved = result as RecordItem
      editingId.value = recordSaved.id
      recordAttachments.value = [...(recordSaved.attachments || recordAttachments.value)]

      for (const attachmentId of [...removedAttachmentIds.value]) {
        await request(`/records/${recordSaved.id}/attachments/${attachmentId}`, { method: 'DELETE' })
        recordAttachments.value = recordAttachments.value.filter(item => item.id !== attachmentId)
        const next = new Set(removedAttachmentIds.value)
        next.delete(attachmentId)
        removedAttachmentIds.value = next
      }

      for (const [kind, selectedFiles] of [['pdf', pendingPdfFiles.value], ['image', pendingImageFiles.value]] as const) {
        for (const selected of [...selectedFiles]) {
          if (!selected.raw) throw new Error(`无法读取待上传文件“${selected.name}”，请重新选择`)
          const attachment = await sendRecordAttachment(recordSaved.id, kind, selected.raw)
          recordAttachments.value = [...recordAttachments.value, attachment]
          const pending = kind === 'pdf' ? pendingPdfFiles : pendingImageFiles
          pending.value = pending.value.filter(file => file.uid !== selected.uid)
        }
      }
    }
    ElMessage.success(`${dialogKind.value === 'person' ? '人员' : dialogKind.value === 'certificate' ? '证书' : '持证记录'}${wasEditing ? '已更新' : '已新增'}`)
    dialogVisible.value = false
    await load()
  } catch (error) {
    const detail = (error as Error).message
    ElMessage.error(recordSaved ? `持证记录已保存，但附件未全部处理：${detail}` : detail)
  }
  finally { saving.value = false }
}

async function remove(path: string, label: string) {
  try {
    await ElMessageBox.confirm(`删除${label}后，相关联的持证记录也会一并删除。`, '确认删除', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
    await request(path, { method: 'DELETE' })
    ElMessage.success(`${label}已删除`)
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error((error as Error).message)
  }
}

async function check() {
  if (checking.value) return
  checking.value = true
  try {
    const result = await request<{ created: number }>('/reminders/check', { method: 'POST' })
    await load()
    ElMessage.success(result.created > 0 ? `检查完成，新增 ${result.created} 条提醒` : '检查完成，没有新增提醒')
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { checking.value = false }
}

function selectTab(value: string) { tab.value = value as TabKey; search.value = '' }
function shiftMonth(amount: number) { calendarDate.value = new Date(calendarDate.value.getFullYear(), calendarDate.value.getMonth() + amount, 1) }
function eventsForDay(day: string) { return reminders.value.filter(item => item.target_date === day) }
async function checkDesktopUpdate() {
  if (!window.desktop) return
  try { await window.desktop.checkForUpdates() }
  catch (error) { ElMessage.error(`检查更新失败：${(error as Error).message}`) }
}
function openItemUrl(url?: string) {
  if (!url) return
  try {
    const parsed = new URL(url)
    if (parsed.protocol === 'https:' || parsed.protocol === 'http:') window.open(parsed.href, '_blank', 'noopener,noreferrer')
    else ElMessage.warning('仅允许打开 http 或 https 地址')
  } catch { ElMessage.warning('网址格式无效') }
}

watch(currentUser, () => {
  personCertificatesVisible.value = false
  selectedPersonId.value = null
  personDetailVisible.value = false
  detailPersonId.value = null
  certificateHoldersVisible.value = false
  selectedCertificateId.value = null
})
watch(tab, value => { if (value === 'records' || value === 'people' || value === 'certificates') void load() })
onMounted(() => {
  void initializeAuth()
  if (window.desktop) {
    removeUpdateListener = window.desktop.onUpdateStatus(status => {
      if (status.state === 'checking') ElMessage.info('正在检查更新…')
      else if (status.state === 'current') ElMessage.success('当前已是最新版本')
      else if (status.state === 'available') ElMessage.info(`发现新版本 ${status.message}，正在下载…`)
      else if (status.state === 'error') ElMessage.error(`更新检查失败：${status.message || '未知错误'}`)
    })
    reminderTimer = window.setInterval(() => { if (currentUser.value) void load() }, 10 * 60 * 1000)
    desktopPopupTimer = window.setInterval(() => { void checkDesktopDueReminders() }, 30 * 1000)
    removeReminderActionListener = window.desktop.onReminderAction?.(handleDesktopReminderAction)
  }
})
onBeforeUnmount(() => { window.clearInterval(reminderTimer); window.clearInterval(desktopPopupTimer); removeUpdateListener?.(); removeReminderActionListener?.(); closeAttachmentPreview() })
</script>

<template>
  <el-config-provider :locale="zhCn" size="default" :z-index="3000">
    <div v-if="!authReady" class="auth-loading"><el-icon class="is-loading"><Lock /></el-icon><span>正在安全连接…</span></div>
    <main v-else-if="!currentUser" class="login-page">
      <section class="login-card">
        <div class="brand-lockup login-brand">
          <span class="brand-mark">证</span>
          <span><b>证事</b><small>PERSONAL DESK</small></span>
        </div>
        <div class="login-heading"><div class="eyebrow">SECURE SIGN IN</div><h1>欢迎回来</h1><p>登录后管理证书资料与重要日期。</p></div>
        <el-alert v-if="loginError" :title="loginError" type="error" show-icon :closable="false" class="login-alert" />
        <el-form :model="loginForm" label-position="top" @submit.prevent="login">
          <el-form-item label="管理员账号"><el-input v-model="loginForm.username" autocomplete="username" autofocus placeholder="请输入账号" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="loginForm.password" type="password" show-password autocomplete="current-password" placeholder="请输入密码" /></el-form-item>
          <el-button native-type="submit" type="primary" size="large" :loading="loginLoading" class="login-submit">安全登录</el-button>
        </el-form>
        <div class="login-security"><el-icon><Lock /></el-icon><span>仅授权管理员可登录，不开放自助注册</span></div>
      </section>
    </main>
    <el-container v-else class="app-shell">
      <el-aside class="app-aside" width="232px">
        <div class="brand-lockup">
          <span class="brand-mark">证</span>
          <span><b>证事</b><small>PERSONAL DESK</small></span>
        </div>
        <div class="menu-caption">工作台</div>
        <el-menu :default-active="tab" class="side-menu" @select="selectTab">
          <el-menu-item index="dashboard"><el-icon><House /></el-icon><span>总览</span></el-menu-item>
          <el-menu-item index="records"><el-icon><Document /></el-icon><span>持证记录</span></el-menu-item>
          <div class="menu-caption menu-caption-spaced">资料管理</div>
          <el-menu-item index="people"><el-icon><User /></el-icon><span>人员档案</span></el-menu-item>
          <el-menu-item index="certificates"><el-icon><Collection /></el-icon><span>证书类型</span></el-menu-item>
        </el-menu>
        <div class="aside-footer">
          <el-avatar :size="34" class="account-avatar">我</el-avatar>
          <div class="account-copy"><b>我的工作台</b><small>个人证书管理</small></div>
          <el-icon class="footer-more"><MoreFilled /></el-icon>
        </div>
      </el-aside>

      <el-container class="main-shell">
        <el-header class="topbar" height="64px">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>证事</el-breadcrumb-item>
            <el-breadcrumb-item>{{ tab === 'dashboard' ? '总览' : tab === 'records' ? '持证记录' : tab === 'people' ? '人员档案' : '证书类型' }}</el-breadcrumb-item>
          </el-breadcrumb>
          <div class="topbar-actions">
            <el-tag v-if="mockMode" type="warning" effect="plain" round><span class="mock-dot"></span>演示数据</el-tag>
            <el-tooltip content="开启桌面提醒" placement="bottom">
              <el-button text circle :icon="Bell" aria-label="开启桌面提醒" @click="enableNotification" />
            </el-tooltip>
            <el-button v-if="!mockMode" text :icon="Message" @click="openEmailSettings">邮箱提醒</el-button>
            <el-button v-if="desktopMode" text @click="checkDesktopUpdate">检查更新 · {{ appVersion }}</el-button>
            <el-button v-if="!mockMode" text @click="passwordDialogVisible = true">修改密码</el-button>
            <el-button v-if="!mockMode" text type="danger" @click="logout">退出</el-button>
            <el-avatar :size="30" class="account-avatar">{{ currentUser.username.slice(0, 1).toUpperCase() }}</el-avatar>
          </div>
        </el-header>

        <el-main class="workspace">
          <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon closable class="page-alert" @close="errorMessage = ''" />

          <template v-if="tab === 'dashboard'">
            <div class="page-heading">
              <div><div class="eyebrow">PERSONAL CERTIFICATE DESK</div><h1>证书事务，一目了然。</h1><p>把重要日期安排好，让每一次更新和延期都有准备。</p></div>
              <el-button type="primary" :icon="Plus" @click="openCreate('record')">新增持证记录</el-button>
            </div>
            <el-row :gutter="16" class="stats-row">
              <el-col v-for="stat in [
                { label: '人员档案', value: people.length, note: '已纳入管理', icon: UserFilled, tone: 'blue' },
                { label: '证书类型', value: certificates.length, note: '证书目录', icon: Collection, tone: 'purple' },
                { label: '持证记录', value: records.length, note: '人员与证书关联', icon: Tickets, tone: 'green' },
                { label: '近期待办', value: upcoming.length, note: '未来 30 天', icon: Clock, tone: 'orange' },
              ]" :key="stat.label" :xs="12" :sm="12" :md="6">
                <el-card shadow="never" class="stat-card" :class="`stat-${stat.tone}`">
                  <div class="stat-head"><span>{{ stat.label }}</span><span class="stat-icon"><el-icon><component :is="stat.icon" /></el-icon></span></div>
                  <div class="stat-value">{{ stat.value }}</div><div class="stat-note">{{ stat.note }}</div>
                </el-card>
              </el-col>
            </el-row>

            <el-card shadow="never" class="section-card upcoming-card">
              <template #header>
                <div class="section-header">
                  <div><h2>近期需要处理</h2><p>按时间整理延期、更新和继续教育事项；证书有效期仅作记录，不触发提醒</p></div>
                  <div class="section-actions">
                    <el-radio-group v-model="viewMode" size="small" class="view-switch">
                      <el-radio-button value="list"><el-icon><Tickets /></el-icon>列表</el-radio-button>
                      <el-radio-button value="calendar"><el-icon><Calendar /></el-icon>日历</el-radio-button>
                    </el-radio-group>
                    <el-button text type="primary" :icon="Refresh" :loading="checking" @click="check">{{ checking ? '正在检查' : '立即检查' }}</el-button>
                  </div>
                </div>
              </template>
              <div v-if="viewMode === 'list'">
                <el-table v-if="upcoming.length" :data="upcoming" row-key="record_id" class="reminder-table" table-layout="fixed">
                  <el-table-column label="日期" width="112">
                    <template #default="{ row }"><div class="date-cell"><b>{{ row.target_date.slice(5) }}</b><span>{{ row.target_date.slice(0, 4) }}</span></div></template>
                  </el-table-column>
                  <el-table-column prop="person" label="人员" min-width="130" />
                  <el-table-column prop="certificate" label="证书类型" min-width="170" />
                  <el-table-column label="事项" min-width="128">
                    <template #default="{ row }"><el-tag :type="row.event_type === 'expiry' ? 'danger' : row.event_type === 'education' ? 'success' : 'warning'" effect="light" round>{{ row.label }}</el-tag></template>
                  </el-table-column>
                  <el-table-column label="剩余时间" width="126" align="right">
                    <template #default="{ row }"><el-tag :type="row.days_left < 0 ? 'danger' : row.days_left <= 7 ? 'warning' : 'info'" effect="plain">{{ row.days_left < 0 ? `逾期 ${-row.days_left} 天` : row.days_left === 0 ? '今天' : `${row.days_left} 天后` }}</el-tag></template>
                  </el-table-column>
                </el-table>
                <el-empty v-else description="未来 30 天没有待办事项" :image-size="72" />
              </div>
              <el-calendar v-else v-model="calendarDate" class="task-calendar">
                <template #header>
                  <div class="calendar-header"><div class="calendar-month">{{ monthTitle }}</div><el-button-group>
                    <el-button size="small" :icon="ArrowLeft" @click="shiftMonth(-1)">上月</el-button>
                    <el-button size="small" @click="calendarDate = new Date()">今天</el-button>
                    <el-button size="small" :icon="ArrowRight" @click="shiftMonth(1)">下月</el-button>
                  </el-button-group></div>
                </template>
                <template #date-cell="{ data }">
                  <div class="calendar-day" :class="{ 'is-other-month': data.type !== 'current-month' }">
                    <span class="calendar-day-number">{{ data.day.split('-')[2] }}</span>
                    <el-tooltip v-for="item in eventsForDay(data.day).slice(0, 2)" :key="`${item.record_id}-${item.event_type}`" :content="`${item.person} · ${item.certificate} · ${item.label}`" placement="top">
                      <el-tag size="small" effect="light" :type="item.event_type === 'expiry' ? 'danger' : item.event_type === 'education' ? 'success' : 'warning'" class="calendar-event">{{ item.person }} · {{ item.label }}</el-tag>
                    </el-tooltip>
                    <span v-if="eventsForDay(data.day).length > 2" class="calendar-overflow">+{{ eventsForDay(data.day).length - 2 }} 项</span>
                  </div>
                </template>
              </el-calendar>
            </el-card>

            <el-row :gutter="16" class="bottom-row">
              <el-col :xs="24" :md="10"><el-card shadow="never" class="section-card quick-card"><template #header><div class="simple-card-heading"><h2>快速创建</h2><span>常用资料入口</span></div></template>
                <div class="quick-actions"><el-button plain :icon="User" @click="openCreate('person')">新增人员</el-button><el-button plain :icon="Collection" @click="openCreate('certificate')">新增证书类型</el-button></div>
              </el-card></el-col>
              <el-col :xs="24" :md="14"><el-card shadow="never" class="section-card tip-card"><div class="tip-symbol"><el-icon><FolderOpened /></el-icon></div><div><el-text type="primary" size="small">管理小贴士</el-text><h2>重要日期，早一点知道。</h2><p>为每条持证记录填写更新、延期和继续教育日期，系统会在总览中统一提醒；证书有效期只记录、不提醒。</p><el-button link type="primary" @click="selectTab('records')">查看全部持证记录 <el-icon><ArrowRight /></el-icon></el-button></div></el-card></el-col>
            </el-row>
          </template>

          <template v-else-if="tab === 'records'">
            <div class="page-heading"><div><div class="eyebrow">CERTIFICATE PORTFOLIO</div><h1>持证记录</h1><p>人员、证书、三类日期与对应网址统一维护。</p></div><el-button type="primary" :icon="Plus" @click="openCreate('record')">新增持证记录</el-button></div>
            <el-card shadow="never" class="section-card data-card">
              <div class="table-toolbar"><div><h2>全部记录 <el-tag effect="plain" round>{{ visibleRecords.length }}</el-tag></h2><p>可按人员、证书名称或证书编号检索</p></div><div class="toolbar-controls"><el-input v-model="search" clearable :prefix-icon="Search" placeholder="搜索持证记录" class="toolbar-search" /><el-button :icon="Download" :loading="exportingRecords" :disabled="visibleRecords.length === 0" @click="exportRecords">导出 Excel</el-button></div></div>
              <el-table :data="visibleRecords" row-key="id" class="data-table" table-layout="auto">
                <el-table-column label="持证人" min-width="170"><template #default="{ row }"><div class="person-cell"><el-avatar :size="34" class="person-avatar">{{ row.person.name.slice(0, 1) }}</el-avatar><div><b>{{ row.person.name }}</b><small>{{ row.certificate_no || '未填写编号' }}</small></div></div></template></el-table-column>
                <el-table-column label="证书类型" min-width="150"><template #default="{ row }"><el-text>{{ row.certificate.name }}</el-text></template></el-table-column>
                <el-table-column label="证书有效期（不提醒）" min-width="190"><template #default="{ row }">{{ row.validity_start_date || row.validity_end_date ? `${row.validity_start_date || '—'} 至 ${row.validity_end_date || '—'}` : '—' }}</template></el-table-column>
                <el-table-column prop="renewal_date" label="更新日期" min-width="120"><template #default="{ row }">{{ row.renewal_date || '—' }}</template></el-table-column>
                <el-table-column prop="expiry_date" label="延期日期" min-width="120"><template #default="{ row }">{{ row.expiry_date || '—' }}</template></el-table-column>
                <el-table-column prop="continuing_education_date" label="继续教育日期" min-width="140"><template #default="{ row }">{{ row.continuing_education_date || '—' }}</template></el-table-column>
                <el-table-column label="办理入口" min-width="190"><template #default="{ row }"><div class="link-list"><el-button v-if="row.renewal_url" link type="primary" @click="openItemUrl(row.renewal_url)">更新</el-button><el-button v-if="row.certificate_url" link type="primary" @click="openItemUrl(row.certificate_url)">延期</el-button><el-button v-if="row.education_url" link type="primary" @click="openItemUrl(row.education_url)">继续教育</el-button><span v-if="!row.renewal_url && !row.certificate_url && !row.education_url">—</span></div></template></el-table-column>
                <el-table-column label="状态" width="94"><template #default="{ row }"><el-tag :type="row.active === false ? 'info' : 'success'" effect="light" round>{{ row.active === false ? '已停用' : '有效' }}</el-tag></template></el-table-column>
                <el-table-column label="操作" width="172" fixed="right" align="right"><template #default="{ row }"><el-button link type="primary" @click="openRecordDetail(row)">详情</el-button><el-button link type="primary" @click="editRecordRow(row)">编辑</el-button><el-button link type="danger" @click="remove(`/records/${row.id}`, '持证记录')">删除</el-button></template></el-table-column>
                <template #empty><el-empty description="没有符合条件的持证记录" :image-size="64" /></template>
              </el-table>
            </el-card>
          </template>

          <template v-else-if="tab === 'people'">
            <div class="page-heading"><div><div class="eyebrow">PEOPLE DIRECTORY</div><h1>人员档案</h1><p>维护人员基本信息，快速查看其持证情况。</p></div><el-button type="primary" :icon="Plus" @click="openCreate('person')">新增人员</el-button></div>
            <el-card shadow="never" class="section-card data-card">
              <div class="table-toolbar"><div><h2>人员列表 <el-tag effect="plain" round>{{ people.length }}</el-tag></h2><p>人员基本资料与持证数量</p></div><el-input v-model="search" clearable :prefix-icon="Search" placeholder="搜索人员" class="toolbar-search" /></div>
              <el-table :data="visiblePeople" row-key="id" class="data-table">
                <el-table-column label="姓名" min-width="180"><template #default="{ row }"><div class="person-cell"><el-avatar :size="34" class="person-avatar">{{ row.name.slice(0,1) }}</el-avatar><b>{{ row.name }}</b></div></template></el-table-column>
                <el-table-column prop="identity_number" label="身份证号" min-width="220"><template #default="{ row }">{{ row.identity_number || '—' }}</template></el-table-column>
                <el-table-column prop="phone" label="手机号" min-width="160"><template #default="{ row }">{{ row.phone || '—' }}</template></el-table-column>
                <el-table-column prop="email" label="邮箱" min-width="200"><template #default="{ row }">{{ row.email || '—' }}</template></el-table-column>
                <el-table-column label="持证数量" width="120"><template #default="{ row }"><el-button link type="primary" :aria-label="`查看${row.name}的持证证书`" @click="openPersonCertificates(row)">{{ recordsByPerson.get(row.id)?.length || 0 }} 项</el-button></template></el-table-column>
                <el-table-column label="操作" width="180" fixed="right" align="right"><template #default="{ row }"><el-button link type="primary" :aria-label="`查看${row.name}的人员详情`" @click="openPersonDetail(row)">详情</el-button><el-button link type="primary" @click="editPersonRow(row)">编辑</el-button><el-button link type="danger" @click="remove(`/people/${row.id}`, '人员档案')">删除</el-button></template></el-table-column>
                <template #empty><el-empty description="还没有人员档案" :image-size="64" /></template>
              </el-table>
            </el-card>
          </template>

          <template v-else>
            <div class="page-heading"><div><div class="eyebrow">CERTIFICATE CATALOG</div><h1>证书类型</h1><p>维护证书类别和发证机构，供持证记录关联。</p></div><el-button type="primary" :icon="Plus" @click="openCreate('certificate')">新增证书类型</el-button></div>
            <el-card shadow="never" class="section-card data-card">
              <div class="table-toolbar"><div><h2>证书目录 <el-tag effect="plain" round>{{ certificates.length }}</el-tag></h2><p>证书类型与发证机构</p></div><el-input v-model="search" clearable :prefix-icon="Search" placeholder="搜索证书类型" class="toolbar-search" /></div>
              <el-table :data="visibleCertificates" row-key="id" class="data-table">
                <el-table-column label="证书名称" min-width="220"><template #default="{ row }"><div class="certificate-cell"><span class="certificate-symbol"><el-icon><Tickets /></el-icon></span><b>{{ row.name }}</b></div></template></el-table-column>
                <el-table-column prop="issuer" label="发证机构" min-width="220"><template #default="{ row }">{{ row.issuer || '—' }}</template></el-table-column>
                <el-table-column prop="description" label="说明" min-width="220"><template #default="{ row }">{{ row.description || '—' }}</template></el-table-column>
                <el-table-column label="持证人数" width="120"><template #default="{ row }"><el-button link type="primary" :aria-label="`查看${row.name}的持证人员`" @click="openCertificateHolders(row)">{{ holdersByCertificate.get(row.id)?.length || 0 }} 人</el-button></template></el-table-column>
                <el-table-column label="操作" width="118" fixed="right" align="right"><template #default="{ row }"><el-button link type="primary" @click="editCertificateRow(row)">编辑</el-button><el-button link type="danger" @click="remove(`/certificates/${row.id}`, '证书类型')">删除</el-button></template></el-table-column>
                <template #empty><el-empty description="还没有证书类型" :image-size="64" /></template>
              </el-table>
            </el-card>
          </template>
          <footer class="page-footer"><span>证事 · 让证书管理简单一点</span><span>{{ mockMode ? '演示数据 · 保存在当前浏览器' : `实时数据 · 服务端持久化${desktopMode ? ` · 桌面版 ${appVersion}` : ''}` }}</span></footer>
        </el-main>
      </el-container>
    </el-container>

    <el-dialog v-model="personCertificatesVisible" :title="`${selectedPerson?.name || '人员'}的持证证书`" width="min(900px, calc(100vw - 32px))" align-center destroy-on-close @closed="selectedPersonId = null">
      <el-table :data="selectedPersonCertificates" row-key="id" max-height="480" table-layout="auto">
        <el-table-column prop="certificate.name" label="证书类型" min-width="180" />
        <el-table-column label="证书编号" min-width="220"><template #default="{ row }">{{ row.certificate_no || '未填写' }}</template></el-table-column>
        <el-table-column label="证书有效期" min-width="240"><template #default="{ row }">{{ formatCertificateValidity(row) }}</template></el-table-column>
        <template #empty><el-empty description="该人员暂无持证记录" :image-size="64" /></template>
      </el-table>
      <template #footer><el-button @click="personCertificatesVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="personDetailVisible" :title="`${detailPerson?.name || '人员'}的档案详情`" width="min(900px, calc(100vw - 32px))" align-center destroy-on-close @closed="detailPersonId = null">
      <div v-if="detailPerson" class="detail-content person-detail-content">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="姓名">{{ detailPerson.name }}</el-descriptions-item>
          <el-descriptions-item label="身份证号">{{ detailPerson.identity_number || '—' }}</el-descriptions-item>
          <el-descriptions-item label="手机号">{{ detailPerson.phone || '—' }}</el-descriptions-item>
          <el-descriptions-item label="邮箱">{{ detailPerson.email || '—' }}</el-descriptions-item>
          <el-descriptions-item label="部门">{{ detailPerson.department || '—' }}</el-descriptions-item>
          <el-descriptions-item label="备注"><span class="person-detail-notes">{{ detailPerson.notes || '—' }}</span></el-descriptions-item>
        </el-descriptions>
        <div class="detail-section-heading"><div><h3>持证证书</h3><span>{{ detailPersonCertificates.length }} 项</span></div></div>
        <el-table :data="detailPersonCertificates" row-key="id" max-height="360" table-layout="auto">
          <el-table-column prop="certificate.name" label="证书类型" min-width="180" />
          <el-table-column label="证书编号" min-width="220"><template #default="{ row }">{{ row.certificate_no || '未填写' }}</template></el-table-column>
          <el-table-column label="证书有效期" min-width="240"><template #default="{ row }">{{ formatCertificateValidity(row) }}</template></el-table-column>
          <el-table-column label="操作" width="100" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openRecordDetail(row)">查看证书</el-button></template></el-table-column>
          <template #empty><el-empty description="该人员暂无持证记录" :image-size="64" /></template>
        </el-table>
      </div>
      <el-empty v-else description="该人员档案已不存在" :image-size="64" />
      <template #footer><el-button @click="personDetailVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="certificateHoldersVisible" :title="`${selectedCertificate?.name || '证书类型'}的持证人员`" width="min(540px, calc(100vw - 32px))" align-center destroy-on-close @closed="selectedCertificateId = null">
      <el-table :data="selectedCertificateHolders" row-key="id" max-height="480">
        <el-table-column type="index" label="序号" width="70" />
        <el-table-column prop="name" label="姓名" min-width="180" />
        <el-table-column label="证书到期时间" min-width="180"><template #default="{ row }"><div v-for="endDate in row.validityEndDates" :key="endDate">{{ endDate || '未填写' }}</div></template></el-table-column>
        <template #empty><el-empty description="该证书类型暂无持证人员" :image-size="64" /></template>
      </el-table>
      <template #footer><el-button @click="certificateHoldersVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="min(660px, calc(100vw - 32px))" :close-on-click-modal="false" class="form-dialog" align-center destroy-on-close>
      <p class="dialog-description">{{ dialogKind === 'record' ? '完善证书关联、重要日期和办理入口。' : '信息仅用于证书管理和日期提醒。' }}</p>
      <el-form v-if="dialogKind === 'person'" ref="formRef" :model="personForm" :rules="dialogRules" label-position="top" class="form-grid">
        <el-form-item label="姓名" prop="name"><el-input v-model="personForm.name" placeholder="例如：林晓雯" maxlength="100" /></el-form-item>
        <el-form-item label="手机号" prop="phone"><el-input v-model="personForm.phone" placeholder="选填" /></el-form-item>
        <el-form-item label="所属部门" prop="department"><el-input v-model="personForm.department" placeholder="例如：工程部" /></el-form-item>
        <el-form-item label="身份证号（选填）" prop="identity_number"><el-input v-model="personForm.identity_number" placeholder="请输入身份证号码" maxlength="18" show-word-limit /></el-form-item>
        <el-form-item label="邮箱" prop="email"><el-input v-model="personForm.email" type="email" placeholder="选填" /></el-form-item>
        <el-form-item label="备注" prop="notes" class="span-two"><el-input v-model="personForm.notes" type="textarea" :rows="3" placeholder="补充信息（选填）" /></el-form-item>
      </el-form>
      <el-form v-else-if="dialogKind === 'certificate'" ref="formRef" :model="certificateForm" :rules="dialogRules" label-position="top" class="form-grid">
        <el-form-item label="证书名称" prop="name" class="span-two"><el-input v-model="certificateForm.name" placeholder="例如：一级建造师" maxlength="150" /></el-form-item>
        <el-form-item label="发证机构" prop="issuer" class="span-two"><el-input v-model="certificateForm.issuer" placeholder="例如：住房和城乡建设部" /></el-form-item>
        <el-form-item label="说明" prop="description" class="span-two"><el-input v-model="certificateForm.description" type="textarea" :rows="3" placeholder="证书类别或其他说明" /></el-form-item>
      </el-form>
      <el-form v-else ref="formRef" :model="recordForm" :rules="dialogRules" label-position="top" class="form-grid record-form-grid">
        <div class="form-section span-two"><div><b>证书归属</b><span>选择人员及证书类型</span></div></div>
        <el-form-item label="持证人员" prop="person_id"><el-select v-model="recordForm.person_id" filterable placeholder="选择人员"><el-option v-for="person in people" :key="person.id" :label="person.name" :value="person.id" /></el-select></el-form-item>
        <el-form-item label="证书类型" prop="certificate_id"><el-select v-model="recordForm.certificate_id" filterable placeholder="选择证书"><el-option v-for="certificate in certificates" :key="certificate.id" :label="certificate.name" :value="certificate.id" /></el-select></el-form-item>
        <el-form-item label="证书编号" prop="certificate_no" class="span-two"><el-input v-model="recordForm.certificate_no" placeholder="证书上的编号（选填）" /></el-form-item>
        <div class="form-section span-two"><div><b>证书有效期</b><span>只记录有效起止时间，不触发提醒</span></div></div>
        <el-form-item label="有效期时间段（不提醒）" class="span-two"><el-date-picker v-model="validityRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="截止日期" unlink-panels /></el-form-item>
        <div class="form-section span-two"><div><b>提醒日期</b><span>系统按更新、延期和继续教育日期提醒</span></div></div>
        <el-form-item label="更新日期"><el-date-picker v-model="recordForm.renewal_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" /></el-form-item>
        <el-form-item label="延期日期"><el-date-picker v-model="recordForm.expiry_date" type="date" value-format="YYYY-MM-DD" placeholder="选择延期办理/提醒日期" /></el-form-item>
        <el-form-item label="继续教育日期"><el-date-picker v-model="recordForm.continuing_education_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" /></el-form-item>
        <div class="form-section span-two"><div><b>对应办理网址</b><span>分别填写更新、延期和继续教育入口</span></div></div>
        <el-form-item label="更新网址" class="span-two"><el-input v-model="recordForm.renewal_url" :prefix-icon="Link" placeholder="https://" /></el-form-item>
        <el-form-item label="延期网址" class="span-two"><el-input v-model="recordForm.certificate_url" :prefix-icon="Link" placeholder="https://" /></el-form-item>
        <el-form-item label="继续教育网址" class="span-two"><el-input v-model="recordForm.education_url" :prefix-icon="Link" placeholder="https://" /></el-form-item>
        <el-form-item label="提前提醒天数"><el-input-number v-model="recordForm.remind_days" :min="1" :max="3650" controls-position="right" /></el-form-item>
        <el-form-item label="记录状态"><el-switch v-model="recordForm.active" active-text="有效" inactive-text="停用" /></el-form-item>
        <el-form-item label="备注" class="span-two"><el-input v-model="recordForm.notes" type="textarea" :rows="2" placeholder="选填" /></el-form-item>
        <div class="form-section span-two"><div><b>证书附件</b><span>保存记录时上传；PDF 和图片分别最多 9 个</span></div></div>
        <el-alert v-if="mockMode" class="span-two form-hint" title="演示模式不支持服务器附件，请连接服务器后管理证书文件。" type="info" :closable="false" show-icon />
        <div class="attachment-section span-two form-attachment-section">
          <div class="detail-section-heading"><div><h3>PDF 证书</h3><span>{{ formPdfAttachments.length + pendingPdfFiles.length }}/9 个 · 单个不超过 15 MB</span></div>
            <el-upload v-model:file-list="pendingPdfFiles" :auto-upload="false" :multiple="true" :limit="pdfSelectionLimit" :disabled="mockMode || pdfSelectionLimit === 0" :show-file-list="false" accept=".pdf" :on-exceed="attachmentLimitReached">
              <el-button type="primary" plain :disabled="mockMode || pdfSelectionLimit === 0"><el-icon><UploadFilled /></el-icon>选择 PDF</el-button>
            </el-upload>
          </div>
          <div v-for="selected in pendingPdfFiles" :key="selected.uid" class="attachment-row attachment-row-pending">
            <div class="attachment-file-icon pdf-file"><el-icon><Document /></el-icon></div>
            <div class="attachment-filename"><b>{{ selected.name }}</b><span>{{ formatAttachmentSize(selected.size || 0) }} · 保存时上传</span></div>
            <el-button link type="danger" @click="removePendingAttachment('pdf', selected.uid)">移除</el-button>
          </div>
          <div v-for="attachment in recordAttachments.filter(item => item.kind === 'pdf')" :key="attachment.id" class="attachment-row" :class="{ 'attachment-row-removing': removedAttachmentIds.has(attachment.id) }">
            <div class="attachment-file-icon pdf-file"><el-icon><Document /></el-icon></div>
            <div class="attachment-filename"><b>{{ attachment.filename }}</b><span>{{ formatAttachmentSize(attachment.size_bytes) }}<template v-if="removedAttachmentIds.has(attachment.id)"> · 保存时删除</template></span></div>
            <el-button link type="primary" :loading="previewBusy" @click="showAttachmentPreview(attachment, editingId || undefined)">查看</el-button>
            <el-button v-if="editingId" link :type="removedAttachmentIds.has(attachment.id) ? 'primary' : 'danger'" @click="toggleAttachmentRemoval(attachment.id)">{{ removedAttachmentIds.has(attachment.id) ? '撤销' : '移除' }}</el-button>
          </div>
          <el-empty v-if="!recordAttachments.some(item => item.kind === 'pdf') && !pendingPdfFiles.length" description="尚无 PDF 证书" :image-size="48" />
        </div>
        <div class="attachment-section span-two form-attachment-section">
          <div class="detail-section-heading"><div><h3>图片证书</h3><span>{{ formImageAttachments.length + pendingImageFiles.length }}/9 张 · PNG、JPG、WebP，每张不超过 15 MB</span></div>
            <el-upload v-model:file-list="pendingImageFiles" :auto-upload="false" :multiple="true" :limit="imageSelectionLimit" :disabled="mockMode || imageSelectionLimit === 0" :show-file-list="false" accept=".png,.jpg,.jpeg,.webp" :on-exceed="attachmentLimitReached">
              <el-button type="primary" plain :disabled="mockMode || imageSelectionLimit === 0"><el-icon><UploadFilled /></el-icon>选择图片</el-button>
            </el-upload>
          </div>
          <div v-for="selected in pendingImageFiles" :key="selected.uid" class="attachment-row attachment-row-pending">
            <div class="attachment-file-icon image-file"><el-icon><Picture /></el-icon></div>
            <div class="attachment-filename"><b>{{ selected.name }}</b><span>{{ formatAttachmentSize(selected.size || 0) }} · 保存时上传</span></div>
            <el-button link type="danger" @click="removePendingAttachment('image', selected.uid)">移除</el-button>
          </div>
          <div v-for="attachment in recordAttachments.filter(item => item.kind === 'image')" :key="attachment.id" class="attachment-row" :class="{ 'attachment-row-removing': removedAttachmentIds.has(attachment.id) }">
            <div class="attachment-file-icon image-file"><el-icon><Picture /></el-icon></div>
            <div class="attachment-filename"><b>{{ attachment.filename }}</b><span>{{ formatAttachmentSize(attachment.size_bytes) }}<template v-if="removedAttachmentIds.has(attachment.id)"> · 保存时删除</template></span></div>
            <el-button link type="primary" :loading="previewBusy" @click="showAttachmentPreview(attachment, editingId || undefined)">查看</el-button>
            <el-button v-if="editingId" link :type="removedAttachmentIds.has(attachment.id) ? 'primary' : 'danger'" @click="toggleAttachmentRemoval(attachment.id)">{{ removedAttachmentIds.has(attachment.id) ? '撤销' : '移除' }}</el-button>
          </div>
          <el-empty v-if="!recordAttachments.some(item => item.kind === 'image') && !pendingImageFiles.length" description="尚无图片证书" :image-size="48" />
        </div>
        <el-alert v-if="!people.length || !certificates.length" class="span-two form-hint" title="请先建立至少一位人员和一种证书类型。" type="warning" :closable="false" show-icon />
      </el-form>
      <template #footer><div class="dialog-footer"><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="dialogKind === 'record' && (!people.length || !certificates.length)" @click="saveDialog">{{ editingId ? '保存修改' : '保存' }}</el-button></div></template>
    </el-dialog>

    <el-drawer v-model="detailVisible" :size="'min(680px, 96vw)'" :with-header="false" class="record-detail-drawer" destroy-on-close>
      <template v-if="detailRecord">
        <div class="detail-heading">
          <div><div class="eyebrow">CERTIFICATE DETAILS</div><h2>{{ detailRecord.certificate.name }}</h2><p>{{ detailRecord.person.name }}<span v-if="detailRecord.certificate_no"> · {{ detailRecord.certificate_no }}</span></p></div>
          <el-button text circle aria-label="关闭详情" @click="detailVisible = false">×</el-button>
        </div>
        <div class="detail-content">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="持证人">{{ detailRecord.person.name }}</el-descriptions-item>
            <el-descriptions-item label="证书类型">{{ detailRecord.certificate.name }}</el-descriptions-item>
            <el-descriptions-item label="证书编号">{{ detailRecord.certificate_no || '—' }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ detailRecord.active === false ? '已停用' : '有效' }}</el-descriptions-item>
            <el-descriptions-item label="证书有效期（不提醒）">{{ detailRecord.validity_start_date || detailRecord.validity_end_date ? `${detailRecord.validity_start_date || '—'} 至 ${detailRecord.validity_end_date || '—'}` : '—' }}</el-descriptions-item>
            <el-descriptions-item label="更新日期">{{ detailRecord.renewal_date || '—' }}</el-descriptions-item>
            <el-descriptions-item label="延期日期">{{ detailRecord.expiry_date || '—' }}</el-descriptions-item>
            <el-descriptions-item label="继续教育日期">{{ detailRecord.continuing_education_date || '—' }}</el-descriptions-item>
            <el-descriptions-item label="提前提醒">{{ detailRecord.remind_days }} 天</el-descriptions-item>
            <el-descriptions-item label="备注">{{ detailRecord.notes || '—' }}</el-descriptions-item>
          </el-descriptions>

          <div class="attachment-section">
            <div class="detail-section-heading"><div><h3>PDF 证书</h3><span>{{ detailPdfCount }}/9 个</span></div></div>
            <el-empty v-if="!detailRecord.attachments?.some(item => item.kind === 'pdf')" description="尚未上传 PDF 证书" :image-size="54" />
            <div v-else class="attachment-list">
              <div v-for="attachment in detailRecord.attachments.filter(item => item.kind === 'pdf')" :key="attachment.id" class="attachment-row">
                <div class="attachment-file-icon pdf-file"><el-icon><Document /></el-icon></div>
                <div class="attachment-filename"><b>{{ attachment.filename }}</b><span>{{ formatAttachmentSize(attachment.size_bytes) }}</span></div>
                <el-button link type="primary" :loading="previewBusy" @click="showAttachmentPreview(attachment)">查看</el-button>
              </div>
            </div>
          </div>

          <div class="attachment-section">
            <div class="detail-section-heading"><div><h3>图片证书</h3><span>{{ detailImageCount }}/9 张</span></div></div>
            <el-empty v-if="!detailRecord.attachments?.some(item => item.kind === 'image')" description="尚未上传图片证书" :image-size="54" />
            <div v-else class="attachment-list">
              <div v-for="attachment in detailRecord.attachments.filter(item => item.kind === 'image')" :key="attachment.id" class="attachment-row">
                <div class="attachment-file-icon image-file"><el-icon><Picture /></el-icon></div>
                <div class="attachment-filename"><b>{{ attachment.filename }}</b><span>{{ formatAttachmentSize(attachment.size_bytes) }}</span></div>
                <el-button link type="primary" :loading="previewBusy" @click="showAttachmentPreview(attachment)">查看</el-button>
              </div>
            </div>
          </div>
        </div>
        <div class="detail-footer"><el-button @click="detailVisible = false">关闭</el-button></div>
      </template>
    </el-drawer>

    <el-dialog v-model="previewVisible" :title="previewAttachment?.filename || '证书预览'" width="min(880px, calc(100vw - 32px))" class="attachment-preview-dialog" align-center destroy-on-close @close="closeAttachmentPreview">
      <div v-loading="previewBusy" class="attachment-preview-content">
        <el-alert v-if="previewError" :title="previewError" type="error" show-icon :closable="false" />
        <PdfCertificatePreview v-else-if="previewBlob && previewAttachment?.kind === 'pdf'" :blob="previewBlob" />
        <div v-else class="attachment-preview-stage">
          <img v-if="previewUrl" :src="previewUrl" :alt="previewAttachment?.filename" class="image-preview" />
          <span v-else-if="previewBusy">正在读取证书…</span>
        </div>
      </div>
      <template #footer><el-button :disabled="!previewBlob" :icon="Download" @click="downloadPreviewAttachment">下载原文件</el-button><el-button @click="previewVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="emailSettingsVisible" title="邮箱提醒设置" width="min(540px, calc(100vw - 32px))" :close-on-click-modal="false" align-center>
      <div v-loading="emailSettingsLoading" class="email-settings-content">
        <p class="email-settings-description">绑定并验证接收邮箱后，系统会发送提前提醒和事项当天提醒。这里填写收件地址，不需要提供邮箱登录密码。</p>
        <el-alert v-if="!emailSettings.smtp_configured" title="服务器还没有配置发信邮箱，当前无法发送验证码。请管理员先配置 SMTP。" type="warning" show-icon :closable="false" />
        <div v-if="emailSettings.verified" class="email-current-binding">
          <div><el-tag type="success" effect="light" round>已验证</el-tag><span>{{ emailSettings.email }}</span></div>
          <div class="email-binding-actions"><el-button link type="primary" :loading="emailActionLoading" @click="sendTestEmail">发送测试邮件</el-button><el-button link type="danger" @click="unbindEmail">解除绑定</el-button></div>
        </div>
        <el-form label-position="top" class="email-binding-form">
          <el-form-item :label="emailSettings.verified ? '更换接收邮箱' : '接收邮箱'">
            <el-input v-model="emailForm.email" type="email" autocomplete="email" placeholder="name@example.com" :disabled="!emailSettings.smtp_configured" />
          </el-form-item>
          <el-form-item label="邮箱验证码">
            <div class="email-code-row"><el-input v-model="emailForm.code" maxlength="6" inputmode="numeric" autocomplete="one-time-code" placeholder="输入 6 位验证码" :disabled="!emailSettings.smtp_configured" /><el-button plain :loading="emailActionLoading" :disabled="!emailSettings.smtp_configured" @click="sendEmailCode">发送验证码</el-button></div>
          </el-form-item>
        </el-form>
        <el-alert v-if="emailSettings.pending_email" :title="`验证码已发送至 ${emailSettings.pending_email}，10 分钟内有效；原绑定邮箱在验证完成前仍继续接收提醒。`" type="info" :closable="false" />
      </div>
      <template #footer><div class="dialog-footer"><el-button @click="emailSettingsVisible = false">关闭</el-button><el-button type="primary" :loading="emailActionLoading" :disabled="!emailSettings.smtp_configured" @click="verifyEmail">验证并绑定</el-button></div></template>
    </el-dialog>

    <el-dialog v-model="passwordDialogVisible" title="修改登录密码" width="min(460px, calc(100vw - 32px))" :close-on-click-modal="false" align-center>
      <el-form :model="passwordForm" label-position="top" @submit.prevent="changePassword">
        <el-form-item label="当前密码"><el-input v-model="passwordForm.current_password" type="password" show-password autocomplete="current-password" /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="passwordForm.new_password" type="password" show-password autocomplete="new-password" placeholder="至少 14 个字符" /></el-form-item>
        <el-form-item label="确认新密码"><el-input v-model="passwordForm.confirm_password" type="password" show-password autocomplete="new-password" /></el-form-item>
      </el-form>
      <template #footer><div class="dialog-footer"><el-button @click="passwordDialogVisible = false">取消</el-button><el-button type="primary" :loading="passwordSaving" @click="changePassword">修改并重新登录</el-button></div></template>
    </el-dialog>
  </el-config-provider>
</template>
