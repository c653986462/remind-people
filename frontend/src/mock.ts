import type { WebsiteDetails } from './website-details'

export type Person = { id: number; name: string; phone?: string; identity_number?: string; email?: string; department?: string; notes?: string }
export type Certificate = { id: number; name: string; issuer?: string; description?: string } & WebsiteDetails
export type RecordAttachment = { id: number; kind: 'pdf' | 'image'; filename: string; content_type: string; size_bytes: number; created_at: string }
export type RecordItem = {
  id: number; person_id: number; certificate_id: number; certificate_no?: string
  validity_start_date?: string; validity_end_date?: string
  expiry_date?: string; continuing_education_date?: string; renewal_date?: string
  remind_days: number; active?: boolean; notes?: string
  attachments?: RecordAttachment[]
  person: Person; certificate: Certificate
} & WebsiteDetails
export type Reminder = { record_id: number; person: string; certificate: string; event_type: string; label: string; target_date: string; days_left: number }

type State = { people: Person[]; certificates: Certificate[]; records: Omit<RecordItem, 'person' | 'certificate'>[] }
const STORAGE_KEY = 'certificate-manager-mock-v2'
const future = (days: number) => { const d = new Date(); d.setDate(d.getDate() + days); return d.toISOString().slice(0, 10) }
const initial: State = {
  people: [
    { id: 1, name: '林晓雯', phone: '138 0000 1288', department: '工程部', email: 'lin@example.com' },
    { id: 2, name: '陈志远', phone: '139 0000 5632', department: '项目管理部' },
    { id: 3, name: '周敏', phone: '137 0000 4410', department: '财务部' },
  ],
  certificates: [
    { id: 1, name: '一级建造师', issuer: '住房和城乡建设部' },
    { id: 2, name: '注册安全工程师', issuer: '应急管理部' },
    { id: 3, name: '中级会计师', issuer: '财政部' },
  ],
  records: [
    { id: 1, person_id: 1, certificate_id: 1, certificate_no: '建造 0110234567', validity_start_date: future(-900), validity_end_date: future(12), expiry_date: future(12), continuing_education_date: future(42), renewal_date: future(120), certificate_url: 'https://www.mohurd.gov.cn/', education_url: 'https://www.mohurd.gov.cn/', renewal_url: 'https://www.mohurd.gov.cn/', remind_days: 30, active: true, notes: '' },
    { id: 2, person_id: 1, certificate_id: 2, certificate_no: '安全 2021-00882', validity_start_date: future(-620), validity_end_date: future(86), expiry_date: future(86), continuing_education_date: future(5), renewal_date: future(160), certificate_url: 'https://www.mem.gov.cn/', education_url: 'https://www.mem.gov.cn/', renewal_url: 'https://www.mem.gov.cn/', remind_days: 30, active: true, notes: '' },
    { id: 3, person_id: 2, certificate_id: 1, certificate_no: '建造 0110238871', validity_start_date: future(-1200), validity_end_date: future(180), expiry_date: future(180), continuing_education_date: future(220), renewal_date: future(250), certificate_url: 'https://www.mohurd.gov.cn/', education_url: 'https://www.mohurd.gov.cn/', renewal_url: 'https://www.mohurd.gov.cn/', remind_days: 45, active: true, notes: '' },
    { id: 4, person_id: 3, certificate_id: 3, certificate_no: '会计 2020-23918', validity_start_date: future(-1800), validity_end_date: future(260), expiry_date: future(260), continuing_education_date: future(-4), renewal_date: future(300), certificate_url: 'https://www.mof.gov.cn/', education_url: 'https://www.mof.gov.cn/', renewal_url: 'https://www.mof.gov.cn/', remind_days: 30, active: true, notes: '' },
  ],
}

function load(): State {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (!saved) return structuredClone(initial)
    const state = JSON.parse(saved) as State
    for (const record of state.records as Array<State['records'][number] & { issue_date?: string }>) {
      record.validity_start_date ||= record.issue_date || ''
      record.validity_end_date ||= record.expiry_date || ''
      delete record.issue_date
    }
    return state
  } catch { return structuredClone(initial) }
}
let state = load()
function persist() { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)) }
function withRelations(item: State['records'][number]): RecordItem {
  return { ...item, attachments: [], person: state.people.find(p => p.id === item.person_id)!, certificate: state.certificates.find(c => c.id === item.certificate_id)! }
}
function reminders(days = 365): Reminder[] {
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const events = [
    ['expiry_date', 'expiry', '延期'],
    ['continuing_education_date', 'education', '继续教育'],
    ['renewal_date', 'renewal', '更新'],
  ] as const
  return state.records.flatMap(record => events.flatMap(([field, type, label]) => {
    const value = record[field]
    if (!value || record.active === false) return []
    const target = new Date(`${value}T00:00:00`)
    const daysLeft = Math.round((target.getTime() - today.getTime()) / 86400000)
    if (daysLeft > days || daysLeft < -30) return []
    const person = state.people.find(p => p.id === record.person_id)
    const certificate = state.certificates.find(c => c.id === record.certificate_id)
    if (!person || !certificate) return []
    return [{ record_id: record.id, person: person.name, certificate: certificate.name, event_type: type, label, target_date: value, days_left: daysLeft }]
  })).sort((a, b) => a.days_left - b.days_left)
}

export const mockApi = {
  async get<T>(path: string): Promise<T> {
    if (path === '/people') return [...state.people].sort((a, b) => b.id - a.id) as T
    if (path === '/certificates') return [...state.certificates].sort((a, b) => a.name.localeCompare(b.name, 'zh')) as T
    if (path.startsWith('/records')) {
      const q = new URLSearchParams(path.split('?')[1] || '').get('q')?.toLowerCase() || ''
      return state.records.map(withRelations).filter(r => !q || `${r.person.name} ${r.certificate.name} ${r.certificate_no || ''}`.toLowerCase().includes(q)).sort((a, b) => b.id - a.id) as T
    }
    if (path.startsWith('/reminders/upcoming')) {
      const days = Number(new URLSearchParams(path.split('?')[1] || '').get('days') || 30)
      return reminders(days) as T
    }
    if (path === '/reminders/check') return { created: reminders(30).length } as T
    if (path === '/reminders/logs') return [] as T
    throw new Error(`Mock API 未实现：${path}`)
  },
  async send<T>(path: string, method: string, body?: Record<string, unknown>): Promise<T | undefined> {
    const match = path.match(/^\/(people|certificates|records)(?:\/(\d+))?$/)
    if (!match) throw new Error(`Mock API 未实现：${path}`)
    const [, kind, rawId] = match
    const id = rawId ? Number(rawId) : undefined
    const list = kind === 'people' ? state.people : kind === 'certificates' ? state.certificates : state.records
    if (method === 'DELETE' && id !== undefined) {
      if (kind === 'people') state.records = state.records.filter(r => r.person_id !== id)
      if (kind === 'certificates') state.records = state.records.filter(r => r.certificate_id !== id)
      if (kind === 'people') state.people = state.people.filter(item => item.id !== id)
      else if (kind === 'certificates') state.certificates = state.certificates.filter(item => item.id !== id)
      else state.records = state.records.filter(item => item.id !== id)
      persist(); return
    }
    if (method !== 'POST' && method !== 'PUT') throw new Error(`Mock API 不支持：${method}`)
    if (kind === 'records' && body) {
      const personId = Number(body.person_id)
      const certificateId = Number(body.certificate_id)
      const person = state.people.find(item => item.id === personId)
      const certificate = state.certificates.find(item => item.id === certificateId)
      if (!person || !certificate) throw new Error('请先添加人员和证书类型')
    }
    if (kind === 'certificates' && body && !id && state.certificates.some(item => item.name === body.name)) throw new Error('证书名称已存在')
    if (id !== undefined) {
      const index = list.findIndex(item => item.id === id)
      if (index < 0) throw new Error('记录不存在')
      Object.assign(list[index], body)
      persist()
      return (kind === 'records' ? withRelations(list[index] as State['records'][number]) : list[index]) as T
    }
    const nextId = Math.max(0, ...list.map(item => item.id)) + 1
    const created = { ...body, id: nextId } as unknown as typeof list[number]
    if (kind === 'records') Object.assign(created, { active: true, remind_days: 30 })
    if (kind === 'people') state.people.unshift(created as Person)
    else if (kind === 'certificates') state.certificates.unshift(created as Certificate)
    else state.records.unshift(created as State['records'][number])
    persist()
    return (kind === 'records' ? withRelations(created as State['records'][number]) : created) as T
  },
  reset() { state = structuredClone(initial); persist() },
}
