"""Authorized provider discovery, health probes and persistent circuit breakers.

Only explicitly configured/owner-approved routes are eligible. The module
never searches for credentials, copies browser sessions, evades quotas or
sends inference traffic as part of a health probe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


PROFILES = ("fast", "balanced", "reasoning")
PROTOCOL = "openai_chat_completions"
_ALLOWED_DATA_CLASSES = {"public", "internal", "confidential", "restricted"}
_SAFE_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")
_INTERNAL_HTTP_HOSTS = {"localhost", "127.0.0.1", "::1", "freellm", "ollama", "litellm"}


class ProviderRouteError(RuntimeError):
    """Invalid provider route or unusable provider response."""


@dataclass(frozen=True)
class ProviderRoute:
    route_id: str
    provider_id: str
    profile: str
    base_url: str
    model: str
    api_key: str = field(default="", repr=False, compare=False)
    protocol: str = PROTOCOL
    price_class: str = "unknown"
    input_usd_per_1m: float | None = None
    output_usd_per_1m: float | None = None
    verified_free: bool = False
    accepted_data_classes: tuple[str, ...] = ("public",)
    priority: int = 100
    is_primary: bool = False
    anonymous: bool = False

    def safe_record(self) -> dict[str, Any]:
        """A route status record that never includes credentials or secret paths."""
        return {
            "route_id": self.route_id,
            "provider_id": self.provider_id,
            "profile": self.profile,
            "model": self.model,
            "protocol": self.protocol,
            "price_class": self.price_class,
            "verified_free": self.verified_free,
            "accepted_data_classes": list(self.accepted_data_classes),
            "priority": self.priority,
            "is_primary": self.is_primary,
        }


def _bool(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"})


def _rate(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ProviderRouteError("Provider price rate must be numeric")
    if not math.isfinite(number) or number < 0:
        raise ProviderRouteError("Provider price rate must be finite and >= 0")
    return number


def _base_url(value: Any, *, allow_private_http: bool = False) -> str:
    url = str(value or "").strip().rstrip("/")
    parts = urlsplit(url)
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ProviderRouteError("Provider base URL is invalid")
    if parts.scheme == "https":
        return url
    if parts.scheme == "http" and (allow_private_http or parts.hostname.lower() in _INTERNAL_HTTP_HOSTS):
        return url
    raise ProviderRouteError("Provider routes must use HTTPS (or an explicitly private local HTTP endpoint)")


def _read_key(
    env: dict[str, str],
    *,
    direct_name: str = "",
    file_name: str = "",
    secret_reader: Callable[[str], str] | None = None,
) -> str:
    if direct_name:
        if not _SAFE_ENV_NAME.fullmatch(direct_name):
            raise ProviderRouteError("Provider key environment reference is invalid")
        value = str(env.get(direct_name, "")).strip()
        if value:
            return value
    if file_name:
        if not _SAFE_ENV_NAME.fullmatch(file_name):
            raise ProviderRouteError("Provider key-file environment reference is invalid")
        path = str(env.get(file_name, "")).strip()
        if path and secret_reader:
            return str(secret_reader(path) or "").strip()
    return ""


def load_provider_routes(
    profile: str,
    *,
    environ: dict[str, str] | None = None,
    secret_reader: Callable[[str], str] | None = None,
    anonymous_detector: Callable[[str], bool] | None = None,
) -> list[ProviderRoute]:
    """Resolve the current profile plus owner-approved fallback routes.

    Fallbacks are configured through QUDRON_PROVIDER_ROUTES_JSON. Each route
    must explicitly set enabled=true and owner_approved=true. Secrets are
    referenced by environment-variable name; raw secret values are never
    accepted in JSON or returned in route status.
    """
    profile = str(profile).lower()
    if profile not in PROFILES:
        profile = "balanced"
    env = dict(os.environ if environ is None else environ)
    prefix = {"fast": "LLM_FAST", "balanced": "LLM_BALANCED", "reasoning": "LLM_REASONING"}[profile]
    base = str(env.get(f"{prefix}_BASE_URL") or env.get("LLM_BASE_URL") or "").strip()
    model = str(env.get(f"{prefix}_MODEL") or env.get("LLM_MODEL") or "").strip()
    key_name = f"{prefix}_API_KEY"
    key_file_name = f"{prefix}_API_KEY_FILE"
    key = str(env.get(key_name) or env.get("LLM_API_KEY") or "").strip()
    if not key:
        key = _read_key(
            env,
            file_name=key_file_name if env.get(key_file_name) else "LLM_API_KEY_FILE",
            secret_reader=secret_reader,
        )
    default_input = env.get(f"{prefix}_INPUT_USD_PER_1M") or env.get("LLM_INPUT_USD_PER_1M")
    default_output = env.get(f"{prefix}_OUTPUT_USD_PER_1M") or env.get("LLM_OUTPUT_USD_PER_1M")
    routes: list[ProviderRoute] = []

    if base and model:
        try:
            safe_base = _base_url(base, allow_private_http=True)
            host = (urlsplit(safe_base).hostname or "configured").lower()
            anonymous = bool(anonymous_detector and anonymous_detector(safe_base))
            route_id = f"primary:{profile}:{host}:{model}"[:240]
            configured_classes = tuple(
                item.strip().lower()
                for item in str(env.get("QUDRON_PROVIDER_DATA_CLASSES", "public,internal")).split(",")
                if item.strip()
            )
            if not configured_classes or not set(configured_classes).issubset(_ALLOWED_DATA_CLASSES):
                configured_classes = ("public", "internal")
            accepted = ("public",) if anonymous else configured_classes
            routes.append(ProviderRoute(
                route_id=route_id,
                provider_id=host,
                profile=profile,
                base_url=safe_base,
                model=model,
                api_key=key,
                price_class="free" if anonymous else "unknown",
                input_usd_per_1m=0.0 if anonymous else _rate(default_input),
                output_usd_per_1m=0.0 if anonymous else _rate(default_output),
                verified_free=anonymous,
                accepted_data_classes=accepted,
                priority=0,
                is_primary=True,
                anonymous=anonymous,
            ))
        except ProviderRouteError:
            # A malformed existing profile is not allowed to bypass route checks.
            pass

    raw_routes = env.get("QUDRON_PROVIDER_ROUTES_JSON", "").strip()
    if raw_routes:
        if len(raw_routes) > 32_000:
            raise ProviderRouteError("QUDRON_PROVIDER_ROUTES_JSON exceeds 32 KB")
        try:
            configured = json.loads(raw_routes)
        except json.JSONDecodeError as exc:
            raise ProviderRouteError("QUDRON_PROVIDER_ROUTES_JSON is not valid JSON") from exc
        if not isinstance(configured, list) or len(configured) > 24:
            raise ProviderRouteError("Provider fallback configuration must be a list of at most 24 routes")
        for item in configured:
            if not isinstance(item, dict):
                continue
            if not _bool(item.get("enabled")) or not _bool(item.get("owner_approved")):
                continue
            route_profile = str(item.get("profile", "all")).lower()
            if route_profile not in {"all", profile}:
                continue
            protocol = str(item.get("protocol", PROTOCOL)).lower()
            if protocol != PROTOCOL:
                # Unsupported protocols are listed in the model catalogue, but
                # cannot enter this Chat Completions execution chain yet.
                continue
            route_id = str(item.get("route_id", "")).strip()[:120]
            provider_id = str(item.get("provider_id", "")).strip()[:120]
            route_model = str(item.get("model", "")).strip()[:160]
            if not route_id or not provider_id or not route_model:
                continue
            base_url = _base_url(
                item.get("base_url"),
                allow_private_http=_bool(item.get("allow_private_http")),
            )
            price_class = str(item.get("price_class", "")).lower()
            if price_class not in {"free", "paid"}:
                continue
            verified_free = _bool(item.get("verified_free"))
            if price_class == "free" and not verified_free:
                # Free means a real, owner-verified free entitlement, not a guess.
                continue
            input_rate = _rate(item.get("input_usd_per_1m"))
            output_rate = _rate(item.get("output_usd_per_1m"))
            if price_class == "paid" and (input_rate is None or output_rate is None):
                continue
            if price_class == "paid" and (
                input_rate == 0 or output_rate == 0
            ) and not _bool(env.get("QUDRON_ALLOW_ZERO_RATE_PROVIDER")):
                continue
            data_classes = item.get("accepted_data_classes", ["public"])
            if not isinstance(data_classes, list) or not data_classes:
                continue
            normalized_classes = tuple(sorted({str(v).lower() for v in data_classes}))
            if not set(normalized_classes).issubset(_ALLOWED_DATA_CLASSES):
                continue
            api_key = _read_key(
                env,
                direct_name=str(item.get("api_key_env", "")),
                file_name=str(item.get("api_key_file_env", "")),
                secret_reader=secret_reader,
            )
            if _bool(item.get("requires_api_key", True)) and not api_key:
                continue
            routes.append(ProviderRoute(
                route_id=route_id,
                provider_id=provider_id,
                profile=profile,
                base_url=base_url,
                model=route_model,
                api_key=api_key,
                protocol=protocol,
                price_class=price_class,
                input_usd_per_1m=input_rate,
                output_usd_per_1m=output_rate,
                verified_free=verified_free,
                accepted_data_classes=normalized_classes,
                priority=max(1, min(10_000, int(item.get("priority", 100)))),
                is_primary=False,
                anonymous=False,
            ))

    seen: set[tuple[str, str, str]] = set()
    unique: list[ProviderRoute] = []
    for route in sorted(routes, key=lambda r: (0 if r.is_primary else 1, r.priority, r.provider_id, r.route_id)):
        key = (route.base_url, route.model, route.profile)
        if key in seen:
            continue
        seen.add(key)
        unique.append(route)
    return unique


def models_endpoint(route: ProviderRoute) -> str:
    """Resolve the read-only model catalogue endpoint for OpenAI-compatible APIs."""
    return route.base_url.rstrip("/") + "/models"


class ProviderHealthStore:
    """Persistent provider health/circuit-breaker state shared by worker restarts."""

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS provider_route_health (
                    route_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model_available INTEGER NOT NULL DEFAULT 0,
                    last_probe REAL,
                    last_success REAL,
                    latency_ms REAL,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    open_until REAL NOT NULL DEFAULT 0,
                    last_error_class TEXT,
                    updated_at REAL NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=20000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def get(self, route: ProviderRoute) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM provider_route_health WHERE route_id=?",
                (route.route_id,),
            ).fetchone()
        return dict(row) if row else None

    def record_probe(
        self, route: ProviderRoute, *, ok: bool, model_available: bool,
        latency_ms: float | None, error_class: str | None = None,
        now: float | None = None,
    ) -> None:
        stamp = time.time() if now is None else now
        previous = self.get(route) or {}
        failures = 0 if ok else int(previous.get("consecutive_failures", 0)) + 1
        cooldown = 0.0
        if not ok:
            if error_class in {"http_401", "http_403"}:
                cooldown = 1800.0
            elif error_class == "http_429":
                cooldown = 120.0
            else:
                cooldown = min(600.0, 15.0 * (2 ** min(failures - 1, 5)))
        status = "healthy" if ok and model_available else (
            "model_not_advertised" if ok else "circuit_open"
        )
        with self._connect() as db:
            db.execute(
                """INSERT INTO provider_route_health
                   (route_id,provider_id,profile,model,status,model_available,
                    last_probe,last_success,latency_ms,consecutive_failures,
                    open_until,last_error_class,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(route_id) DO UPDATE SET
                     provider_id=excluded.provider_id,profile=excluded.profile,
                     model=excluded.model,status=excluded.status,
                     model_available=excluded.model_available,last_probe=excluded.last_probe,
                     last_success=COALESCE(excluded.last_success,provider_route_health.last_success),
                     latency_ms=excluded.latency_ms,
                     consecutive_failures=excluded.consecutive_failures,
                     open_until=excluded.open_until,last_error_class=excluded.last_error_class,
                     updated_at=excluded.updated_at""",
                (
                    route.route_id, route.provider_id, route.profile, route.model,
                    status, 1 if (ok and model_available) else 0, stamp,
                    stamp if ok and model_available else None, latency_ms, failures,
                    stamp + cooldown, error_class, stamp,
                ),
            )

    def mark_call_success(self, route: ProviderRoute, *, now: float | None = None) -> None:
        stamp = time.time() if now is None else now
        with self._connect() as db:
            db.execute(
                """INSERT INTO provider_route_health
                   (route_id,provider_id,profile,model,status,model_available,
                    last_probe,last_success,latency_ms,consecutive_failures,
                    open_until,last_error_class,updated_at)
                   VALUES(?,?,?,?, 'healthy',1,NULL,?,NULL,0,0,NULL,?)
                   ON CONFLICT(route_id) DO UPDATE SET
                     status='healthy',model_available=1,last_success=excluded.last_success,
                     consecutive_failures=0,open_until=0,last_error_class=NULL,updated_at=excluded.updated_at""",
                (route.route_id, route.provider_id, route.profile, route.model, stamp, stamp),
            )

    def mark_call_failure(
        self, route: ProviderRoute, error_class: str, *, now: float | None = None
    ) -> None:
        self.record_probe(
            route, ok=False, model_available=False, latency_ms=None,
            error_class=error_class, now=now,
        )

    def circuit_open(self, route: ProviderRoute, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        record = self.get(route)
        return bool(record and float(record.get("open_until") or 0) > current)

    def probe_due(
        self, route: ProviderRoute, *, interval_seconds: int = 300,
        now: float | None = None,
    ) -> bool:
        current = time.time() if now is None else now
        record = self.get(route)
        if record is None:
            return True
        if float(record.get("open_until") or 0) > current:
            return False
        last_probe = float(record.get("last_probe") or 0)
        return current - last_probe >= max(60, interval_seconds)

    def snapshot(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT route_id,provider_id,profile,model,status,model_available,
                          last_probe,last_success,latency_ms,consecutive_failures,
                          open_until,last_error_class
                   FROM provider_route_health ORDER BY updated_at DESC LIMIT ?""",
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [dict(row) for row in rows]


def probe_route(
    route: ProviderRoute,
    store: ProviderHealthStore,
    *,
    timeout_seconds: int = 5,
    opener: Callable[..., Any] = urlopen,
    now: float | None = None,
) -> dict[str, Any]:
    """Perform one small read-only /models request; never runs model inference."""
    started = time.monotonic()
    request = Request(
        models_endpoint(route),
        headers={
            "Accept": "application/json",
            **({"Authorization": f"Bearer {route.api_key}"} if route.api_key else {}),
        },
        method="GET",
    )
    error_class: str | None = None
    model_available = False
    try:
        with opener(request, timeout=max(2, min(15, int(timeout_seconds)))) as response:
            status = int(getattr(response, "status", 200))
            if status < 200 or status >= 300:
                error_class = f"http_{status}"
            else:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    error_class = "catalogue_too_large"
                else:
                    payload = json.loads(raw.decode("utf-8"))
                    entries = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else []
                    if not isinstance(entries, list):
                        error_class = "catalogue_schema_invalid"
                    else:
                        model_available = any(
                            isinstance(item, dict) and str(item.get("id", item.get("name", ""))) == route.model
                            for item in entries
                        )
                        if not model_available:
                            error_class = "model_not_advertised"
    except HTTPError as exc:
        error_class = f"http_{int(exc.code)}"
    except (URLError, TimeoutError):
        error_class = "network_unavailable"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        error_class = "catalogue_response_invalid"
    latency_ms = max(0.0, (time.monotonic() - started) * 1000.0)
    ok = error_class is None and model_available
    store.record_probe(
        route, ok=ok, model_available=model_available, latency_ms=latency_ms,
        error_class=error_class, now=now,
    )
    return {
        "route_id": route.route_id,
        "provider_id": route.provider_id,
        "profile": route.profile,
        "model": route.model,
        "status": "healthy" if ok else (error_class or "unavailable"),
        "model_available": model_available,
        "latency_ms": round(latency_ms, 2),
    }


def route_allowed_for_data(route: ProviderRoute, data_class: str) -> bool:
    return str(data_class).lower() in route.accepted_data_classes


def eligible_routes(
    routes: list[ProviderRoute],
    store: ProviderHealthStore,
    *,
    data_class: str = "public",
    now: float | None = None,
) -> list[ProviderRoute]:
    """Keep approved in-scope routes, skipping routes whose breaker is open."""
    current = time.time() if now is None else now
    return [
        route for route in routes
        if route_allowed_for_data(route, data_class) and not store.circuit_open(route, now=current)
    ]


def probe_due_routes(
    routes: list[ProviderRoute],
    store: ProviderHealthStore,
    *,
    interval_seconds: int = 300,
    timeout_seconds: int = 5,
    now: float | None = None,
) -> list[dict[str, Any]]:
    reports = []
    for route in routes:
        if store.probe_due(route, interval_seconds=interval_seconds, now=now):
            reports.append(probe_route(route, store, timeout_seconds=timeout_seconds, now=now))
    return reports


def route_health_snapshot(database_path: str | Path, *, limit: int = 100) -> list[dict[str, Any]]:
    return ProviderHealthStore(database_path).snapshot(limit=limit)
