import { motion } from 'framer-motion'
import React, { useCallback, useEffect, useState } from 'react'
import { api, fmtDate } from '../api.js'
import { Btn, CardSkeleton, Empty, I, Score, stagger } from '../ui.jsx'

// Where each address came from, in plain language.
const SOURCE_LABEL = {
  'hiring-post': 'recruiter hiring post',
  'websearch-person': 'web search · named person',
  websearch: 'web search',
  pattern: 'inferred from company format',
  'escalated-person': 'deep search · named person',
  escalated: 'deep search',
  'search-person': 'search + lookup',
  'page-person': 'posting page · named person',
  page: 'posting page',
  guessed: 'guessed mailbox',
}

export default function Leads({ toast }) {
  const [data, setData] = useState(null)
  const [filter, setFilter] = useState('')

  const load = useCallback(() => {
    api.leads().then(setData).catch((e) => toast(e.message, 'error'))
  }, [toast])

  useEffect(load, [load])

  const run = (task) => async () => {
    toast(`Running "${task}"…`)
    try {
      const r = await api.run(task)
      toast(r.message, 'success')
      load()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  if (!data) return (
    <>
      <div className="topbar"><div><h1>Web leads</h1>
        <div className="sub">Loading…</div></div></div>
      <CardSkeleton cards={3} />
    </>
  )
  const rows = filter
    ? data.leads.filter((l) => l.contact_source === filter)
    : data.leads

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Web leads</h1>
          <div className="sub">
            {data.leads.length} contacts found by searching or scraping the open web —
            {' '}{data.people} are real people, {data.emailed} already emailed
          </div>
        </div>
        <div className="spacer" />
        <Btn variant="ghost" onClick={run('fetch')}>Search hiring posts</Btn>
        <Btn variant="ghost" onClick={run('contacts')}>Find more contacts</Btn>
      </div>

      <div className="content">
        <div className="tabs">
          <button className={`tab ${filter === '' ? 'active' : ''}`}
            onClick={() => setFilter('')}>
            All ({data.leads.length})
          </button>
          {Object.entries(data.by_source)
            .sort((a, b) => b[1] - a[1])
            .map(([src, n]) => (
              <button key={src}
                className={`tab ${filter === src ? 'active' : ''}`}
                onClick={() => setFilter(src)}>
                {SOURCE_LABEL[src] || src} ({n})
              </button>
            ))}
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Score</th><th>Email</th><th>Person</th><th>Company</th>
                <th>Role</th><th>How it was found</th><th>Verdict</th>
                <th>Status</th><th>Found</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={9}>
                  <Empty text="No web-sourced contacts yet"
                    hint='Run "Search hiring posts" — it finds recruiters who published their own address.' />
                </td></tr>
              )}
              {rows.map((l, i) => (
                <motion.tr key={l.contact_id} className="rowlink" {...stagger(i)}
                  onClick={() => (window.location.hash = '#/jobs/' + l.job_id)}>
                  <td><Score value={l.match_score} /></td>
                  <td className="mono">{l.email}</td>
                  <td>
                    {l.name || (l.is_person
                      ? <span className="muted">unnamed</span>
                      : <span className="faint">shared inbox</span>)}
                    {l.role && <div className="tcell-sub">{l.role}</div>}
                  </td>
                  <td>{l.company || <span className="faint">—</span>}</td>
                  <td style={{ maxWidth: 240 }}>
                    <div className="tcell-main">{l.title}</div>
                    <div className="tcell-sub">{l.location || l.country}</div>
                  </td>
                  <td className="muted" style={{ whiteSpace: 'nowrap' }}>
                    {SOURCE_LABEL[l.contact_source] || l.contact_source}
                  </td>
                  <td>
                    {l.verified === null
                      ? <span className="pill">unverified</span>
                      : l.is_person
                        ? <span className="pill shortlisted">{I.person()} real person</span>
                        : <span className="pill skipped">{I.inbox()} {l.kind || 'not a person'}</span>}
                    {l.verify_note && <div className="tcell-sub">{l.verify_note}</div>}
                  </td>
                  <td>
                    {l.emailed
                      ? <span className="pill sent">{I.mailed()} emailed</span>
                      : l.is_primary
                        ? <span className="pill">primary</span>
                        : <span className="faint">—</span>}
                  </td>
                  <td className="faint" style={{ whiteSpace: 'nowrap' }}>
                    {fmtDate(l.found_at)}
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
