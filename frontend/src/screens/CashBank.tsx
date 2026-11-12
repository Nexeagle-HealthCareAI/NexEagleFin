import { useEffect, useState, type FormEvent } from 'react'
import { api, localToday, type MoneyAccount, type Project } from '../api'
import { Button, Card, Choice, ErrorNote, Page, StatCard, TopBar, cleanAmount, fieldClass, labelClass, rupees } from '../ui'

/** Every cash box and bank account of the project, what is in each, and moving money between them. */
export default function CashBank({ project, canManage, onBack }: { project: Project; canManage: boolean; onBack: () => void }) {
  const [accounts, setAccounts] = useState<MoneyAccount[] | null>(null)
  const [total, setTotal] = useState('0')
  const [error, setError] = useState('')
  const [form, setForm] = useState<'' | 'add' | 'move'>('')
  const [opening, setOpening] = useState<string | null>(null)

  const load = () =>
    api<{ accounts: MoneyAccount[]; total: string }>(`/money-accounts?project_id=${project.id}`)
      .then((r) => { setAccounts(r.accounts); setTotal(r.total); setError('') })
      .catch((e: Error) => setError(e.message))
  useEffect(() => { load() }, [project.id])
  const done = async () => { setForm(''); setOpening(null); await load() }

  return (
    <Page wide>
      <TopBar title="Cash and bank" sub={project.name} onBack={onBack} backOnPhoneOnly />
      <ErrorNote>{error}</ErrorNote>
      {accounts && (
        <>
          <section aria-label="Total" className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
            <StatCard dark label="In all accounts" value={rupees(total)} />
          </section>
          <ul className="m-0 flex list-none flex-col gap-3 p-0 lg:grid lg:grid-cols-2 lg:items-start lg:gap-4">
            {accounts.map((a) => (
              <li key={a.id}>
                <Card>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="truncate text-[17px] font-semibold">{a.name}</span>
                      <span className="text-[13px] text-muted">{a.kind === 'cash' ? 'Cash' : 'Bank'}{a.is_default ? ' · used when no account is chosen' : ''}</span>
                    </div>
                    <span className={`text-[19px] font-semibold whitespace-nowrap ${Number(a.balance) < 0 ? 'text-red-800' : ''}`}>{rupees(a.balance)}</span>
                  </div>
                  {canManage && !a.has_opening && opening !== a.id && (
                    <Button tone="link" className="mt-1 -ml-4" onClick={() => setOpening(a.id)}>Set the balance it started with</Button>
                  )}
                  {opening === a.id && <OpeningForm account={a} onCancel={() => setOpening(null)} onDone={done} />}
                </Card>
              </li>
            ))}
          </ul>
        </>
      )}

      {canManage && accounts && (
        <div className="mt-4 flex flex-col gap-3 lg:max-w-xl">
          {form === 'add' && <AddForm project={project} onCancel={() => setForm('')} onDone={done} />}
          {form === 'move' && <MoveForm accounts={accounts} onCancel={() => setForm('')} onDone={done} />}
          {!form && (
            <div className="grid grid-cols-2 gap-2 lg:flex">
              <Button tone="ink" className="lg:px-6" onClick={() => setForm('move')}>Move money</Button>
              <Button tone="plain" className="lg:px-6" onClick={() => setForm('add')}>Add an account</Button>
            </div>
          )}
        </div>
      )}
    </Page>
  )
}

function OpeningForm({ account, onCancel, onDone }: { account: MoneyAccount; onCancel: () => void; onDone: () => Promise<void> }) {
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(localToday())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    const a = cleanAmount(amount)
    if (!a) return setError('Enter the balance, for example 35000')
    setBusy(true)
    try {
      await api(`/money-accounts/${account.id}/opening`, { amount: a, date })
      await onDone()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }
  return (
    <form onSubmit={submit} className="mt-3 flex flex-col gap-3 border-t border-line pt-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor={`ob-${account.id}`} className={labelClass}>Balance (₹)</label>
          <input id={`ob-${account.id}`} className={fieldClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label htmlFor={`od-${account.id}`} className={labelClass}>As on</label>
          <input id={`od-${account.id}`} type="date" className={fieldClass} max={localToday()} value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>
      <p className="m-0 text-[13px] text-muted">The amount in the account on the day you start using NexEagleFin. It is not counted as income.</p>
      <ErrorNote>{error}</ErrorNote>
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save balance'}</Button>
      </div>
    </form>
  )
}

function AddForm({ project, onCancel, onDone }: { project: Project; onCancel: () => void; onDone: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState<'cash' | 'bank'>('bank')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(localToday())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    const a = cleanAmount(amount || '0', true)
    if (a === null) return setError('Enter the balance, or leave it empty')
    setBusy(true)
    try {
      await api('/money-accounts', { project_id: project.id, name: name.trim(), kind, opening_balance: a, as_of: date })
      await onDone()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4 rounded-2xl border border-line bg-white p-4">
      <h2 className="m-0 text-lg font-semibold">Add an account</h2>
      <div>
        <label htmlFor="acc-name" className={labelClass}>Name, for example HDFC current account or Pharmacy cash</label>
        <input id="acc-name" className={fieldClass} required minLength={2} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <Choice label="Kind" value={kind} onChange={setKind} options={[{ value: 'bank', label: 'Bank account' }, { value: 'cash', label: 'Cash box' }]} />
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="acc-open" className={labelClass}>Balance it starts with (₹)</label>
          <input id="acc-open" className={fieldClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label htmlFor="acc-date" className={labelClass}>As on</label>
          <input id="acc-date" type="date" className={fieldClass} max={localToday()} value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>
      <ErrorNote>{error}</ErrorNote>
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Add account'}</Button>
      </div>
    </form>
  )
}

function MoveForm({ accounts, onCancel, onDone }: { accounts: MoneyAccount[]; onCancel: () => void; onDone: () => Promise<void> }) {
  const cash = accounts.find((a) => a.kind === 'cash') ?? accounts[0]
  const bank = accounts.find((a) => a.kind === 'bank' && a.id !== cash.id) ?? accounts[1] ?? accounts[0]
  const [from, setFrom] = useState(cash.id)
  const [to, setTo] = useState(bank.id)
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(localToday())
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    const a = cleanAmount(amount)
    if (!a) return setError('Enter the amount moved')
    if (from === to) return setError('Choose two different accounts')
    setBusy(true)
    try {
      await api('/transfers', { from_account_id: from, to_account_id: to, amount: a, date, note: note.trim() || null })
      await onDone()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4 rounded-2xl border border-line bg-white p-4">
      <h2 className="m-0 text-lg font-semibold">Move money</h2>
      <p className="m-0 -mt-2 text-[13px] text-muted">For cash deposited in the bank, cash withdrawn, or money moved between banks. It is not income or a cost.</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="mv-from" className={labelClass}>From</label>
          <select id="mv-from" className={fieldClass} value={from} onChange={(e) => setFrom(e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="mv-to" className={labelClass}>To</label>
          <select id="mv-to" className={fieldClass} value={to} onChange={(e) => setTo(e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="mv-amount" className={labelClass}>Amount (₹)</label>
          <input id="mv-amount" className={fieldClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label htmlFor="mv-date" className={labelClass}>Date</label>
          <input id="mv-date" type="date" className={fieldClass} max={localToday()} value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>
      <div>
        <label htmlFor="mv-note" className={labelClass}>Note (optional)</label>
        <input id="mv-note" className={fieldClass} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <ErrorNote>{error}</ErrorNote>
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Move money'}</Button>
      </div>
    </form>
  )
}
