"""Reports, assistant, glossary, privacy, audit trail and account linking."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..ai import assistant
from ..config import get_settings
from ..models import (
    Account,
    AIConversation,
    AIProposal,
    AuditLog,
    Expense,
    Household,
    HouseholdAccess,
    Member,
    RealEstate,
    Report,
    User,
    UserSession,
    now,
)
from ..providers.aggregation import get_provider
from ..security.core import verify_password
from ..services import insights as insights_svc
from ..services import reports as report_svc
from ..services import runs
from ..services.assumptions import save_assumptions
from ..services.glossary import GLOSSARY
from .data import row_dict
from .deps import CSRF_COOKIE, SESSION_COOKIE, Ctx, audit, current_user, get_ctx, get_writer
from .planning import DEFAULT_SEED

router = APIRouter(tags=["misc"])

MIME = {"pdf": "application/pdf", "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


# ----------------------------------------------------------------------------- reports


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_format: Literal["pdf", "xlsx", "csv"] = "pdf"
    scenario_id: str | None = None
    include_monte_carlo: bool = True


def _freshness(ctx: Ctx) -> list[dict]:
    out = []
    for a in ctx.db.scalars(select(Account).where(Account.household_id == ctx.hid)).unique():
        out.append({"item": f"{a.name} (balance)", "as_of": a.balance_as_of.isoformat() if a.balance_as_of else "",
                    "source": {"manual": "Entered by hand", "csv": "CSV import", "plaid": "Linked account"}
                    .get(a.source, a.source)})
    for r in ctx.db.scalars(select(RealEstate).where(RealEstate.household_id == ctx.hid)):
        out.append({"item": f"{r.name} (value)", "as_of": r.value_as_of.isoformat() if r.value_as_of else "",
                    "source": "Entered by hand"})
    return out


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, ctx: Ctx = Depends(get_ctx)):
    plan_input, _, _, _ = runs.resolve(ctx, body.scenario_id)
    proj = runs.projection(ctx, scenario_id=body.scenario_id)
    mc = runs.monte_carlo(ctx, n_paths=1000, seed=DEFAULT_SEED, scenario_id=body.scenario_id) \
        if body.include_monte_carlo and body.file_format != "csv" else None
    ins = insights_svc.build(plan_input, proj, mc)
    fresh = _freshness(ctx)
    if body.file_format == "pdf":
        content = report_svc.build_pdf(plan_input, proj, mc, fresh, ins, get_settings().app_name)
    elif body.file_format == "xlsx":
        content = report_svc.build_xlsx(plan_input, proj, mc, fresh, ins)
    else:
        content = report_svc.build_csv(proj)
    stamp = date.today().isoformat()
    safe = "".join(ch if ch.isalnum() else "-" for ch in plan_input.name).strip("-").lower() or "plan"
    row = Report(household_id=ctx.hid, title=f"{plan_input.name} ({stamp})", file_format=body.file_format,
                 filename=f"{safe}-{stamp}.{body.file_format}", input_hash=plan_input.content_hash(),
                 size_bytes=len(content), content=content)
    ctx.db.add(row)
    ctx.db.flush()
    ctx.log("report.create", "report", row.id, {"format": body.file_format})
    return row_dict(row, exclude=("household_id", "content"))


@router.get("/reports")
def list_reports(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(Report).where(Report.household_id == ctx.hid)
                          .order_by(Report.created_at.desc()).limit(50))
    return [row_dict(r, exclude=("household_id", "content")) for r in rows]


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, ctx: Ctx = Depends(get_ctx)):
    r = ctx.owned(Report, report_id)
    ctx.log("report.download", "report", r.id)
    return Response(content=r.content, media_type=MIME[r.file_format],
                    headers={"Content-Disposition": f'attachment; filename="{r.filename}"'})


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: str, ctx: Ctx = Depends(get_writer)):
    ctx.db.delete(ctx.owned(Report, report_id))
    return Response(status_code=204)


# ----------------------------------------------------------------------------- assistant


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None


class ConsentIn(BaseModel):
    consent: bool


@router.get("/assistant/status")
def assistant_status(ctx: Ctx = Depends(get_ctx)):
    return assistant.status(ctx)


@router.post("/assistant/consent")
def assistant_consent(body: ConsentIn, ctx: Ctx = Depends(get_ctx)):
    """Explicit opt-in (or opt-out) for sending plan data to an external AI service."""
    ctx.user.ai_consent_at = now() if body.consent else None
    ctx.user.ai_consent_version = assistant.CONSENT_VERSION if body.consent else None
    ctx.log("ai.consent_given" if body.consent else "ai.consent_withdrawn",
            detail={"version": assistant.CONSENT_VERSION})
    return assistant.status(ctx)


@router.post("/assistant/chat")
def assistant_chat(body: ChatIn, ctx: Ctx = Depends(get_ctx)):
    return assistant.chat(ctx, body.conversation_id, body.message.strip())


@router.get("/assistant/conversations")
def conversations(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(AIConversation).where(
        AIConversation.household_id == ctx.hid, AIConversation.user_id == ctx.user.id)
        .order_by(AIConversation.created_at.desc()).limit(30)).unique()
    return [{"id": c.id, "title": c.title, "mode": c.mode, "created_at": c.created_at.isoformat()} for c in rows]


@router.get("/assistant/conversations/{conversation_id}")
def conversation(conversation_id: str, ctx: Ctx = Depends(get_ctx)):
    c = ctx.owned(AIConversation, conversation_id)
    if c.user_id != ctx.user.id:
        raise HTTPException(404, "Not found.")
    proposals = ctx.db.scalars(select(AIProposal).where(AIProposal.conversation_id == c.id))
    return {"id": c.id, "title": c.title, "mode": c.mode,
            "messages": [{"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
                         for m in c.messages if m.role in ("user", "assistant") and not m.tool_calls],
            "proposals": [assistant.proposal_out(p) for p in proposals]}


@router.delete("/assistant/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, ctx: Ctx = Depends(get_ctx)):
    c = ctx.owned(AIConversation, conversation_id)
    if c.user_id != ctx.user.id:
        raise HTTPException(404, "Not found.")
    ctx.db.delete(c)
    return Response(status_code=204)


class DecisionIn(BaseModel):
    decision: Literal["apply", "reject"]


@router.post("/assistant/proposals/{proposal_id}")
def decide_proposal(proposal_id: str, body: DecisionIn, ctx: Ctx = Depends(get_writer)):
    """The only way an assistant suggestion can change the plan: the user confirms it here."""
    p = ctx.owned(AIProposal, proposal_id)
    if p.status != "pending":
        raise HTTPException(409, "This suggestion was already decided.")
    if body.decision == "reject":
        p.status = "rejected"
    else:
        ch = p.change
        kind, value = ch.get("kind"), ch.get("value")
        try:
            if kind == "set_retirement_age":
                m = ctx.owned(Member, ch["member_id"])
                age = int(value)
                if not 18 <= age <= 100:
                    raise ValueError("age out of range")
                m.retirement_age = age
            elif kind == "set_ss_claim_age":
                m = ctx.owned(Member, ch["member_id"])
                age = int(value)
                if not 62 <= age <= 70 or m.ss_estimate is None:
                    raise ValueError("claim age must be 62-70 and a benefit must be entered")
                m.ss_estimate.claim_age = age
                m.ss_estimate.claim_months = 0
            elif kind == "set_expense_amount":
                e = ctx.owned(Expense, ch["expense_id"])
                if float(value) < 0:
                    raise ValueError("amount cannot be negative")
                e.amount = float(value)
            elif kind == "set_guardrails":
                save_assumptions(ctx, {"guardrails": {"enabled": bool(value)}}, "Assistant suggestion (confirmed)")
            elif kind == "set_withdrawal_strategy":
                save_assumptions(ctx, {"withdrawal_strategy": str(value)}, "Assistant suggestion (confirmed)")
            else:
                raise ValueError("unknown change")
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(422, f"This suggestion cannot be applied: {exc}") from exc
        p.status = "applied"
    p.decided_at = now()
    ctx.log(f"ai.proposal_{p.status}", "ai_proposal", p.id, {"kind": p.change.get("kind")})
    return assistant.proposal_out(p)


# ----------------------------------------------------------------------------- glossary, linking, audit


@router.get("/glossary")
def glossary():
    return [{"key": k, **v} for k, v in sorted(GLOSSARY.items(), key=lambda kv: kv[1]["term"])]


@router.get("/linking/status")
def linking_status(ctx: Ctx = Depends(get_ctx)):
    st = get_provider(get_settings()).status()
    return {"provider": st.provider, "available": st.available, "message": st.message,
            "credentials_note": "This app never sees or stores your bank passwords."}


@router.post("/linking/token")
def linking_token(ctx: Ctx = Depends(get_writer)):
    provider = get_provider(get_settings())
    if not provider.status().available:
        raise HTTPException(503, provider.status().message)
    try:
        token = provider.create_link_token(ctx.user.id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, "The linking service did not respond. Please try again later.") from exc
    ctx.log("linking.token_created", detail={"provider": provider.name})
    return token


@router.get("/audit")
def audit_trail(limit: int = 100, ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(AuditLog).where(AuditLog.household_id == ctx.hid)
                          .order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 500)))
    return [{"at": r.created_at.isoformat(), "action": r.action, "entity": r.entity, "entity_id": r.entity_id,
             "detail": r.detail, "by_you": r.user_id == ctx.user.id} for r in rows]


@router.get("/sessions")
def sessions(user: User = Depends(current_user), ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
                          .order_by(UserSession.last_seen_at.desc()).limit(20))
    return [{"id": s.id, "created_at": s.created_at.isoformat(), "last_seen_at": s.last_seen_at.isoformat(),
             "user_agent": s.user_agent, "ip": s.ip} for s in rows]


# ----------------------------------------------------------------------------- privacy


@router.get("/privacy/export")
def export_data(ctx: Ctx = Depends(get_ctx)):
    """Everything stored about you and this household, as one JSON document."""
    if ctx.role != "owner":
        raise HTTPException(403, "Only the owner can export the household's data.")
    from .. import models as M
    tables = [M.Member, M.SSEstimate, M.AssetClass, M.Account, M.Allocation, M.Security, M.Price, M.Holding,
              M.Transaction, M.IncomeSource, M.Pension, M.Expense, M.Liability, M.RealEstate, M.Business, M.Plan,
              M.AssumptionSet, M.Scenario, M.ProjectionResult, M.MonteCarloRun, M.RothStrategy, M.AIConversation,
              M.AIMessage, M.AIProposal]
    out: dict = {
        "exported_at": now().isoformat(),
        "user": {"email": ctx.user.email, "display_name": ctx.user.display_name,
                 "created_at": ctx.user.created_at.isoformat(), "mfa_enabled": ctx.user.mfa_enabled,
                 "ai_consent_at": ctx.user.ai_consent_at.isoformat() if ctx.user.ai_consent_at else None},
        "household": row_dict(ctx.household, exclude=()),
    }
    for model in tables:
        out[model.__tablename__] = [row_dict(r) for r in ctx.db.scalars(
            select(model).where(model.household_id == ctx.hid)).unique()]
    out["reports"] = [row_dict(r, exclude=("household_id", "content")) for r in ctx.db.scalars(
        select(Report).where(Report.household_id == ctx.hid))]
    out["audit_logs"] = [row_dict(r, exclude=()) for r in ctx.db.scalars(
        select(AuditLog).where(AuditLog.household_id == ctx.hid))]
    ctx.log("privacy.export")
    return out


class DeleteIn(BaseModel):
    password: str
    confirm: Literal["DELETE"]


@router.post("/privacy/delete-account")
def delete_account(body: DeleteIn, response: Response, ctx: Ctx = Depends(get_ctx)):
    """Permanently delete the account, its households and everything in them."""
    if not verify_password(ctx.user.password_hash, body.password):
        raise HTTPException(401, "Your password is not right.")
    user_id = ctx.user.id
    for h in list(ctx.db.scalars(select(Household).where(Household.owner_user_id == user_id))):
        for log in ctx.db.scalars(select(AuditLog).where(AuditLog.household_id == h.id)):
            ctx.db.delete(log)
        ctx.db.delete(h)
    ctx.db.flush()  # the database cascades the household's rows, including its access rows
    for row in ctx.db.scalars(select(HouseholdAccess).where(HouseholdAccess.user_id == user_id)):
        ctx.db.delete(row)
    for log in ctx.db.scalars(select(AuditLog).where(AuditLog.user_id == user_id)):
        ctx.db.delete(log)
    ctx.db.flush()
    ctx.db.delete(ctx.user)
    audit(ctx.db, ctx.request, "privacy.account_deleted")  # anonymous record that a deletion happened
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}
