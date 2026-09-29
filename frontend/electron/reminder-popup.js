const params = new URLSearchParams(window.location.search)
const person = params.get('person') || '持证人员'
const certificate = params.get('certificate') || '证书'
const label = params.get('label') || '证书事项'
const targetDate = params.get('targetDate') || ''

document.getElementById('summary').textContent = `${person} · ${certificate}：${label}`
document.getElementById('date').textContent = targetDate ? `办理日期：${targetDate}` : '请及时处理'
document.getElementById('later').addEventListener('click', () => window.reminderPopup.submit('later'))
document.getElementById('dismiss').addEventListener('click', () => window.reminderPopup.submit('dismiss'))
