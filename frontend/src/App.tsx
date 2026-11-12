import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { api, hasToken, setToken, type Me } from './api'
import EntryForm, { type EntryKind } from './screens/EntryForm'
import Assistant from './screens/Assistant'
import CashBank from './screens/CashBank'
import Dues from './screens/Dues'
import Entries from './screens/Entries'
import Loans from './screens/Loans'
import Login from './screens/Login'
import ProjectHome from './screens/ProjectHome'
import Projects from './screens/Projects'
import Sort from './screens/Sort'
import AssistantDrawer from './AssistantDrawer'
import Sidebar, { icons } from './Sidebar'
import { ErrorNote, Page } from './ui'

// the 3D library is large, so it is only downloaded when the office is opened
const Office = lazy(() => import('./screens/Office'))

type View =
  | { name: 'projects' }
  | { name: 'project'; id: string }
  | { name: 'entry'; id: string; kind: EntryKind }
  | { name: 'dues'; id: string; tab: 'receive' | 'pay' | 'advances' }
  | { name: 'cash'; id: string }
  | { name: 'sort'; id: string }
  | { name: 'assistant'; id: string }
  | { name: 'office'; id: string }
  | { name: 'entries'; id: string }
  | { name: 'loans'; id: string }

export default function App() {
  const [authed, setAuthed] = useState(hasToken())
  const [me, setMe] = useState<Me | null>(null)
  const [view, setView] = useState<View>({ name: 'projects' })
  const [error, setError] = useState('')
  const [drawer, setDrawer] = useState(false)
  const [stamp, setStamp] = useState(0)   // bumped when the assistant closes, so the screen behind reloads its numbers
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('nexeaglefin.menu') === 'collapsed' } catch { return false }
  })
  const toggleMenu = () => {
    setCollapsed((was) => {
      try { localStorage.setItem('nexeaglefin.menu', was ? 'open' : 'collapsed') } catch { /* preference just is not remembered */ }
      return !was
    })
  }

  const loadMe = useCallback(async () => {
    try {
      setMe(await api<Me>('/me'))
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setAuthed(false)
    setMe(null)
    setView({ name: 'projects' })
  }, [])

  useEffect(() => {
    window.addEventListener('nexeaglefin:logout', logout)
    return () => window.removeEventListener('nexeaglefin:logout', logout)
  }, [logout])

  useEffect(() => { if (authed) loadMe() }, [authed, loadMe])

  if (!authed) return <Login onDone={() => setAuthed(true)} />
  if (!me) return <Page><div className="pt-10"><ErrorNote>{error}</ErrorNote>{!error && <p className="text-muted">Loading…</p>}</div></Page>

  const project = view.name === 'projects' ? null : me.projects.find((p) => p.id === view.id) ?? null
  const openProject = (id: string) => setView({ name: 'project', id })
  const canWrite = me.role !== 'auditor'
  // only people who see the whole project see its accounts and loans
  const whole = !!project?.units.some((u) => u.kind === 'general')

  let screen
  if (!project) {
    screen = <Projects me={me} onOpen={openProject} onChanged={loadMe} onLogout={logout} />
  } else {
    const back = () => openProject(project.id)
    if (view.name === 'dues') {
      screen = <Dues key={view.tab} project={project} tab={view.tab} canWrite={me.role !== 'auditor'} onBack={back} />
    } else if (view.name === 'cash') {
      screen = <CashBank project={project} canManage={me.role === 'owner' || me.role === 'accountant'} onBack={back} />
    } else if (view.name === 'loans') {
      screen = <Loans project={project} canManage={me.role === 'owner' || me.role === 'accountant'} onBack={back} />
    } else if (view.name === 'entries') {
      screen = <Entries project={project} me={me} onBack={back} />
    } else if (view.name === 'office') {
      screen = (
        <Suspense fallback={<p className="p-8 text-muted">Opening the office…</p>}>
          <Office project={project} onBack={back} onAssistant={() => setView({ name: 'assistant', id: project.id })} />
        </Suspense>
      )
    } else if (view.name === 'assistant') {
      screen = <Assistant project={project} me={me} onBack={back} />
    } else if (view.name === 'sort') {
      screen = <Sort project={project} me={me} onBack={back} />
    } else if (view.name === 'entry') {
      screen = <EntryForm key={view.kind} kind={view.kind} project={project} me={me} onDone={back} onCancel={back} />
    } else {
      screen = (
        <ProjectHome
          project={project}
          canWrite={canWrite}
          canInvest={me.role === 'owner' || me.role === 'accountant'}
          onBack={() => setView({ name: 'projects' })}
          onRecord={(kind) => setView({ name: 'entry', id: project.id, kind })}
          onDues={(tab) => setView({ name: 'dues', id: project.id, tab })}
          onSort={() => setView({ name: 'sort', id: project.id })}
          onEntries={() => setView({ name: 'entries', id: project.id })}
          onLoans={() => setView({ name: 'loans', id: project.id })}
          onCash={whole ? () => setView({ name: 'cash', id: project.id }) : undefined}
        />
      )
    }
  }

  const id = project?.id ?? ''
  const isEntry = (kind: EntryKind) => view.name === 'entry' && view.kind === kind
  return (
    <div className="lg:flex">
      <Sidebar
        me={me}
        project={project}
        onLogout={logout}
        collapsed={collapsed}
        onToggle={toggleMenu}
        onAssistant={() => setDrawer(true)}
        top={{ label: 'All projects', icon: icons.grid, active: !project, go: () => setView({ name: 'projects' }) }}
        items={[
          { label: 'Home', icon: icons.home, active: view.name === 'project', go: () => openProject(id) },
          ...(canWrite ? [
            { label: 'Record collection', icon: icons.in, active: isEntry('collection'), go: () => setView({ name: 'entry', id, kind: 'collection' as const }) },
            { label: 'Record expense', icon: icons.out, active: isEntry('expense'), go: () => setView({ name: 'entry', id, kind: 'expense' as const }) },
          ] : []),
          { label: 'Entries', icon: icons.entries, active: view.name === 'entries', go: () => setView({ name: 'entries', id }) },
          ...(whole ? [{ label: 'Cash and bank', icon: icons.cash, active: view.name === 'cash', go: () => setView({ name: 'cash', id }) }] : []),
          { label: 'Dues', icon: icons.dues, active: view.name === 'dues', go: () => setView({ name: 'dues', id, tab: 'receive' }) },
          { label: 'Loans', icon: icons.loans, active: view.name === 'loans', go: () => setView({ name: 'loans', id }) },
          { label: 'Office', icon: icons.office, active: view.name === 'office', go: () => setView({ name: 'office', id }) },
        ]}
      />
      <div key={stamp} className="min-w-0 flex-1">{screen}</div>

      {/* on phones the assistant lives in the top corner of every screen */}
      {canWrite && me.projects.length > 0 && !drawer && (
        <button type="button" aria-label="Open assistant" onClick={() => setDrawer(true)}
          className="fixed top-3.5 right-4 z-30 flex size-11 items-center justify-center rounded-full bg-action text-white shadow-lg lg:hidden">
          {icons.assistant}
        </button>
      )}
      {drawer && (
        <AssistantDrawer
          me={me}
          current={project}
          onClose={() => { setDrawer(false); setStamp((n) => n + 1) }}
          onFullPage={(pid) => { setDrawer(false); setView({ name: 'assistant', id: pid }) }}
          onOffice={(pid) => { setDrawer(false); setView({ name: 'office', id: pid }) }}
        />
      )}
    </div>
  )
}
