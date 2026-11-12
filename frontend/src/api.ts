const BASE = import.meta.env.VITE_API_URL ?? '/api'
const KEY = 'nexeaglefin.token'

function load(): string | null {
  try {
    return sessionStorage.getItem(KEY)
  } catch {
    return null
  }
}

let token: string | null = load()

export function setToken(t: string | null) {
  token = t
  try {
    if (t) sessionStorage.setItem(KEY, t)
    else sessionStorage.removeItem(KEY)
  } catch {
    // storage unavailable: the session simply lasts until the tab closes
  }
}

export const hasToken = () => token !== null

export class ApiError extends Error {
  status: number
  /** Cash-limit warnings: the save stopped so the person can look again. Resend with confirmed: true to save anyway. */
  warnings?: string[]
  constructor(status: number, message: string, warnings?: string[]) {
    super(message)
    this.status = status
    this.warnings = warnings
  }
}

function message(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  return 'Something went wrong. Please try again.'
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'No connection. Check your internet and try again.')
  }
  if (res.status === 401 && token) {
    setToken(null)
    window.dispatchEvent(new Event('nexeaglefin:logout'))
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const w = data?.detail?.code === 'confirm' ? (data.detail.warnings as string[]) : undefined
    throw new ApiError(res.status, w ? w.join(' ') : message(data?.detail), w)
  }
  return data as T
}

export type Unit = { id: string; name: string; kind: string }
export type Project = { id: string; name: string; units: Unit[] }
export type Me = { name: string; role: string; projects: Project[]; categories: { id: string; name: string }[] }

export type ProjectRow = {
  id: string
  name: string
  cash_and_bank: string
  invested: string
  income_this_month: string
  costs_this_month: string
  profit_this_month: string
  to_receive: string
  to_pay: string
}
export type Dashboard = { date: string; projects: ProjectRow[]; totals: Omit<ProjectRow, 'id' | 'name'> }

export type Home = {
  date: string
  cash_and_bank: string
  money_in_today: string
  money_out_today: string
  to_receive: string
  to_pay: string
  needs_attention: number
  loans: LoansOverview
  advances_held: string
  units_this_month: { unit_id: string; unit: string; income: string; costs: string; profit: string }[]
}

export const localToday = () => new Date().toLocaleDateString('en-CA') // YYYY-MM-DD in the user's own timezone

export type OpenItem = {
  id: string
  party: string | null
  reference: string | null
  date: string
  unit: string
  amount: string
  due: string
  age_days: number
}
export type Dues = { total: string; ageing: Record<'0-30' | '31-60' | '61-90' | '90+', string> }
export type Doc = {
  id: string
  type: 'collection' | 'expense' | 'vendor_payment' | 'claim' | 'claim_settlement' | 'investment' | 'loan_received' | 'loan_payment'
    | 'transfer' | 'opening_balance' | 'advance_received' | 'advance_adjusted' | 'advance_refund'
  status: string
  paid: boolean
  date: string
  amount: string
  party: string | null
  unit: string
  note: string | null
  category?: string | null
  payment_mode?: string | null
  reference?: string | null
  deduction?: string
}

export type Suggestion = {
  id: string
  source: 'text' | 'bank_csv'
  raw_text: string
  type: 'expense' | 'collection' | 'investment'
  date: string
  amount: string | null
  payment_mode: string | null
  paid: boolean
  party: string | null
  category_id: string | null
  unit_id: string
  confidence: number
  reason: string
  flags: string[]
  read_by: string
}

export type DocDetail = Doc & {
  recorded_by: string | null
  recorded_at: string
  month_locked: boolean
  books: { account: string; debit: string; credit: string; reversal: boolean }[]
  payments: { id: string; type: string; date: string; amount: string; deduction: string; status: string }[]
}

export type LoansOverview = {
  count: number
  outstanding: string
  monthly_instalments: string
  overdue: number
  next: { lender: string; date: string; amount: string; days: number } | null
}
export type Loan = {
  id: string
  lender: string
  loan_type: string
  amount: string
  already_running: boolean
  rate: string
  emi: string
  start_date: string
  note: string | null
  status: 'active' | 'closed' | 'cancelled'
  outstanding: string
  principal_paid: string
  interest_paid: string
  instalments_paid: number
  instalments_left: number | null
  next_due: string | null
  next_amount: string
  next_interest: string
  overdue: number
  days_to_due: number | null
}
export type LoanDetail = Loan & {
  payments: { id: string; date: string; amount: string; interest: string; principal: string }[]
  plan: { date: string; amount: string; interest: string; principal: string; balance: string }[]
}

export type MoneyAccount = { id: string; name: string; kind: 'cash' | 'bank'; is_default: boolean; balance: string; has_opening: boolean }

/** The project's cash boxes and bank accounts, or null for people who cannot see the whole project. */
export async function moneyAccounts(projectId: string): Promise<MoneyAccount[] | null> {
  try {
    return (await api<{ accounts: MoneyAccount[] }>(`/money-accounts?project_id=${projectId}`)).accounts
  } catch {
    return null
  }
}
