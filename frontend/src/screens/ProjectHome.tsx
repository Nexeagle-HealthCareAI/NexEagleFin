import { useEffect, useState } from 'react'
import { api, type Doc, type Home, type Project } from '../api'
import { describe } from '../entries'
import type { EntryKind } from './EntryForm'
import { Button, Card, ErrorNote, Page, StatCard, StatRow, TopBar, niceDate, rupees } from '../ui'

export default function ProjectHome({ project, canWrite, canInvest, onBack, onRecord, onDues, onSort, onEntries, onLoans, onCash }: {
  project: Project
  canWrite: boolean
  canInvest: boolean
  onBack: () => void
  onRecord: (kind: EntryKind) => void
  onDues: (tab: 'receive' | 'pay' | 'advances') => void
  onSort: () => void
  onEntries: () => void
  onLoans: () => void
  onCash?: () => void
}) {
  const [home, setHome] = useState<Home | null>(null)
  const [latest, setLatest] = useState<Doc[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    api<Home>(`/reports/home?project_id=${project.id}`).then(setHome).catch((e: Error) => setError(e.message))
    api<Doc[]>(`/documents?project_id=${project.id}&limit=8`)
      .then((docs) => setLatest(docs.filter((d) => d.status !== 'reversed')))
      .catch((e: Error) => setError(e.message))
  }, [project.id])

  return (
    <Page wide>
      <TopBar title={project.name} sub="Today" onBack={onBack} backOnPhoneOnly />
      <ErrorNote>{error}</ErrorNote>
      {home && (
        <div className="flex flex-col gap-4 lg:gap-6">
          <StatRow label="Today">
            <StatCard dark label="Cash and bank today" value={rupees(home.cash_and_bank)} onClick={onCash} />
            <StatCard label="Money in today" value={rupees(home.money_in_today)} />
            <StatCard label="Money out today" value={rupees(home.money_out_today)} />
            <StatCard label="To receive" value={rupees(home.to_receive)} onClick={() => onDues('receive')} />
            <StatCard label="To pay" value={rupees(home.to_pay)} onClick={() => onDues('pay')} />
          </StatRow>

          <div className="grid grid-cols-2 gap-2 lg:flex">
            {canWrite && <Button className="lg:px-6" onClick={() => onRecord('expense')}>Record expense</Button>}
            {canWrite && <Button tone="ink" className="lg:px-6" onClick={() => onRecord('collection')}>Record collection</Button>}
            {canInvest && <Button tone="plain" className="col-span-2 lg:px-6" onClick={() => onRecord('investment')}>Add investment</Button>}
          </div>

          {home.needs_attention > 0 && (
            <button type="button" onClick={onSort}
              className="flex min-h-12 items-center justify-between rounded-xl bg-amber-100 px-3 text-left text-sm font-medium text-amber-900">
              <span>{home.needs_attention} {home.needs_attention === 1 ? 'expense needs' : 'expenses need'} a category</span>
              <span>Sort now</span>
            </button>
          )}

          {Number(home.advances_held) > 0 && (
            <button type="button" onClick={() => onDues('advances')}
              className="flex min-h-12 items-center justify-between gap-3 rounded-xl border border-line bg-white px-4 text-left text-sm">
              <span><span className="font-semibold">{rupees(home.advances_held)}</span> of the cash and bank is patient advances held</span>
              <span className="font-medium text-action">See</span>
            </button>
          )}

          <button type="button" onClick={onLoans}
            className="flex min-h-14 items-center justify-between gap-3 rounded-2xl border border-line bg-white px-4 py-3 text-left">
            <span className="flex min-w-0 flex-col">
              <span className="text-[15px] font-semibold">Loans</span>
              <span className="text-[13px] text-muted">
                {home.loans.count === 0 ? 'None recorded. Add a loan to track its instalments.'
                  : `${rupees(home.loans.outstanding)} still owed${home.loans.next ? ` · next ${rupees(home.loans.next.amount)} on ${niceDate(home.loans.next.date)}` : ''}`}
              </span>
            </span>
            {home.loans.overdue > 0 && (
              <span className="shrink-0 rounded-lg bg-red-100 px-2 py-0.5 text-xs font-medium text-red-900">
                {home.loans.overdue} overdue
              </span>
            )}
          </button>

          <div className="flex flex-col gap-4 lg:grid lg:grid-cols-5 lg:items-start lg:gap-6">
          <section className="lg:col-span-3">
            <h2 className="mb-2 text-[13px] font-semibold text-muted">This month, by unit</h2>
            <Card className="overflow-x-auto p-0!">
              <table className="w-full whitespace-nowrap text-left text-sm">
                <thead>
                  <tr className="text-[13px] text-muted">
                    <th scope="col" className="px-3 py-2.5 font-medium">Unit</th>
                    <th scope="col" className="px-1.5 py-2.5 text-right font-medium">Income</th>
                    <th scope="col" className="px-1.5 py-2.5 text-right font-medium">Costs</th>
                    <th scope="col" className="px-3 py-2.5 text-right font-medium">Profit</th>
                  </tr>
                </thead>
                <tbody>
                  {home.units_this_month.map((u) => (
                    <tr key={u.unit_id} className="border-t border-line">
                      <th scope="row" className="px-3 py-3 font-medium">{u.unit}</th>
                      <td className="px-1.5 py-3 text-right">{rupees(u.income)}</td>
                      <td className="px-1.5 py-3 text-right">{rupees(u.costs)}</td>
                      <td className={`px-3 py-3 text-right font-semibold ${Number(u.profit) < 0 ? 'text-red-800' : ''}`}>{rupees(u.profit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </section>

          <section className="lg:col-span-2">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="m-0 text-[13px] font-semibold text-muted">Latest entries</h2>
              <button type="button" onClick={onEntries} className="min-h-11 px-1 text-sm font-medium text-action">See all</button>
            </div>
            <Card className="p-0!">
              {latest.length === 0 && <p className="m-0 p-4 text-sm text-muted">Nothing recorded yet.</p>}
              <ul className="m-0 list-none p-0">
                {latest.map((d) => {
                  const e = describe(d)
                  return (
                    <li key={d.id} className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 first:border-t-0">
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate text-[15px] font-medium">{e.label}</span>
                        <span className="text-[13px] text-muted">{d.unit} · {niceDate(d.date)}</span>
                      </div>
                      <span className={`whitespace-nowrap text-[15px] font-semibold ${e.sign === '+' ? 'text-green-800' : ''}`}>
                        {e.sign && `${e.sign} `}{rupees(d.amount)}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </Card>
          </section>
          </div>
        </div>
      )}
    </Page>
  )
}
