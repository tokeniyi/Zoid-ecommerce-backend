"""Phase 16 — the composition root wires every router and every seat.

Two promises, checked without touching a database:

* **Mounting is complete.** ``create_app()`` assembles the whole surface — one
  router per domain plus the system health probe — and the application's schema
  can be generated, which only works if every route registered with
  importable request/response models.
* **Provider selection lives only at the root and is driven by configuration.**
  The container chooses the payment, email and storage implementations by the
  names in settings; nothing under ``app/domains`` or ``app/security`` reaches a
  factory or names a provider itself. Business logic is handed a contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.infrastructure.container import get_file_storage
from app.integrations.storage.contract import AbstractFileStorage
from app.integrations.storage.factory import build_file_storage, supported_providers
from app.main import app, create_app
from app.shared.exceptions import ProviderNotConfiguredError

API = get_settings().api_v1_prefix
_APP = Path(__file__).resolve().parents[2] / "app"

#: One representative operation per mounted router, plus the system probe. If a
#: domain router failed to register its anchor disappears and this fails.
ANCHOR_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("POST", f"{API}/auth/signup"),
        ("GET", f"{API}/auth/me"),
        ("GET", f"{API}/users/me"),
        ("GET", f"{API}/products"),
        ("GET", f"{API}/categories"),
        ("GET", f"{API}/cart"),
        ("GET", f"{API}/wishlist"),
        ("POST", f"{API}/orders"),
        ("POST", f"{API}/payments/initiate"),
        ("GET", f"{API}/admin/dashboard"),
        ("POST", f"{API}/admin/products"),
    }
)

#: The top-level segment each feature router contributes under the API prefix.
MOUNTED_DOMAINS: frozenset[str] = frozenset(
    {
        "admin",
        "auth",
        "cart",
        "categories",
        "orders",
        "payments",
        "products",
        "users",
        "wishlist",
    }
)

_NON_OPERATIONS = frozenset({"parameters", "servers", "summary", "description", "trace"})

#: The provider-selection callables the composition root owns.
_SELECTORS = frozenset(
    {
        "build_payment_gateway",
        "build_webhook_adapter",
        "build_email_sender",
        "build_file_storage",
    }
)

#: The only cross-layer integration import business code may make: a provider
#: *contract*, never a factory. Adding a consumer here is the signal to widen it.
_ALLOWED_INTEGRATION_IMPORTS = frozenset({"app.integrations.email.sender"})


def _operations(built: dict) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, item in built["paths"].items()
        for method in item
        if method not in _NON_OPERATIONS
    }


def _domains_mounted(built: dict) -> set[str]:
    return {
        path[len(API) + 1 :].split("/")[0]
        for path in built["paths"]
        if path.startswith(f"{API}/")
    }


def _scan(path: Path) -> tuple[set[str], set[str]]:
    """(imported modules, imported/aliased names) for one source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
                names.add(alias.asname or alias.name.split(".")[0])
    return modules, names


# ── Routers register ─────────────────────────────────────────────────


def test_every_domain_router_is_mounted() -> None:
    missing = ANCHOR_OPERATIONS - _operations(app.openapi())
    assert not missing, f"these routes did not register: {sorted(missing)}"


def test_exactly_the_expected_domains_are_mounted() -> None:
    """Every domain is present, and nothing unrecognised was mounted beside it."""
    assert _domains_mounted(app.openapi()) == set(MOUNTED_DOMAINS)


def test_create_app_boots_and_serves_its_surface() -> None:
    """The factory builds a working app; health answers without any database."""
    # Deliberately not a context manager: that would run the lifespan and tear
    # down the shared engine the session-scoped API client still relies on.
    client = TestClient(create_app())
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/openapi.json").status_code == 200


# ── Providers are selected from configuration, at the root ───────────


def test_file_storage_is_selected_from_configuration() -> None:
    default = get_settings().storage_provider.strip().lower()
    assert default in supported_providers()
    storage = get_file_storage()
    assert isinstance(storage, AbstractFileStorage)
    assert storage.provider == default

    forced = Settings().model_copy(update={"storage_provider": "s3"})
    assert build_file_storage(forced).provider == "s3"


def test_an_unknown_provider_name_is_refused_at_the_root() -> None:
    forced = Settings().model_copy(update={"storage_provider": "ftp"})
    with pytest.raises(ProviderNotConfiguredError):
        build_file_storage(forced)


def test_the_composition_root_selects_every_external_seat() -> None:
    modules, names = _scan(_APP / "infrastructure" / "container.py")
    assert {
        "app.integrations.payments",
        "app.integrations.email",
        "app.integrations.storage",
    } <= modules
    assert _SELECTORS <= names


def test_no_business_module_selects_a_provider_itself() -> None:
    """Domains and security may hold a contract, never reach a factory.

    This is the executable form of "the application business logic must not
    select providers itself": the only integration import allowed in a business
    layer is a provider *contract* module, and none of the selection callables
    may be named there at all.
    """
    for layer in ("domains", "security"):
        for path in (_APP / layer).rglob("*.py"):
            modules, names = _scan(path)
            integration = {m for m in modules if m.startswith("app.integrations")}
            assert integration <= _ALLOWED_INTEGRATION_IMPORTS, f"{path}: {integration}"
            assert names.isdisjoint(_SELECTORS), f"{path}: names a provider selector"
