import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Annotated
from uuid import UUID

import httpx
import psycopg
from psycopg.errors import UniqueViolation
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException

from .storage import PostgresRepository
from .telemetry import logger, propagator, provider, request_id

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class User(Input):
    name: Name
    email: EmailStr


class Product(Input):
    name: Name
    price: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


class Order(Input):
    user_id: UUID
    product_id: UUID
    quantity: Annotated[int, Field(ge=1, le=1000, strict=True)]


class UserRecord(User):
    id: UUID


class ProductRecord(Product):
    id: UUID


class OrderRecord(Order):
    id: UUID


@dataclass(frozen=True)
class Settings:
    service: str
    database_url: str
    user_url: str = "http://user-service:8000"
    product_url: str = "http://product-service:8000"
    timeout: float = 0.5
    attempts: int = 2
    fault: str = ""
    lab_enabled: bool = False
    export_spans: bool = False

    @classmethod
    def from_env(cls, service):
        return cls(
            service=service,
            database_url=os.environ["DATABASE_URL"],
            user_url=os.getenv("USER_SERVICE_URL", cls.user_url),
            product_url=os.getenv("PRODUCT_SERVICE_URL", cls.product_url),
            timeout=float(os.getenv("UPSTREAM_TIMEOUT", str(cls.timeout))),
            attempts=int(os.getenv("UPSTREAM_ATTEMPTS", str(cls.attempts))),
            fault=os.getenv("LAB_FAULT", ""),
            lab_enabled=os.getenv("LAB_ENABLED") == "1",
            export_spans=os.getenv("TRACE_EXPORT") == "stdout",
        )


def create_app(settings, *, repository=None, tracer_provider=None, transport=None):
    service = settings.service
    schema, output, resource = {
        "user": (User, UserRecord, "users"),
        "product": (Product, ProductRecord, "products"),
        "order": (Order, OrderRecord, "orders"),
    }[service]
    allowed = {"product": {"delay", "unavailable"},
               "order": {"processing", "processing_before_lookup", "database"},
               "user": {"delay", "unavailable"}}
    if settings.fault and (not settings.lab_enabled or settings.fault not in allowed[service]):
        raise ValueError("Invalid or disabled lab fault")
    if not 0 < settings.timeout <= 30 or not 1 <= settings.attempts <= 5:
        raise ValueError("Invalid dependency timeout or retry budget")
    unreachable = "postgresql://unused:unused@127.0.0.1:1/unused"
    repo = repository or PostgresRepository(settings.database_url, service,
                                            unreachable if settings.fault == "database" else None)
    tp = tracer_provider or provider(service, settings.export_spans)
    tracer = tp.get_tracer("thesis.microservices")
    log = logger()

    def record(event, level=20, **fields):
        log.log(level, event, extra={"service": service, "fields": fields})

    @asynccontextmanager
    async def lifespan(app):
        await repo.initialize()
        async with httpx.AsyncClient(timeout=settings.timeout, transport=transport, trust_env=False) as client:
            app.state.client = client
            try:
                yield
            finally:
                if tracer_provider is None:
                    tp.shutdown()

    app = FastAPI(title=f"{service.title()} Service", lifespan=lifespan)

    @app.middleware("http")
    async def trace_request(request: Request, call_next):
        start = perf_counter()
        with tracer.start_as_current_span(request.method, context=propagator.extract(request.headers),
                                          kind=SpanKind.SERVER, record_exception=False,
                                          set_status_on_exception=False) as span:
            status = 500
            token = request_id.set(f"{span.get_span_context().span_id:016x}")
            try:
                response = await call_next(request)
                status = response.status_code
                ctx = span.get_span_context()
                if ctx.is_valid:
                    response.headers["x-trace-id"] = f"{ctx.trace_id:032x}"
                return response
            except Exception:
                record("request_failed", level=40, code="internal_error")
                ctx = span.get_span_context()
                return JSONResponse({"error": {"code": "internal_error"}}, status_code=500,
                                    headers={"x-trace-id": f"{ctx.trace_id:032x}"} if ctx.is_valid else {})
            finally:
                route = getattr(request.scope.get("route"), "path", "unmatched")
                span.update_name(f"{request.method} {route}")
                span.set_attributes({"http.request.method": request.method, "http.route": route,
                                     "http.response.status_code": status})
                if status >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                record("request_completed", level=40 if status >= 500 else 20,
                       method=request.method, route=route, status=status,
                       duration_ms=round((perf_counter() - start) * 1000, 2))
                request_id.reset(token)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        code = exc.detail if exc.status_code != 404 or exc.detail != "Not Found" else "not_found"
        return JSONResponse({"error": {"code": code}}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [".".join(map(str, item["loc"])) for item in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "fields": fields}}, status_code=422)

    @app.exception_handler(UniqueViolation)
    async def conflict(request, exc):
        return JSONResponse({"error": {"code": "conflict"}}, status_code=409)

    @app.exception_handler(psycopg.OperationalError)
    async def database_unavailable(request, exc):
        record("database_connection_failed", level=40, code="database_unavailable")
        return JSONResponse({"error": {"code": "database_unavailable"}}, status_code=503)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": service}

    @app.get("/ready")
    async def ready():
        await repo.ready()
        return {"status": "ready"}

    async def lookup(client, dependency, url, path):
        last_status = 502
        for attempt in range(1, settings.attempts + 1):
            with tracer.start_as_current_span("GET dependency", kind=SpanKind.CLIENT) as span:
                span.set_attributes({"peer.service": dependency, "retry.attempt": attempt})
                headers = {}
                propagator.inject(headers)
                try:
                    response = await client.get(f"{url.rstrip('/')}{path}", headers=headers)
                    span.set_attribute("http.response.status_code", response.status_code)
                    if response.status_code == 200:
                        return
                    if response.status_code == 404:
                        raise HTTPException(422, f"unknown_{dependency}")
                    if response.status_code not in (502, 503, 504):
                        raise HTTPException(502, "dependency_error")
                    last_status = 504 if response.status_code == 504 else 502
                except httpx.TimeoutException:
                    last_status = 504
                except httpx.RequestError:
                    last_status = 502
                span.set_status(Status(StatusCode.ERROR))
                error = "dependency_timeout" if last_status == 504 else "dependency_unavailable"
                record("dependency_attempt_failed", level=30, dependency=dependency, code=error,
                       attempt=attempt, attempts=settings.attempts, status=last_status)
            if attempt < settings.attempts:
                await asyncio.sleep(.05 * attempt)
        error = "dependency_timeout" if last_status == 504 else "dependency_unavailable"
        record("dependency_exhausted", level=40, dependency=dependency, status=last_status, code=error)
        raise HTTPException(last_status, error)

    async def check_order(payload, request):
        if service != "order":
            return
        if settings.fault == "processing_before_lookup":
            record("order_processing_failed", level=40, code="order_processing_error",
                   stage="before_dependency_lookup")
            raise HTTPException(500, "order_processing_error")
        await lookup(request.app.state.client, "user", settings.user_url, f"/users/{payload.user_id}")
        await lookup(request.app.state.client, "product", settings.product_url, f"/products/{payload.product_id}")
        if settings.fault == "processing":
            record("order_processing_failed", level=40, code="order_processing_error")
            raise HTTPException(500, "order_processing_error")

    @app.post(f"/{resource}", status_code=201, response_model=output)
    async def create(payload: schema, request: Request):
        await check_order(payload, request)
        return await repo.create(payload.model_dump(mode="json"))

    @app.get(f"/{resource}", response_model=list[output])
    async def list_records(limit: Annotated[int, Query(ge=1, le=100)] = 20,
                           offset: Annotated[int, Query(ge=0)] = 0):
        return await repo.list(limit, offset)

    @app.get(f"/{resource}/{{key}}", response_model=output)
    async def get_record(key: UUID):
        if settings.fault == "delay":
            await asyncio.sleep(settings.timeout + .25)
        if settings.fault == "unavailable":
            raise HTTPException(503, "service_unavailable")
        result = await repo.get(key)
        if result is None:
            raise HTTPException(404, "not_found")
        return result

    @app.put(f"/{resource}/{{key}}", response_model=output)
    async def replace(key: UUID, payload: schema, request: Request):
        if await repo.get(key) is None:
            raise HTTPException(404, "not_found")
        await check_order(payload, request)
        result = await repo.update(key, payload.model_dump(mode="json"))
        if result is None:
            raise HTTPException(404, "not_found")
        return result

    @app.delete(f"/{resource}/{{key}}", status_code=204)
    async def delete(key: UUID):
        if not await repo.delete(key):
            raise HTTPException(404, "not_found")
        return Response(status_code=204)

    return app
