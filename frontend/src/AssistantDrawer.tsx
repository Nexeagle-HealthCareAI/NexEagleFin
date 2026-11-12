import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type Me, type Project, type Suggestion } from './api'
import { SuggestionRow } from './screens/Assistant'
import { Button, ErrorNote, fieldClass, labelClass } from './ui'

type Fact = { label: string; value: string }
type Turn =
  | { who: 'you'; text: string }
  | { who: 'assistant'; text: string; facts?: Fact[]; ids?: string[]; action?: Action; choices?: string[]; decided?: 'done' | 'cancelled' | 'failed' }
type Action = { id: string; title: string; rows: Fact[]; danger: boolean; warnings?: string[] }
type Reply = { reply: string; facts: Fact[]; proposals: Suggestion[]; action: Action | null; pending: object | null; choices: string[] }

const STARTERS = ['How much cash do we have?', 'Who owes us money?', 'Which bills are unpaid?', 'Profit this month?', 'Paid the EMI', 'Close last month']

/**
 * The assistant, in a drawer that opens over whatever screen is showing.
 * Ask about the numbers, or type what happened and it prepares entries to approve.
 */
export default function AssistantDrawer({ me, current, onClose, onFullPage, onOffice }: {
  me: Me
  current: Project | null
  onClose: () => void
  onFullPage: (projectId: string) => void
  onOffice: (projectId: string) => void
}) {
  const [projectId, setProjectId] = useState(current?.id ?? me.projects[0]?.id ?? '')
  const project = me.projects.find((p) => p.id === projectId) ?? null
  const canApprove = me.role === 'owner' || me.role === 'accountant'
  const [turns, setTurns] = useState<Turn[]>([])
  const [pending, setPending] = useState<Suggestion[]>([])
  const [question, setQuestion] = useState<object | null>(null)   // what the assistant asked last, sent back with the answer
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const end = useRef<HTMLDivElement>(null)

  const loadPending = () =>
    projectId ? api<Suggestion[]>(`/agents/proposals?project_id=${projectId}`).then(setPending).catch(() => undefined) : Promise.resolve()

  useEffect(() => { setTurns([]); setQuestion(null); loadPending() }, [projectId])
  useEffect(() => { box.current?.focus() }, [])
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [turns, pending.length])
  useEffect(() => {
    // Escape closes; Tab stays inside the drawer while it is open
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') return onClose()
      if (e.key !== 'Tab' || !panel.current) return
      const items = panel.current.querySelectorAll<HTMLElement>('button:not([disabled]), textarea, select, input, a[href]')
      if (!items.length) return
      const first = items[0], last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  async function say(said: string) {
    if (said.length < 2 || !projectId || busy) return
    setText('')
    setError('')
    const next: Turn[] = [...turns, { who: 'you', text: said }]
    setTurns(next)
    setBusy(true)
    try {
      const out = await api<Reply>('/agents/chat', {
        project_id: projectId, message: said, pending: question,
        history: turns.slice(-8).map((t) => ({ who: t.who, text: t.text })),
      })
      setQuestion(out.pending)
      setTurns([...next, {
        who: 'assistant', text: out.reply, facts: out.facts, ids: out.proposals.map((p) => p.id),
        action: out.action ?? undefined, choices: out.choices,
      }])
      if (out.proposals.length) await loadPending()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
      box.current?.focus()
    }
  }

  async function decide(index: number, action: Action, yes: boolean) {
    setBusy(true)
    setError('')
    try {
      const out = await api<{ status: 'done' | 'cancelled' | 'failed'; reply: string }>(`/agents/actions/${action.id}/${yes ? 'confirm' : 'cancel'}`, {})
      setTurns((now) => [
        ...now.map((t, i) => (i === index && t.who === 'assistant' ? { ...t, decided: out.status } : t)),
        { who: 'assistant', text: out.reply },
      ])
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
      box.current?.focus()
    }
  }

  function send(e: FormEvent) {
    e.preventDefault()
    say(text.trim())
  }

  const shown = new Set(turns.flatMap((t) => (t.who === 'assistant' ? t.ids ?? [] : [])))
  const earlier = pending.filter((p) => !shown.has(p.id)).length

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} aria-hidden="true" />
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby="assistant-title"
        className="relative flex h-dvh w-full max-w-md flex-col bg-ground shadow-2xl">
        <header className="flex items-center justify-between gap-2 border-b border-line bg-white px-4 py-3">
          <h2 id="assistant-title" className="m-0 text-lg font-semibold">Assistant</h2>
          <button type="button" aria-label="Close assistant" onClick={onClose} className="flex size-11 items-center justify-center rounded-xl hover:bg-slate-100">
            <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {me.projects.length > 1 && (
            <div className="mb-4">
              <label htmlFor="as-project" className={labelClass}>Project</label>
              <select id="as-project" className={fieldClass} value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                {me.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
          )}
          {!project && <p className="text-muted">Create a project first, then I can help with it.</p>}

          {project && turns.length === 0 && (
            <div className="rounded-2xl border border-line bg-white p-4 text-[15px]">
              <p className="mt-0 mb-1 font-medium">Ask me about {project.name}, or tell me what to do.</p>
              <p className="mt-0 mb-3 text-[13px] text-muted">For example: paid 4850 to Shree Medical Gases for oxygen cash. I show you every change before I make it.</p>
              <div className="flex flex-wrap gap-2">
                {STARTERS.map((q) => (
                  <button key={q} type="button" onClick={() => say(q)}
                    className="min-h-11 rounded-full border border-slate-300 bg-white px-3.5 text-sm font-medium">{q}</button>
                ))}
              </div>
            </div>
          )}

          <div className="mt-3 flex flex-col gap-3" aria-live="polite">
            {turns.map((t, i) => t.who === 'you' ? (
              <p key={i} className="m-0 ml-10 self-end rounded-2xl rounded-br-md bg-ink px-3.5 py-2.5 text-[15px] whitespace-pre-wrap text-white">{t.text}</p>
            ) : (
              <div key={i} className="flex flex-col gap-2">
                <div className="mr-6 self-start rounded-2xl rounded-bl-md border border-line bg-white px-3.5 py-2.5 text-[15px]">
                  <p className="m-0">{t.text}</p>
                  {t.facts && t.facts.length > 0 && (
                    <dl className="mt-2.5 mb-0 flex flex-col gap-1.5 border-t border-line pt-2.5">
                      {t.facts.map((f, n) => (
                        <div key={n} className="flex flex-col">
                          <dt className="text-[13px] text-muted">{f.label}</dt>
                          <dd className="m-0 font-medium">{f.value}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </div>
                {t.action && (
                  <div className={`mr-6 rounded-2xl border bg-white p-3.5 ${t.action.danger ? 'border-red-300' : 'border-action'}`}>
                    <h3 className="m-0 text-[15px] font-semibold">{t.action.title}</h3>
                    <dl className="mt-2 mb-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[15px]">
                      {t.action.rows.map((r) => (
                        <div key={r.label} className="contents">
                          <dt className="text-[13px] leading-6 text-muted">{r.label}</dt>
                          <dd className="m-0 text-right font-medium break-words">{r.value}</dd>
                        </div>
                      ))}
                    </dl>
                    {t.action.warnings && t.action.warnings.length > 0 && (
                      <div className="mt-3 flex flex-col gap-1.5 rounded-lg bg-amber-50 px-3 py-2.5">
                        {t.action.warnings.map((w) => <p key={w} className="m-0 text-[13px] text-amber-900">{w}</p>)}
                      </div>
                    )}
                    {t.decided ? (
                      <p className="mt-3 mb-0 text-[13px] font-medium text-muted">
                        {t.decided === 'done' ? 'Confirmed.' : t.decided === 'cancelled' ? 'Not done.' : 'Could not be done.'}
                      </p>
                    ) : (
                      <div className="mt-3 grid grid-cols-2 gap-2">
                        <Button tone="plain" disabled={busy} onClick={() => decide(i, t.action!, false)}>No</Button>
                        <Button disabled={busy} className={t.action.danger ? 'bg-red-700!' : ''} onClick={() => decide(i, t.action!, true)}>
                          {t.action.danger ? 'Yes, go ahead' : 'Yes, record it'}
                        </Button>
                      </div>
                    )}
                  </div>
                )}
                {t.choices && t.choices.length > 0 && i === turns.length - 1 && (
                  <div className="flex flex-wrap gap-2">
                    {t.choices.map((c) => (
                      <button key={c} type="button" disabled={busy} onClick={() => say(c)}
                        className="min-h-11 rounded-2xl border border-slate-300 bg-white px-3.5 py-1.5 text-left text-sm font-medium">{c}</button>
                    ))}
                  </div>
                )}
                {project && pending.filter((p) => t.ids?.includes(p.id)).map((p) => (
                  <SuggestionRow key={p.id} s={p} project={project} me={me} canApprove={canApprove} onDone={loadPending} />
                ))}
              </div>
            ))}
            {busy && <p className="m-0 self-start text-sm text-muted">Looking that up…</p>}
          </div>

          {project && earlier > 0 && (
            <button type="button" onClick={() => onFullPage(project.id)}
              className="mt-4 flex min-h-12 w-full items-center justify-between rounded-xl bg-amber-100 px-3 text-left text-sm font-medium text-amber-900">
              <span>{earlier} earlier {earlier === 1 ? 'suggestion is' : 'suggestions are'} waiting</span><span>Review</span>
            </button>
          )}
          <div ref={end} />
        </div>

        {project && (
          <form onSubmit={send} className="flex flex-col gap-2 border-t border-line bg-white px-4 pt-3 pb-4">
            <ErrorNote>{error}</ErrorNote>
            <label htmlFor="as-box" className="sr-only">Message to the assistant</label>
            <textarea id="as-box" ref={box} rows={2} value={text} onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) e.currentTarget.form?.requestSubmit() }}
              placeholder="Ask, or say what to do…" className="w-full resize-none rounded-xl border border-slate-300 p-3 text-base" />
            <div className="flex items-center justify-between gap-2">
              <div className="flex gap-1">
                <Button tone="link" className="px-2" onClick={() => onFullPage(project.id)}>Bank statement</Button>
                <Button tone="link" className="px-2" onClick={() => onOffice(project.id)}>Office</Button>
              </div>
              <Button type="submit" disabled={busy || text.trim().length < 2} className="px-6">Send</Button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
