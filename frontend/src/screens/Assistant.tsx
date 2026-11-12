import { useEffect, useState } from 'react'
import { api, type Me, type Project, type Suggestion } from '../api'
import { Button, Card, ErrorNote, MODES, Page, TopBar, cleanAmount, fieldClass, labelClass, niceDate, rupees, trySave, WarningBox } from '../ui'

const FLAG_TEXT: Record<string, [string, 'bad' | 'warn']> = {
  possible_duplicate: ['Looks already recorded', 'bad'],
  amount_unclear: ['Amount not clear', 'bad'],
  cash_deposit: ['Cash deposit: usually already counted', 'bad'],
  no_category: ['Needs a category', 'warn'],
  unit_unclear: ['Check the unit', 'warn'],
  mode_unclear: ['How was it paid?', 'warn'],
  date_unclear: ['Check the date', 'warn'],
}
const TYPE_TEXT = { expense: 'Money out', collection: 'Money in', investment: 'Investment' }
const tone = { bad: 'bg-red-100 text-red-900', warn: 'bg-amber-100 text-amber-900', good: 'bg-green-100 text-green-900' }

function Pill({ kind, children }: { kind: keyof typeof tone; children: string }) {
  return <span className={`rounded-lg px-2 py-0.5 text-xs font-medium ${tone[kind]}`}>{children}</span>
}

/** The bookkeeper agent: paste notes or a bank statement, review what it suggests, approve. */
export default function Assistant({ project, me, onBack }: { project: Project; me: Me; onBack: () => void }) {
  const canApprove = me.role === 'owner' || me.role === 'accountant'
  const [source, setSource] = useState<'text' | 'bank_csv'>('text')
  const [content, setContent] = useState('')
  const [fileName, setFileName] = useState('')
  const [list, setList] = useState<Suggestion[] | null>(null)
  const [readBy, setReadBy] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () =>
    api<Suggestion[]>(`/agents/proposals?project_id=${project.id}`).then(setList).catch((e: Error) => setError(e.message))
  useEffect(() => { load() }, [project.id])

  async function read() {
    if (content.trim().length < 3) return setError(source === 'text' ? 'Type or paste at least one entry' : 'Choose the statement file first')
    setBusy(true)
    setError('')
    try {
      const out = await api<{ read_by: string }>('/agents/bookkeeper/run', { project_id: project.id, source, content })
      setReadBy(out.read_by)
      setContent('')
      setFileName('')
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function pickFile(file: File | undefined) {
    if (!file) return
    setError('')
    if (file.size > 190_000) return setError('This file is too large. Export a shorter period, up to about 200 lines.')
    setFileName(file.name)
    setContent(await file.text())
  }

  const sure = list?.filter((s) => s.confidence >= 0.8 && s.flags.length === 0) ?? []
  async function approveSure() {
    setBusy(true)
    setError('')
    try {
      for (const s of sure) await api(`/agents/proposals/${s.id}/approve`, {})
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
      await load()
    }
  }

  return (
    <Page wide>
      <TopBar title="Assistant: all suggestions" sub={project.name} onBack={onBack} backOnPhoneOnly />

      <Card className="mb-4 flex flex-col gap-3 lg:max-w-3xl">
        <div className="grid grid-cols-2 gap-1 rounded-xl border border-slate-300 p-1">
          {([['text', 'Notes'], ['bank_csv', 'Bank statement']] as const).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={source === value}
              onClick={() => { setSource(value); setContent(''); setFileName(''); setError('') }}
              className={`min-h-11 rounded-lg text-sm ${source === value ? 'bg-ink font-semibold text-white' : 'font-medium'}`}>
              {label}
            </button>
          ))}
        </div>
        {source === 'text' ? (
          <div>
            <label htmlFor="notes" className={labelClass}>One entry per line, in your own words</label>
            <textarea id="notes" rows={5} value={content} onChange={(e) => setContent(e.target.value)}
              placeholder={'paid 4850 to Shree Medical Gases for oxygen cash\nreceived 26400 pharmacy counter upi'}
              className="w-full rounded-xl border border-slate-300 bg-white p-3 text-base" />
          </div>
        ) : (
          <div>
            <label htmlFor="stmt" className={labelClass}>Statement file from your bank (CSV)</label>
            <input id="stmt" type="file" accept=".csv,text/csv" onChange={(e) => pickFile(e.target.files?.[0])}
              className="block w-full text-sm file:mr-3 file:min-h-11 file:rounded-xl file:border file:border-slate-300 file:bg-white file:px-4 file:font-medium" />
            {fileName && <p className="mt-2 mb-0 text-[13px] text-muted">{fileName} is ready to read.</p>}
          </div>
        )}
        <ErrorNote>{error}</ErrorNote>
        <Button disabled={busy} onClick={read}>{busy ? 'Reading…' : 'Read and suggest entries'}</Button>
        <p className="m-0 text-[13px] text-muted">Nothing is added to the books until it is approved.</p>
      </Card>

      {list && list.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="m-0 text-[15px] font-semibold">
            {list.length} {list.length === 1 ? 'suggestion' : 'suggestions'} waiting
            {readBy && <span className="font-normal text-muted"> · read by {readBy === 'groq' ? 'AI' : 'keyword rules'}</span>}
          </h2>
          {canApprove && sure.length > 0 && (
            <Button tone="ink" disabled={busy} onClick={approveSure}>Approve {sure.length} sure {sure.length === 1 ? 'one' : 'ones'}</Button>
          )}
        </div>
      )}
      {list?.length === 0 && <p className="text-muted">No suggestions waiting.</p>}

      <div className="flex flex-col gap-3 lg:grid lg:grid-cols-2 lg:items-start lg:gap-4">
        {list?.map((s) => <SuggestionRow key={s.id} s={s} project={project} me={me} canApprove={canApprove} onDone={load} />)}
      </div>
    </Page>
  )
}

export function SuggestionRow({ s, project, me, canApprove, onDone }: {
  s: Suggestion
  project: Project
  me: Me
  canApprove: boolean
  onDone: () => Promise<unknown>
}) {
  const [amount, setAmount] = useState(s.amount ?? '')
  const [unitId, setUnitId] = useState(s.unit_id)
  const [categoryId, setCategoryId] = useState(s.category_id ?? '')
  const [mode, setMode] = useState(s.payment_mode ?? '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const needsMode = s.type !== 'expense' || s.paid
  const [warnings, setWarnings] = useState<string[]>([])

  async function decide(action: 'approve' | 'reject', confirmed = false) {
    let body = {}
    if (action === 'approve') {
      const clean = cleanAmount(amount)
      if (!clean) return setError('Enter the amount')
      if (needsMode && !mode) return setError('Choose how the money moved')
      body = { amount: clean, unit_id: unitId, category_id: categoryId || null, payment_mode: mode || null, confirmed }
    }
    setBusy(true)
    setError('')
    if (await trySave(() => api(`/agents/proposals/${s.id}/${action}`, body), setWarnings, setError)) return onDone()
    setBusy(false)
  }

  const level = s.confidence >= 0.8 ? ['Sure', 'good'] as const : s.confidence >= 0.5 ? ['Check', 'warn'] as const : ['Unsure', 'bad'] as const
  const selectClass = `${fieldClass} h-11 text-[15px]`
  return (
    <Card className={busy ? 'opacity-50' : ''}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-[15px] font-semibold">{TYPE_TEXT[s.type]}{s.party ? ` · ${s.party}` : ''}{s.type === 'expense' && !s.paid ? ' · to pay later' : ''}</span>
          <span className="text-[13px] text-muted">{niceDate(s.date)}</span>
        </div>
        <span className="whitespace-nowrap text-[17px] font-semibold">{s.amount ? rupees(s.amount) : '?'}</span>
      </div>
      <p className="mt-2 mb-0 rounded-lg bg-slate-100 px-2.5 py-1.5 text-[13px] break-words text-muted">{s.raw_text}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Pill kind={level[1]}>{level[0]}</Pill>
        {s.flags.map((f) => FLAG_TEXT[f] && <Pill key={f} kind={FLAG_TEXT[f][1]}>{FLAG_TEXT[f][0]}</Pill>)}
      </div>
      {s.reason && <p className="mt-2 mb-0 text-[13px] text-muted">{s.reason}</p>}

      {canApprove ? (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {!s.amount && (
              <div className="col-span-2">
                <label htmlFor={`a-${s.id}`} className={labelClass}>Amount (₹)</label>
                <input id={`a-${s.id}`} className={selectClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
              </div>
            )}
            {s.type !== 'investment' && (
              <div>
                <label htmlFor={`u-${s.id}`} className={labelClass}>Unit</label>
                <select id={`u-${s.id}`} className={selectClass} value={unitId} onChange={(e) => setUnitId(e.target.value)}>
                  {project.units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                </select>
              </div>
            )}
            {s.type === 'expense' && (
              <div>
                <label htmlFor={`c-${s.id}`} className={labelClass}>What for</label>
                <select id={`c-${s.id}`} className={selectClass} value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                  <option value="">Sort later</option>
                  {me.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
            )}
            {needsMode && !s.payment_mode && (
              <div>
                <label htmlFor={`m-${s.id}`} className={labelClass}>{s.type === 'expense' ? 'Paid by' : 'Received by'}</label>
                <select id={`m-${s.id}`} className={selectClass} value={mode} onChange={(e) => setMode(e.target.value)}>
                  <option value="">Choose</option>
                  {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </div>
            )}
          </div>
          <ErrorNote>{error}</ErrorNote>
          <div className="mt-3"><WarningBox warnings={warnings} busy={busy} onBack={() => setWarnings([])} onConfirm={() => decide('approve', true)} /></div>
          <div className={`mt-3 grid grid-cols-2 gap-2 ${warnings.length ? 'hidden' : ''}`}>
            <Button tone="plain" disabled={busy} onClick={() => decide('reject')}>Reject</Button>
            <Button disabled={busy} onClick={() => decide('approve')}>Approve</Button>
          </div>
        </>
      ) : (
        <p className="mt-3 mb-0 text-[13px] font-medium text-muted">Waiting for the owner or accountant to approve.</p>
      )}
    </Card>
  )
}
