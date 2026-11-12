import { useEffect, useRef, useState } from 'react'
import { api, type Project, type Suggestion } from '../api'
import { Office as OfficeScene, type AgentInfo, type Status } from '../office/scene'
import { Button, Card, Page, TopBar } from '../ui'

const TEAM: (AgentInfo & { job: string })[] = [
  { key: 'bookkeeper', name: 'Bookkeeper', color: '#2563EB', built: true, job: 'Reads notes and bank statements, suggests entries' },
  { key: 'reconciler', name: 'Reconciler', color: '#DB2777', built: false, job: 'Matches bank lines to the books' },
  { key: 'claims', name: 'Claims', color: '#D97706', built: false, job: 'Chases insurance dues' },
  { key: 'tax', name: 'Tax', color: '#059669', built: false, job: 'Prepares GST and TDS workings' },
  { key: 'close', name: 'Month close', color: '#7C3AED', built: false, job: 'Runs the month-end checklist' },
  { key: 'auditor', name: 'Auditor', color: '#DC2626', built: false, job: 'Looks for duplicates and odd amounts' },
  { key: 'ask', name: 'Ask', color: '#0891B2', built: false, job: 'Answers questions about the numbers' },
]

/** A 3D view of the assistants at work, in meetings and on a break. */
export default function Office({ project, onBack, onAssistant }: { project: Project; onBack: () => void; onAssistant: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const scene = useRef<OfficeScene | null>(null)
  const drag = useRef<number | null>(null)
  const [status, setStatus] = useState<Status>({})
  const [paused, setPaused] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [failed, setFailed] = useState(false)
  const [pending, setPending] = useState(0)

  useEffect(() => {
    if (!canvas.current) return
    let office: OfficeScene
    try {
      office = new OfficeScene(canvas.current, TEAM, setStatus)
    } catch {
      setFailed(true)
      return
    }
    scene.current = office
    office.setPaused(window.matchMedia('(prefers-reduced-motion: reduce)').matches)
    const watcher = new ResizeObserver(() => office.resize())
    watcher.observe(canvas.current)
    return () => {
      watcher.disconnect()
      office.dispose()
      scene.current = null
    }
  }, [])

  // the Bookkeeper's behaviour follows the real queue of suggestions
  useEffect(() => {
    let alive = true
    const check = () =>
      api<Suggestion[]>(`/agents/proposals?project_id=${project.id}`)
        .then((list) => alive && setPending(list.length))
        .catch(() => undefined)
    check()
    const timer = window.setInterval(check, 15000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [project.id])
  useEffect(() => { scene.current?.setPending(pending) }, [pending])

  function toggle() {
    scene.current?.setPaused(!paused)
    setPaused(!paused)
  }

  return (
    <Page wide>
      <TopBar title="Assistant office" sub={project.name} onBack={onBack} backOnPhoneOnly />

      {failed ? (
        <Card><p className="m-0 text-muted">This device cannot show the 3D office. The team list below still shows what everyone is doing.</p></Card>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-line bg-slate-200">
          <canvas
            ref={canvas}
            role="img"
            aria-label="Animated 3D office floor: assistants working at desks, meeting in a glass room and taking breaks at a pool table"
            className="block aspect-[4/5] w-full cursor-grab touch-pan-y active:cursor-grabbing sm:aspect-[16/9]"
            onPointerDown={(e) => { drag.current = e.clientX; e.currentTarget.setPointerCapture(e.pointerId) }}
            onPointerMove={(e) => {
              if (drag.current === null) return
              scene.current?.rotate((drag.current - e.clientX) * 0.006)
              drag.current = e.clientX
            }}
            onPointerUp={() => { drag.current = null }}
            onPointerCancel={() => { drag.current = null }}
          />
        </div>
      )}

      {!failed && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button tone="plain" onClick={toggle}>{paused ? 'Play' : 'Pause'}</Button>
          <Button tone="plain" aria-label="Turn the view left" onClick={() => scene.current?.rotate(-0.25)}>Turn left</Button>
          <Button tone="plain" aria-label="Turn the view right" onClick={() => scene.current?.rotate(0.25)}>Turn right</Button>
          <span className="text-[13px] text-muted">Drag the picture to look around.</span>
        </div>
      )}

      <h2 className="mt-6 mb-2 text-[15px] font-semibold">The team</h2>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 lg:grid lg:grid-cols-2 lg:gap-3">
        {TEAM.map((a) => (
          <li key={a.key} className="flex items-start gap-3 rounded-2xl border border-line bg-white p-3.5">
            <span aria-hidden="true" className="mt-1 size-3.5 shrink-0 rounded-full" style={{ background: a.color }} />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[15px] font-semibold">{a.name}</span>
                <span className={`rounded-lg px-2 py-0.5 text-xs font-medium ${a.built ? 'bg-green-100 text-green-900' : 'bg-slate-100 text-slate-700'}`}>
                  {a.built ? 'On the job' : 'Joining soon'}
                </span>
              </div>
              <span className="text-[13px] text-muted">{a.job}</span>
              <span className="text-sm font-medium">{status[a.key] ?? (failed ? '' : 'Arriving…')}</span>
            </div>
            {a.built && pending > 0 && <Button tone="link" className="shrink-0 px-2" onClick={onAssistant}>Review</Button>}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[13px] text-muted">
        Only the Bookkeeper does real work so far, and its desk follows the real queue of suggestions. The others are shown
        around the office until they are built.
      </p>
    </Page>
  )
}
