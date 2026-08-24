import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle, Award, Briefcase, Building2, Calendar, Check,
  CheckCircle2, ChevronRight, Clock, FileText, Inbox, Kanban,
  LayoutDashboard, LogOut, Mail, MailCheck, Search, Send, Sparkles, User,
  X, XCircle,
} from 'lucide-react'
import React, { useEffect, useRef, useState } from 'react'

/* Motion is used to show *state change*, never as decoration:
   rows enter as data arrives, numbers count to their value, panels
   settle rather than pop. Everything respects reduced-motion. */

export const ease = [0.16, 1, 0.3, 1]

export const fadeUp = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.28, ease },
}

/** Rows/cards appear in sequence so a long list reads as it loads. */
export const stagger = (i = 0) => ({
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.32, ease, delay: Math.min(i * 0.022, 0.35) },
})

export const Page = ({ children }) => (
  <motion.div {...fadeUp} style={{ display: 'contents' }}>{children}</motion.div>
)

/** Counts up to the target so a changing metric is noticeable. */
export function Num({ value = 0, duration = 550 }) {
  const [shown, setShown] = useState(0)
  const from = useRef(0)
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setShown(value)
      return
    }
    const start = performance.now()
    const a = from.current
    const b = Number(value) || 0
    let raf
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      setShown(Math.round(a + (b - a) * eased))
      if (t < 1) raf = requestAnimationFrame(tick)
      else from.current = b
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])
  return <>{shown}</>
}

export const Pill = ({ status }) => (
  <span className={`pill ${status}`}>{status}</span>
)

export const Score = ({ value }) => {
  if (value === null || value === undefined) return <span className="score lo">—</span>
  const cls = value >= 65 ? 'hi' : value >= 45 ? 'mid' : 'lo'
  return (
    <motion.span className={`score ${cls}`}
      initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.2, ease }}>
      {Math.round(value)}
    </motion.span>
  )
}

export const Btn = ({ children, onClick, variant = '', disabled, small, title }) => {
  const [busy, setBusy] = useState(false)
  const handle = async (e) => {
    e.stopPropagation()
    if (!onClick) return
    setBusy(true)
    try { await onClick() } finally { setBusy(false) }
  }
  return (
    <motion.button
      className={`btn ${variant} ${small ? 'sm' : ''}`}
      onClick={handle}
      disabled={disabled || busy}
      title={title}
      whileTap={{ scale: 0.97 }}
      transition={{ duration: 0.12 }}
    >
      <AnimatePresence mode="wait" initial={false}>
        {busy && (
          <motion.span key="s" className="spinner"
            initial={{ opacity: 0, width: 0 }}
            animate={{ opacity: 1, width: 11 }}
            exit={{ opacity: 0, width: 0 }}
            transition={{ duration: 0.15 }} />
        )}
      </AnimatePresence>
      {children}
    </motion.button>
  )
}

export const Empty = ({ icon: Icon = Inbox, text, hint }) => (
  <motion.div className="empty" {...fadeUp}>
    <Icon size={20} strokeWidth={1.5} className="faint" />
    <div>{text}</div>
    {hint && <div className="faint" style={{ fontSize: 12 }}>{hint}</div>}
  </motion.div>
)

/** Placeholder rows while a request is in flight - better than a blank page. */
export const Skeleton = ({ rows = 6, cols = 6 }) => (
  <tbody>
    {Array.from({ length: rows }).map((_, r) => (
      <tr key={r}>
        {Array.from({ length: cols }).map((__, c) => (
          <td key={c}>
            <span className="skel" style={{ width: `${45 + ((r + c) % 4) * 15}%` }} />
          </td>
        ))}
      </tr>
    ))}
  </tbody>
)

/** Card-shaped placeholders. The table Skeleton above is a <tbody> and so
 *  cannot be used on the card pages, which is why those used to render a
 *  blank screen for the second or two the request takes. */
export const CardSkeleton = ({ cards = 3, lines = 3 }) => (
  <div className="content">
    {Array.from({ length: cards }).map((_, i) => (
      <div className="card" key={i} style={{ opacity: 1 - i * 0.18 }}>
        <span className="skel" style={{ width: '38%', height: 13 }} />
        {Array.from({ length: lines }).map((__, l) => (
          <span key={l} className="skel"
            style={{ width: `${88 - l * 17}%`, marginTop: 10 }} />
        ))}
      </div>
    ))}
  </div>
)

/** KPI tiles + panels, for the dashboard's first paint. */
export const DashSkeleton = () => (
  <div className="content">
    <div className="kpis">
      {Array.from({ length: 6 }).map((_, i) => (
        <div className="kpi" key={i}>
          <span className="skel" style={{ width: '45%', height: 20 }} />
          <span className="skel" style={{ width: '70%', marginTop: 12 }} />
        </div>
      ))}
    </div>
    <CardSkeleton cards={2} lines={4} />
  </div>
)

export const icons = {
  dashboard: <LayoutDashboard className="ico" size={15} strokeWidth={1.75} />,
  jobs: <Briefcase className="ico" size={15} strokeWidth={1.75} />,
  board: <Kanban className="ico" size={15} strokeWidth={1.75} />,
  leads: <Search className="ico" size={15} strokeWidth={1.75} />,
  queue: <Mail className="ico" size={15} strokeWidth={1.75} />,
  apply: <FileText className="ico" size={15} strokeWidth={1.75} />,
  outreach: <Send className="ico" size={15} strokeWidth={1.75} />,
  logout: <LogOut className="ico" size={15} strokeWidth={1.75} />,
}

/* Named icons used inline, so no emoji anywhere in the interface. */
export const I = {
  person: (p) => <User size={12} strokeWidth={2} {...p} />,
  inbox: (p) => <Inbox size={12} strokeWidth={2} {...p} />,
  warn: (p) => <AlertTriangle size={12} strokeWidth={2} {...p} />,
  ok: (p) => <CheckCircle2 size={12} strokeWidth={2} {...p} />,
  no: (p) => <XCircle size={12} strokeWidth={2} {...p} />,
  clock: (p) => <Clock size={12} strokeWidth={2} {...p} />,
  file: (p) => <FileText size={12} strokeWidth={2} {...p} />,
  mail: (p) => <Mail size={12} strokeWidth={2} {...p} />,
  mailed: (p) => <MailCheck size={12} strokeWidth={2} {...p} />,
  company: (p) => <Building2 size={12} strokeWidth={2} {...p} />,
  award: (p) => <Award size={12} strokeWidth={2} {...p} />,
  spark: (p) => <Sparkles size={12} strokeWidth={2} {...p} />,
  search: (p) => <Search size={12} strokeWidth={2} {...p} />,
  megaphone: (p) => <Send size={12} strokeWidth={2} {...p} />,
  chevron: (p) => <ChevronRight size={12} strokeWidth={2} {...p} />,
  check: (p) => <Check size={12} strokeWidth={2} {...p} />,
  x: (p) => <X size={12} strokeWidth={2} {...p} />,
  calendar: (p) => <Calendar size={12} strokeWidth={2} {...p} />,
}
