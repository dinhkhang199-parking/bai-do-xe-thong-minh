import json
import math
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from datetime import time as day_time
from pathlib import Path

from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from api.schemas import (
    AdminUsersResponse,
    AuthResponse,
    AutoQRInput,
    HealthResponse,
    ListResponse,
    MBCaptchaInput,
    MBConnectInput,
    MBSettingsInput,
    OperationSummaryResponse,
    PaymentInput,
    PaymentQRInput,
    ReadinessResponse,
    ScorecardResponse,
    TariffInput,
    TicketDetailResponse,
)
from api.web import index_response
from backend import billing, mb_monitor, mb_payments, mb_requests, read_queries, scan_cache
from backend.app_service import (
    ProcessedPlate,
    confirm_vehicle_entry,
    confirm_vehicle_exit,
    process_plate_image,
)
from backend.auth import (
    ALL_ROLES,
    WRITE_ROLES,
    AuthUser,
    authenticate_streamlit_user,
    create_session_token,
    parse_static_bearer_token,
    register_streamlit_user,
    require_role,
    verify_session_token,
)
from backend.config import (
    API_EXPOSE_INTERNAL_PATHS,
    API_TOKEN,
    APP_TITLE,
    LOG_LEVEL,
    SCHEMA_VERSION,
    UPLOAD_DIR,
)
from backend.cv_readiness import build_cv_readiness
from backend.db import (
    LastAdminError,
    append_audit_log,
    delete_app_user,
    fetch_parking_events,
    fetch_ticket_detail,
    init_db,
    list_app_users,
    update_app_user_active,
    update_app_user_role,
)
from backend.logging_config import get_logger, setup_logging
from backend.monitoring import finish_request_context, start_request_context
from backend.openai_vision_adapter import vision_configuration_status
from backend.parking_metrics import classify_operational_health
from backend.parking_service import cancel_ticket, resolve_review_ticket
from backend.production_readiness import runtime_readiness
from backend.storage import save_uploaded_file
from backend.validators import ValidationError, validate_image_extension
from integrations.barrier_service import barrier_simulator
from integrations.camera_service import CameraSnapshotSimulator
from integrations.device_config import load_device_config
from integrations.mb_bridge_client import MBConnectionError, call_worker
from integrations.mqtt_adapter import mqtt_simulator

setup_logging(LOG_LEVEL)
logger = get_logger(__name__)

WRITE_WINDOW_SECONDS = 60
WRITE_LIMIT = 30
_WRITE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    mb_monitor.monitor.start()
    logger.info("API started")
    try:
        yield
    finally:
        mb_monitor.monitor.stop()


app = FastAPI(title=APP_TITLE, version=f"schema-{SCHEMA_VERSION}", lifespan=lifespan)


def require_token(x_api_token: str = Header(default="")):
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="API token is not configured")
    if x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_read_access(
    x_api_token: str = Header(default=""), authorization: str = Header(default="")
):
    if x_api_token:
        require_token(x_api_token)
        return None
    user = require_bearer_user(authorization)
    return require_role(user, ALL_ROLES)


def require_bearer_user(authorization: str = Header(default="")) -> AuthUser:
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    user = verify_session_token(token) or parse_static_bearer_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def require_roles(*allowed_roles: str):
    def _dependency(user: AuthUser = Depends(require_bearer_user)) -> AuthUser:
        try:
            return require_role(user, set(allowed_roles))
        except PermissionError:
            raise HTTPException(status_code=403, detail="Forbidden")

    return _dependency


def enforce_write_rate_limit(request: Request, user: AuthUser):
    key = f"{request.client.host if request.client else 'unknown'}:{user.username}"
    now = time.monotonic()
    bucket = _WRITE_BUCKETS[key]
    while bucket and now - bucket[0] > WRITE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= WRITE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many write requests")
    bucket.append(now)


def validate_upload(file: UploadFile):
    validate_image_extension(file.filename or "")
    if file.content_type and not file.content_type.startswith("image/"):
        raise ValidationError("Unsupported upload content type")


def _sanitize_ocr_payload(ocr: dict | None) -> dict:
    payload = dict(ocr or {})
    if not API_EXPOSE_INTERNAL_PATHS:
        return _strip_internal_paths(payload)
    return payload


def _strip_internal_paths(value):
    if isinstance(value, dict):
        return {
            key: _strip_internal_paths(item)
            for key, item in value.items()
            if key != "path" and not key.endswith("_path")
        }
    if isinstance(value, list):
        return [_strip_internal_paths(item) for item in value]
    return value


def _sanitize_record(record: dict) -> dict:
    payload = dict(record or {})
    if not API_EXPOSE_INTERNAL_PATHS:
        return _strip_internal_paths(payload)
    return payload


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def ok(payload: dict, status_code: int = 200):
    return JSONResponse(status_code=status_code, content=_json_safe({"ok": True, **payload}))


def error_payload(code: str, message: str, **extra):
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if extra:
        payload["error"].update(extra)
    return payload


def map_business_failure(result: dict, *, resource: str):
    message = result.get("message", "Business operation failed")
    code = "BUSINESS_RULE_VIOLATION"
    status_code = 409

    if "not found" in message.lower():
        code = f"{resource.upper()}_NOT_FOUND"
        status_code = 404
    elif "already" in message.lower() or "cancel" in message.lower() or "review" in message.lower():
        code = f"{resource.upper()}_CONFLICT"
        status_code = 409
    elif "invalid" in message.lower() or "required" in message.lower():
        code = "VALIDATION_ERROR"
        status_code = 400

    return JSONResponse(
        status_code=status_code, content=error_payload(code, message, result=result)
    )


@app.exception_handler(LastAdminError)
async def last_admin_error_handler(request: Request, exc: LastAdminError):
    return JSONResponse(status_code=409, content=error_payload("last_admin", str(exc)))


@app.exception_handler(ValidationError)
async def validation_error_handler(_, exc: ValidationError):
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": {"code": "VALIDATION_ERROR", "message": str(exc)}},
    )


@app.exception_handler(billing.BillingError)
async def billing_error_handler(_, exc):
    return JSONResponse(status_code=exc.status, content=error_payload("BILLING_ERROR", str(exc)))


@app.exception_handler(MBConnectionError)
async def mb_connection_error(_, exc):
    return JSONResponse(status_code=exc.status, content=error_payload("MB_UNAVAILABLE", str(exc)))


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    start_request_context(request)
    try:
        response = await call_next(request)
    except Exception:
        reference = request.state.request_id
        logger.exception(
            "Request failed: %s %s reference=%s", request.method, request.url.path, reference
        )
        response = JSONResponse(
            status_code=500,
            content=error_payload(
                "INTERNAL_ERROR",
                "Máy chủ gặp lỗi xử lý. Kiểm tra trạng thái trước khi gửi lại.",
                request_id=reference,
            ),
        )
    context = finish_request_context(request)
    if context.get("request_id"):
        response.headers["X-Request-ID"] = context["request_id"]
    if context.get("duration_ms") is not None:
        response.headers["X-Process-Time-Ms"] = str(context["duration_ms"])
    return response


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "schema_version": SCHEMA_VERSION}


@app.get("/readiness", response_model=ReadinessResponse)
def readiness():
    checks = runtime_readiness()
    ready = not any(c["status"] == "fail" for c in checks)
    return ok(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status_code=200 if ready else 503,
    )


@app.get("/system/scorecard", response_model=ScorecardResponse)
def system_scorecard():
    items = [
        {"criterion": c["name"], "score": None, "status": c["status"], "evidence": c["detail"]}
        for c in runtime_readiness()
    ]
    items.append(
        {
            "criterion": "Testing",
            "score": None,
            "status": "not_measured",
            "evidence": "Use a fresh regression test report; runtime does not execute tests",
        }
    )
    return ok({"overall_score": None, "items": items})


@app.get("/cv/readiness")
def cv_readiness(_: AuthUser = Depends(require_roles(*ALL_ROLES))):
    return ok(_sanitize_record(build_cv_readiness()))


@app.get("/metrics")
def metrics():
    return {"status": "prototype", "notes": ["Replace with Prometheus/OpenTelemetry in production"]}


@app.post("/auth/login", response_model=AuthResponse)
def api_login(username: str = Form(...), password: str = Form(...)):
    user = authenticate_streamlit_user(username, password)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        token = create_session_token(user)
    except ValueError:
        raise HTTPException(status_code=401, detail="Unauthorized") from None
    return ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "user": {"username": user.username, "role": user.role},
        }
    )


@app.get("/auth/me")
def auth_me(user: AuthUser = Depends(require_bearer_user)):
    return {"ok": True, "user": {"username": user.username, "role": user.role}}


@app.get("/auth/whoami")
def whoami(user: AuthUser = Depends(require_bearer_user)):
    return {"ok": True, "user": {"username": user.username, "role": user.role}}


@app.get("/ai/status")
def ai_status(user: AuthUser = Depends(require_bearer_user)):
    return ok(vision_configuration_status())


def _normalize_time_bound(value: str, *, upper: bool) -> datetime:
    clean = (value or "").strip()
    try:
        parsed = datetime.fromisoformat(clean)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean):
            parsed = datetime.combine(parsed.date(), day_time.max if upper else day_time.min)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone(timedelta(hours=7)))
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid date/time filter") from None


def _record_time(value):
    try:
        return _normalize_time_bound(str(value), upper=False)
    except HTTPException:
        return None


@app.get("/logs", response_model=ListResponse, dependencies=[Depends(require_read_access)])
def logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    ticket_id: str | None = Query(default=None),
    from_time: str | None = Query(default=None),
    to_time: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
):
    page = read_queries.logs_page(
        limit,
        offset,
        status,
        ticket_id,
        q,
        _normalize_time_bound(from_time, upper=False) if from_time else None,
        _normalize_time_bound(to_time, upper=True) if to_time else None,
    )
    page["items"] = [_sanitize_record(item) for item in page["items"]]
    response = ok(page)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get(
    "/tickets/active", response_model=ListResponse, dependencies=[Depends(require_read_access)]
)
def active_tickets(
    limit: int | None = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=100),
    plate: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, pattern="^(IN_PARKING|NEEDS_REVIEW)$"),
):
    page = read_queries.active_page(limit, offset, query=q, plate=plate, status=status)
    page["items"] = [_sanitize_record(item) for item in page["items"]]
    response = ok(page)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get("/tickets/{ticket_id}", response_model=TicketDetailResponse)
def ticket_detail(ticket_id: str, _: AuthUser = Depends(require_roles(*ALL_ROLES))):
    ticket = fetch_ticket_detail(ticket_id)
    if ticket is None:
        return map_business_failure(
            {"success": False, "message": "Ticket ID not found"}, resource="ticket"
        )
    events = fetch_parking_events(ticket_id).to_dict(orient="records")
    return ok({"ticket": _sanitize_record(ticket), "events": events})


@app.get("/tickets/{ticket_id}/images/{direction}")
def ticket_image(ticket_id: str, direction: str, _: AuthUser = Depends(require_roles(*ALL_ROLES))):
    if direction not in {"entry", "exit"}:
        raise HTTPException(status_code=404, detail="Image not found")
    ticket = fetch_ticket_detail(ticket_id)
    raw = ticket.get(direction + "_image_path") if ticket else None
    try:
        if not raw:
            raise ValueError("missing")
        root = Path(UPLOAD_DIR).resolve(strict=True)
        path = Path(raw).resolve(strict=True)
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}
        ):
            raise ValueError("invalid")
        from PIL import Image

        with Image.open(path) as image:
            media = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(
                image.format
            )
            image.verify()
        if media is None:
            raise ValueError("unsupported")
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(status_code=404, detail="Image not found") from None
    return FileResponse(
        path,
        media_type=media,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/events", dependencies=[Depends(require_read_access)])
def events(
    ticket_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    response = ok(read_queries.events_page(ticket_id, limit, offset))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get("/audit-logs")
def audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: AuthUser = Depends(require_roles("admin")),
):
    response = ok(read_queries.audit_page(limit, offset))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get(
    "/devices/status", response_model=ListResponse, dependencies=[Depends(require_read_access)]
)
def devices_status():
    camera = CameraSnapshotSimulator()
    config = load_device_config()
    statuses = [
        camera.status().__dict__,
        barrier_simulator.status().__dict__,
        mqtt_simulator.status().__dict__,
    ]
    statuses.append(
        {
            "device_id": "device-config",
            "device_type": "configuration",
            "state": config.mode,
            "detail": "missing=" + ",".join(config.missing)
            if config.missing
            else "real device endpoints configured",
        }
    )
    return ok({"items": statuses, "count": len(statuses)})


@app.post("/devices/barrier/open")
def open_barrier(
    request: Request,
    lane_id: str = Form(default="lane-1"),
    reason: str = Form(default="operator-approved"),
    user: AuthUser = Depends(require_roles(*WRITE_ROLES)),
):
    enforce_write_rate_limit(request, user)
    command = barrier_simulator.open_barrier(lane_id, reason, actor_username=user.username)
    return ok({"command": command.__dict__})


def _audit_admin_action(actor: AuthUser, action: str, username: str, **details):
    try:
        append_audit_log(
            actor.username,
            actor.role,
            action,
            target_type="user",
            target_id=username,
            details_json=json.dumps(details, ensure_ascii=False) if details else None,
        )
    except Exception as exc:
        logger.warning("append_audit_log failed for %s: %s", action, exc)


@app.get("/admin/users", response_model=AdminUsersResponse)
def admin_users(_: AuthUser = Depends(require_roles("admin"))):
    df = list_app_users()
    return ok({"items": df.to_dict(orient="records"), "count": len(df)})


@app.post("/admin/users")
def admin_create_user(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(default="viewer"),
    actor: AuthUser = Depends(require_roles("admin")),
):
    if role not in ALL_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    success, message = register_streamlit_user(username, password, role=role)  # type: ignore[arg-type]
    if not success:
        raise HTTPException(status_code=400, detail=message)
    _audit_admin_action(actor, "admin.user.create", username, role=role)
    return ok({"message": message}, status_code=201)


@app.patch("/admin/users/{username}/role")
def admin_update_user_role(
    username: str, role: str = Form(...), actor: AuthUser = Depends(require_roles("admin"))
):
    if role not in ALL_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if username.strip() == actor.username and role != "admin":
        raise HTTPException(
            status_code=400,
            detail="Không thể tự hạ quyền tài khoản đang đăng nhập. Nhờ quản trị viên khác thay đổi vai trò.",
        )
    if not update_app_user_role(username, role):
        raise HTTPException(status_code=404, detail="User not found")
    _audit_admin_action(actor, "admin.user.role", username, new_role=role)
    return ok({"message": "Role updated"})


@app.patch("/admin/users/{username}/active")
def admin_update_user_active(
    username: str, is_active: bool = Form(...), actor: AuthUser = Depends(require_roles("admin"))
):
    if username == actor.username and not is_active:
        raise HTTPException(status_code=400, detail="Cannot disable current user")
    if not update_app_user_active(username, is_active):
        raise HTTPException(status_code=404, detail="User not found")
    _audit_admin_action(actor, "admin.user.active", username, is_active=bool(is_active))
    return ok({"message": "Active state updated"})


@app.delete("/admin/users/{username}")
def admin_delete_user(username: str, actor: AuthUser = Depends(require_roles("admin"))):
    if username == actor.username:
        raise HTTPException(status_code=400, detail="Cannot delete current user")
    if not delete_app_user(username):
        raise HTTPException(status_code=404, detail="User not found")
    _audit_admin_action(actor, "admin.user.delete", username)
    return ok({"message": "User deleted"})


@app.get(
    "/operations/summary",
    response_model=OperationSummaryResponse,
    dependencies=[Depends(require_read_access)],
)
def operations_summary():
    kpis = read_queries.parking_kpis()
    health_code, health_tone = classify_operational_health(kpis)
    return ok({"kpis": kpis.__dict__, "health": {"code": health_code, "tone": health_tone}})


@app.post("/ocr")
def ocr_image(file: UploadFile = File(...), access=Depends(require_read_access)):
    validate_upload(file)
    saved_path = save_uploaded_file(file, "api_ocr")
    processed = process_plate_image(saved_path)
    payload = {"ocr": _sanitize_ocr_payload(processed.ocr)}
    if access is not None:
        token = scan_cache.remember(saved_path, access.username, processed)
        if token:
            payload["scan_token"] = token
            payload["scan_ttl_seconds"] = scan_cache.TTL_SECONDS
    if API_EXPOSE_INTERNAL_PATHS:
        payload["image_path"] = saved_path
    return ok(payload)


def _confirmation_scan(path, plate_text, token, manual_only, confirmed, user):
    if token and manual_only:
        raise HTTPException(
            status_code=400, detail="Chọn quét ảnh hoặc xác nhận nhập tay, không dùng đồng thời."
        )
    if token:
        processed = scan_cache.reuse(token, path, user.username)
        if processed is None:
            raise HTTPException(
                status_code=409,
                detail="Kết quả quét đã hết hạn hoặc ảnh đã đổi. Bấm Quét lại trước khi xác nhận.",
            )
        return processed
    if manual_only:
        if not confirmed or not (plate_text or "").strip():
            raise HTTPException(
                status_code=400, detail="Nhập biển số và đối chiếu ảnh trước khi xác nhận thủ công."
            )
        return ProcessedPlate(
            ocr={
                "text": plate_text.strip(),
                "confidence": None,
                "ocr_engine": "manual",
                "review_required": False,
            },
            plate_text=plate_text.strip(),
        )
    return process_plate_image(path)


@app.post("/vehicle/entry")
def vehicle_entry(
    request: Request,
    file: UploadFile = File(...),
    plate_text: str | None = Form(default=None),
    ai_review_confirmed: bool = Form(default=False),
    vehicle_type: str = Form(default="motorcycle", pattern="^(motorcycle|car)$"),
    scan_token: str | None = Form(default=None, max_length=128),
    manual_only: bool = Form(default=False),
    user: AuthUser = Depends(require_roles(*WRITE_ROLES)),
):
    enforce_write_rate_limit(request, user)
    validate_upload(file)
    saved_path = save_uploaded_file(file, "api_entry")
    processed = _confirmation_scan(
        saved_path, plate_text, scan_token, manual_only, ai_review_confirmed, user
    )
    final_plate = (plate_text or processed.plate_text).strip()
    manual_override = ai_review_confirmed or bool(
        plate_text
        and plate_text.strip()
        and plate_text.strip() != (processed.plate_text or "").strip()
    )
    result = confirm_vehicle_entry(
        final_plate,
        vehicle_type=vehicle_type,
        image_path=saved_path,
        detected_path=processed.ocr.get("annotated_path"),
        ocr_confidence=processed.ocr.get("confidence"),
        ocr_engine=processed.ocr.get("ocr_engine"),
        ocr_text=processed.plate_text,
        manual_override=manual_override,
        ocr_review_required=bool(processed.ocr.get("review_required")),
        actor=user,
    )
    if not result.get("success"):
        return map_business_failure(result, resource="ticket")
    return ok({"ocr": _sanitize_ocr_payload(processed.ocr), "result": result}, status_code=201)


@app.post("/vehicle/exit")
def vehicle_exit(
    request: Request,
    ticket_id: str = Form(...),
    file: UploadFile = File(...),
    plate_text: str | None = Form(default=None),
    ai_review_confirmed: bool = Form(default=False),
    scan_token: str | None = Form(default=None, max_length=128),
    manual_only: bool = Form(default=False),
    user: AuthUser = Depends(require_roles(*WRITE_ROLES)),
):
    enforce_write_rate_limit(request, user)
    validate_upload(file)
    saved_path = save_uploaded_file(file, "api_exit")
    processed = _confirmation_scan(
        saved_path, plate_text, scan_token, manual_only, ai_review_confirmed, user
    )
    final_plate = (plate_text or processed.plate_text).strip()
    manual_override = ai_review_confirmed or bool(
        plate_text
        and plate_text.strip()
        and plate_text.strip() != (processed.plate_text or "").strip()
    )
    result = confirm_vehicle_exit(
        ticket_id,
        final_plate,
        image_path=saved_path,
        detected_path=processed.ocr.get("annotated_path"),
        ocr_confidence=processed.ocr.get("confidence"),
        ocr_engine=processed.ocr.get("ocr_engine"),
        ocr_text=processed.plate_text,
        manual_override=manual_override,
        ocr_review_required=bool(processed.ocr.get("review_required")),
        actor=user,
    )
    if not result.get("success"):
        return map_business_failure(result, resource="ticket")
    return ok({"ocr": _sanitize_ocr_payload(processed.ocr), "result": result})


@app.post("/tickets/{ticket_id}/resolve")
def resolve_ticket(
    request: Request,
    ticket_id: str,
    resolution: str = Form(...),
    note: str | None = Form(default=None),
    user: AuthUser = Depends(require_roles(*WRITE_ROLES)),
):
    enforce_write_rate_limit(request, user)
    result = resolve_review_ticket(ticket_id, resolution, actor=user, note=note)
    if not result.get("success"):
        return map_business_failure(result, resource="ticket")
    return ok({"result": result})


@app.post("/tickets/{ticket_id}/cancel")
def cancel_ticket_endpoint(
    request: Request,
    ticket_id: str,
    reason: str = Form(...),
    user: AuthUser = Depends(require_roles("admin")),
):
    enforce_write_rate_limit(request, user)
    result = cancel_ticket(ticket_id, actor=user, reason=reason)
    if not result.get("success"):
        return map_business_failure(result, resource="ticket")
    return ok({"result": result})


@app.get("/pricing")
def get_pricing(_: AuthUser = Depends(require_roles("admin"))):
    return ok({"items": billing.get_tariffs()})


@app.get("/payments")
def list_payments(
    q: str = Query(default="", max_length=100),
    payment_state: str = Query(default="", pattern="^(paid|unpaid|unconfigured)?$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: AuthUser = Depends(require_roles(*ALL_ROLES)),
):
    response = ok(billing.payment_overview(q, payment_state, limit, offset))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.post("/payments/qr-preview")
def quick_payment_qr(
    payload: PaymentQRInput, request: Request, user: AuthUser = Depends(require_roles(*WRITE_ROLES))
):
    enforce_write_rate_limit(request, user)
    response = ok({"qr": mb_payments.manual_qr_preview(payload.amount, user)})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.post("/payments/qr-requests")
def create_auto_qr(
    payload: AutoQRInput, request: Request, user: AuthUser = Depends(require_roles(*WRITE_ROLES))
):
    enforce_write_rate_limit(request, user)
    qr = mb_requests.create_request(payload.amount, payload.idempotency_key, user)
    mb_monitor.monitor.wake()
    return ok({"qr": qr, "monitor": mb_monitor.monitor.status()})


@app.get("/payments/qr-requests")
def list_auto_qr(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default="", max_length=100),
    status: str = Query(default="", pattern="^(pending|paid|expired|cancelled)?$"),
    _: AuthUser = Depends(require_roles(*ALL_ROLES)),
):
    response = ok(
        {
            **mb_requests.list_requests(limit, offset, q, status),
            "monitor": mb_monitor.monitor.status(),
        }
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get("/payments/qr-requests/{code}")
def get_auto_qr(code: str, _: AuthUser = Depends(require_roles(*ALL_ROLES))):
    response = ok({"qr": mb_requests.get_request(code), "monitor": mb_monitor.monitor.status()})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.post("/payments/qr-requests/{code}/cancel")
def cancel_auto_qr(
    code: str, request: Request, user: AuthUser = Depends(require_roles(*WRITE_ROLES))
):
    enforce_write_rate_limit(request, user)
    return ok({"qr": mb_requests.cancel_request(code, user)})


@app.put("/pricing/{vehicle_type}")
def update_pricing(
    vehicle_type: str,
    payload: TariffInput,
    request: Request,
    user: AuthUser = Depends(require_roles("admin")),
):
    enforce_write_rate_limit(request, user)
    return ok({"tariff": billing.set_tariff(vehicle_type, payload.model_dump(), user)})


@app.post("/tickets/lookup-qr")
def find_ticket_qr(
    payload: str = Form(..., max_length=128), _: AuthUser = Depends(require_roles(*ALL_ROLES))
):
    return ok({"ticket": billing.lookup_qr(payload)})


@app.get("/tickets/{ticket_id}/pass")
def ticket_qr_pass(ticket_id: str, _: AuthUser = Depends(require_roles(*ALL_ROLES))):
    response = ok(billing.ticket_pass(ticket_id))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get("/tickets/{ticket_id}/finance")
def ticket_finance(ticket_id: str, _: AuthUser = Depends(require_roles(*ALL_ROLES))):
    return ok({"finance": billing.get_finance(ticket_id)})


@app.post("/tickets/{ticket_id}/payment")
def pay_ticket(
    ticket_id: str,
    payload: PaymentInput,
    request: Request,
    user: AuthUser = Depends(require_roles(*WRITE_ROLES)),
):
    enforce_write_rate_limit(request, user)
    return ok(billing.record_payment(ticket_id, **payload.model_dump(), actor=user))


@app.get("/mb/status")
def mb_status(_: AuthUser = Depends(require_roles("admin"))):
    config = mb_payments.settings()
    try:
        worker = call_worker("/status", timeout=3)
    except MBConnectionError as error:
        worker = {"state": "unavailable", "message": str(error), "accounts": []}
    response = ok({"settings": config, "connection": worker})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.post("/mb/connect")
def mb_connect(
    request: Request,
    payload: MBConnectInput | None = Body(default=None),
    user: AuthUser = Depends(require_roles("admin")),
):
    enforce_write_rate_limit(request, user)
    return ok(
        {
            "connection": call_worker(
                "/connect", {"captcha_mode": payload.captcha_mode if payload else "manual"}
            )
        }
    )


@app.post("/mb/disconnect")
def mb_disconnect(request: Request, user: AuthUser = Depends(require_roles("admin"))):
    enforce_write_rate_limit(request, user)
    return ok({"connection": call_worker("/disconnect", {})})


@app.post("/mb/captcha")
def mb_captcha(
    payload: MBCaptchaInput, request: Request, user: AuthUser = Depends(require_roles("admin"))
):
    enforce_write_rate_limit(request, user)
    call_worker("/captcha", payload.model_dump())
    return ok({})


@app.put("/mb/settings")
def mb_settings(
    payload: MBSettingsInput, request: Request, user: AuthUser = Depends(require_roles("admin"))
):
    enforce_write_rate_limit(request, user)
    return ok({"settings": mb_payments.save_settings(**payload.model_dump(), actor=user)})


@app.post("/tickets/{ticket_id}/mb-order")
def mb_create_order(
    ticket_id: str, request: Request, user: AuthUser = Depends(require_roles(*WRITE_ROLES))
):
    enforce_write_rate_limit(request, user)
    order = mb_payments.create_order(ticket_id, user)
    mb_monitor.monitor.wake()
    return ok({"order": order})


@app.get("/tickets/{ticket_id}/mb-order")
def mb_get_order(ticket_id: str, _: AuthUser = Depends(require_roles(*ALL_ROLES))):
    response = ok(
        {"order": mb_payments.get_order(ticket_id), "monitor": mb_monitor.monitor.status()}
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.post("/tickets/{ticket_id}/mb-order/check")
def mb_check_order(
    ticket_id: str, request: Request, user: AuthUser = Depends(require_roles(*WRITE_ROLES))
):
    enforce_write_rate_limit(request, user)
    return ok(mb_payments.reconcile(ticket_id, user))


@app.post("/tickets/{ticket_id}/mb-order/cancel")
def mb_cancel_order(
    ticket_id: str, request: Request, user: AuthUser = Depends(require_roles(*WRITE_ROLES))
):
    enforce_write_rate_limit(request, user)
    return ok({"order": mb_payments.cancel_order(ticket_id, user)})


WEB_DIR = Path(__file__).resolve().parents[1] / "frontend" / "web"


@app.get("/", include_in_schema=False)
def web_index():
    return index_response(WEB_DIR, offline_demo=os.getenv("ITS_DEMO_OFFLINE") == "true")


app.mount(
    "/static",
    GZipMiddleware(StaticFiles(directory=str(WEB_DIR)), minimum_size=1024, compresslevel=5),
    name="static",
)
