import { useState, type FormEvent } from 'react'
import { api, setToken } from '../api'
import { Button, ErrorNote, Page, fieldClass, labelClass } from '../ui'

export default function Login({ onDone }: { onDone: () => void }) {
  const [phone, setPhone] = useState('')
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const out = await api<{ token: string }>('/auth/login', { phone: phone.trim(), pin })
      setToken(out.token)
      onDone()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page>
      <form onSubmit={submit} className="flex flex-1 flex-col justify-center gap-5">
        <div>
          <h1 className="text-3xl font-semibold">NexEagleFin</h1>
          <p className="mt-1 text-muted">Money in, money out, for every project.</p>
        </div>
        <div>
          <label htmlFor="phone" className={labelClass}>Phone number</label>
          <input id="phone" className={fieldClass} inputMode="tel" autoComplete="username" required minLength={8} maxLength={15}
            value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        <div>
          <label htmlFor="pin" className={labelClass}>PIN</label>
          <input id="pin" className={fieldClass} type="password" inputMode="numeric" autoComplete="current-password" required
            minLength={4} maxLength={12} value={pin} onChange={(e) => setPin(e.target.value)} />
        </div>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy} className="min-h-14 text-[17px]">{busy ? 'Logging in…' : 'Log in'}</Button>
      </form>
    </Page>
  )
}
