# CashPilot

AI-powered financial assistant. Connects to bank accounts via Plaid, detects income and spending events, and recommends financial actions for user approval before any execution.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11 + FastAPI + SQLAlchemy (async) |
| Frontend | Next.js 16 + React 19 + Tailwind |
| Database | Postgres 16 |
| Cache / Queue | Redis 7 + Celery |
| AI | Anthropic Claude API |
| Bank Data | Plaid (sandbox) |

---

## Quick Start

### 1. Clone & configure

```bash
git clone <repo>
cd cashpilot
cp .env.example backend/.env
# Edit backend/.env with your Plaid + Anthropic keys
```

Generate an encryption key:
```bash
python -c "import os,binascii; print(binascii.hexlify(os.urandom(32)).decode())"
```

### 2. Start the dev stack

```bash
docker compose up -d
```

This starts:
- Postgres on `localhost:5432` (schema auto-applied from `db/schema.sql`)
- Redis on `localhost:6379`
- FastAPI backend on `http://localhost:8000`
- Next.js frontend on `http://localhost:3000`

### 3. Backend (local, without Docker)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # then fill in keys
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

### 4. Frontend (local, without Docker)

```bash
cd frontend
npm install
npm run dev
```

---

## Project Structure

```
cashpilot/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + router mounting
│   │   ├── core/config.py       # Settings (pydantic-settings)
│   │   ├── db/database.py       # Async SQLAlchemy engine
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── routers/             # API route handlers (thin layer)
│   │   └── services/            # Business logic
│   │       ├── user_service.py
│   │       ├── plaid_service.py
│   │       ├── ingestion_service.py
│   │       ├── rules_engine.py      # Deterministic paycheck/event detection
│   │       ├── decision_engine.py   # Orchestrates rules + LLM → intents
│   │       ├── llm_service.py       # Claude API wrapper + chat streaming
│   │       ├── approval_service.py  # Intent approval lifecycle
│   │       ├── execution_service.py # Guarded execution with idempotency
│   │       └── audit_service.py     # Append-only audit log writer
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx           # Landing
│       │   ├── login/             # Auth
│       │   ├── dashboard/         # Balances + account linking
│       │   ├── approvals/         # Pending intent review
│       │   └── chat/              # AI chat interface
│       ├── components/
│       │   ├── PlaidLink/         # Plaid Link SDK wrapper
│       │   └── ApprovalCard/      # Intent approve/reject UI
│       └── lib/api-client.ts      # Typed fetch wrapper
├── db/schema.sql                  # Full Postgres schema
├── docker-compose.yml
└── .env.example
```

---

## API Reference

Full interactive docs at `http://localhost:8000/docs` when backend is running.

```
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/plaid/link-token       start Plaid Link
POST /api/v1/plaid/exchange         complete bank connection
GET  /api/v1/transactions/state     financial summary
GET  /api/v1/approvals              pending AI recommendations
POST /api/v1/approvals/{id}/approve
POST /api/v1/approvals/{id}/reject
POST /api/v1/chat/sessions/{id}/messages   SSE stream
```

---

## Safety Model

No money moves without explicit user approval:

1. Rules engine detects financial event (e.g. paycheck)
2. Decision engine (rules + Claude) generates a structured **Intent**
3. Intent sits in `pending_approval` — user sees it in the Approvals UI
4. User approves with a client-generated idempotency key
5. Execution service re-validates balance before calling Plaid
6. Every step writes an immutable entry to `audit_log`

---

## Environment Variables

See `.env.example` for the full list. Minimum required for MVP:

| Variable | Source |
|---|---|
| `PLAID_CLIENT_ID` | https://dashboard.plaid.com |
| `PLAID_SECRET` | Plaid dashboard → sandbox secret |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `ENCRYPTION_KEY` | `python -c "import os,binascii; print(binascii.hexlify(os.urandom(32)).decode())"` |
| `SECRET_KEY` | Any random 32+ char string |
