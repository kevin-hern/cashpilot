from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
import bcrypt
import jwt
import uuid

from app.core.config import settings
from app.models.user_model import User
from app.schemas.user_schema import UserRegister, UserLogin, TokenResponse


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, body: UserRegister) -> User:
        existing = await self.db.execute(select(User).where(User.email == body.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        hashed = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
        user = User(email=body.email, hashed_password=hashed, full_name=body.full_name)
        self.db.add(user)
        await self.db.flush()
        return user

    async def login(self, body: UserLogin) -> TokenResponse:
        result = await self.db.execute(select(User).where(User.email == body.email, User.is_active == True))
        user = result.scalar_one_or_none()
        if not user or not bcrypt.checkpw(body.password.encode(), user.hashed_password.encode()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        return TokenResponse(
            access_token=self._make_access_token(user),
            refresh_token=self._make_refresh_token(user),
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenResponse:
        try:
            payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=["HS256"])
            if payload.get("type") != "refresh":
                raise ValueError("Not a refresh token")
            user_id = payload["sub"]
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        result = await self.db.execute(select(User).where(User.id == user_id, User.is_active == True))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        return TokenResponse(
            access_token=self._make_access_token(user),
            refresh_token=self._make_refresh_token(user),
        )

    async def revoke_refresh_token(self, refresh_token: str) -> None:
        # TODO: add to Redis revocation list
        pass

    def _make_access_token(self, user: User) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        return jwt.encode({"sub": str(user.id), "exp": expire, "type": "access"}, settings.SECRET_KEY, algorithm="HS256")

    def _make_refresh_token(self, user: User) -> str:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        return jwt.encode({"sub": str(user.id), "exp": expire, "type": "refresh"}, settings.SECRET_KEY, algorithm="HS256")
