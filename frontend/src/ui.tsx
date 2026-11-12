import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { MoneyAccount } from './api'

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
const inr0 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

/** Indian-format rupees. Whole amounts drop the paise. */
export function rupees(value: string | number): string {
  const n = Number(value)
  return Number.isInteger(n) ? inr0.format(n) : inr.format(n)
}

/** A screen. Forms stay a narrow column; `wide` screens spread out on a desktop. */
export function Page({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className={`mx-auto flex min-h-dvh w-full max-w-xl flex-col px-5 pb-10 ${wide ? 'lg:max-w-6xl lg:px-8' : ''}`}>
      {children}
    </div>
  )
}

/** One headline number. The dark one leads; on a phone it spans the full width. */
export function StatCard({ label, value, dark = false, onClick }: {
  label: string
  value: string
  dark?: boolean
  onClick?: () => void
}) {
  const box = dark
    ? 'col-span-2 bg-ink text-white lg:col-span-1'
    : 'border border-line bg-white'
  const inner = (
    <>
      <span className={`block text-[13px] ${dark ? 'text-slate-300' : 'text-muted'}`}>{label}</span>
      <span className={`block font-semibold tracking-tight ${dark ? 'text-[32px] lg:text-[22px]' : 'text-[19px] lg:text-[22px]'}`}>{value}</span>
    </>
  )
  const cls = `rounded-2xl p-4 text-left ${box}`
  return onClick
    ? <button type="button" onClick={onClick} className={cls}>{inner}</button>
    : <div className={cls}>{inner}</div>
}

export function StatRow({ children, label }: { children: ReactNode; label: string }) {
  return <section aria-label={label} className="grid grid-cols-2 gap-3 lg:grid-cols-5">{children}</section>
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-line bg-white p-4 ${className}`}>{children}</div>
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { tone?: 'action' | 'ink' | 'plain' | 'link' }

export function Button({ tone = 'action', className = '', ...rest }: BtnProps) {
  const tones = {
    action: 'bg-action text-white font-semibold',
    ink: 'bg-ink text-white font-semibold',
    plain: 'bg-white text-ink border border-slate-300 font-medium',
    link: 'text-action font-medium',
  }
  return (
    <button
      type="button"
      {...rest}
      className={`min-h-12 rounded-xl px-4 text-[15px] disabled:opacity-50 ${tones[tone]} ${className}`}
    />
  )
}

export function Stat({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'bad' }) {
  const color = tone === 'bad' ? 'text-red-800' : tone === 'good' ? 'text-green-800' : ''
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[13px] text-muted">{label}</span>
      <span className={`text-[17px] font-semibold ${color}`}>{value}</span>
    </div>
  )
}

export function ErrorNote({ children }: { children: ReactNode }) {
  if (!children) return null
  return (
    <p role="alert" className="rounded-xl bg-red-100 px-3 py-2 text-sm font-medium text-red-900">
      {children}
    </p>
  )
}

export function TopBar({ title, sub, onBack, right, backOnPhoneOnly = false }: {
  title: string
  sub?: string
  onBack?: () => void
  right?: ReactNode
  /** On a desktop the sidebar already offers the way back. */
  backOnPhoneOnly?: boolean
}) {
  return (
    <header className="flex items-center gap-1 py-4 max-lg:pr-12 lg:py-6">
      {onBack && (
        <button type="button" aria-label="Back" onClick={onBack} className={`-ml-3 flex size-11 items-center justify-center ${backOnPhoneOnly ? 'lg:hidden' : ''}`}>
          <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 6l-6 6 6 6" />
          </svg>
        </button>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        {sub && <span className="truncate text-[13px] text-muted">{sub}</span>}
        <h1 className="truncate text-[22px] font-semibold lg:text-[28px]">{title}</h1>
      </div>
      {right}
    </header>
  )
}

export function Choice<T extends string>({ label, options, value, onChange }: {
  label: string
  options: { value: T; label: string }[]
  value: T | null
  onChange: (v: T) => void
}) {
  return (
    <fieldset className="m-0 border-0 p-0">
      <legend className="mb-2 p-0 text-[13px] font-medium text-muted">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => {
          const on = o.value === value
          return (
            <button
              key={o.value}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(o.value)}
              className={`min-h-11 rounded-full px-4 text-sm ${on ? 'border-2 border-action bg-blue-100 font-semibold text-blue-900' : 'border border-slate-300 bg-white font-medium'}`}
            >
              {o.label}
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}

export const fieldClass = 'h-12 w-full rounded-xl border border-slate-300 bg-white px-3.5 text-base font-medium'
export const labelClass = 'mb-1.5 block text-[13px] font-medium text-muted'

/** Returns a clean "1234.50" string, or null when the typed amount is not valid money. */
export function cleanAmount(typed: string, allowZero = false): string | null {
  const clean = typed.replace(/[,₹\s]/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  if (!allowZero && Number(clean) <= 0) return null
  return clean
}

export const MODES = [
  { value: 'cash', label: 'Cash' },
  { value: 'upi', label: 'UPI' },
  { value: 'card', label: 'Card' },
  { value: 'bank', label: 'Bank transfer' },
] as const
export type Mode = (typeof MODES)[number]['value']

/** "2026-11-10" -> "10 Nov 2026" */
export function niceDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Shown when the server stops a save with a warning. The person decides; nothing is saved until they do. */
export function WarningBox({ warnings, busy, onConfirm, onBack }: {
  warnings: string[]
  busy?: boolean
  onConfirm: () => void
  onBack: () => void
}) {
  if (!warnings.length) return null
  return (
    <div role="alert" className="flex flex-col gap-2.5 rounded-xl border border-amber-300 bg-amber-50 p-3.5">
      <p className="m-0 text-sm font-semibold text-amber-900">Check before saving</p>
      {warnings.map((w) => <p key={w} className="m-0 text-sm text-amber-900">{w}</p>)}
      <div className="grid grid-cols-2 gap-2">
        <Button tone="plain" onClick={onBack}>Go back</Button>
        <Button tone="ink" disabled={busy} onClick={onConfirm}>Save anyway</Button>
      </div>
    </div>
  )
}

/** Run a save; if the server answers with warnings, keep them so a WarningBox can ask. */
export async function trySave(send: () => Promise<unknown>, onWarn: (w: string[]) => void, onError: (m: string) => void): Promise<boolean> {
  try {
    await send()
    return true
  } catch (err) {
    const e = err as { warnings?: string[]; message: string }
    if (e.warnings) onWarn(e.warnings)
    else onError(e.message)
    return false
  }
}

/** Pick which cash box or bank account the money moved through. Only shown when there is a real choice. */
export function AccountPicker({ accounts, mode, value, onChange, label }: {
  accounts: MoneyAccount[] | null
  mode: string | null
  value: string
  onChange: (id: string) => void
  label: string
}) {
  if (!accounts || !mode) return null
  const kind = mode === 'cash' ? 'cash' : 'bank'
  const fitting = accounts.filter((a) => a.kind === kind)
  if (fitting.length < 2) return null
  const fallback = fitting.find((a) => a.is_default) ?? fitting[0]
  return (
    <div>
      <label htmlFor="money-account" className={labelClass}>{label}</label>
      <select id="money-account" className={fieldClass} value={fitting.some((a) => a.id === value) ? value : fallback.id}
        onChange={(e) => onChange(e.target.value)}>
        {fitting.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>
    </div>
  )
}

/** The account id to send: the one picked if it fits the payment mode, otherwise none (the project default). */
export function chosenAccount(accounts: MoneyAccount[] | null, mode: string | null, picked: string): string | null {
  if (!accounts || !mode) return null
  const kind = mode === 'cash' ? 'cash' : 'bank'
  return accounts.some((a) => a.id === picked && a.kind === kind) ? picked : null
}
