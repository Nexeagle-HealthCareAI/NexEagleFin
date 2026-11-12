import { useEffect, useState, type FormEvent } from 'react'
import { api, type Dashboard, type Me } from '../api'
import { Button, Card, ErrorNote, Page, Stat, StatCard, StatRow, TopBar, fieldClass, labelClass, rupees } from '../ui'

const UNIT_CHOICES = [
  { value: 'hospital', label: 'Hospital' },
  { value: 'diagnostics', label: 'Diagnostics' },
  { value: 'path_lab', label: 'Path lab' },
  { value: 'pharmacy', label: 'Pharmacy' },
]

export default function Projects({ me, onOpen, onChanged, onLogout }: {
  me: Me
  onOpen: (projectId: string) => void
  onChanged: () => Promise<void>
  onLogout: () => void
}) {
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)

  const load = () => api<Dashboard>('/reports/projects').then(setDash).catch((e: Error) => setError(e.message))
  useEffect(() => { load() }, [])

  const t = dash?.totals
  return (
    <Page wide>
      <TopBar title="All projects" sub={me.name} right={<Button tone="link" className="lg:hidden" onClick={onLogout}>Log out</Button>} />
      <ErrorNote>{error}</ErrorNote>

      {t && dash.projects.length > 0 && (
        <div className="mb-4 lg:mb-6">
          <StatRow label="Totals across all projects">
            <StatCard dark label="Cash and bank, all projects" value={rupees(t.cash_and_bank)} />
            <StatCard label="Invested so far" value={rupees(t.invested)} />
            <StatCard label="Profit this month" value={rupees(t.profit_this_month)} />
            <StatCard label="To receive" value={rupees(t.to_receive)} />
            <StatCard label="To pay" value={rupees(t.to_pay)} />
          </StatRow>
        </div>
      )}

      <div className="flex flex-col gap-3 lg:grid lg:grid-cols-2 lg:gap-4">
        {dash?.projects.map((p) => (
          <button key={p.id} type="button" onClick={() => onOpen(p.id)} className="rounded-2xl border border-line bg-white p-4 text-left">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-[17px] font-semibold">{p.name}</span>
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="#475569" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4l4 4-4 4" /></svg>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-3">
              <Stat label="Cash and bank" value={rupees(p.cash_and_bank)} />
              <Stat label="Invested" value={rupees(p.invested)} />
              <Stat label="Profit this month" value={rupees(p.profit_this_month)} tone={Number(p.profit_this_month) < 0 ? 'bad' : undefined} />
              <Stat label="To receive / to pay" value={`${rupees(p.to_receive)} / ${rupees(p.to_pay)}`} />
            </div>
          </button>
        ))}
        {dash && dash.projects.length === 0 && !adding && (
          <Card><p className="m-0 text-muted">No projects yet. Create your first one, for example your hospital.</p></Card>
        )}
      </div>

      {me.role === 'owner' && (adding
        ? <NewProject onCancel={() => setAdding(false)} onSaved={async () => { setAdding(false); await onChanged(); await load() }} />
        : <Button tone="ink" className="mt-4 min-h-14 lg:min-h-12 lg:self-start lg:px-6" onClick={() => setAdding(true)}>New project</Button>)}
    </Page>
  )
}

function NewProject({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [units, setUnits] = useState<string[]>(['hospital'])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api('/projects', { name, units })
      await onSaved()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-4 flex flex-col gap-4 rounded-2xl border border-line bg-white p-4 lg:max-w-xl">
      <h2 className="m-0 text-lg font-semibold">New project</h2>
      <div>
        <label htmlFor="pname" className={labelClass}>Project name</label>
        <input id="pname" className={fieldClass} required minLength={2} maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <fieldset className="m-0 border-0 p-0">
        <legend className="mb-2 p-0 text-[13px] font-medium text-muted">What does it include?</legend>
        <div className="grid grid-cols-2 gap-2">
          {UNIT_CHOICES.map((u) => (
            <label key={u.value} className="flex min-h-11 items-center gap-2 rounded-xl border border-slate-300 px-3 text-[15px] font-medium">
              <input type="checkbox" className="size-5" checked={units.includes(u.value)}
                onChange={(e) => setUnits(e.target.checked ? [...units, u.value] : units.filter((x) => x !== u.value))} />
              {u.label}
            </label>
          ))}
        </div>
      </fieldset>
      <ErrorNote>{error}</ErrorNote>
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create project'}</Button>
      </div>
    </form>
  )
}
