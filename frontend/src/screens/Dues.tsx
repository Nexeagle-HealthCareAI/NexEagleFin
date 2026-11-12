import { useEffect, useState, type FormEvent } from 'react'
import Advances from './Advances'
import { api, localToday, type Dues as DuesReport, type OpenItem, type Project } from '../api'
import { Button, Card, Choice, ErrorNote, MODES, Page, TopBar, cleanAmount, fieldClass, labelClass, niceDate, rupees, trySave, WarningBox, type Mode } from '../ui'

type Tab = 'receive' | 'pay' | 'advances'
const BUCKETS = [
  { key: '0-30', label: '0–30 days', color: '#86EFAC' },
  { key: '31-60', label: '31–60', color: '#FBBF24' },
  { key: '61-90', label: '61–90', color: '#EA580C' },
  { key: '90+', label: '90+', color: '#7F1D1D' },
] as const

function AgePill({ days }: { days: number }) {
  const [text, tone] =
    days > 60 ? [`${days} days, overdue`, 'bg-red-100 text-red-900']
    : days > 30 ? [`${days} days, due soon`, 'bg-amber-100 text-amber-900']
    : [days <= 0 ? 'Today' : `${days} ${days === 1 ? 'day' : 'days'}`, 'bg-green-100 text-green-900']
  return <span className={`rounded-lg px-2 py-0.5 text-xs font-medium ${tone}`}>{text}</span>
}

export default function Dues({ project, tab: firstTab, canWrite, onBack }: {
  project: Project
  tab: Tab
  canWrite: boolean
  onBack: () => void
}) {
  const [tab, setTab] = useState<Tab>(firstTab)
  const [items, setItems] = useState<OpenItem[] | null>(null)
  const [report, setReport] = useState<DuesReport | null>(null)
  const [open, setOpen] = useState<string | null>(null) // id of the row whose form is showing
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    try {
      const kind = tab === 'receive' ? 'claim' : 'bill'
      setItems(await api<OpenItem[]>(`/reports/open-items?kind=${kind}&project_id=${project.id}`))
      if (tab === 'receive') setReport(await api<DuesReport>(`/reports/dues?project_id=${project.id}`))
    } catch (e) {
      setError((e as Error).message)
    }
  }
  useEffect(() => { setItems(null); setOpen(null); setAdding(false); if (tab !== 'advances') load() }, [tab, project.id])

  const total = items?.reduce((sum, i) => sum + Number(i.due), 0) ?? 0
  const done = async () => { setOpen(null); setAdding(false); await load() }

  return (
    <Page wide>
      <TopBar title="Dues" sub={project.name} onBack={onBack} backOnPhoneOnly />
      <div className="mb-4 grid grid-cols-3 gap-1 rounded-xl border border-slate-300 bg-white p-1 lg:w-[26rem]">
        {(['receive', 'pay', 'advances'] as const).map((t) => (
          <button key={t} type="button" aria-pressed={tab === t} onClick={() => setTab(t)}
            className={`min-h-11 rounded-lg text-sm ${tab === t ? 'bg-ink font-semibold text-white' : 'font-medium'}`}>
            {t === 'receive' ? 'To receive' : t === 'pay' ? 'To pay' : 'Advances'}
          </button>
        ))}
      </div>
      <ErrorNote>{error}</ErrorNote>
      {tab === 'advances' && <Advances project={project} canWrite={canWrite} />}

      {tab !== 'advances' && items && (
        <Card className="mb-4">
          <span className="text-[13px] text-muted">{tab === 'receive' ? 'Total to receive' : 'Total to pay'}</span>
          <div className="text-[30px] font-semibold tracking-tight">{rupees(total)}</div>
          {tab === 'receive' && report && total > 0 && (
            <>
              <div role="img" aria-label="Amount due by age" className="mt-3 flex h-3.5 gap-0.5 overflow-hidden rounded-full">
                {BUCKETS.map((b) => Number(report.ageing[b.key]) > 0 && (
                  <div key={b.key} style={{ flex: `${Number(report.ageing[b.key])} 1 0`, background: b.color }} />
                ))}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
                {BUCKETS.map((b) => (
                  <div key={b.key} className="flex items-center justify-between gap-2 text-[13px]">
                    <span className="flex items-center gap-1.5 text-muted">
                      <span className="size-2.5 rounded-sm" style={{ background: b.color }} />{b.label}
                    </span>
                    <span className="font-semibold">{rupees(report.ageing[b.key])}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
      )}

      <div className="flex flex-col gap-3 lg:grid lg:grid-cols-2 lg:items-start lg:gap-4">
        {tab !== 'advances' && items?.map((i) => (
          <Card key={i.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 flex-col gap-1">
                <span className="truncate text-[15px] font-semibold">{i.party ?? 'No name given'}</span>
                <span className="text-[13px] text-muted">{i.unit}{i.reference ? ` · ${i.reference}` : ''} · {niceDate(i.date)}</span>
                <span><AgePill days={i.age_days} /></span>
              </div>
              <div className="flex flex-col items-end gap-0.5">
                <span className="text-[17px] font-semibold">{rupees(i.due)}</span>
                {i.due !== i.amount && <span className="text-xs text-muted">of {rupees(i.amount)}</span>}
              </div>
            </div>
            {canWrite && (open === i.id
              ? <SettleForm item={i} tab={tab} onCancel={() => setOpen(null)} onDone={done} />
              : <Button tone="plain" className="mt-3 w-full" onClick={() => setOpen(i.id)}>
                  {tab === 'receive' ? 'Record money received' : 'Record payment'}
                </Button>)}
          </Card>
        ))}
        {tab !== 'advances' && items?.length === 0 && !adding && (
          <Card><p className="m-0 text-muted">{tab === 'receive' ? 'Nobody owes this project money right now.' : 'No unpaid bills. To add one, record an expense and choose "To pay later".'}</p></Card>
        )}
      </div>

      {tab === 'receive' && canWrite && (adding
        ? <ClaimForm project={project} onCancel={() => setAdding(false)} onDone={done} />
        : <Button tone="ink" className="mt-4 min-h-14 lg:min-h-12 lg:self-start lg:px-6" onClick={() => setAdding(true)}>Add insurance or credit bill</Button>)}
    </Page>
  )
}

function SettleForm({ item, tab, onCancel, onDone }: { item: OpenItem; tab: Tab; onCancel: () => void; onDone: () => Promise<void> }) {
  const [amount, setAmount] = useState(item.due)
  const [cut, setCut] = useState('0')
  const [mode, setMode] = useState<Mode>('bank')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])
  useEffect(() => { setError(''); setWarnings([]) }, [amount, cut, mode])

  async function submit(e?: FormEvent, confirmed = false) {
    e?.preventDefault()
    const a = cleanAmount(amount)
    const c = cleanAmount(cut || '0', true)
    if (!a) return setError('Enter the amount, for example 162000')
    if (tab === 'receive' && c === null) return setError('Enter the amount the insurer cut, or 0')
    setBusy(true)
    const send = () => tab === 'receive'
      ? api(`/documents/${item.id}/settle`, { date: localToday(), received: a, deduction: c, payment_mode: mode, confirmed })
      : api(`/documents/${item.id}/pay`, { date: localToday(), amount: a, payment_mode: mode, confirmed })
    if (await trySave(send, setWarnings, setError)) return onDone()
    setBusy(false)
  }

  const id = item.id
  return (
    <form onSubmit={submit} className="mt-3 flex flex-col gap-3 border-t border-line pt-3">
      <div className={tab === 'receive' ? 'grid grid-cols-2 gap-3' : ''}>
        <div>
          <label htmlFor={`amt-${id}`} className={labelClass}>{tab === 'receive' ? 'Received (₹)' : 'Paid now (₹)'}</label>
          <input id={`amt-${id}`} className={fieldClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        {tab === 'receive' && (
          <div>
            <label htmlFor={`cut-${id}`} className={labelClass}>Cut by insurer (₹)</label>
            <input id={`cut-${id}`} className={fieldClass} inputMode="decimal" value={cut} onChange={(e) => setCut(e.target.value)} />
          </div>
        )}
      </div>
      <Choice label={tab === 'receive' ? 'Received by' : 'Paid by'} value={mode} onChange={setMode} options={[...MODES]} />
      <ErrorNote>{error}</ErrorNote>
      <WarningBox warnings={warnings} busy={busy} onBack={() => setWarnings([])} onConfirm={() => submit(undefined, true)} />
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button>
      </div>
    </form>
  )
}

function ClaimForm({ project, onCancel, onDone }: { project: Project; onCancel: () => void; onDone: () => Promise<void> }) {
  const firstUnit = project.units.find((u) => u.kind !== 'general') ?? project.units[0]
  const [payer, setPayer] = useState('')
  const [reference, setReference] = useState('')
  const [amount, setAmount] = useState('')
  const [unitId, setUnitId] = useState(firstUnit?.id ?? '')
  const [date, setDate] = useState(localToday())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const a = cleanAmount(amount)
    if (!a) return setError('Enter the billed amount, for example 180000')
    setBusy(true)
    setError('')
    try {
      await api('/documents/claim', { unit_id: unitId, date, amount: a, payer: payer.trim(), reference: reference.trim() || null })
      await onDone()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-4 flex flex-col gap-4 rounded-2xl border border-line bg-white p-4 lg:max-w-xl">
      <h2 className="m-0 text-lg font-semibold">New insurance or credit bill</h2>
      <div>
        <label htmlFor="payer" className={labelClass}>Who will pay (insurer, TPA, scheme or company)</label>
        <input id="payer" className={fieldClass} required minLength={2} maxLength={200} value={payer} onChange={(e) => setPayer(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="billed" className={labelClass}>Billed amount (₹)</label>
          <input id="billed" className={fieldClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label htmlFor="ref" className={labelClass}>Bill number</label>
          <input id="ref" className={fieldClass} maxLength={100} value={reference} onChange={(e) => setReference(e.target.value)} />
        </div>
        <div>
          <label htmlFor="cunit" className={labelClass}>Unit</label>
          <select id="cunit" className={fieldClass} value={unitId} onChange={(e) => setUnitId(e.target.value)}>
            {project.units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="cdate" className={labelClass}>Bill date</label>
          <input id="cdate" type="date" className={fieldClass} required max={localToday()} value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>
      <ErrorNote>{error}</ErrorNote>
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save bill'}</Button>
      </div>
    </form>
  )
}
