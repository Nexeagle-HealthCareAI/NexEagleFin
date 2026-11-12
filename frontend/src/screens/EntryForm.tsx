import { useEffect, useState } from 'react'
import { api, localToday, moneyAccounts, type Me, type MoneyAccount, type Project } from '../api'
import { AccountPicker, Button, Choice, ErrorNote, MODES, Page, TopBar, WarningBox, chosenAccount, cleanAmount, fieldClass, labelClass, trySave, type Mode } from '../ui'

export type EntryKind = 'expense' | 'collection' | 'investment'

const TITLES: Record<EntryKind, string> = {
  expense: 'Record expense',
  collection: 'Record collection',
  investment: 'Add investment',
}

export default function EntryForm({ kind, project, me, onDone, onCancel }: {
  kind: EntryKind
  project: Project
  me: Me
  onDone: () => void
  onCancel: () => void
}) {
  const firstUnit = project.units.find((u) => u.kind !== 'general') ?? project.units[0]
  const [amount, setAmount] = useState('')
  const [unitId, setUnitId] = useState(firstUnit?.id ?? '')
  const [date, setDate] = useState(localToday())
  const [mode, setMode] = useState<Mode | null>(kind === 'investment' ? 'bank' : null)
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [paidTo, setPaidTo] = useState('')
  const [paid, setPaid] = useState<'paid' | 'to_pay'>('paid')
  const [note, setNote] = useState('')
  const [reference, setReference] = useState('')
  const [error, setError] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  const [sortLater, setSortLater] = useState(false)
  const [accounts, setAccounts] = useState<MoneyAccount[] | null>(null)
  const [accountId, setAccountId] = useState('')
  useEffect(() => { moneyAccounts(project.id).then(setAccounts) }, [project.id])
  const [busy, setBusy] = useState(false)

  // a message about a field goes away once the person changes something
  useEffect(() => { setError(''); setWarnings([]) }, [amount, unitId, date, mode, categoryId, paidTo, paid, reference])

  async function save(later = false, confirmed = false) {
    const clean = cleanAmount(amount)
    if (!clean) return setError('Enter the amount, for example 4850 or 4850.50')
    const needsMode = kind !== 'expense' || paid === 'paid'
    if (needsMode && !mode) return setError('Choose how the money moved')
    if (kind === 'expense' && !later && !categoryId) return setError('Choose what it was for, or use "Save now, sort later"')
    if (kind === 'expense' && paid === 'to_pay' && !paidTo.trim()) return setError('Say who is to be paid')

    setBusy(true)
    setError('')
    setSortLater(later)
    const send = () => {
      if (kind === 'expense') {
        return api('/documents/expense', {
          unit_id: unitId, date, amount: clean, category_id: later ? null : categoryId,
          paid_to: paidTo.trim() || null, paid: paid === 'paid', payment_mode: paid === 'paid' ? mode : null,
          note: note.trim() || null, confirmed, money_account_id: paid === 'paid' ? chosenAccount(accounts, mode, accountId) : null,
        })
      }
      if (kind === 'collection') {
        return api('/documents/collection', {
          unit_id: unitId, date, amount: clean, payment_mode: mode, reference: reference.trim() || null, note: note.trim() || null, confirmed,
          money_account_id: chosenAccount(accounts, mode, accountId),
        })
      }
      return api('/documents/investment', {
        project_id: project.id, date, amount: clean, payment_mode: mode, note: note.trim() || null, confirmed,
        money_account_id: chosenAccount(accounts, mode, accountId),
      })
    }
    if (await trySave(send, setWarnings, setError)) return onDone()
    setBusy(false)
  }

  return (
    <Page>
      <TopBar title={TITLES[kind]} sub={project.name} onBack={onCancel} />
      <form className="flex flex-1 flex-col gap-5" onSubmit={(e) => { e.preventDefault(); save() }}>
        <div>
          <label htmlFor="amount" className={labelClass}>Amount (₹)</label>
          <input id="amount" inputMode="decimal" autoFocus autoComplete="off" value={amount} onChange={(e) => setAmount(e.target.value)}
            className="h-16 w-full rounded-2xl border border-slate-300 bg-white px-4 text-[32px] font-semibold" />
        </div>

        {kind === 'expense' && (
          <>
            <div>
              <label htmlFor="paidto" className={labelClass}>Paid to</label>
              <input id="paidto" className={fieldClass} maxLength={200} value={paidTo} onChange={(e) => setPaidTo(e.target.value)} />
            </div>
            <Choice label="What for" value={categoryId} onChange={setCategoryId}
              options={me.categories.map((c) => ({ value: c.id, label: c.name }))} />
            <Choice label="Status" value={paid} onChange={setPaid}
              options={[{ value: 'paid', label: 'Paid' }, { value: 'to_pay', label: 'To pay later' }]} />
          </>
        )}

        {(kind !== 'expense' || paid === 'paid') && (
          <Choice label={kind === 'expense' ? 'Paid by' : 'Received by'} value={mode} onChange={setMode} options={[...MODES]} />
        )}
        {(kind !== 'expense' || paid === 'paid') && (
          <AccountPicker accounts={accounts} mode={mode} value={accountId} onChange={setAccountId}
            label={kind === 'expense' ? 'Paid from' : 'Received into'} />
        )}

        <div className="grid grid-cols-2 gap-3">
          {kind !== 'investment' && (
            <div>
              <label htmlFor="unit" className={labelClass}>Unit</label>
              <select id="unit" className={fieldClass} value={unitId} onChange={(e) => setUnitId(e.target.value)}>
                {project.units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label htmlFor="date" className={labelClass}>Date</label>
            <input id="date" type="date" className={fieldClass} required max={localToday()} value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
        </div>

        {kind === 'collection' && (
          <div>
            <label htmlFor="ref" className={labelClass}>Patient or bill number (optional)</label>
            <input id="ref" className={fieldClass} maxLength={100} value={reference} onChange={(e) => setReference(e.target.value)} />
            <p className="mt-1 mb-0 text-[13px] text-muted">Lets the app add up cash from the same patient against the ₹2 lakh cash limit. No names needed.</p>
          </div>
        )}

        <div>
          <label htmlFor="note" className={labelClass}>Note (optional)</label>
          <input id="note" className={fieldClass} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>

        <ErrorNote>{error}</ErrorNote>
        <WarningBox warnings={warnings} busy={busy} onBack={() => setWarnings([])} onConfirm={() => save(sortLater, true)} />
        <div className={`mt-auto flex flex-col gap-1 pt-2 ${warnings.length ? 'hidden' : ''}`}>
          <Button type="submit" disabled={busy} className="min-h-14 text-[17px]">{busy ? 'Saving…' : 'Save'}</Button>
          {kind === 'expense' && <Button tone="link" disabled={busy} onClick={() => save(true)}>Save now, sort later</Button>}
        </div>
      </form>
    </Page>
  )
}
