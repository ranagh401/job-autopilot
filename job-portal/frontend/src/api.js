async function req(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (res.status === 401) {
    window.dispatchEvent(new Event('portal-unauthorized'))
    throw new Error('Not logged in')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || data.message || res.statusText)
  return data
}

export const api = {
  me: () => req('/api/me'),
  login: (password) => req('/api/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => req('/api/logout', { method: 'POST' }),
  stats: () => req('/api/stats'),
  jobs: (params) => req('/api/jobs?' + new URLSearchParams(params)),
  job: (id) => req('/api/jobs/' + id),
  board: () => req('/api/board'),
  jobAction: (id, action, extra = {}) =>
    req(`/api/jobs/${id}/action`, { method: 'POST', body: JSON.stringify({ action, ...extra }) }),
  queue: () => req('/api/queue'),
  queueAction: (id, payload) =>
    req('/api/queue/' + id, { method: 'POST', body: JSON.stringify(payload) }),
  outreach: () => req('/api/outreach'),
  leads: () => req('/api/leads'),
  applications: () => req('/api/applications'),
  applicationAction: (id, action) =>
    req('/api/applications/' + id, { method: 'POST', body: JSON.stringify({ action }) }),
  approveAllApplications: () =>
    req('/api/applications/approve_all', { method: 'POST' }),
  run: (task) => req('/api/run/' + task, { method: 'POST' }),
  uploadResume: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return req('/api/resume/upload', { method: 'POST', body: fd })
  },
}

export const fmtDate = (s) => {
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d) ? s : d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

/** "2h ago" / "3d ago" / "12 Aug" — how fresh a posting is. */
export const fmtAge = (iso) => {
  if (!iso) return null
  const d = new Date(iso)
  if (isNaN(d)) return null
  const hours = (Date.now() - d.getTime()) / 3.6e6
  if (hours < 1) return 'just now'
  if (hours < 24) return `${Math.round(hours)}h ago`
  const days = Math.round(hours / 24)
  if (days <= 30) return `${days}d ago`
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
}

/** Fresh postings are worth applying to first. */
export const ageClass = (iso) => {
  if (!iso) return 'faint'
  const days = (Date.now() - new Date(iso).getTime()) / 8.64e7
  return days <= 3 ? 'age-fresh' : days <= 14 ? 'age-ok' : 'age-old'
}
