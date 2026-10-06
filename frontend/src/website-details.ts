export type WebsiteDetails = {
  certificate_url?: string | null; certificate_account?: string | null; certificate_password?: string | null; certificate_notes?: string | null
  education_url?: string | null; education_account?: string | null; education_password?: string | null; education_notes?: string | null
  renewal_url?: string | null; renewal_account?: string | null; renewal_password?: string | null; renewal_notes?: string | null
}
export type WebsiteForm = Required<{ [Key in keyof WebsiteDetails]: string }>

export const websiteSections = [
  { label: '更新', url: 'renewal_url', account: 'renewal_account', password: 'renewal_password', notes: 'renewal_notes' },
  { label: '延期', url: 'certificate_url', account: 'certificate_account', password: 'certificate_password', notes: 'certificate_notes' },
  { label: '继续教育', url: 'education_url', account: 'education_account', password: 'education_password', notes: 'education_notes' },
] as const

export function websiteDetails(source: WebsiteDetails = {}): WebsiteForm {
  return Object.fromEntries(websiteSections.flatMap(website =>
    (['url', 'account', 'password', 'notes'] as const).map(field => [website[field], source[website[field]] ?? ''])
  )) as WebsiteForm
}
