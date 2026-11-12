import { useEffect, useState } from 'react'
import { api, localToday, type Doc, type DocDetail, type Me, type Project } from '../api'
import { describe } from '../entries'
import { Button, Card, ErrorNote, Page, TopBar, fieldClass, labelClass, niceDate, rupees } from '../ui'

type Group = '' | 'in' | 'out' | 'dues'
const GROUPS: { value: Group; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'in', label: 'Money in' },
  { value: 'out', label: 'Money out' },
  { value: 'dues', label: 'Dues' },
]
const PAGE = 50
const MODE_TEXT: Record<string, string> = { cash: 'Cash', upi: 'UPI', card: 'Card', bank: 'Bank transfer' }

function lastMonths(count: number): { value: string; label: string }[] {
  const [y, m] = localToday().split('-').map(Number)
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(y, m - 1 - i, 1)
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    return { value, label: d.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' }) }
  })
}

/** Every entry in the project (the day book), with what sits behind each one. */
export default function Entries({ project, me, onBack }: { project: Project; me: Me; onBack: () => void }) {
  const months = lastMonths(12)
  const [group, setGroup] = useState<Group>('')
  const [month, setMonth] = useState(months[0].value)
  const [docs, setDocs] = useState<Doc[] | null>(null)
  const [more, setMore] = useState(false)
  const [locked, setLocked] = useState<string[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const query = (offset: number) =>
    `/documents?project_id=${project.id}&limit=${PAGE}&offset=${offset}${group ? `&group=${group}` : ''}${month ? `&month=${month}` : ''}`

  async function load() {
    try {
      const [list, periods] = await Promise.all([api<Doc[]>(query(0)), api<{ locked: string[] }>(`/periods?project_id=${project.id}`)])
      setDocs(list)
      setMore(list.length === PAGE)
      setLocked(periods.locked)
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }
  useEffect(() => { setDocs(null); setOpen(null); load() }, [group, month, project.id])

  async function loadMore() {
    if (!docs) return
    try {
      const next = await api<Doc[]>(query(docs.length))
      setDocs([...docs, ...next])
      setMore(next.length === PAGE)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const isLocked = locked.includes(month)
  async function setLock(action: 'lock' | 'unlock') {
    setBusy(true)
    try {
      await api(`/projects/${project.id}/periods/${month}/${action}`, {})
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const monthName = months.find((m) => m.value === month)?.label

  return (
    <Page wide>
      <TopBar title="Entries" sub={project.name} onBack={onBack} backOnPhoneOnly />

      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div role="group" aria-label="Show" className="grid grid-cols-4 gap-1 rounded-xl border border-slate-300 bg-white p-1 lg:w-[26rem]">
          {GROUPS.map((g) => (
            <button key={g.value} type="button" aria-pressed={group === g.value} onClick={() => setGroup(g.value)}
              className={`min-h-11 rounded-lg text-sm ${group === g.value ? 'bg-ink font-semibold text-white' : 'font-medium'}`}>
              {g.label}
            </button>
          ))}
        </div>
        <div className="lg:w-56">
          <label htmlFor="month" className={labelClass}>Month</label>
          <select id="month" className={fieldClass} value={month} onChange={(e) => setMonth(e.target.value)}>
            {months.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            <option value="">All months</option>
          </select>
        </div>
      </div>

      {month && (
        <div className={`mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl px-3.5 py-2.5 text-sm ${isLocked ? 'bg-slate-200' : 'bg-white border border-line'}`}>
          <span className="font-medium">
            {isLocked ? `${monthName} is closed for this project. Entries in it cannot be added or cancelled.` : `${monthName} is open.`}
          </span>
          {me.role === 'owner' && (
            <Button tone="plain" disabled={busy} onClick={() => setLock(isLocked ? 'unlock' : 'lock')}>
              {isLocked ? 'Reopen month' : 'Close month'}
            </Button>
          )}
        </div>
      )}

      <ErrorNote>{error}</ErrorNote>
      {docs?.length === 0 && <Card><p className="m-0 text-muted">No entries here.</p></Card>}

      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {docs?.map((d) => {
          const e = describe(d)
          const cancelled = d.status === 'reversed'
          const expanded = open === d.id
          return (
            <li key={d.id} className="rounded-2xl border border-line bg-white">
              <button type="button" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : d.id)}
                className="flex min-h-14 w-full items-center justify-between gap-3 px-4 py-3 text-left">
                <span className="flex min-w-0 flex-col">
                  <span className={`truncate text-[15px] font-medium ${cancelled ? 'text-muted line-through' : ''}`}>{e.label}</span>
                  <span className="text-[13px] text-muted">
                    {d.unit} · {niceDate(d.date)}{d.category ? ` · ${d.category}` : ''}
                  </span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-0.5">
                  <span className={`text-[15px] font-semibold whitespace-nowrap ${cancelled ? 'text-muted line-through' : e.sign === '+' ? 'text-green-800' : ''}`}>
                    {e.sign && `${e.sign} `}{rupees(d.amount)}
                  </span>
                  {cancelled && <span className="rounded-lg bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-800">Cancelled</span>}
                </span>
              </button>
              {expanded && <Detail id={d.id} canCancel={me.role === 'owner' || me.role === 'accountant'} onChanged={load} />}
            </li>
          )
        })}
      </ul>
      {more && <Button tone="plain" className="mt-3 self-center px-6" onClick={loadMore}>Show more</Button>}
    </Page>
  )
}

function Detail({ id, canCancel, onChanged }: { id: string; canCancel: boolean; onChanged: () => Promise<void> }) {
  const [d, setD] = useState<DocDetail | null>(null)
  const [error, setError] = useState('')
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api<DocDetail>(`/documents/${id}`).then(setD).catch((e: Error) => setError(e.message)) }, [id])

  async function cancel() {
    if (reason.trim().length < 3) return setError('Say why this entry is being cancelled')
    setBusy(true)
    setError('')
    try {
      await api(`/documents/${id}/reverse`, { reason: reason.trim() })
      await onChanged()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  if (!d) return <div className="border-t border-line px-4 py-3"><ErrorNote>{error}</ErrorNote>{!error && <span className="text-sm text-muted">Loading…</span>}</div>
  const facts: [string, string][] = [
    ['Recorded by', `${d.recorded_by ?? 'Unknown'} on ${niceDate(d.recorded_at.slice(0, 10))}`],
    ...(d.payment_mode ? [['Paid or received by', MODE_TEXT[d.payment_mode] ?? d.payment_mode] as [string, string]] : []),
    ...(d.reference ? [['Bill number', d.reference] as [string, string]] : []),
    ...(Number(d.deduction ?? 0) > 0 ? [['Cut by insurer', rupees(d.deduction!)] as [string, string]] : []),
    ...(d.note ? [['Note', d.note] as [string, string]] : []),
  ]
  return (
    <div className="flex flex-col gap-4 border-t border-line px-4 py-4">
      <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
        {facts.map(([k, v]) => (
          <div key={k} className="flex flex-col">
            <dt className="text-[13px] text-muted">{k}</dt>
            <dd className="m-0 text-[15px] break-words">{v}</dd>
          </div>
        ))}
      </dl>

      {d.payments.length > 0 && (
        <div>
          <h3 className="mb-1 text-[13px] font-semibold text-muted">Payments against this entry</h3>
          <ul className="m-0 list-none p-0 text-[15px]">
            {d.payments.map((p) => (
              <li key={p.id} className={`flex justify-between py-1 ${p.status === 'reversed' ? 'text-muted line-through' : ''}`}>
                <span>{niceDate(p.date)}</span>
                <span className="font-medium">{rupees(p.amount)}{Number(p.deduction) > 0 ? ` + ${rupees(p.deduction)} cut` : ''}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="mb-1 text-[13px] font-semibold text-muted">In the books (for your accountant)</h3>
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-left text-sm whitespace-nowrap">
            <thead>
              <tr className="text-[13px] text-muted">
                <th scope="col" className="px-3 py-2 font-medium">Account</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Debit</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Credit</th>
              </tr>
            </thead>
            <tbody>
              {d.books.map((b, i) => (
                <tr key={i} className={`border-t border-line ${b.reversal ? 'text-muted' : ''}`}>
                  <th scope="row" className="px-3 py-2 font-normal">{b.account}{b.reversal ? ' (cancel)' : ''}</th>
                  <td className="px-3 py-2 text-right">{Number(b.debit) ? rupees(b.debit) : ''}</td>
                  <td className="px-3 py-2 text-right">{Number(b.credit) ? rupees(b.credit) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {canCancel && d.status !== 'reversed' && (d.month_locked ? (
        <p className="m-0 text-[13px] text-muted">This month is closed, so the entry cannot be cancelled.</p>
      ) : asking ? (
        <div className="flex flex-col gap-2">
          <label htmlFor={`why-${id}`} className={labelClass}>Why is it being cancelled?</label>
          <input id={`why-${id}`} className={fieldClass} maxLength={250} value={reason} onChange={(e) => setReason(e.target.value)} />
          <p className="m-0 text-[13px] text-muted">The entry stays visible as cancelled, and its effect on the books is undone.</p>
          <ErrorNote>{error}</ErrorNote>
          <div className="grid grid-cols-2 gap-2 sm:flex">
            <Button tone="plain" onClick={() => { setAsking(false); setError('') }}>Keep entry</Button>
            <Button tone="ink" disabled={busy} onClick={cancel}>{busy ? 'Cancelling…' : 'Cancel entry'}</Button>
          </div>
        </div>
      ) : (
        <Button tone="plain" className="self-start" onClick={() => setAsking(true)}>Cancel this entry</Button>
      ))}
    </div>
  )
}
