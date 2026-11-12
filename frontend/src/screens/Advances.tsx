import { useEffect, useState, type FormEvent } from 'react'
import { api, localToday, moneyAccounts, type MoneyAccount, type OpenItem, type Project } from '../api'
import { AccountPicker, Button, Card, Choice, ErrorNote, MODES, WarningBox, chosenAccount, cleanAmount, fieldClass, labelClass, niceDate, rupees, trySave, type Mode } from '../ui'

/** Deposits taken from patients: held until the final bill, then used for the bill or refunded. */
export default function Advances({ project, canWrite }: { project: Project; canWrite: boolean }) {
  const [items, setItems] = useState<OpenItem[] | null>(null)
  const [accounts, setAccounts] = useState<MoneyAccount[] | null>(null)
  const [open, setOpen] = useState<{ id: string; what: 'adjust' | 'refund' } | null>(null)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState('')

  const load = () =>
    api<OpenItem[]>(`/reports/open-items?kind=advance&project_id=${project.id}`).then(setItems).catch((e: Error) => setError(e.message))
  useEffect(() => { load(); moneyAccounts(project.id).then(setAccounts) }, [project.id])
  const done = async () => { setOpen(null); setAdding(false); await load() }
  const total = items?.reduce((sum, i) => sum + Number(i.due), 0) ?? 0

  return (
    <>
      <ErrorNote>{error}</ErrorNote>
      {items && (
        <Card className="mb-4">
          <span className="text-[13px] text-muted">Patient advances held</span>
          <div className="text-[30px] font-semibold tracking-tight">{rupees(total)}</div>
          <p className="m-0 text-[13px] text-muted">This is the patients' money until their bills are settled, so it is not counted as income.</p>
        </Card>
      )}
      <div className="flex flex-col gap-3 lg:grid lg:grid-cols-2 lg:items-start lg:gap-4">
        {items?.map((i) => (
          <Card key={i.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-[15px] font-semibold">{i.reference}</span>
                <span className="text-[13px] text-muted">{i.unit} · taken {niceDate(i.date)}</span>
              </div>
              <div className="flex flex-col items-end">
                <span className="text-[17px] font-semibold">{rupees(i.due)}</span>
                {i.due !== i.amount && <span className="text-xs text-muted">of {rupees(i.amount)}</span>}
              </div>
            </div>
            {canWrite && (open?.id === i.id
              ? <UseForm item={i} what={open.what} accounts={accounts} onCancel={() => setOpen(null)} onDone={done} />
              : (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <Button tone="plain" onClick={() => setOpen({ id: i.id, what: 'adjust' })}>Use for the bill</Button>
                  <Button tone="plain" onClick={() => setOpen({ id: i.id, what: 'refund' })}>Refund</Button>
                </div>
              ))}
          </Card>
        ))}
        {items?.length === 0 && !adding && <Card><p className="m-0 text-muted">No advances are held right now.</p></Card>}
      </div>
      {canWrite && (adding
        ? <TakeForm project={project} accounts={accounts} onCancel={() => setAdding(false)} onDone={done} />
        : <Button tone="ink" className="mt-4 min-h-14 lg:min-h-12 lg:self-start lg:px-6" onClick={() => setAdding(true)}>Take an advance</Button>)}
    </>
  )
}

function UseForm({ item, what, accounts, onCancel, onDone }: {
  item: OpenItem; what: 'adjust' | 'refund'; accounts: MoneyAccount[] | null; onCancel: () => void; onDone: () => Promise<void>
}) {
  const [amount, setAmount] = useState(item.due)
  const [mode, setMode] = useState<Mode>('upi')
  const [accountId, setAccountId] = useState('')
  const [error, setError] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => { setError(''); setWarnings([]) }, [amount, mode])

  async function submit(e?: FormEvent, confirmed = false) {
    e?.preventDefault()
    const a = cleanAmount(amount)
    if (!a) return setError('Enter the amount')
    setBusy(true)
    const send = () => what === 'adjust'
      ? api(`/documents/${item.id}/adjust-advance`, { date: localToday(), amount: a })
      : api(`/documents/${item.id}/refund-advance`, { date: localToday(), amount: a, payment_mode: mode, money_account_id: chosenAccount(accounts, mode, accountId), confirmed })
    if (await trySave(send, setWarnings, setError)) return onDone()
    setBusy(false)
  }
  return (
    <form onSubmit={submit} className="mt-3 flex flex-col gap-3 border-t border-line pt-3">
      <div>
        <label htmlFor={`ua-${item.id}`} className={labelClass}>{what === 'adjust' ? 'Amount of the final bill paid from the advance (₹)' : 'Amount refunded (₹)'}</label>
        <input id={`ua-${item.id}`} className={fieldClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </div>
      {what === 'adjust'
        ? <p className="m-0 text-[13px] text-muted">That amount becomes {item.unit} income today. Refund anything left over separately.</p>
        : (
          <>
            <Choice label="Refunded by" value={mode} onChange={setMode} options={[...MODES]} />
            <AccountPicker accounts={accounts} mode={mode} value={accountId} onChange={setAccountId} label="Paid from" />
          </>
        )}
      <ErrorNote>{error}</ErrorNote>
      <WarningBox warnings={warnings} busy={busy} onBack={() => setWarnings([])} onConfirm={() => submit(undefined, true)} />
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button>
      </div>
    </form>
  )
}

function TakeForm({ project, accounts, onCancel, onDone }: { project: Project; accounts: MoneyAccount[] | null; onCancel: () => void; onDone: () => Promise<void> }) {
  const firstUnit = project.units.find((u) => u.kind === 'hospital') ?? project.units.find((u) => u.kind !== 'general') ?? project.units[0]
  const [reference, setReference] = useState('')
  const [amount, setAmount] = useState('')
  const [unitId, setUnitId] = useState(firstUnit?.id ?? '')
  const [mode, setMode] = useState<Mode | null>(null)
  const [accountId, setAccountId] = useState('')
  const [date, setDate] = useState(localToday())
  const [error, setError] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => { setError(''); setWarnings([]) }, [amount, mode, reference])

  async function submit(e?: FormEvent, confirmed = false) {
    e?.preventDefault()
    const a = cleanAmount(amount)
    if (!reference.trim()) return setError('Enter the patient or IP number, so the advance can be found at discharge')
    if (!a) return setError('Enter the amount')
    if (!mode) return setError('Choose how the money came in')
    setBusy(true)
    const send = () => api('/advances', {
      unit_id: unitId, date, amount: a, payment_mode: mode, reference: reference.trim(),
      money_account_id: chosenAccount(accounts, mode, accountId), confirmed,
    })
    if (await trySave(send, setWarnings, setError)) return onDone()
    setBusy(false)
  }
  return (
    <form onSubmit={submit} className="mt-4 flex flex-col gap-4 rounded-2xl border border-line bg-white p-4 lg:max-w-xl">
      <h2 className="m-0 text-lg font-semibold">Take an advance</h2>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="adv-ref" className={labelClass}>Patient or IP number</label>
          <input id="adv-ref" className={fieldClass} maxLength={100} value={reference} onChange={(e) => setReference(e.target.value)} />
        </div>
        <div>
          <label htmlFor="adv-amount" className={labelClass}>Amount (₹)</label>
          <input id="adv-amount" className={fieldClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label htmlFor="adv-unit" className={labelClass}>Unit</label>
          <select id="adv-unit" className={fieldClass} value={unitId} onChange={(e) => setUnitId(e.target.value)}>
            {project.units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="adv-date" className={labelClass}>Date</label>
          <input id="adv-date" type="date" className={fieldClass} max={localToday()} value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>
      <Choice label="Received by" value={mode} onChange={setMode} options={[...MODES]} />
      <AccountPicker accounts={accounts} mode={mode} value={accountId} onChange={setAccountId} label="Received into" />
      <ErrorNote>{error}</ErrorNote>
      <WarningBox warnings={warnings} busy={busy} onBack={() => setWarnings([])} onConfirm={() => submit(undefined, true)} />
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save advance'}</Button>
      </div>
    </form>
  )
}
