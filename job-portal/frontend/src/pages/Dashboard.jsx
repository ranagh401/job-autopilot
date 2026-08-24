import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Btn, DashSkeleton } from '../ui.jsx'

const RUN_TASKS = [
  ['fetch', 'Fetch jobs'],
  ['score', 'Score new'],
  ['contacts', 'Find HR emails'],
  ['draft', 'Draft emails'],
  ['send', 'Send approved'],
  ['replies', 'Check replies'],
  ['enrich', 'Enrich postings'],
  ['tailor', 'Tailor resumes'],
  ['apply', 'Apply on sites'],
  ['followups', 'Queue follow-ups'],
  ['cleanup', 'Re-apply filters'],
  // Both open a real browser window, so they only work when the portal is
  // running on your own machine - not on the hosted instance.
  ['wellfound_login', 'Wellfound sign-in'],
  ['wellfound_apply', 'Apply on Wellfound'],
]

const KPI_DEFS = [
  ['found', 'New / unscored', ''],
  ['shortlisted', 'Shortlisted', 'green'],
  ['tailored', 'Resume tailored', 'green'],
  ['sent', 'Emailed', 'accent'],
  ['replied', 'Replied', 'amber'],
  ['interview', 'Interviews', 'amber'],
]

export default function Dashboard({ toast }) {
  const [stats, setStats] = useState(null)
  const fileRef = useRef()

  const load = useCallback(() => {
    api.stats().then(setStats).catch((e) => toast(e.message, 'error'))
  }, [toast])

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [load])

  const run = (task) => async () => {
    toast(`Running "${task}"…`)
    try {
      const r = await api.run(task)
      toast(r.message || 'done', 'success')
    } catch (e) {
      toast(e.message, 'error')
    }
    load()
  }

  const upload = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    try {
      const r = await api.uploadResume(f)
      toast(r.message, 'success')
      load()
    } catch (err) {
      toast(err.message, 'error')
    }
    e.target.value = ''
  }

  if (!stats) return (
    <>
      <div className="topbar"><div><h1>Dashboard</h1>
        <div className="sub">Loading…</div></div></div>
      <DashSkeleton />
    </>
  )
  const c = stats.counts || {}
  const total = Object.values(c).reduce((a, b) => a + b, 0)

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Dashboard</h1>
          <div className="sub">{total} jobs tracked · {stats.sent_today}/{stats.cap} emails sent today</div>
        </div>
        <div className="spacer" />
        <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" hidden onChange={upload} />
        <Btn variant="ghost" onClick={() => fileRef.current.click()}>Upload base resume</Btn>
      </div>

      <div className="content">
        <div className="kpis">
          <div className="kpi" onClick={() => (window.location.hash = '#/jobs')}>
            <div className="num">{total}</div>
            <div className="label">Total jobs</div>
          </div>
          {KPI_DEFS.map(([key, label, color]) => (
            <div key={key} className={`kpi ${color}`} onClick={() => (window.location.hash = '#/jobs?status=' + key)}>
              <div className="num">{c[key] || 0}</div>
              <div className="label">{label}</div>
            </div>
          ))}
          <div className="kpi accent" onClick={() => (window.location.hash = '#/queue')}>
            <div className="num">{stats.queue_n}</div>
            <div className="label">Awaiting approval</div>
          </div>
          <div className="kpi">
            <div className="num">
              {stats.sent_today}<span className="frac">/{stats.cap}</span>
            </div>
            <div className="label">Emails today</div>
          </div>
        </div>

        <div className="card">
          <h3>
            Auto-send
            <span className={`pill ${stats.autosend?.on ? 'shortlisted' : ''}`}
              style={{ marginLeft: 8, textTransform: 'none', letterSpacing: 0 }}>
              {stats.autosend?.on ? 'on' : 'off'}
            </span>
          </h3>
          {stats.autosend?.on ? (
            <div style={{ fontSize: 12.5, lineHeight: 1.65 }}>
              Verified emails send without approval, {stats.autosend.window.replace('-', ':00–')}:00,
              max <b>{stats.cap}/day</b>, jobs scoring ≥{stats.autosend.min_score}.
              <div className="muted" style={{ marginTop: 5 }}>
                {stats.autosend.held > 0
                  ? <><b>{stats.autosend.held}</b> held back by the safety checks — see the
                    reason on each in the <a href="#/queue">queue</a>.</>
                  : 'Nothing is being held back.'}
              </div>
              <div className="faint" style={{ marginTop: 5, fontSize: 11.5 }}>
                AUTO_SEND=false in .env turns this off.
              </div>
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 13 }}>
              Drafts wait in the Queue for your approval. Set AUTO_SEND=true in .env to send automatically.
            </div>
          )}
        </div>

        <div className="card">
          <h3>Pipeline actions</h3>
          <div className="actions-row">
            {RUN_TASKS.map(([task, label]) => (
              <Btn key={task} variant={task === 'send' ? '' : 'ghost'} onClick={run(task)}>
                {label}
              </Btn>
            ))}
          </div>
          <div className="muted" style={{ marginTop: 12, fontSize: 12.5 }}>
            The scheduler runs all of this automatically every hour
            (last cycle: {stats.sched.last_cycle || 'not yet'} · last source fetch: {stats.sched.last_fetch || 'not yet'}).
            Approved emails only go out between 9:00–19:00, staggered, max {stats.cap}/day.
          </div>
        </div>

        <div className="card">
          <h3>Configuration</h3>
          <div className="checklist">
            {Object.entries(stats.config).map(([name, ok]) => (
              <div key={name} className="check-item">
                <span className={`dot ${ok ? 'on' : 'off'}`} />
                {name}
                {name.startsWith('Hunter') && ok && stats.hunter?.remaining != null && (
                  <span className="faint" style={{ marginLeft: 'auto', fontSize: 11.5 }}>
                    {stats.hunter.remaining} searches left
                  </span>
                )}
                {!ok && <span className="faint" style={{ marginLeft: 'auto', fontSize: 11.5 }}>missing</span>}
              </div>
            ))}
          </div>
        </div>

        <div className="grid-2">
          <div className="card">
            <h3>Recent replies</h3>
            {stats.recent_replies.length === 0 ? (
              <div className="muted">No replies yet — they'll show up here automatically.</div>
            ) : (
              stats.recent_replies.map((r) => (
                <div key={r.id} className="log-item" style={{ marginBottom: 9 }}>
                  <span className="t">{r.when}</span>
                  <span>
                    <a href={'#/jobs/' + r.job_id}><b>{r.company || r.to_email}</b></a>
                    {' — '}{r.snippet}
                  </span>
                </div>
              ))
            )}
          </div>
          <div className="card">
            <h3>Activity log</h3>
            <div className="log">
              {stats.sched.log.length === 0 && <div className="muted">Quiet so far.</div>}
              {stats.sched.log.map(([t, m], i) => (
                <div key={i} className="log-item">
                  <span className="t">{t}</span>
                  <span>{m}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
