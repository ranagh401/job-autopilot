import React, { useCallback, useEffect, useState } from 'react'
import { ageClass, api, fmtAge } from '../api.js'
import { CardSkeleton, Score } from '../ui.jsx'

const KIND_LABEL = {
  interview: 'interview',
  offer: 'offer',
  rejection: 'rejected',
  info_request: 'info asked',
  auto_ack: 'auto-ack',
}

export default function Board({ toast }) {
  const [cols, setCols] = useState(null)
  const [drag, setDrag] = useState(null)

  const load = useCallback(() => {
    api.board().then((r) => setCols(r.columns)).catch((e) => toast(e.message, 'error'))
  }, [toast])

  useEffect(load, [load])

  const drop = async (colKey) => {
    if (!drag || drag.status === colKey) return setDrag(null)
    const moving = drag
    setDrag(null)
    try {
      await api.jobAction(moving.id, 'set_status', { status: colKey })
      toast(`Moved "${moving.title.slice(0, 40)}" to ${colKey}`, 'success')
      load()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  if (!cols) return (
    <>
      <div className="topbar"><div><h1>Pipeline</h1>
        <div className="sub">Loading…</div></div></div>
      <CardSkeleton cards={4} lines={2} />
    </>
  )
  const total = cols.reduce((a, c) => a + c.count, 0)

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Pipeline board</h1>
          <div className="sub">{total} active jobs · drag a card between columns to update its stage</div>
        </div>
      </div>
      <div className="content">
        <div className="board">
          {cols.map((col) => (
            <div
              key={col.key}
              className={`board-col ${drag ? 'droppable' : ''}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => drop(col.key)}
            >
              <div className="board-head">
                <span>{col.label}</span>
                <span className="count">{col.count}</span>
              </div>
              <div className="board-cards">
                {col.cards.length === 0 && <div className="faint" style={{ fontSize: 12, padding: '8px 2px' }}>empty</div>}
                {col.cards.map((c) => (
                  <div
                    key={c.id}
                    className="board-card"
                    draggable
                    onDragStart={() => setDrag(c)}
                    onDragEnd={() => setDrag(null)}
                    onClick={() => (window.location.hash = '#/jobs/' + c.id)}
                  >
                    <div className="bc-top">
                      <Score value={c.match_score} />
                      <span className="bc-title">{c.title}</span>
                    </div>
                    <div className="bc-sub">{c.company || '—'}{c.location ? ` · ${c.location}` : ''}</div>
                    <div className="bc-tags">
                      {c.posted_dt && <span className={`pill ${ageClass(c.posted_dt)}`}>{fmtAge(c.posted_dt)}</span>}
                      {c.experience_required && <span className="pill">{c.experience_required}</span>}
                      {c.has_resume && <span className="pill">resume</span>}
                      {c.contact_email && <span className="pill shortlisted">contact</span>}
                      {c.sponsorship_likely && <span className="pill">sponsor</span>}
                      {c.reply_kind && <span className="pill replied">{KIND_LABEL[c.reply_kind] || c.reply_kind}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
