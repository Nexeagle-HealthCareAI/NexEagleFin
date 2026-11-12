import { useEffect, useState, type FormEvent } from 'react'
import { api, localToday, type Loan, type LoanDetail, type LoansOverview, type Project } from '../api'
import { Button, Card, Choice, ErrorNote, MODES, Page, StatCard, TopBar, cleanAmount, fieldClass, labelClass, niceDate, rupees, trySave, WarningBox, type Mode } from '../ui'

function DuePill({ loan }: { loan: Loan }) {
  if (loan.status !== 'active' || loan.days_to_due === null) return <span className="rounded-lg bg-green-100 px-2 py-0.5 text-xs font-medium text-green-900">Fully repaid</span>
  if (loan.overdue > 0) return <span className="rounded-lg bg-red-100 px-2 py-0.5 text-xs font-medium text-red-900">{loan.overdue} {loan.overdue === 1 ? 'instalment' : 'instalments'} overdue</span>
  if (loan.days_to_due <= 7) return <span className="rounded-lg bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">Due {loan.days_to_due === 0 ? 'today' : `in ${loan.days_to_due} ${loan.days_to_due === 1 ? 'day' : 'days'}`}</span>
  return <span className="rounded-lg bg-green-100 px-2 py-0.5 text-xs font-medium text-green-900">Up to date</span>
}

/** Loans taken for the project: what is owed, what is due, and paying instalments. */
export default function Loans({ project, canManage, onBack }: { project: Project; canManage: boolean; onBack: () => void }) {
  const [loans, setLoans] = useState<Loan[] | null>(null)
  const [overview, setOverview] = useState<LoansOverview | null>(null)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState('')

  const load = () =>
    api<{ overview: LoansOverview; loans: Loan[] }>(`/loans?project_id=${project.id}`)
      .then((r) => { setLoans(r.loans); setOverview(r.overview) })
      .catch((e: Error) => setError(e.message))
  useEffect(() => { load() }, [project.id])

  return (
    <Page wide>
      <TopBar title="Loans" sub={project.name} onBack={onBack} backOnPhoneOnly />
      <ErrorNote>{error}</ErrorNote>

      {overview && overview.count > 0 && (
        <section aria-label="Loan totals" className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
          <StatCard dark label="Still owed on all loans" value={rupees(overview.outstanding)} />
          <StatCard label="Instalments each month" value={rupees(overview.monthly_instalments)} />
          <StatCard label="Next instalment" value={overview.next ? `${rupees(overview.next.amount)} · ${niceDate(overview.next.date)}` : 'None'} />
        </section>
      )}

      <div className="flex flex-col gap-3 lg:grid lg:grid-cols-2 lg:items-start lg:gap-4">
        {loans?.map((l) => <LoanCard key={l.id} loan={l} canManage={canManage} onChanged={load} />)}
      </div>
      {loans?.length === 0 && !adding && (
        <Card><p className="m-0 text-muted">No loans recorded for this project. Add one to see what is owed and get its instalments tracked.</p></Card>
      )}

      {canManage && (adding
        ? <LoanForm project={project} onCancel={() => setAdding(false)} onDone={async () => { setAdding(false); await load() }} />
        : <Button tone="ink" className="mt-4 min-h-14 lg:min-h-12 lg:self-start lg:px-6" onClick={() => setAdding(true)}>Add a loan</Button>)}
    </Page>
  )
}

function LoanCard({ loan, canManage, onChanged }: { loan: Loan; canManage: boolean; onChanged: () => Promise<unknown> }) {
  const [paying, setPaying] = useState(false)
  const [detail, setDetail] = useState<LoanDetail | null>(null)
  const [showing, setShowing] = useState(false)
  const repaid = Math.min(100, Math.round((Number(loan.principal_paid) / Number(loan.amount)) * 100))

  async function toggleDetail() {
    if (!showing) setDetail(await api<LoanDetail>(`/loans/${loan.id}`))
    setShowing(!showing)
  }

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="truncate text-[17px] font-semibold">{loan.lender}</span>
          <span className="text-[13px] text-muted">{loan.loan_type} · {Number(loan.rate)}% a year</span>
          <span><DuePill loan={loan} /></span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-[13px] text-muted">Still owed</span>
          <span className="text-[19px] font-semibold whitespace-nowrap">{rupees(loan.outstanding)}</span>
          <span className="text-xs text-muted">of {rupees(loan.amount)}</span>
        </div>
      </div>

      <div role="img" aria-label={`${repaid}% of this loan repaid`} className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full bg-green-700" style={{ width: `${repaid}%` }} />
      </div>

      <dl className="mt-3 mb-0 grid grid-cols-2 gap-x-4 gap-y-2 text-[13px]">
        <div><dt className="text-muted">Monthly instalment</dt><dd className="m-0 text-[15px] font-medium">{rupees(loan.emi)}</dd></div>
        <div><dt className="text-muted">Next due</dt><dd className="m-0 text-[15px] font-medium">{loan.next_due ? niceDate(loan.next_due) : 'Nothing due'}</dd></div>
        <div><dt className="text-muted">Instalments paid</dt><dd className="m-0 text-[15px] font-medium">{loan.instalments_paid}</dd></div>
        <div><dt className="text-muted">Instalments left</dt><dd className="m-0 text-[15px] font-medium">{loan.instalments_left ?? 'Check the rate'}</dd></div>
        <div><dt className="text-muted">Interest paid so far</dt><dd className="m-0 text-[15px] font-medium">{rupees(loan.interest_paid)}</dd></div>
        <div><dt className="text-muted">{loan.already_running ? 'In these books since' : 'Taken on'}</dt><dd className="m-0 text-[15px] font-medium">{niceDate(loan.start_date)}</dd></div>
      </dl>

      {paying ? (
        <PayForm loan={loan} onCancel={() => setPaying(false)} onDone={async () => { setPaying(false); setShowing(false); await onChanged() }} />
      ) : (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Button tone="plain" aria-expanded={showing} onClick={toggleDetail}>{showing ? 'Hide details' : 'Payments and plan'}</Button>
          {canManage && loan.status === 'active' && <Button onClick={() => setPaying(true)}>Pay instalment</Button>}
        </div>
      )}

      {showing && detail && (
        <div className="mt-3 flex flex-col gap-3 border-t border-line pt-3">
          <Rows title="Paid so far" empty="No instalments paid yet." rows={detail.payments.map((p) => [niceDate(p.date), rupees(p.amount), rupees(p.interest), rupees(p.principal)])}
            heads={['Date', 'Paid', 'Interest', 'Off the loan']} />
          <Rows title="Coming up, if paid on time" empty="Nothing left to pay." rows={detail.plan.map((p) => [niceDate(p.date), rupees(p.amount), rupees(p.interest), rupees(p.balance)])}
            heads={['Date', 'Instalment', 'Interest', 'Owed after']} />
        </div>
      )}
    </Card>
  )
}

function Rows({ title, heads, rows, empty }: { title: string; heads: string[]; rows: string[][]; empty: string }) {
  return (
    <div>
      <h3 className="mb-1 text-[13px] font-semibold text-muted">{title}</h3>
      {rows.length === 0 ? <p className="m-0 text-sm text-muted">{empty}</p> : (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-left text-sm whitespace-nowrap">
            <thead>
              <tr className="text-[13px] text-muted">
                {heads.map((h, i) => <th key={h} scope="col" className={`px-3 py-2 font-medium ${i ? 'text-right' : ''}`}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, n) => (
                <tr key={n} className="border-t border-line">
                  {r.map((c, i) => i === 0
                    ? <th key={i} scope="row" className="px-3 py-2 font-normal">{c}</th>
                    : <td key={i} className="px-3 py-2 text-right">{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function PayForm({ loan, onCancel, onDone }: { loan: Loan; onCancel: () => void; onDone: () => Promise<void> }) {
  const [amount, setAmount] = useState(loan.next_amount)
  const [interest, setInterest] = useState(loan.next_interest)
  const [mode, setMode] = useState<Mode>('bank')
  const [date, setDate] = useState(localToday())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])
  useEffect(() => setError(''), [amount, interest, mode, date])

  const a = cleanAmount(amount), i = cleanAmount(interest || '0', true)
  const principal = a && i !== null ? Number(a) - Number(i) : null

  async function submit(e?: FormEvent, confirmed = false) {
    e?.preventDefault()
    if (!a) return setError('Enter the amount paid')
    if (i === null) return setError('Enter the interest part, or 0')
    if (Number(i) > Number(a)) return setError('The interest part cannot be more than the amount paid')
    setBusy(true)
    const send = () => api(`/loans/${loan.id}/pay`, { date, amount: a, interest: i, payment_mode: mode, confirmed })
    if (await trySave(send, setWarnings, setError)) return onDone()
    setBusy(false)
  }

  const id = loan.id
  return (
    <form onSubmit={submit} className="mt-3 flex flex-col gap-3 border-t border-line pt-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor={`pa-${id}`} className={labelClass}>Amount paid (₹)</label>
          <input id={`pa-${id}`} className={fieldClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label htmlFor={`pi-${id}`} className={labelClass}>Of which interest (₹)</label>
          <input id={`pi-${id}`} className={fieldClass} inputMode="decimal" value={interest} onChange={(e) => setInterest(e.target.value)} />
        </div>
      </div>
      <p className="m-0 text-[13px] text-muted">
        {principal !== null && principal >= 0 ? `${rupees(principal)} comes off the loan. ` : ''}
        The interest is worked out from the rate; change it if your lender's statement shows a different figure.
      </p>
      <Choice label="Paid by" value={mode} onChange={setMode} options={[...MODES]} />
      <div>
        <label htmlFor={`pd-${id}`} className={labelClass}>Date paid</label>
        <input id={`pd-${id}`} type="date" className={fieldClass} required max={localToday()} value={date} onChange={(e) => setDate(e.target.value)} />
      </div>
      <ErrorNote>{error}</ErrorNote>
      <WarningBox warnings={warnings} busy={busy} onBack={() => setWarnings([])} onConfirm={() => submit(undefined, true)} />
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save payment'}</Button>
      </div>
    </form>
  )
}

function LoanForm({ project, onCancel, onDone }: { project: Project; onCancel: () => void; onDone: () => Promise<void> }) {
  const [types, setTypes] = useState<string[]>([])
  const [lender, setLender] = useState('')
  const [type, setType] = useState('')
  const [kind, setKind] = useState<'new' | 'running'>('new')
  const [amount, setAmount] = useState('')
  const [rate, setRate] = useState('')
  const [emi, setEmi] = useState('')
  const [start, setStart] = useState(localToday())
  const [firstDue, setFirstDue] = useState('')
  const [mode, setMode] = useState<Mode>('bank')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([])

  useEffect(() => { api<string[]>('/loan-types').then((t) => { setTypes(t); setType(t[0]) }).catch(() => undefined) }, [])

  async function submit(e?: FormEvent, confirmed = false) {
    e?.preventDefault()
    const a = cleanAmount(amount), m = cleanAmount(emi)
    if (!a) return setError(kind === 'new' ? 'Enter the loan amount' : 'Enter how much is still owed')
    if (!/^\d{1,2}(\.\d{1,2})?$/.test(rate.trim())) return setError('Enter the yearly interest rate, for example 10.5. Use 0 if there is no interest.')
    if (!m) return setError('Enter the monthly instalment')
    if (!firstDue) return setError('Choose the date of the next instalment')
    setBusy(true)
    setError('')
    const send = () => api('/loans', {
      project_id: project.id, lender: lender.trim(), loan_type: type, amount: a, already_running: kind === 'running',
      start_date: kind === 'running' ? localToday() : start, payment_mode: kind === 'new' ? mode : null,
      rate: rate.trim(), emi: m, first_due: firstDue, note: note.trim() || null, confirmed,
    })
    if (await trySave(send, setWarnings, setError)) return onDone()
    setBusy(false)
  }

  return (
    <form onSubmit={submit} className="mt-4 flex flex-col gap-4 rounded-2xl border border-line bg-white p-4 lg:max-w-xl">
      <h2 className="m-0 text-lg font-semibold">Add a loan</h2>
      <div>
        <label htmlFor="lender" className={labelClass}>Who lent the money (bank, company or person)</label>
        <input id="lender" className={fieldClass} required minLength={2} maxLength={200} value={lender} onChange={(e) => setLender(e.target.value)} />
      </div>
      <div>
        <label htmlFor="ltype" className={labelClass}>Type of loan</label>
        <select id="ltype" className={fieldClass} value={type} onChange={(e) => setType(e.target.value)}>
          {types.map((t) => <option key={t}>{t}</option>)}
        </select>
      </div>
      <Choice label="Is this a new loan?" value={kind} onChange={setKind}
        options={[{ value: 'new', label: 'New, money just received' }, { value: 'running', label: 'Already being repaid' }]} />
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label htmlFor="lamount" className={labelClass}>{kind === 'new' ? 'Loan amount received (₹)' : 'Amount still owed today, without future interest (₹)'}</label>
          <input id="lamount" className={fieldClass} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label htmlFor="lrate" className={labelClass}>Interest rate (% a year)</label>
          <input id="lrate" className={fieldClass} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
        </div>
        <div>
          <label htmlFor="lemi" className={labelClass}>Monthly instalment (₹)</label>
          <input id="lemi" className={fieldClass} inputMode="decimal" value={emi} onChange={(e) => setEmi(e.target.value)} />
        </div>
        {kind === 'new' && (
          <div>
            <label htmlFor="lstart" className={labelClass}>Date received</label>
            <input id="lstart" type="date" className={fieldClass} required max={localToday()} value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
        )}
        <div className={kind === 'new' ? '' : 'col-span-2'}>
          <label htmlFor="ldue" className={labelClass}>{kind === 'new' ? 'First instalment date' : 'Next instalment date'}</label>
          <input id="ldue" type="date" className={fieldClass} min={kind === 'new' ? start : localToday()} value={firstDue} onChange={(e) => setFirstDue(e.target.value)} />
        </div>
      </div>
      {kind === 'new' && <Choice label="Received by" value={mode} onChange={setMode} options={[...MODES]} />}
      <div>
        <label htmlFor="lnote" className={labelClass}>Note (optional), for example what it was taken for</label>
        <input id="lnote" className={fieldClass} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <ErrorNote>{error}</ErrorNote>
      <WarningBox warnings={warnings} busy={busy} onBack={() => setWarnings([])} onConfirm={() => submit(undefined, true)} />
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save loan'}</Button>
      </div>
    </form>
  )
}
