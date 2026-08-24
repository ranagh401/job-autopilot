import { motion } from 'framer-motion'
import { Briefcase } from 'lucide-react'
import React, { useState } from 'react'
import { api } from '../api.js'

export default function Login({ onLogin }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      await api.login(pw)
      onLogin()
    } catch {
      setErr('Wrong password')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <motion.form className="login-card" onSubmit={submit}
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}>
        <div className="logo">
          <div className="mark"><Briefcase size={12} strokeWidth={2} /></div>
          Job Mania
        </div>
        <div className="muted" style={{ fontSize: 12.5 }}>
          Sourcing, tailoring and outreach for your job search.
        </div>
        <input
          className="input"
          type="password"
          placeholder="Password"
          value={pw}
          autoFocus
          onChange={(e) => setPw(e.target.value)}
        />
        {err && (
          <motion.div className="login-err"
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: [0, -5, 5, -3, 0] }}
            transition={{ duration: 0.34 }}>
            {err}
          </motion.div>
        )}
        <button className="btn" disabled={busy || !pw} type="submit">
          {busy && <span className="spinner" />} Sign in
        </button>
      </motion.form>
    </div>
  )
}
