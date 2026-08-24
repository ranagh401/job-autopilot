import { motion } from 'framer-motion'
import { Check, Search, X } from 'lucide-react'
import React, { useCallback, useEffect, useState } from 'react'
import { ageClass, api, fmtAge } from '../api.js'
import { Btn, Empty, Pill, Score, Skeleton, stagger } from '../ui.jsx'

const STATUSES = ['found', 'scored', 'shortlisted', 'tailored', 'sent',
  'replied', 'interview', 'skipped', 'closed']

/** Green when the required experience is within reach of ~2 years. */
const expClass = (min) => {
  if (min === null || min === undefined) return 'pill'
  return min <= 3 ? 'pill shortlisted' : min <= 5 ? 'pill' : 'pill skipped'
}

const SCOPES = [
  { key: '', label: 'All jobs' },
  { key: 'domestic', label: 'India' },
  { key: 'abroad', label: 'Abroad + sponsorship' },
]

export default function Jobs({ toast }) {
  const initialStatus = new URLSearchParams(window.location.hash.split('?')[1] || '').get('status') || ''
  const [rows, setRows] = useState(null)
  const [status, setStatus] = useState(initialStatus)
  const [q, setQ] = useState('')
  const [minscore, setMinscore] = useState('')
  const [scope, setScope] = useState('')
  const [country, setCountry] = useState('')
  const [countries, setCountries] = useState([])

  const load = useCallback(() => {
    api.jobs({ status, q, minscore, scope, country })
      .then((r) => {
        setRows(r.jobs)
        setCountries(r.countries || [])
      })
      .catch((e) => toast(e.message, 'error'))
  }, [status, q, minscore, scope, country, toast])

  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [load])

  const act = (id, action) => async () => {
    try {
      const r = await api.jobAction(id, action)
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
          <h1>Jobs</h1>
          <div className="sub">{rows ? `${rows.length} shown` : 'loading…'}</div>
        </div>
      </div>
      <div className="content">
        <div className="tabs">
          {SCOPES.map((sc) => (
            <button
              key={sc.key}
              className={`tab ${scope === sc.key ? 'active' : ''}`}
              onClick={() => { setScope(sc.key); setCountry('') }}
            >
              {sc.label}
            </button>
          ))}
        </div>
        <div className="filters">
          {scope !== 'domestic' && countries.length > 0 && (
            <select className="input" value={country}
              onChange={(e) => setCountry(e.target.value)}>
              <option value="">All countries ({countries.length})</option>
              {countries.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Active pipeline (default)</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s === 'skipped' ? 'skipped (rejected)' : s}
              </option>
            ))}
          </select>
          <input
            className="input" style={{ width: 260 }}
            placeholder="Search title, company, location…"
            value={q} onChange={(e) => setQ(e.target.value)}
          />
          <input
            className="input" style={{ width: 110 }} type="number"
            placeholder="Min score" value={minscore}
            onChange={(e) => setMinscore(e.target.value)}
          />
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Score</th><th>Role</th><th>Company</th><th>Location</th>
                <th>Posted</th><th>Experience</th>
                <th>HR contact</th><th>Source</th><th>Status</th><th></th>
              </tr>
            </thead>
            {rows === null && <Skeleton rows={8} cols={10} />}
            <tbody>
              {rows && rows.length === 0 && (
                <tr><td colSpan={10}>
                  <Empty icon={Search} text="No jobs match"
                    hint='Run "Fetch jobs" on the dashboard, or loosen the filters.' />
                </td></tr>
              )}
              {rows && rows.map((j, i) => (
                <motion.tr key={j.id} className="rowlink" {...stagger(i)}
                  onClick={() => (window.location.hash = '#/jobs/' + j.id)}>
                  <td><Score value={j.match_score} /></td>
                  <td style={{ maxWidth: 320 }}>
                    <div className="tcell-main">{j.title}</div>
                    <div className="tcell-sub">
                      {j.remote && <span className="pill">remote</span>}{' '}
                      {j.sponsorship_likely && <span className="pill shortlisted">sponsor likely</span>}
                    </div>
                  </td>
                  <td>{j.company || <span className="faint">—</span>}</td>
                  <td className="muted" style={{ maxWidth: 170 }}>
                    <div>{j.location || j.country || '—'}</div>
                    <div className="tcell-sub">
                      {j.domestic ? 'India' : `${j.country || 'abroad'}`}
                    </div>
                  </td>
                  <td className={ageClass(j.posted_dt)} style={{ whiteSpace: 'nowrap' }}>
                    {fmtAge(j.posted_dt) || <span className="faint">—</span>}
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {j.experience_required
                      ? <span className={expClass(j.exp_min_years)}>{j.experience_required}</span>
                      : <span className="faint">—</span>}
                  </td>
                  <td>
                    {j.contact_email
                      ? <span className="mono">{j.contact_email}</span>
                      : <span className="faint">none yet{j.contacts_count > 0 ? ` (${j.contacts_count} found)` : ''}</span>}
                  </td>
                  <td className="faint">{j.source}</td>
                  <td><Pill status={j.status} /></td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div style={{ display: 'flex', gap: 5 }}>
                      <Btn small variant="green" onClick={act(j.id, 'shortlist')}
                        title="Shortlist"><Check size={12} strokeWidth={2.5} /></Btn>
                      <Btn small variant="danger" onClick={act(j.id, 'skip')}
                        title="Skip"><X size={12} strokeWidth={2.5} /></Btn>
                    </div>
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
