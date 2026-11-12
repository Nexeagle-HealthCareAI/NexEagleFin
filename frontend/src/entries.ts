import type { Doc } from './api'

/** Plain-language line for one entry, and whether cash went up (+), down (−) or did not move. */
export function describe(d: Doc): { label: string; sign: '+' | '−' | '' } {
  const who = d.party ?? ''
  switch (d.type) {
    case 'collection': return { label: 'Collection', sign: '+' }
    case 'investment': return { label: 'Investment', sign: '+' }
    case 'claim_settlement': return { label: `Received from ${who}`, sign: '+' }
    case 'vendor_payment': return { label: `Paid ${who}`, sign: '−' }
    case 'loan_received': return { label: `Loan from ${who}`, sign: d.payment_mode ? '+' : '' }
    case 'loan_payment': return { label: `Loan instalment to ${who}`, sign: '−' }
    case 'transfer': return { label: d.note || 'Transfer between accounts', sign: '' }
    case 'opening_balance': return { label: d.note || 'Opening balance', sign: '' }
    case 'advance_received': return { label: `Advance · ${d.reference ?? ''}`.trim(), sign: '+' }
    case 'advance_adjusted': return { label: `Advance used for bill · ${d.reference ?? ''}`.trim(), sign: '' }
    case 'advance_refund': return { label: `Advance refunded · ${d.reference ?? ''}`.trim(), sign: '−' }
    case 'claim': return { label: `Bill to ${who}`, sign: '' }
    default: {
      const name = who || 'Expense'
      if (!d.paid) return { label: `${name} · to pay`, sign: '' }
      return { label: d.status === 'needs_attention' ? `${name} · not sorted yet` : name, sign: '−' }
    }
  }
}
