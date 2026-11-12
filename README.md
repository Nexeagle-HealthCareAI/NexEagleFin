# NexEagleFin

Finance management for healthcare projects: hospitals, diagnostic centres, path labs and pharmacies.

## What is built so far (backend)

- **Projects**: create any number (for example "Glisan Hospital"), each with its own units. One dashboard across all.
- **Money in**: daily collections by unit and payment mode.
- **Money out**: expenses, paid or to-pay, with "save now, sort later".
- **Investments**: owner money put into a project, kept separate from income.
- **Dues**: insurance claims (billed, received, deducted kept apart), vendor bills with part payments, ageing report.
- **Reports**: home summary, profit by unit, all-projects dashboard.
- **Controls**: PIN login with lockout, roles, per-unit access, month lock, cancel-by-reversal, audit log.

Underneath is a double-entry ledger. All bookkeeping rules are in `backend/app/posting.py`.

## Run locally (no Docker, SQLite)

    cd backend
    pip install -r requirements-dev.txt
    python -m app.seed "My Group" 9876543210 4321     # creates the account and owner login
    uvicorn app.main:app --reload
    # API docs: http://localhost:8000/docs

## Run tests

    cd backend && python -m pytest -q

## Run with PostgreSQL (Docker)

    cp .env.example .env      # set real values
    docker compose up --build
    docker compose exec api python -m app.seed "My Group" 9876543210 4321

## Web app (frontend)

React + TypeScript + Vite + Tailwind. One codebase, two layouts: a single column on phones and,
from 1024px wide, a sidebar with multi-column pages.
Screens so far: login, all-projects dashboard, new project, project home with latest entries,
dues (to receive and to pay), the needs-a-category queue, and forms to record an expense,
a collection and an investment.

    cd frontend
    npm install
    npm run dev          # http://localhost:5173, talks to the API on localhost:8000

Browser test of the whole flow (needs the API and `npm run preview` running, plus Playwright):

    cd e2e && mkdir -p shots
    python browser_flow.py      # phone size, on a fresh database
    python desktop_shots.py     # desktop size, run after the phone flow

## Feature roadmap

Features first, built one at a time; the automated finance assistants come after the features are complete.

| # | Feature | Status |
| --- | --- | --- |
| 1 | Projects, money in, money out, investment, dues, needs-a-category, dashboards | Built |
| 2 | Entries (day book): filters, what is behind each entry, cancel with a reason, close and reopen a month | Built |
| 3 | Cash-limit warnings: ₹2 lakh cash from one patient, ₹10,000 cash to one vendor a day, loans in cash | Built |
| 4 | Cash and bank accounts: several per project, opening balances, moving money between them | Built |
| 5 | Patient advances: held as owed, used for the final bill, refunded | Built |
| 6 | Loans: instalments split into interest and principal, due and overdue tracking | Built |
| 7 | Doctor payouts with TDS (10% professional fees, yearly threshold), TDS on rent and contracts | Next |
| 8 | Tax treatment on every entry (exempt, taxable at a rate, credit blocked); GST registers; Rule 42 credit reversal | |
| 9 | Edit log with before and after values, a log screen, daily backups kept in India | |
| 10 | Pharmacy stock value at month end, so pharmacy profit is right | |
| 11 | Trial balance, profit and loss, balance sheet, cash flow; April to March year; PDF and Excel | |
| 12 | Bank reconciliation | |
| 13 | Vendors and payers list (no duplicates), bill photos, recurring costs (rent, salaries, AMC) | |
| 14 | Scheme claims (Ayushman Bharat) with their own expected delay; unbilled income for admitted patients | |
| 15 | Fixed assets and depreciation, salaries, budgets and alerts | |
| 16 | Tally export, CA pack, staff users and roles | |

Browser tests (each on a fresh database): `python e2e/entries_flow.py`, `python e2e/loans_flow.py`.

### Cash limits (confirm the details with your CA)

Checked in one place (`backend/app/checks.py`) before any entry is saved, from the screens,
from suggestion approval and from chat cards:

- Cash of ₹2,00,000 or more from one patient: added up across visits by patient or bill number,
  including advances. Without a number, a single large amount is checked and the number is asked for.
- Cash expenses to one vendor above ₹10,000 in a day: added up across the day.
- Loans taken or repaid in cash of ₹20,000 or more.

The warning never blocks recording what happened. The person sees it, then goes back or saves anyway
(`confirmed: true`). A chat card shows the warning before its Yes.

### Cash and bank accounts, advances

- Every project starts with "Cash in hand" and "Main bank account"; more can be added, each with its
  own ledger account (codes 1000-n, 1010-n). Entries go to the chosen account, or the default for the
  payment mode. A cash box cannot take a UPI payment.
- Opening balances are set against "Opening balances" (3900): counted in cash and bank, never as income
  or as today's money in. Moving money between accounts is not money in or out either.
- Patient advances are owed to the patient (2200) until used for the final bill (then unit income)
  or refunded.

### How loans are kept

- A new loan puts money in the bank and is owed to the lender; it is never income.
- A loan that was already being repaid is entered with what is still owed today. No money moves;
  it is set against an "Opening balances" account.
- Each instalment is split: interest (a cost of the project) and the rest, which reduces the loan.
  Interest is worked out on the reducing balance from the yearly rate, and can be overridden with
  the figure on the lender's statement.
- What is still owed is always worked out from the payments, never typed in.
- `GET /api/loans?project_id=` returns each loan's next due date, amount, and overdue count.
  This is what an assistant will read later to remind and to match bank debits to instalments.
- Not handled yet: processing fees and insurance added to a loan, moratorium periods, floating
  rates changing over time, prepayment charges, overdraft limits that go up and down.

## Step-by-step review (12 Nov 2026)

Each problem below was first proved with a failing test (`backend/tests/test_review.py`), then fixed.

| Step | Problem | Fix |
| --- | --- | --- |
| Log in | A number typed as "+91 98765 43210" or "098765..." was refused | Numbers are stored and compared as plain digits |
| Record money in, money out, bills, investment | The server accepted dates in the future | Refused with a plain message |
| Dues | A payment could be dated before the bill it pays | Refused |
| Dues, loans | Two payments saved at the same instant could both pass the "still due" check | The bill or loan row is locked while a payment is saved (PostgreSQL) |
| Month close | Closing a month in one project closed it for every project | Months are closed per project |
| Loans | Staff limited to one unit could see the project's loans | Loans are visible only to people who can see the whole project |
| Home | Read-only users (auditor) were shown record buttons that then failed | Buttons hidden for read-only roles |

Still open, not fixed by this review:

- Never run on PostgreSQL or Docker. Every test uses SQLite. This is the largest unknown.
- One cash box and one bank account for everything, and no opening balances (roadmap 3).
- An entry cannot be edited, only cancelled and entered again.
- Staff users cannot be added from the app, and a PIN cannot be changed.
- Vendors and payers are created from the typed name, so a spelling difference makes a second vendor.
- A repeated save is blocked on the screen but not on the server.
- Insurance bills count as income when billed; counter collections count when received. A CA should
  confirm which basis the books follow.
- Loan interest is one twelfth of the yearly rate each month, not day-counted.
- No GST, TDS, backups or deployment yet.

## Navigation

- The side menu folds down to icons (button at its top) and remembers the choice on that device.
- The assistant sits at the top of the menu, and in the top corner on phones. It opens in a drawer
  over the current screen: type what happened, get suggested entries, approve them there.
  It records entries only; it says so when asked a question. Bank statements and the full list of
  suggestions are on the page the drawer links to.

Browser test: `python e2e/drawer_flow.py` (fresh database).

## AI agents (paused until the features above are complete)

Built one at a time. Three rules hold for all of them: agents only suggest and never write to the
ledger; code, not the model, works out every amount, date and direction; a person approves.

### Chat assistant (all four slices built)

Goal: do everything from the assistant drawer without opening the screens.
Code: `backend/app/agents/chat.py` (LangGraph: understand -> look up -> answer),
`backend/app/agents_api.py` (read tools, `/agents/chat`), `backend/app/agents_actions.py` (changes).

What it can do from chat:

| Ask | Do (always shown on a confirm card first) |
| --- | --- |
| Cash and bank, today's money in and out | Record entries from your own words (approve each) |
| Profit by unit for any month | Money received against an insurance or company bill, with the insurer's cut |
| Who owes you, bills to pay | Pay a vendor's unpaid bill, in full or in part |
| Loans, next instalment, overdue | Pay a loan instalment (interest split worked out) |
| Recent entries, by month | Add a new or already-running loan |
| Follow-ups: "and last month?" | Cancel an entry, sort an expense, close or reopen a month |

How changes are kept safe:

- A change is only prepared in chat: the exact details are stored as a `ChatAction` and shown on a card.
  Nothing happens until the same person taps Yes (`POST /api/agents/actions/{id}/confirm`).
- On Yes it runs the same function the screen uses, so every rule (closed months, amounts still due,
  roles) applies. If the books refuse, the card says why and nothing changes.
- Cancelling an entry and closing a month show a red card.
- When something is missing or there are several matches, it asks one question and offers choices
  ("Which bill is this money for?"). The answer is understood by plain code, with or without Groq.
- Every figure comes from a tool. If the model's reply contains a figure of 100 or more that no tool
  returned, or converts to lakh or crore, its text is discarded and the code-written reply is sent.
- Without Groq, keyword rules understand requests phrased close to the examples. Groq is needed for
  free wording and Hindi or Hinglish; that path is tested only with a stand-in model.

Browser test: `python e2e/chat_actions_flow.py` (fresh database).

### 1. Bookkeeper (built)

Reads typed or pasted notes, or a bank statement saved as CSV, and suggests entries.
Code is in `backend/app/agents/`; the flow is a LangGraph graph: parse -> classify -> check.

- `parse.py`: plain code. Amounts, dates, money in or out, payment mode, bank CSV columns.
- `extractors.py`: who was paid, category, unit. Uses Groq when configured, keyword rules otherwise,
  and falls back to the rules if Groq fails.
- `bookkeeper.py`: the graph, plus checks: drops categories and units not on the allowed lists,
  flags likely duplicates, caps confidence when something is unclear.

To use Groq, set these before starting the API (pick a current model name from Groq's model list):

    export GROQ_API_KEY=...
    export GROQ_MODEL=...

What is sent to Groq: the line of text with any number of 6 or more digits and any email masked,
plus your category and unit names. Money received by UPI, cash or card is never sent, because
those lines carry patient names.

Browser test: `python e2e/assistant_flow.py` (fresh database, API and preview running).

### Assistant office (3D)

A screen that shows the assistants as figures on an office floor: desks, a glass meeting room,
and a lounge with a pool table, coffee counter and sofa. Code: `frontend/src/office/scene.ts`
(three.js, loaded only when the screen is opened) and `frontend/src/screens/Office.tsx`.

- The floor loops through work, a meeting, work, a break. Who joins is picked afresh each time,
  people leave a few seconds apart and walk at their own pace.
- The Bookkeeper follows real data: with suggestions waiting it stays at (or returns to) its desk;
  when the queue is cleared it stretches and is free to join the others.
- The other six are marked "Joining soon" and are shown around the office until they are built.
- Pause button, turn buttons and drag to look around. Starts paused when the device asks for
  reduced motion. A text list under the picture says what each assistant is doing.

Capture script: `python e2e/office_shots.py` (needs WebGL; software rendering works).

### Next agents, in order

2. Reconciler (match bank lines to existing entries)  3. Claims  4. Tax (GST and TDS workings)
5. Month close  6. Auditor  7. Ask (questions in plain language)

## Not built yet

bank statement matching, bill photo upload, day close, Tally export, GST and TDS, OTP login,
bill photo reading, Redis job queue and saved agent runs in PostgreSQL, adding staff users from the app, database migrations (Alembic), PostgreSQL row-level security,
Hindi, offline capture.
