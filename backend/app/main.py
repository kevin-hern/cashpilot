from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.db.database import engine, Base
from app.routers import auth, plaid, transactions, decisions, approvals, chat, audit


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (swap for Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="CashPilot API",
    version="0.1.0",
    description="AI-powered financial assistant backend",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,         prefix="/api/v1/auth",         tags=["Auth"])
app.include_router(plaid.router,        prefix="/api/v1/plaid",        tags=["Plaid"])
app.include_router(transactions.router, prefix="/api/v1/transactions",  tags=["Transactions"])
app.include_router(decisions.router,    prefix="/api/v1/decisions",    tags=["Decisions"])
app.include_router(approvals.router,    prefix="/api/v1/approvals",    tags=["Approvals"])
app.include_router(chat.router,         prefix="/api/v1/chat",         tags=["Chat"])
app.include_router(audit.router,        prefix="/api/v1/audit",        tags=["Audit"])


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": "0.1.0"}
