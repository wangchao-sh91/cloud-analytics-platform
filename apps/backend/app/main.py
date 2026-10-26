import logging
from typing import Annotated
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from .db import get_db
from .models import Server
from .schemas import CreateServer, PatchServer, ServerOut, ServerPage, Status

app = FastAPI(title="Lab Physical Server Inventory")
DB = Annotated[Session, Depends(get_db)]


def error(status, code, message, field_errors=None):
    return JSONResponse(status_code=status, content={"code": code, "message": message, "field_errors": field_errors or {}})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    fields = {".".join(str(p) for p in e["loc"][1:]): e["msg"] for e in exc.errors()}
    return error(422, "validation_error", "Please check the highlighted fields.", fields)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return error(exc.status_code, "not_found" if exc.status_code == 404 else "request_error", str(exc.detail))


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    logging.exception("Database request failed")
    return error(503, "service_unavailable", "The service is temporarily unavailable. Please try again.")


def find(db, server_id):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(404, "Server not found.")
    return server


def save(db, server):
    try:
        db.add(server)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(409, "A server with this Service Tag already exists.") from None
        raise
    db.refresh(server)
    return server


@app.get("/api/servers", response_model=ServerPage)
def list_servers(db: DB, q: str = "", model: str = "", status: Status | None = None,
                 page: Annotated[int, Query(ge=1)] = 1,
                 page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    conditions = []
    if q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(or_(*(column.ilike(pattern, escape="\\") for column in
                                [Server.name, Server.service_tag, Server.management_ip, Server.idrac_ip])))
    if model:
        conditions.append(Server.model == model)
    if status:
        conditions.append(Server.status == status)
    total = db.scalar(select(func.count()).select_from(Server).where(*conditions))
    items = db.scalars(select(Server).where(*conditions).order_by(Server.created_at.desc(), Server.id.desc())
                       .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/api/servers", status_code=201, response_model=ServerOut)
def create_server(payload: CreateServer, db: DB):
    return save(db, Server(**payload.model_dump()))


@app.get("/api/servers/{server_id}", response_model=ServerOut)
def get_server(server_id: UUID, db: DB):
    return find(db, server_id)


@app.patch("/api/servers/{server_id}", response_model=ServerOut)
def update_server(server_id: UUID, payload: PatchServer, db: DB):
    server = find(db, server_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(server, key, value)
    return save(db, server)


@app.delete("/api/servers/{server_id}", status_code=204)
def delete_server(server_id: UUID, db: DB):
    db.delete(find(db, server_id))
    db.commit()
    return Response(status_code=204)


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready(db: DB):
    try:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        expected = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        if revision != expected:
            return error(503, "not_ready", "Database migration is required.")
    except SQLAlchemyError:
        return error(503, "not_ready", "Database is unavailable or migration is required.")
    return {"status": "ready"}
