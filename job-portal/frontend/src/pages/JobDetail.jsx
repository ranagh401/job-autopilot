import React, { useCallback, useEffect, useState } from 'react'
import { ageClass, api, fmtAge, fmtDate } from '../api.js'
import { Btn, CardSkeleton, Pill, Score } from '../ui.jsx'

// How the LLM classified each address.
const KIND_LABEL = {
  hr: 'HR / recruiter',
  engineering: 'engineer',
  other_person: 'person (other team)',
  role_inbox: 'shared inbox',
  wrong_company: 'different company',
  unknown: '? unknown',
}
const KIND_STYLE = {
  hr: 'shortlisted',
  engineering: 'shortlisted',
  other_person: '',
  role_inbox: '',
  wrong_company: 'skipped',
}

export default function JobDetail({ id, toast }) {
  const [job, setJob] = useState(null)
  const [email, setEmail] = useState('')

  const load = useCallback(() => {
    api.job(id).then(setJob).catch((e) => toast(e.message, 'error'))
  }, [id, toast])

  useEffect(load, [load])

  const act = (action, extra = {}) => async () => {
    try {
      const r = await api.jobAction(id, action, extra)
      toast(r.message, 'success')
      load()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  if (!job) return (
    <>
      <div className="topbar"><div><h1>Loading job…</h1></div></div>
      <CardSkeleton cards={3} lines={4} />
    </>
  )

  return (
    <>
      <div className="topbar">
        <div>
          <button className="backlink" onClick={() => (window.location.hash = '#/jobs')}>
            ← Back to jobs
          </button>
          <div className="detail-head" style={{ marginTop: 8 }}>
            <h2>{job.title}</h2>
            <Score value={job.match_score} />
            <Pill status={job.status} />
          </div>
          <div className="detail-meta" style={{ marginTop: 6 }}>
            <b style={{ color: 'var(--text)' }}>{job.company || 'Unknown company'}</b>
            <span>· {job.location || job.country || 'n/a'}</span>
            <span className="pill">{job.domestic ? 'India' : `${job.country || 'abroad'}`}</span>
            {job.remote && <span className="pill">remote</span>}
            {job.sponsorship_likely && <span className="pill shortlisted">sponsor likely</span>}
            <span className="faint">· via {job.source}</span>
            {job.posted_dt && <span className={ageClass(job.posted_dt)}>· posted {fmtAge(job.posted_dt)}</span>}
            {job.experience_required && <span className="pill">{job.experience_required}</span>}
            {job.salary && <span>· {job.salary}</span>}
            {job.url && <a href={job.url} target="_blank" rel="noreferrer">Open posting ↗</a>}
          </div>
        </div>
      </div>

      <div className="content">
        <div className="card">
          <h3>Actions</h3>
          <div className="actions-row">
            <Btn variant="ghost" onClick={act('score')}>Score with AI</Btn>
            <Btn variant="green" onClick={act('shortlist')}>Shortlist</Btn>
            <Btn variant="ghost" onClick={act('contacts')}>Find HR emails</Btn>
            <Btn variant="ghost" onClick={act('tailor')}>Tailor resume</Btn>
            <Btn onClick={act('draft')}>Draft cold email</Btn>
            <Btn onClick={act('apply')}>Apply on site</Btn>
            <Btn variant="danger" onClick={act('skip')}>Skip</Btn>
          </div>
          {job.match_notes && (
            <div className="muted" style={{ marginTop: 12, lineHeight: 1.6 }}>
              <b>AI assessment:</b> {job.match_notes}
            </div>
          )}
        </div>

        <div className="grid-2">
          <div className="card kv">
            <h3>HR / recruiter contacts</h3>
            <div className="row">
              <span className="muted">Primary:</span>
              {job.contact_email
                ? <span className="mono">{job.contact_email}</span>
                : <span className="faint">none set</span>}
            </div>
            {job.contacts.length === 0 && (
              <div className="muted">No contacts yet — hit "Find HR emails".</div>
            )}
            {job.contacts.map((c) => (
              <div key={c.id} className="row">
                <span className={`pill ${KIND_STYLE[c.kind] || ''}`}>
                  {KIND_LABEL[c.kind] || (c.verified === null ? '… unverified' : 'unknown')}
                </span>
                <span className="mono">{c.email}</span>
                {c.name && <b>{c.name}</b>}
                {c.role && <span className="muted">{c.role}</span>}
                {c.confidence != null && (
                  <span className="faint">{c.confidence}%</span>
                )}
                {c.linkedin && <a href={c.linkedin} target="_blank" rel="noreferrer">LinkedIn ↗</a>}
                <span className="faint">via {c.source}</span>
                {c.verify_note && <span className="faint">— {c.verify_note}</span>}
                <Btn small variant="ghost" onClick={act('set_contact', { to_email: c.email })}>
                  use
                </Btn>
              </div>
            ))}
            <div className="row">
              <input
                className="input" style={{ width: 240 }}
                placeholder="add email manually"
                value={email} onChange={(e) => setEmail(e.target.value)}
              />
              <Btn small variant="ghost" disabled={!email.includes('@')}
                onClick={act('set_contact', { to_email: email })}>
                Set
              </Btn>
            </div>
          </div>

          <div className="card kv">
            <h3>Documents & outreach</h3>
            {job.resumes.length === 0 && job.outreach.length === 0 && (
              <div className="muted">Nothing yet — tailor a resume or draft an email.</div>
            )}
            {job.resumes.map((r) => (
              <div key={r.id} className="ats">
                <div className="row">
                  <span></span>
                  <a href={`/api/resumes/${r.id}/download`}>{r.filename}</a>
                  <span className="faint">{fmtDate(r.created_at)}</span>
                </div>
                {r.ats_score !== null && r.ats_score !== undefined && (
                  <>
                    <div className="row" style={{ gap: 8 }}>
                      <b>ATS fit {Math.round(r.ats_score)}/100</b>
                      <div className="ats-bar" style={{ flex: 1, minWidth: 120 }}>
                        <span style={{ width: `${r.ats_score}%` }} />
                      </div>
                    </div>
                    <div className="ats-sub">
                      <span>keywords {Math.round(r.ats_keyword)}%</span>
                      <span>required skills {Math.round(r.ats_skills)}%</span>
                      <span>sections {Math.round(r.ats_sections)}%</span>
                    </div>
                    {r.missing_keywords?.length > 0 && (
                      <>
                        <div className="muted" style={{ fontSize: 12.5 }}>
                          Keywords this posting wants that your resume doesn't evidence:
                        </div>
                        <div className="kw">
                          {r.missing_keywords.map((k) => <span key={k} className="pill">{k}</span>)}
                        </div>
                      </>
                    )}
                  </>
                )}
              </div>
            ))}
            {job.outreach.map((o) => (
              <div key={o.id} className="row">
                <Pill status={o.status} />
                <span className="mono">{o.to_email || '?'}</span>
                <span className="muted" style={{ flex: 1 }}>"{o.subject}"</span>
                {o.sent_at && <span className="faint">{fmtDate(o.sent_at)}</span>}
                {o.reply_received_at && <span className="pill replied">replied</span>}
              </div>
            ))}
          </div>
        </div>

        {job.applications?.length > 0 && (
          <div className="card kv">
            <h3>Applications</h3>
            {job.applications.map((a) => (
              <div key={a.id}>
                <div className="row">
                  <span className={`pill ${a.status === 'submitted' ? 'shortlisted'
                    : a.status === 'failed' ? 'skipped' : ''}`}>
                    {a.status === 'submitted' ? 'submitted'
                      : a.status === 'manual_needed' ? 'ready to submit'
                        : 'failed'}
                  </span>
                  <span className="muted">{a.ats}</span>
                  {a.submitted_at && <span className="faint">{fmtDate(a.submitted_at)}</span>}
                  {a.url && <a href={a.url} target="_blank" rel="noreferrer">Open form ↗</a>}
                </div>
                <div className="muted" style={{ fontSize: 12.5, margin: '4px 0 8px' }}>{a.detail}</div>
                {a.cover_letter && (
                  <details>
                    <summary className="muted" style={{ cursor: 'pointer', fontSize: 12.5 }}>
                      Prepared answers (cover letter, notice period, work authorisation…)
                    </summary>
                    <pre className="desc" style={{ marginTop: 8 }}>{a.cover_letter}
{Object.entries(a.answers || {}).filter(([k]) => k !== 'cover_letter')
  .map(([k, v]) => `\n${k.replace(/_/g, ' ')}: ${v}`).join('')}</pre>
                  </details>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="card">
          <h3>Job description</h3>
          <div className="desc">{job.description || '(no description captured — open the original posting)'}</div>
        </div>
      </div>
    </>
  )
}
