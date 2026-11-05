from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TariffInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)
    enabled: bool
    mode: Literal["hourly", "flat"]
    flat_amount: int = Field(ge=0, le=10000000)
    first_minutes: int = Field(ge=1, le=1440)
    first_amount: int = Field(ge=0, le=10000000)
    next_minutes: int = Field(ge=1, le=1440)
    next_amount: int = Field(ge=0, le=10000000)
    daily_cap: int = Field(ge=0, le=10000000)
    grace_minutes: int = Field(ge=0, le=1440)


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    amount: int = Field(ge=0)
    quote_id: str = Field(min_length=64, max_length=64)
    method: Literal["cash", "transfer"]
    received_amount: int = Field(ge=0, le=1000000000)


class PaymentQRInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    amount: int = Field(ge=1, le=1000000000)


class AutoQRInput(PaymentQRInput):
    idempotency_key: str = Field(min_length=16, max_length=80, pattern="^[A-Za-z0-9_-]+$")


class MBSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    account_no: str = Field(max_length=24, pattern="^[0-9]*$")
    enabled: bool
    revision: int = Field(ge=1)


class MBCaptchaInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=32, max_length=32, pattern="^[a-f0-9]+$")
    text: str = Field(min_length=4, max_length=12, pattern="^[A-Za-z0-9]+$")


class MBConnectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    captcha_mode: Literal["manual", "ecaptcha", "local"] = "manual"


class ApiError(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel):
    ok: bool = True


class ErrorResponse(BaseModel):
    ok: bool = False
    error: ApiError


class UserIdentity(BaseModel):
    username: str
    role: str


class AuthResponse(ApiResponse):
    access_token: str
    token_type: str = "bearer"
    user: UserIdentity


class ListResponse(ApiResponse):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    total: int | None = None
    limit: int | None = None
    offset: int | None = None


class HealthResponse(BaseModel):
    status: str
    schema_version: int


class ReadinessCheck(BaseModel):
    name: str
    status: str
    detail: str


class ReadinessResponse(ApiResponse):
    status: str
    checks: list[ReadinessCheck]


class ScorecardItem(BaseModel):
    criterion: str
    score: float | None = None
    status: str
    evidence: str


class ScorecardResponse(ApiResponse):
    overall_score: float | None = None
    items: list[ScorecardItem]


class OperationSummaryResponse(ApiResponse):
    kpis: dict[str, Any]
    health: dict[str, str]


class DeviceStatusResponse(ListResponse):
    pass


class ParkingLogRecord(BaseModel):
    ticket_id: str | None = None
    plate_entry: str | None = None
    plate_exit: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None
    status: str | None = None
    match_result: str | None = None
    review_required: int | None = None
    review_reason: str | None = None


class ParkingEventRecord(BaseModel):
    id: int | None = None
    ticket_id: str | None = None
    event_type: str | None = None
    actor_username: str | None = None
    actor_role: str | None = None
    plate_text: str | None = None
    confidence: float | None = None
    source: str | None = None
    created_at: str | None = None


class AuditLogRecord(BaseModel):
    id: int | None = None
    actor_username: str | None = None
    actor_role: str | None = None
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    created_at: str | None = None


class TicketDetailResponse(ApiResponse):
    ticket: dict[str, Any]
    events: list[dict[str, Any]] = Field(default_factory=list)


class UserRecord(BaseModel):
    username: str
    role: str
    is_active: int | None = None
    created_at: str | None = None
    failed_login_count: int | None = None
    locked_until: str | None = None
    last_login_at: str | None = None


class AdminUsersResponse(ApiResponse):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
