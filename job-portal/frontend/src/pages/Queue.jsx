import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Btn, CardSkeleton, Empty, Pill } from '../ui.jsx'

function Draft({ o, toast, reload, onLocalChange }) {
  const [to, setTo] = useState(o.to_email)
  const [subject, setSubject] = useState(o.subject)
  const [body, setBody] = useState(o.body)
  const [busy, setBusy] = useState(false)

  const act = (action, confirmMsg) => async () => {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setBusy(true)
    try {
      const r = await api.queueAction(o.id, { action, to_email: to, subject, body })
      toast(r.message, 'success')
      // Move the card straight away rather than waiting on the refetch -
      // re-reading the whole queue takes a moment, and until it lands the
      // row sits there looking as though nothing happened.
      if (action === 'delete' || action === 'send') onLocalChange(o.id, null)
      else if (action === 'approve') onLocalChange(o.id, { status: 'approved' })
      else if (action === 'unapprove') onLocalChange(o.id, { status: 'draft' })
      else onLocalChange(o.id, { to_email: to, subject, body })
      reload()   // reconcile with the server
    } catch (e) {
      toast(e.message, 'error')
      reload()   // our guess may be wrong; take the server's word for it
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card queue-card">
      <div className="head">
        <span className="title">
          <a href={'#/jobs/' + o.job_id}>{o.job_title || 'job ' + o.job_id}</a>
        </span>
        <span className="muted">{o.company}</span>
        <Pill status={o.status} />
        {o.followup_n > 0 && <span className="pill replied">follow-up #{o.followup_n}</span>}
        {o.blockers?.length > 0
          ? <span className="pill skipped" title={o.blockers.join('; ')}>
              held: {o.blockers[0]}
            </span>
          : <span className="pill shortlisted">Yes will auto-send</span>}
        <span className="faint" style={{ marginLeft: 'auto', fontSize: 12 }}>
          {o.resume_filename || 'no attachment'}
        </span>
      </div>
      {o.error && <div style={{ color: 'var(--red)', fontSize: 12.5 }}>Last error: {o.error}</div>}
      <div className="queue-grid">
        <label>To</label>
        <input className="input mono" value={to} placeholder="recipient email"
          onChange={(e) => setTo(e.target.value)} />
        <label>Subject</label>
        <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} />
      </div>
      <textarea className="input" value={body} onChange={(e) => setBody(e.target.value)} />
      <div className="actions-row">
        <Btn variant="ghost" disabled={busy} onClick={act('save')}>Save</Btn>
        {o.status === 'approved'
          ? <Btn variant="ghost" disabled={busy} onClick={act('unapprove')}>Back to draft</Btn>
          : <Btn variant="green" disabled={busy} onClick={act('approve')}>Approve</Btn>}
        <Btn disabled={busy} onClick={act('send', `Send this email to ${to} right now?`)}>
          {busy ? 'Working…' : 'Send now'}
        </Btn>
        <Btn variant="danger" disabled={busy} onClick={act('delete', 'Delete this draft?')}>Delete</Btn>
      </div>
    </div>
  )
}

export default function Queue({ toast, onChanged }) {
  const [drafts, setDrafts] = useState(null)
  const [info, setInfo] = useState({})

  const load = useCallback(() => {
    api.queue().then((r) => {
      setDrafts(r.drafts)
      setInfo({ ready: r.ready, held: r.held, auto: r.auto_send })
      onChanged && onChanged()
    }).catch((e) => toast(e.message, 'error'))
  }, [toast, onChanged])

  useEffect(load, [load])

  // Apply a card's outcome locally: patch === null removes it.
  const onLocalChange = useCallback((id, patch) => {
    setDrafts((cur) => {
      if (!cur) return cur
      if (patch === null) return cur.filter((d) => d.id !== id)
      return cur.map((d) => (d.id === id ? { ...d, ...patch } : d))
    })
    // The ready/held counts depend on each draft's blockers, which only
    // the server computes - the refetch right behind this corrects them.
  }, [])

  const sendReady = async () => {
    try {
      await api.run('autosend')
      const r = await api.run('send')
      toast(r.message, 'success')
      load()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Email queue</h1>
          <div className="sub">
            {info.auto
              ? <><b>{info.ready ?? 0} ready to auto-send</b>, {info.held ?? 0} held —
                each held email shows its reason. Auto-send runs 9:00–19:00, within the daily cap.</>
              : <>Auto-send is off — nothing goes out without your approval.</>}
          </div>
        </div>
        <div className="spacer" />
        <Btn onClick={sendReady} disabled={!info.ready}>
          Send the {info.ready ?? 0} ready now
        </Btn>
      </div>
      {drafts === null && <CardSkeleton cards={3} lines={4} />}
      <div className="content">
        {drafts && drafts.length === 0 && (
          <div className="card">
            <Empty icon="" text="Queue is clear"
              hint='Draft emails from a job page, or "Draft emails" on the dashboard.' />
          </div>
        )}
        {drafts && drafts.map((o) => (
          <Draft key={o.id} o={o} toast={toast} reload={load}
            onLocalChange={onLocalChange} />
        ))}
      </div>
    </>
  )
}
