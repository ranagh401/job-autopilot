import { AnimatePresence, motion } from 'framer-motion'
import { Briefcase, CheckCircle2, Loader2, XCircle } from 'lucide-react'
import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import Applications from './pages/Applications.jsx'
import Board from './pages/Board.jsx'
import Leads from './pages/Leads.jsx'
import Dashboard from './pages/Dashboard.jsx'
import JobDetail from './pages/JobDetail.jsx'
import Jobs from './pages/Jobs.jsx'
import Login from './pages/Login.jsx'
import Outreach from './pages/Outreach.jsx'
import Queue from './pages/Queue.jsx'
import { icons } from './ui.jsx'

const NAV = [
  { key: 'dashboard', label: 'Dashboard', icon: icons.dashboard },
  { key: 'jobs', label: 'Jobs', icon: icons.jobs },
  { key: 'board', label: 'Pipeline', icon: icons.board },
  { key: 'leads', label: 'Web leads', icon: icons.leads },
  { key: 'queue', label: 'Queue', icon: icons.queue },
  { key: 'applications', label: 'Applications', icon: icons.apply },
  { key: 'outreach', label: 'Outreach', icon: icons.outreach },
]

const parseHash = () => {
  const h = (window.location.hash || '#/dashboard').replace(/^#\/?/, '')
  // Strip the query first: '#/jobs?status=shortlisted' must still route to
  // the jobs page. Leaving it on made page === 'jobs?status=shortlisted',
  // which matched nothing and silently fell through to the dashboard.
  const [path, qs = ''] = h.split('?')
  const [page, arg] = path.split('/')
  return { page: page || 'dashboard', arg, qs }
}

export default function App() {
  const [authed, setAuthed] = useState(null)
  const [route, setRoute] = useState(parseHash())
  const [toasts, setToasts] = useState([])
  const [queueCount, setQueueCount] = useState(0)

  const toast = useCallback((msg, kind = '') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t, { id, msg, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5500)
  }, [])

  const refreshBadges = useCallback(() => {
    api.stats().then((s) => setQueueCount(s.queue_n)).catch(() => {})
  }, [])

  useEffect(() => {
    api.me().then((r) => setAuthed(r.auth)).catch(() => setAuthed(false))
    const onHash = () => setRoute(parseHash())
    const onUnauth = () => setAuthed(false)
    window.addEventListener('hashchange', onHash)
    window.addEventListener('portal-unauthorized', onUnauth)
    return () => {
      window.removeEventListener('hashchange', onHash)
      window.removeEventListener('portal-unauthorized', onUnauth)
    }
  }, [])

  useEffect(() => {
    if (authed) refreshBadges()
  }, [authed, route, refreshBadges])

  // Until /api/me answers we know neither who they are nor what to draw.
  // Returning null here blanked the whole window, which on a sleeping free
  // instance is a 30-50s cold start staring at nothing.
  if (authed === null) {
    return (
      <div className="boot">
        <Loader2 size={18} strokeWidth={2} className="spin-slow" />
        <div>Waking up Job Mania…</div>
        <div className="faint" style={{ fontSize: 12 }}>
          The free instance sleeps when idle; the first load takes a moment.
        </div>
      </div>
    )
  }
  if (!authed) return <Login onLogin={() => setAuthed(true)} />

  const go = (page) => { window.location.hash = '#/' + page }

  let body
  if (route.page === 'jobs' && route.arg) {
    body = <JobDetail id={route.arg} toast={toast} />
  } else if (route.page === 'jobs') {
    body = <Jobs toast={toast} />
  } else if (route.page === 'board') {
    body = <Board toast={toast} />
  } else if (route.page === 'queue') {
    body = <Queue toast={toast} onChanged={refreshBadges} />
  } else if (route.page === 'leads') {
    body = <Leads toast={toast} />
  } else if (route.page === 'applications') {
    body = <Applications toast={toast} onChanged={refreshBadges} />
  } else if (route.page === 'outreach') {
    body = <Outreach toast={toast} />
  } else {
    body = <Dashboard toast={toast} />
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="logo">
          <div className="mark"><Briefcase size={12} strokeWidth={2} /></div>
          Job Mania
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <button
              key={n.key}
              className={`nav-item ${route.page === n.key ? 'active' : ''}`}
              onClick={() => go(n.key)}
            >
              {n.icon}
              {n.label}
              {n.key === 'queue' && queueCount > 0 && <span className="count">{queueCount}</span>}
            </button>
          ))}
        </nav>
        <div className="nav-footer">
          <button
            className="nav-item"
            onClick={() => api.logout().then(() => setAuthed(false))}
          >
            {icons.logout}
            Log out
          </button>
        </div>
      </aside>
      <div className="main">
        <AnimatePresence mode="wait">
          {/* The query is part of the key so that moving between
              '#/jobs?status=shortlisted' and '#/jobs?status=sent' remounts
              the page and re-reads the filter. */}
          <motion.div key={route.page + (route.arg || '') + route.qs}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
            style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
            {body}
          </motion.div>
        </AnimatePresence>
      </div>
      <div className="toasts">
        <AnimatePresence initial={false}>
          {toasts.map((t) => (
            <motion.div key={t.id} className={`toast ${t.kind}`}
              initial={{ opacity: 0, x: 24, scale: 0.97 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24, scale: 0.97 }}
              transition={{ type: 'spring', stiffness: 400, damping: 32 }}>
              {t.kind === 'error'
                ? <XCircle size={13} strokeWidth={2} style={{ color: 'var(--bad)' }} />
                : t.kind === 'success'
                  ? <CheckCircle2 size={13} strokeWidth={2} style={{ color: 'var(--good)' }} />
                  : <Loader2 size={13} strokeWidth={2} className="spin-slow" />}
              <span>{t.msg}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  )
}
