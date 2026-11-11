"""Database schema.

Every row that belongs to a user carries ``household_id`` (or hangs off a row
that does) and every query filters on it, so one user's data can never be read
by another. All tables are timestamped. Results store a full snapshot of the
inputs they were calculated from, so any number can be reproduced later.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


def Money(**kw):  # noqa: N802 - reads like a type
    return mapped_column(Numeric(18, 2, asdecimal=False), **kw)


def Rate(**kw):  # noqa: N802
    return mapped_column(Float, **kw)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Pk:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


def household_fk(**kw):
    return mapped_column(String(32), ForeignKey("households.id", ondelete="CASCADE"), index=True, **kw)


# ----------------------------------------------------------------------------- identity


class User(Base, Pk, Timestamps):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")  # user | advisor | admin
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    recovery_code_hashes: Mapped[list | None] = mapped_column(JSON)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_consent_version: Mapped[str | None] = mapped_column(String(20))
    simple_mode: Mapped[bool] = mapped_column(Boolean, default=True)


class UserSession(Base, Pk, Timestamps):
    __tablename__ = "sessions"
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class Household(Base, Pk, Timestamps):
    __tablename__ = "households"
    owner_user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    filing_status: Mapped[str] = mapped_column(String(10), default="single")
    state: Mapped[str] = mapped_column(String(2), default="FL")
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class HouseholdAccess(Base, Pk, Timestamps):
    """Who may open a household. Lets an advisor serve many client households later."""
    __tablename__ = "household_access"
    __table_args__ = (UniqueConstraint("household_id", "user_id"),)
    household_id: Mapped[str] = household_fk()
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")  # owner | editor | viewer


class Member(Base, Pk, Timestamps):
    __tablename__ = "members"
    household_id: Mapped[str] = household_fk()
    name: Mapped[str] = mapped_column(String(120))
    relationship_kind: Mapped[str] = mapped_column(String(20), default="self")  # self | spouse
    birth_year: Mapped[int] = mapped_column(Integer)
    retirement_age: Mapped[int] = mapped_column(Integer, default=65)
    life_expectancy: Mapped[int] = mapped_column(Integer, default=92)
    ss_estimate: Mapped[SSEstimate | None] = relationship(back_populates="member", cascade="all, delete-orphan",
                                                          uselist=False, lazy="joined")


class SSEstimate(Base, Pk, Timestamps):
    __tablename__ = "ss_estimates"
    household_id: Mapped[str] = household_fk()
    member_id: Mapped[str] = mapped_column(String(32), ForeignKey("members.id", ondelete="CASCADE"), unique=True)
    monthly_benefit: Mapped[float] = Money(default=0)
    basis: Mapped[str] = mapped_column(String(12), default="at_fra")  # at_fra | as_claimed
    claim_age: Mapped[int] = mapped_column(Integer, default=67)
    claim_months: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str | None] = mapped_column(String(120))
    as_of: Mapped[date | None] = mapped_column(Date)
    member: Mapped[Member] = relationship(back_populates="ss_estimate")


# ----------------------------------------------------------------------------- investments


class AssetClass(Base, Pk, Timestamps):
    __tablename__ = "asset_classes"
    __table_args__ = (UniqueConstraint("household_id", "key"),)
    household_id: Mapped[str] = household_fk()
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80))
    expected_return: Mapped[float] = Rate()
    volatility: Mapped[float] = Rate()
    income_yield: Mapped[float] = Rate(default=0)
    qualified_ratio: Mapped[float] = Rate(default=0)
    proxy: Mapped[str] = mapped_column(String(10), default="equity")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Account(Base, Pk, Timestamps):
    __tablename__ = "accounts"
    household_id: Mapped[str] = household_fk()
    member_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("members.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    institution: Mapped[str | None] = mapped_column(String(120))
    tax_type: Mapped[str] = mapped_column(String(12))  # cash | taxable | traditional | roth | hsa
    balance: Mapped[float] = Money(default=0)
    cost_basis: Mapped[float | None] = Money()
    annual_contribution: Mapped[float] = Money(default=0)
    employer_match: Mapped[float] = Money(default=0)
    contribution_real_growth: Mapped[float] = Rate(default=0)
    annual_fee: Mapped[float] = Rate(default=0)
    source: Mapped[str] = mapped_column(String(12), default="manual")  # manual | csv | plaid
    external_id: Mapped[str | None] = mapped_column(String(120))
    balance_as_of: Mapped[date | None] = mapped_column(Date)
    allocations: Mapped[list[Allocation]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    holdings: Mapped[list[Holding]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class Allocation(Base, Pk, Timestamps):
    __tablename__ = "allocations"
    __table_args__ = (UniqueConstraint("account_id", "asset_class_key"),)
    household_id: Mapped[str] = household_fk()
    account_id: Mapped[str] = mapped_column(String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    asset_class_key: Mapped[str] = mapped_column(String(40))
    weight: Mapped[float] = Rate()


class Security(Base, Pk, Timestamps):
    __tablename__ = "securities"
    __table_args__ = (UniqueConstraint("household_id", "symbol"),)
    household_id: Mapped[str] = household_fk()
    symbol: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))
    asset_class_key: Mapped[str] = mapped_column(String(40), default="other")
    is_fund: Mapped[bool] = mapped_column(Boolean, default=False)
    composition: Mapped[list | None] = mapped_column(JSON)  # look-through parts [{kind,key,name,weight}]
    composition_source: Mapped[str | None] = mapped_column(String(160))
    composition_as_of: Mapped[date | None] = mapped_column(Date)


class Price(Base, Pk, Timestamps):
    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("security_id", "price_date"),)
    household_id: Mapped[str] = household_fk()
    security_id: Mapped[str] = mapped_column(String(32), ForeignKey("securities.id", ondelete="CASCADE"), index=True)
    price_date: Mapped[date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False))
    source: Mapped[str] = mapped_column(String(40), default="manual")


class Holding(Base, Pk, Timestamps):
    __tablename__ = "holdings"
    household_id: Mapped[str] = household_fk()
    account_id: Mapped[str] = mapped_column(String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    security_id: Mapped[str] = mapped_column(String(32), ForeignKey("securities.id", ondelete="CASCADE"), index=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(20, 6, asdecimal=False))
    value: Mapped[float] = Money(default=0)
    cost_basis: Mapped[float | None] = Money()
    as_of: Mapped[date | None] = mapped_column(Date)
    security: Mapped[Security] = relationship(lazy="joined")


class Transaction(Base, Pk, Timestamps):
    __tablename__ = "transactions"
    household_id: Mapped[str] = household_fk()
    account_id: Mapped[str] = mapped_column(String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    txn_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))  # buy | sell | dividend | interest | deposit | withdrawal | fee
    symbol: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[float | None] = mapped_column(Numeric(20, 6, asdecimal=False))
    amount: Mapped[float] = Money()
    description: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(12), default="manual")


# ----------------------------------------------------------------------------- cash flows


class IncomeSource(Base, Pk, Timestamps):
    __tablename__ = "income_sources"
    household_id: Mapped[str] = household_fk()
    member_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("members.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(12), default="salary")
    amount: Mapped[float] = Money()
    start_year: Mapped[int | None] = mapped_column(Integer)
    end_year: Mapped[int | None] = mapped_column(Integer)
    ends_at_retirement: Mapped[bool] = mapped_column(Boolean, default=False)
    growth_mode: Mapped[str] = mapped_column(String(10), default="inflation")
    growth_rate: Mapped[float] = Rate(default=0)
    tax_treatment: Mapped[str] = mapped_column(String(10), default="ordinary")
    survivor_pct: Mapped[float] = Rate(default=0)


class Pension(Base, Pk, Timestamps):
    __tablename__ = "pensions"
    household_id: Mapped[str] = household_fk()
    member_id: Mapped[str] = mapped_column(String(32), ForeignKey("members.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    annual_amount: Mapped[float] = Money()
    start_age: Mapped[int] = mapped_column(Integer, default=65)
    has_cola: Mapped[bool] = mapped_column(Boolean, default=False)
    survivor_pct: Mapped[float] = Rate(default=0.5)


class Expense(Base, Pk, Timestamps):
    __tablename__ = "expenses"
    household_id: Mapped[str] = household_fk()
    name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float] = Money()
    category: Mapped[str] = mapped_column(String(14), default="essential")
    kind: Mapped[str] = mapped_column(String(12), default="living")
    start_year: Mapped[int | None] = mapped_column(Integer)
    end_year: Mapped[int | None] = mapped_column(Integer)
    starts_at_retirement: Mapped[bool] = mapped_column(Boolean, default=False)
    ends_at_retirement: Mapped[bool] = mapped_column(Boolean, default=False)
    inflation_mode: Mapped[str] = mapped_column(String(12), default="general")
    custom_rate: Mapped[float] = Rate(default=0)
    survivor_pct: Mapped[float | None] = Rate()


class Liability(Base, Pk, Timestamps):
    __tablename__ = "liabilities"
    household_id: Mapped[str] = household_fk()
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="mortgage")
    balance: Mapped[float] = Money()
    interest_rate: Mapped[float] = Rate()
    monthly_payment: Mapped[float] = Money()
    real_estate_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("real_estate.id", ondelete="SET NULL"))


class RealEstate(Base, Pk, Timestamps):
    __tablename__ = "real_estate"
    household_id: Mapped[str] = household_fk()
    name: Mapped[str] = mapped_column(String(120))
    value: Mapped[float] = Money()
    cost_basis: Mapped[float] = Money(default=0)
    growth_rate: Mapped[float] = Rate(default=0.03)
    sale_year: Mapped[int | None] = mapped_column(Integer)
    sale_cost_pct: Mapped[float] = Rate(default=0.06)
    primary_residence: Mapped[bool] = mapped_column(Boolean, default=True)
    value_as_of: Mapped[date | None] = mapped_column(Date)


class Business(Base, Pk, Timestamps):
    __tablename__ = "businesses"
    household_id: Mapped[str] = household_fk()
    member_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("members.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    value: Mapped[float] = Money()
    cost_basis: Mapped[float] = Money(default=0)
    growth_rate: Mapped[float] = Rate(default=0.03)
    annual_income: Mapped[float] = Money(default=0)
    sale_year: Mapped[int | None] = mapped_column(Integer)
    sale_cost_pct: Mapped[float] = Rate(default=0.05)


# ----------------------------------------------------------------------------- planning


class TaxRuleVersion(Base, Pk, Timestamps):
    """Registry of the tax-rule files shipped with the engine (synced at startup)."""
    __tablename__ = "tax_rule_versions"
    tax_year: Mapped[int] = mapped_column(Integer, unique=True)
    version: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class Plan(Base, Pk, Timestamps):
    __tablename__ = "plans"
    household_id: Mapped[str] = household_fk()
    name: Mapped[str] = mapped_column(String(120), default="My plan")
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=True)
    start_year: Mapped[int] = mapped_column(Integer)


class AssumptionSet(Base, Pk, Timestamps):
    """Assumptions are versioned: each save adds a row, the highest version is active."""
    __tablename__ = "assumptions"
    __table_args__ = (UniqueConstraint("plan_id", "version"),)
    household_id: Mapped[str] = household_fk()
    plan_id: Mapped[str] = mapped_column(String(32), ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSON)
    correlations: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[str | None] = mapped_column(String(32))


class Scenario(Base, Pk, Timestamps):
    """A named what-if. It stores only overrides; the baseline plan is never modified."""
    __tablename__ = "scenarios"
    household_id: Mapped[str] = household_fk()
    plan_id: Mapped[str] = mapped_column(String(32), ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)


class ProjectionResult(Base, Pk, Timestamps):
    __tablename__ = "projection_results"
    household_id: Mapped[str] = household_fk()
    plan_id: Mapped[str] = mapped_column(String(32), ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("scenarios.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="projection")  # projection | stress | strategies
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    engine_version: Mapped[str] = mapped_column(String(20))
    assumption_version: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)


class MonteCarloRun(Base, Pk, Timestamps):
    __tablename__ = "monte_carlo_runs"
    household_id: Mapped[str] = household_fk()
    plan_id: Mapped[str] = mapped_column(String(32), ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("scenarios.id", ondelete="CASCADE"))
    seed: Mapped[int] = mapped_column(Integer)
    n_paths: Mapped[int] = mapped_column(Integer)
    distribution: Mapped[str] = mapped_column(String(12))
    degrees_of_freedom: Mapped[float | None] = mapped_column(Float)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    engine_version: Mapped[str] = mapped_column(String(20))
    numpy_version: Mapped[str] = mapped_column(String(20))
    assumption_version: Mapped[int | None] = mapped_column(Integer)
    success_probability: Mapped[float] = mapped_column(Float)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON)


class RothStrategy(Base, Pk, Timestamps):
    __tablename__ = "roth_strategies"
    household_id: Mapped[str] = household_fk()
    plan_id: Mapped[str] = mapped_column(String(32), ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("scenarios.id", ondelete="CASCADE"))
    input_hash: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    weights: Mapped[dict] = mapped_column(JSON)
    recommended_key: Mapped[str] = mapped_column(String(40))
    applied_key: Mapped[str | None] = mapped_column(String(40))
    result: Mapped[dict] = mapped_column(JSON)


class Report(Base, Pk, Timestamps):
    __tablename__ = "reports"
    household_id: Mapped[str] = household_fk()
    title: Mapped[str] = mapped_column(String(160))
    file_format: Mapped[str] = mapped_column(String(6))  # pdf | xlsx | csv
    filename: Mapped[str] = mapped_column(String(200))
    input_hash: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary)


# ----------------------------------------------------------------------------- assistant & audit


class AIConversation(Base, Pk, Timestamps):
    __tablename__ = "ai_conversations"
    household_id: Mapped[str] = household_fk()
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(160), default="Conversation")
    mode: Mapped[str] = mapped_column(String(10), default="demo")  # demo | live
    model: Mapped[str | None] = mapped_column(String(120))
    messages: Mapped[list[AIMessage]] = relationship(cascade="all, delete-orphan", order_by="AIMessage.seq",
                                                     lazy="selectin")


class AIMessage(Base, Pk, Timestamps):
    __tablename__ = "ai_messages"
    household_id: Mapped[str] = household_fk()
    conversation_id: Mapped[str] = mapped_column(String(32), ForeignKey("ai_conversations.id", ondelete="CASCADE"),
                                                 index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant | tool
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    tool_call_id: Mapped[str | None] = mapped_column(String(80))
    tool_name: Mapped[str | None] = mapped_column(String(80))


class AIProposal(Base, Pk, Timestamps):
    """A change suggested by the assistant. Nothing is applied until the user confirms."""
    __tablename__ = "ai_proposals"
    household_id: Mapped[str] = household_fk()
    conversation_id: Mapped[str] = mapped_column(String(32), ForeignKey("ai_conversations.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    explanation: Mapped[str] = mapped_column(Text, default="")
    change: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | applied | rejected
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base, Pk):
    __tablename__ = "audit_logs"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    household_id: Mapped[str | None] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
