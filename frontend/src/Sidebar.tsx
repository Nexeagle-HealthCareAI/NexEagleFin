import type { ReactNode } from 'react'
import type { Me, Project } from './api'

type Item = { label: string; icon: ReactNode; active: boolean; go: () => void }

const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' } as const
const Icon = ({ children }: { children: ReactNode }) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" {...stroke}>{children}</svg>
)
export const icons = {
  grid: <Icon><rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" /></Icon>,
  home: <Icon><path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z" /></Icon>,
  in: <Icon><path d="M12 4v14M6 12l6 6 6-6" /></Icon>,
  out: <Icon><path d="M12 20V6M6 12l6-6 6 6" /></Icon>,
  assistant: <Icon><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" /><path d="M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8z" /></Icon>,
  office: <Icon><path d="M4 20V6l8-3v17M12 9l8 2v9M3 20h18M7.5 9v.01M7.5 12.5v.01M7.5 16v.01M16 14v.01M16 17v.01" /></Icon>,
  cash: <Icon><rect x="3" y="6" width="18" height="12" rx="2" /><circle cx="12" cy="12" r="2.5" /><path d="M7 9.5v.01M17 14.5v.01" /></Icon>,
  loans: <Icon><path d="M4 10l8-5 8 5M6 10v8M10 10v8M14 10v8M18 10v8M4 20h16" /></Icon>,
  entries: <Icon><path d="M8 6h12M8 12h12M8 18h12M4 6v.01M4 12v.01M4 18v.01" /></Icon>,
  dues: <Icon><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></Icon>,
}

function NavButton({ item, collapsed }: { item: Item; collapsed: boolean }) {
  return (
    <button type="button" aria-current={item.active ? 'page' : undefined} onClick={item.go}
      aria-label={collapsed ? item.label : undefined} title={collapsed ? item.label : undefined}
      className={`flex min-h-11 w-full items-center gap-2.5 rounded-[10px] text-left text-[15px] ${collapsed ? 'justify-center px-0' : 'px-3'} ${item.active ? 'bg-slate-800 font-semibold text-white' : 'font-medium text-slate-300 hover:bg-slate-800/60'}`}>
      {item.icon}{!collapsed && item.label}
    </button>
  )
}

/** Desktop navigation. Hidden on phones, where each screen has its own back button. Folds down to icons. */
export default function Sidebar({ me, project, top, items, collapsed, onToggle, onAssistant, onLogout }: {
  me: Me
  project: Project | null
  top: Item
  items: Item[]
  collapsed: boolean
  onToggle: () => void
  onAssistant: () => void
  onLogout: () => void
}) {
  return (
    <aside className={`sticky top-0 hidden h-dvh shrink-0 flex-col gap-1 overflow-y-auto bg-ink py-6 transition-[width] duration-150 motion-reduce:transition-none lg:flex ${collapsed ? 'w-[4.5rem] px-3' : 'w-60 px-4'}`}>
      <div className={`flex items-center pb-3 ${collapsed ? 'justify-center' : 'justify-between pl-3'}`}>
        {!collapsed && <span className="text-xl font-semibold text-white">NexEagleFin</span>}
        <button type="button" onClick={onToggle} aria-expanded={!collapsed} aria-label={collapsed ? 'Expand menu' : 'Collapse menu'}
          title={collapsed ? 'Expand menu' : 'Collapse menu'}
          className="flex size-11 items-center justify-center rounded-[10px] text-slate-300 hover:bg-slate-800/60">
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" {...stroke}>
            <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><path d="M9 4.5v15" />
            <path d={collapsed ? 'M13.5 9.5l2.5 2.5-2.5 2.5' : 'M16 9.5L13.5 12l2.5 2.5'} />
          </svg>
        </button>
      </div>

      <button type="button" onClick={onAssistant} aria-label={collapsed ? 'Assistant' : undefined} title={collapsed ? 'Assistant' : undefined}
        className={`mb-3 flex min-h-11 w-full items-center gap-2.5 rounded-[10px] bg-action text-[15px] font-semibold text-white ${collapsed ? 'justify-center px-0' : 'px-3'}`}>
        {icons.assistant}{!collapsed && 'Assistant'}
      </button>

      <nav aria-label="Main" className="flex flex-col gap-1">
        <NavButton item={top} collapsed={collapsed} />
        {project && (
          <>
            {collapsed
              ? <span className="my-2 border-t border-slate-700" />
              : <span className="mt-4 truncate px-3 pb-1 text-xs font-semibold text-slate-400">{project.name}</span>}
            {items.map((i) => <NavButton key={i.label} item={i} collapsed={collapsed} />)}
          </>
        )}
      </nav>
      <div className="mt-auto flex flex-col gap-1 border-t border-slate-700 pt-4">
        {!collapsed && <span className="truncate px-3 text-[13px] text-slate-400">{me.name} · {me.role}</span>}
        <button type="button" onClick={onLogout} aria-label={collapsed ? 'Log out' : undefined} title={collapsed ? 'Log out' : undefined}
          className={`flex min-h-11 items-center gap-2.5 rounded-[10px] text-left text-[15px] font-medium text-slate-300 hover:bg-slate-800/60 ${collapsed ? 'justify-center px-0' : 'px-3'}`}>
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" {...stroke}><path d="M10 5H6a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h4M15 8l4 4-4 4M19 12H9" /></svg>
          {!collapsed && 'Log out'}
        </button>
      </div>
    </aside>
  )
}
