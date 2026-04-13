"""
auth.py — JWT Authentication for ResearchLens AI
─────────────────────────────────────────────────
In-memory user store (no DB needed for demo).
Passwords hashed with bcrypt via passlib.
JWTs signed with HS256 via python-jose.

Endpoints:
  POST /auth/register  → create account, return token
  POST /auth/login     → authenticate, return token
  GET  /auth/me        → return current user info (Bearer token)
"""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET", "researchlens-jwt-secret-k9f2b3c4d5e6f7a8b9c0d1e")
ALGORITHM  = "HS256"
TOKEN_EXPIRE_DAYS = 7

# ── Password hashing ──────────────────────────────────────────────────────────
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── In-memory user store  { email → user_dict } ──────────────────────────────
_users: Dict[str, Dict[str, Any]] = {}


# ── Pydantic schemas ──────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    papers_analyzed: int
    chats_sent: int
    reviews_done: int
    joined: str   # ISO date string


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Helpers ───────────────────────────────────────────────────────────────────
def _hash(pw: str) -> str:
    return pwd_ctx.hash(pw)


def _verify(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def _make_token(payload: dict) -> str:
    data = payload.copy()
    data["exp"] = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def _user_out(u: dict) -> UserOut:
    return UserOut(
        id=u["id"],
        name=u["name"],
        email=u["email"],
        papers_analyzed=u.get("papers_analyzed", 0),
        chats_sent=u.get("chats_sent", 0),
        reviews_done=u.get("reviews_done", 0),
        joined=u.get("joined", ""),
    )


def increment_stat(token: str, field: str) -> None:
    """Increment a user stat (papers_analyzed, chats_sent, reviews_done)."""
    payload = _decode_token(token)
    if not payload:
        return
    user = _users.get(payload.get("email", ""))
    if user and field in ("papers_analyzed", "chats_sent", "reviews_done"):
        user[field] = user.get(field, 0) + 1


# ── Router ────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    name = req.name.strip()
    email = req.email.strip().lower()

    if len(name) < 2:
        raise HTTPException(400, "Name must be at least 2 characters.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Invalid email address.")
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    if email in _users:
        raise HTTPException(409, "An account with this email already exists.")

    user: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "email": email,
        "hashed_password": _hash(req.password),
        "papers_analyzed": 0,
        "chats_sent": 0,
        "reviews_done": 0,
        "joined": datetime.now(timezone.utc).strftime("%B %Y"),
        "created_at": time.time(),
    }
    _users[email] = user

    token = _make_token({"sub": user["id"], "email": email})
    return TokenResponse(access_token=token, user=_user_out(user))


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    email = req.email.strip().lower()
    user = _users.get(email)
    if not user or not _verify(req.password, user["hashed_password"]):
        raise HTTPException(401, "Invalid email or password.")

    token = _make_token({"sub": user["id"], "email": email})
    return TokenResponse(access_token=token, user=_user_out(user))


@router.get("/me", response_model=UserOut)
async def me(creds: HTTPAuthorizationCredentials = Depends(_bearer)):
    if not creds:
        raise HTTPException(401, "Authentication required.")
    payload = _decode_token(creds.credentials)
    if not payload:
        raise HTTPException(401, "Token invalid or expired.")
    user = _users.get(payload.get("email", ""))
    if not user:
        raise HTTPException(404, "User account not found.")
    return _user_out(user)
