from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import HouseholdAccess, User, UserSession, now
from ..security import core as sec
from ..services.setup import create_household
from .deps import CSRF_COOKIE, SESSION_COOKIE, audit, client_ip, current_user, limit, pending_session, session_expiry

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class DisableMfaIn(BaseModel):
    password: str
    code: str


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=200)


class PrefsIn(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=120)
    simple_mode: bool | None = None


def _start_session(db: Session, request: Request, response: Response, user: User, mfa_verified: bool) -> None:
    s = get_settings()
    token = sec.new_token()
    csrf = sec.new_token()
    db.add(UserSession(user_id=user.id, token_hash=sec.token_hash(token), csrf_token=csrf,
                       mfa_verified=mfa_verified, expires_at=session_expiry(), ip=client_ip(request),
                       user_agent=(request.headers.get("user-agent") or "")[:300]))
    max_age = s.session_hours * 3600
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=s.secure_cookies,
                        samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=s.secure_cookies,
                        samesite="lax", path="/")


def user_out(user: User) -> dict:
    s = get_settings()
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role,
            "mfa_enabled": user.mfa_enabled, "simple_mode": user.simple_mode,
            "ai_consent": user.ai_consent_at is not None, "app_name": s.app_name, "environment": s.environment}


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    limit(request, "auth", get_settings().rate_limit_auth_per_minute)
    problem = sec.password_problem(body.password)
    if problem:
        raise HTTPException(422, problem)
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists. Try signing in instead.")
    user = User(email=email, display_name=body.display_name.strip(), password_hash=sec.hash_password(body.password))
    db.add(user)
    db.flush()
    household = create_household(db, user)
    audit(db, request, "auth.register", user_id=user.id, household_id=household.id)
    _start_session(db, request, response, user, mfa_verified=True)
    return user_out(user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    limit(request, "auth", s.rate_limit_auth_per_minute)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    t = now()
    generic = HTTPException(401, "The email or password is not right.")
    if user is None:
        sec.verify_password(sec.hash_password("timing-equaliser"), body.password)
        raise generic
    locked = user.locked_until
    if locked is not None and (locked if locked.tzinfo else locked.replace(tzinfo=t.tzinfo)) > t:
        raise HTTPException(423, "Too many wrong attempts. Please try again in a few minutes.")
    if not sec.verify_password(user.password_hash, body.password):
        user.failed_logins += 1
        if user.failed_logins >= s.max_failed_logins:
            user.locked_until = t + timedelta(minutes=s.lockout_minutes)
            user.failed_logins = 0
        audit(db, request, "auth.login_failed", user_id=user.id)
        db.commit()
        raise generic
    user.failed_logins = 0
    user.locked_until = None
    _start_session(db, request, response, user, mfa_verified=not user.mfa_enabled)
    audit(db, request, "auth.login", user_id=user.id)
    return {"mfa_required": user.mfa_enabled, "user": None if user.mfa_enabled else user_out(user)}


@router.post("/mfa/verify")
def mfa_verify(body: CodeIn, request: Request, pending=Depends(pending_session), db: Session = Depends(get_db)):
    limit(request, "auth", get_settings().rate_limit_auth_per_minute)
    sess, user = pending
    secret = sec.decrypt(user.totp_secret_enc or "")
    ok = bool(secret) and sec.verify_totp(secret, body.code)
    if not ok and user.recovery_code_hashes:
        h = sec.recovery_hash(body.code)
        if h in user.recovery_code_hashes:
            user.recovery_code_hashes = [x for x in user.recovery_code_hashes if x != h]
            ok = True
            audit(db, request, "auth.recovery_code_used", user_id=user.id)
    if not ok:
        audit(db, request, "auth.mfa_failed", user_id=user.id)
        db.commit()
        raise HTTPException(401, "That code is not right. Please try again.")
    sess.mfa_verified = True
    audit(db, request, "auth.mfa_verified", user_id=user.id)
    return user_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, pending=Depends(pending_session), db: Session = Depends(get_db)):
    sess, user = pending
    sess.revoked_at = now()
    audit(db, request, "auth.logout", user_id=user.id)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = user_out(user)
    out["households"] = [
        {"household_id": a.household_id, "role": a.role}
        for a in db.scalars(select(HouseholdAccess).where(HouseholdAccess.user_id == user.id))
    ]
    return out


@router.patch("/me")
def update_me(body: PrefsIn, user: User = Depends(current_user)):
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.simple_mode is not None:
        user.simple_mode = body.simple_mode
    return user_out(user)


@router.post("/mfa/setup")
def mfa_setup(user: User = Depends(current_user)):
    """Step 1: create a secret to scan into an authenticator app. Not active until confirmed."""
    if user.mfa_enabled:
        raise HTTPException(409, "Two-step verification is already on.")
    secret = sec.new_totp_secret()
    user.totp_secret_enc = sec.encrypt(secret)
    return {"secret": secret, "otpauth_uri": sec.totp_uri(secret, user.email)}


@router.post("/mfa/enable")
def mfa_enable(body: CodeIn, request: Request, user: User = Depends(current_user),
               pending=Depends(pending_session), db: Session = Depends(get_db)):
    secret = sec.decrypt(user.totp_secret_enc or "")
    if not secret or not sec.verify_totp(secret, body.code):
        raise HTTPException(401, "That code is not right. Check the time on your phone and try again.")
    codes = sec.new_recovery_codes()
    user.mfa_enabled = True
    user.recovery_code_hashes = [sec.recovery_hash(c) for c in codes]
    pending[0].mfa_verified = True
    audit(db, request, "auth.mfa_enabled", user_id=user.id)
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
def mfa_disable(body: DisableMfaIn, request: Request, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    secret = sec.decrypt(user.totp_secret_enc or "")
    if not sec.verify_password(user.password_hash, body.password) or not secret \
            or not sec.verify_totp(secret, body.code):
        raise HTTPException(401, "The password or code is not right.")
    user.mfa_enabled = False
    user.totp_secret_enc = None
    user.recovery_code_hashes = None
    audit(db, request, "auth.mfa_disabled", user_id=user.id)
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordIn, request: Request, user: User = Depends(current_user),
                    pending=Depends(pending_session), db: Session = Depends(get_db)):
    if not sec.verify_password(user.password_hash, body.current_password):
        raise HTTPException(401, "Your current password is not right.")
    problem = sec.password_problem(body.new_password)
    if problem:
        raise HTTPException(422, problem)
    user.password_hash = sec.hash_password(body.new_password)
    t = now()
    for s in db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))):
        if s.id != pending[0].id:
            s.revoked_at = t  # sign out everywhere else
    audit(db, request, "auth.password_changed", user_id=user.id)
    return {"ok": True}
