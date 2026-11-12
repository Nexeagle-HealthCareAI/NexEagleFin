import { useEffect, useState } from 'react'
import { api, type Doc, type Me, type Project } from '../api'
import { Card, Choice, ErrorNote, Page, TopBar, niceDate, rupees } from '../ui'

/** Expenses saved with "sort later". Pick a category and the entry leaves the list. */
export default function Sort({ project, me, onBack }: { project: Project; me: Me; onBack: () => void }) {
  const [docs, setDocs] = useState<Doc[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const load = () =>
    api<Doc[]>(`/documents?status=needs_attention&project_id=${project.id}`).then(setDocs).catch((e: Error) => setError(e.message))
  useEffect(() => { load() }, [project.id])

  async function choose(doc: Doc, categoryId: string) {
    setBusy(doc.id)
    setError('')
    try {
      await api(`/documents/${doc.id}/categorize`, { category_id: categoryId })
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Page wide>
      <TopBar title="Needs a category" sub={project.name} onBack={onBack} backOnPhoneOnly />
      <ErrorNote>{error}</ErrorNote>
      {docs?.length === 0 && <Card><p className="m-0 font-medium text-green-800">All sorted. Nothing is waiting.</p></Card>}
      <div className="flex flex-col gap-3 lg:grid lg:grid-cols-2 lg:items-start lg:gap-4">
        {docs?.map((d) => (
          <Card key={d.id} className={busy === d.id ? 'opacity-50' : ''}>
            <div className="mb-3 flex items-start justify-between gap-3">
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-[15px] font-semibold">{d.party ?? 'No name given'}</span>
                <span className="text-[13px] text-muted">{d.unit} · {niceDate(d.date)}{d.note ? ` · ${d.note}` : ''}</span>
              </div>
              <span className="text-[17px] font-semibold">{rupees(d.amount)}</span>
            </div>
            <Choice label="What was it for?" value={null} onChange={(id) => choose(d, id)}
              options={me.categories.map((c) => ({ value: c.id, label: c.name }))} />
          </Card>
        ))}
      </div>
    </Page>
  )
}
