import { motion } from 'framer-motion'
import { ChevronRight, ExternalLink, FileText, Paperclip } from 'lucide-react'
import React, { useCallback, useEffect, useState } from 'react'
import { api, fmtDate } from '../api.js'
import { Btn, CardSkeleton, Empty, Score, stagger } from '../ui.jsx'

const STATUS = {
  pending_approval: { label: 'awaiting your approval', cls: 'replied' },
  submitted: { label: 'submitted', cls: 'shortlisted' },
  manual_needed: { label: 'fill the form yourself', cls: '' },
  failed: { label: 'failed', cls: 'skipped' },
  skipped: { label: 'skipped', cls: 'skipped' },
}

function Card({ a, toast, reload, onLocalChange }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const st = STATUS[a.status] || { label: a.status, cls: '' }

  const act = (action, confirmMsg) => async () => {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setBusy(true)
    try {
      const r = await api.applicationAction(a.id, action)
      toast(r.message, 'success')
      // Re-status the card at once; the refetch behind this confirms it.
      if (action === 'skip') onLocalChange(a.id, { status: 'skipped' })
      else if (action === 'approve') onLocalChange(a.id, { status: 'submitted' })
      reload()
    } catch (e) {
      toast(e.message, 'error')
      reload()
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.div className="card queue-card" {...stagger(a.idx || 0)}>
      <div className="head">
        <Score value={a.match_score} />
        <span className="title">{a.title}</span>
        <span className="muted">{a.company}</span>
        <span className={`pill ${st.cls}`}>{st.label}</span>
        {a.auto
          ? <span className="pill shortlisted">
              {a.how === 'browser' ? 'browser-fills' : 'auto-submit'} ({a.ats})
            </span>
          : <span className="pill">{a.ats}</span>}
        <span className="faint" style={{ marginLeft: 'auto', fontSize: 12 }}>
          {a.location || a.country}
        </span>
      </div>

      <div className="muted" style={{ fontSize: 12.5 }}>{a.detail}</div>

      <div className="row" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <a href={a.url} target="_blank" rel="noreferrer" className="inline-ico">
          Open the application form <ExternalLink size={11} strokeWidth={2} />
        </a>
        <span className="faint inline-ico" style={{ fontSize: 12 }}>
          <Paperclip size={11} strokeWidth={2} />{a.resume_filename || 'no resume'}
        </span>
        <a href={'#/jobs/' + a.job_id} className="faint" style={{ fontSize: 12 }}>job details</a>
        {a.submitted_at && <span className="faint" style={{ fontSize: 12 }}>sent {fmtDate(a.submitted_at)}</span>}
      </div>

      <button className="backlink" onClick={() => setOpen(!open)}>
        <motion.span animate={{ rotate: open ? 90 : 0 }}
          transition={{ duration: 0.18 }} style={{ display: 'inline-flex' }}>
          <ChevronRight size={12} strokeWidth={2} />
        </motion.span>
        cover letter &amp; answers
      </button>
      {open && (
        <pre className="desc">{a.cover_letter}
{Object.entries(a.answers || {})
  .filter(([k]) => k !== 'cover_letter')
  .map(([k, v]) => `\n${k.replace(/_/g, ' ')}: ${v}`).join('')}</pre>
      )}

      {a.status === 'pending_approval' && (
        <div className="actions-row">
          <Btn disabled={busy} onClick={act('approve', a.auto
            ? `Submit this application to ${a.company} now?`
            : `Mark the ${a.company} application as done? (${a.ats} forms must be filled on their site)`)}>
            {busy ? 'Working…' : a.auto ? 'Approve & submit' : 'Approve'}
          </Btn>
          <Btn variant="danger" disabled={busy} onClick={act('skip')}>Skip</Btn>
        </div>
      )}
      {a.status === 'failed' && (
        <div className="actions-row">
          <Btn variant="ghost" disabled={busy} onClick={act('retry')}>Retry</Btn>
          <Btn variant="danger" disabled={busy} onClick={act('skip')}>Skip</Btn>
        </div>
      )}
    </motion.div>
  )
}

export default function Applications({ toast, onChanged }) {
  const [rows, setRows] = useState(null)

  const load = useCallback(() => {
    api.applications().then((r) => {
      setRows(r.applications)
      onChanged && onChanged()
    }).catch((e) => toast(e.message, 'error'))
  }, [toast, onChanged])

  useEffect(load, [load])

  const onLocalChange = useCallback((id, patch) => {
    setRows((cur) => (cur
      ? cur.map((a) => (a.id === id ? { ...a, ...patch } : a))
      : cur))
  }, [])

  const prepare = async () => {
    toast('Preparing applications…')
    try {
      const r = await api.run('apply')
      toast(r.message, 'success')
      load()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const approveAll = async () => {
    const auto = (rows || []).filter((a) => a.status === 'pending_approval' && a.auto)
    if (!auto.length) return toast('Nothing can be auto-submitted right now')
    if (!window.confirm(`Submit ${auto.length} application(s) now?\n\n`
      + auto.map((a) => `• ${a.title} — ${a.company}`).join('\n'))) return
    try {
      const r = await api.approveAllApplications()
      toast(r.message, 'success')
      load()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const pending = (rows || []).filter((a) => a.status === 'pending_approval')

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Applications</h1>
          <div className="sub">
            {pending.length} awaiting your approval — nothing is submitted until you say so
          </div>
        </div>
        <div className="spacer" />
        <Btn variant="ghost" onClick={prepare}>Prepare more</Btn>
        <Btn onClick={approveAll}>Approve all auto-submittable</Btn>
      </div>
      {rows === null && <CardSkeleton cards={3} lines={3} />}
      <div className="content">
        {rows && rows.length === 0 && (
          <div className="card">
            <Empty icon={FileText} text="No applications prepared yet"
              hint='Run "Prepare more" to draft applications for your shortlisted jobs.' />
          </div>
        )}
        {rows && rows.map((a, i) => (
          <Card key={a.id} a={{ ...a, idx: i }} toast={toast} reload={load}
            onLocalChange={onLocalChange} />
        ))}
      </div>
    </>
  )
}
