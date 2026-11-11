"""Request dependencies: who is calling, which household, and may they write."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, Household, HouseholdAccess, Plan, User, UserSession, now
from ..security.core import rate_limiter, token_hash

SESSION_COOKIE = "tg_session"
CSRF_COOKIE = "tg_csrf"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit(request: Request, bucket: str, per_minute: int) -> None:
    if not rate_limiter.allow(f"{bucket}:{client_ip(request)}", per_minute):
        raise HTTPException(429, "Too many requests. Please wait a minute and try again.")


def audit(db: Session, request: Request | None, action: str, *, user_id: str | None = None,
          household_id: str | None = None, entity: str | None = None, entity_id: str | None = None,
          detail: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, household_id=household_id, action=action, entity=entity,
                    entity_id=entity_id, detail=detail, ip=client_ip(request) if request else None))


def _session(request: Request, db: Session, *, require_mfa: bool) -> tuple[UserSession, User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Please sign in.")
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    t = now()
    if sess is None or sess.revoked_at is not None:
        raise HTTPException(401, "Please sign in.")
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=t.tzinfo)
    if expires < t:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    user = db.get(User, sess.user_id)
    if user is None:
        raise HTTPException(401, "Please sign in.")
    if request.method in UNSAFE and request.headers.get("x-csrf-token") != sess.csrf_token:
        raise HTTPException(403, "Security check failed. Please reload the page and try again.")
    if require_mfa and user.mfa_enabled and not sess.mfa_verified:
        raise HTTPException(401, "Two-step verification is required.", headers={"X-MFA-Required": "1"})
    sess.last_seen_at = t
    return sess, user


def pending_session(request: Request, db: Session = Depends(get_db)) -> tuple[UserSession, User]:
    """A signed-in session that may still be waiting for its MFA code."""
    return _session(request, db, require_mfa=False)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    limit(request, "api", get_settings().rate_limit_per_minute)
    return _session(request, db, require_mfa=True)[1]


@dataclass
class Ctx:
    db: Session
    request: Request
    user: User
    household: Household
    role: str  # owner | editor | viewer

    @property
    def hid(self) -> str:
        return self.household.id

    def log(self, action: str, entity: str | None = None, entity_id: str | None = None,
            detail: dict | None = None) -> None:
        audit(self.db, self.request, action, user_id=self.user.id, household_id=self.hid, entity=entity,
              entity_id=entity_id, detail=detail)

    def plan(self) -> Plan:
        plan = self.db.scalar(select(Plan).where(Plan.household_id == self.hid, Plan.is_baseline.is_(True)))
        if plan is None:
            raise HTTPException(404, "No plan found for this household.")
        return plan

    def owned(self, model, entity_id: str):
        """Fetch a row by id, but only if it belongs to this household."""
        row = self.db.get(model, entity_id)
        if row is None or getattr(row, "household_id", None) != self.hid:
            raise HTTPException(404, "Not found.")
        return row


def get_ctx(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ctx:
    wanted = request.headers.get("x-household-id")
    q = select(HouseholdAccess).where(HouseholdAccess.user_id == user.id)
    if wanted:
        q = q.where(HouseholdAccess.household_id == wanted)
    access = db.scalars(q.order_by(HouseholdAccess.created_at)).first()
    if access is None:
        raise HTTPException(404, "No household found for this account.")
    household = db.get(Household, access.household_id)
    if household is None:
        raise HTTPException(404, "No household found for this account.")
    return Ctx(db=db, request=request, user=user, household=household, role=access.role)


def get_writer(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    if ctx.role == "viewer":
        raise HTTPException(403, "You have view-only access to this household.")
    return ctx


def session_expiry():
    return now() + timedelta(hours=get_settings().session_hours)
