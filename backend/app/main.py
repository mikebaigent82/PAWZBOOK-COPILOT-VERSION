from __future__ import annotations

import hashlib
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .api import auth, data, misc, planning
from .config import get_settings
from .db import get_engine
from .engine.models import ENGINE_VERSION
from .engine.taxrules import available_years, load_rules
from .models import TaxRuleVersion

log = logging.getLogger("planner")

DISCLAIMER = ("Projections are estimates based on your inputs and assumptions. They are not guarantees and not "
              "financial, tax, investment or legal advice.")


def sync_tax_rules() -> None:
    """Record the tax-rule files shipped with this build in the database."""
    with Session(get_engine()) as db:
        for year in available_years():
            rules = load_rules(year)
            digest = hashlib.sha256(json.dumps(rules.raw, sort_keys=True).encode()).hexdigest()
            row = db.scalar(select(TaxRuleVersion).where(TaxRuleVersion.tax_year == year))
            if row is None:
                db.add(TaxRuleVersion(tax_year=year, version=rules.version, sha256=digest, payload=rules.raw))
            elif row.sha256 != digest:
                row.version, row.sha256, row.payload = rules.version, digest, rules.raw
        db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        sync_tax_rules()
    except Exception:  # noqa: BLE001 - e.g. migrations not applied yet; /health reports it
        log.exception("Could not sync tax rule versions")
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version=ENGINE_VERSION, lifespan=lifespan,
                  docs_url="/api/docs" if s.is_dev else None, redoc_url=None,
                  openapi_url="/api/openapi.json" if s.is_dev else None)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                       allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "X-CSRF-Token", "X-Household-Id"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        if not s.is_dev:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError):
        """Turn validation errors into one readable sentence."""
        first = exc.errors()[0]
        field = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query"))
        msg = str(first.get("msg", "Invalid value")).removeprefix("Value error, ")
        nice = msg if not field or " " in msg and msg[0].isupper() and "should" not in msg.lower() \
            else f"{field.replace('_', ' ').capitalize()}: {msg}"
        return JSONResponse(status_code=422, content={"detail": nice})

    @app.exception_handler(HTTPException)
    async def http_handler(_request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    for r in (auth.router, data.router, planning.router, misc.router):
        app.include_router(r, prefix="/api")

    @app.get("/api/health")
    def health():
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        return JSONResponse(status_code=200 if db_ok else 503, content={
            "status": "ok" if db_ok else "database unavailable", "engine_version": ENGINE_VERSION,
            "environment": s.environment, "tax_rule_years": list(available_years())})

    @app.get("/api/about")
    def about():
        return {"app_name": s.app_name, "engine_version": ENGINE_VERSION, "disclaimer": DISCLAIMER,
                "ai_mode": "live" if s.ai_live else "demo", "linking": s.aggregation_provider,
                "tax_rule_years": list(available_years())}

    return app


app = create_app()
