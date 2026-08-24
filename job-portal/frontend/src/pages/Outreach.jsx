import React, { useEffect, useState } from 'react'
import { api, fmtDate } from '../api.js'
import { Empty, Skeleton } from '../ui.jsx'

const KIND_LABEL = {
  interview: 'interview',
  offer: 'offer',
  rejection: 'rejection',
  info_request: 'info requested',
  auto_ack: 'auto-ack',
  other: 'replied',
}

export default function Outreach({ toast }) {
  const [rows, setRows] = useState(null)

  useEffect(() => {
    api.outreach().then((r) => setRows(r.rows)).catch((e) => toast(e.message, 'error'))
  }, [toast])

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Sent outreach</h1>
          <div className="sub">{rows ? `${rows.length} emails sent` : 'loading…'}</div>
        </div>
      </div>
      <div className="content">
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr><th>Sent</th><th>To</th><th>Company</th><th>Role</th><th>Subject</th><th>Reply</th></tr>
            </thead>
            {rows === null && <Skeleton rows={6} cols={6} />}
            <tbody>
              {rows && rows.length === 0 && (
                <tr><td colSpan={6}>
                  <Empty icon="" text="Nothing sent yet"
                    hint="Approve drafts in the Queue and they'll appear here." />
                </td></tr>
              )}
              {rows && rows.map((o) => (
                <tr key={o.id}>
                  <td className="muted" style={{ whiteSpace: 'nowrap' }}>{fmtDate(o.sent_at)}</td>
                  <td className="mono">{o.to_email}</td>
                  <td>{o.company}</td>
                  <td><a href={'#/jobs/' + o.job_id}>{o.job_title}</a></td>
                  <td className="muted" style={{ maxWidth: 260 }}>{o.subject}</td>
                  <td style={{ maxWidth: 280 }}>
                    {o.reply_received_at ? (
                      <>
                        <span className={`pill ${o.reply_kind === 'rejection' ? 'skipped' : 'replied'}`}>
                          {KIND_LABEL[o.reply_kind] || 'replied'} · {fmtDate(o.reply_received_at)}
                        </span>
                        <div className="tcell-sub">{o.reply_snippet}</div>
                      </>
                    ) : (
                      <span className="faint">
                        no reply yet{o.followup_n > 0 ? ` · ${o.followup_n} follow-up(s)` : ''}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
