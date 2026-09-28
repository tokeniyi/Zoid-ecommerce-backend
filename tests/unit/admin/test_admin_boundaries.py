"""The admin domain stays inside the application boundaries (§34).

"The admin module should not directly manipulate SQLAlchemy" is an architectural
rule, and a rule that only holds until someone is in a hurry is not a rule. So
this reads the source of every module under ``app/domains/admin`` and refuses any
import that would let it reach the database, the ORM or the composition root: the
admin surface has to be *handed* its repositories, not go and get them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.domains.admin.api.router import router as admin_router
from app.security.authorization import require_admin

ADMIN_PACKAGE = Path(__file__).resolve().parents[3] / "app" / "domains" / "admin"

#: What no admin module may ever import. `app.infrastructure.persistence` is the
#: SQLAlchemy session, the unit of work and the ORM repositories themselves.
FORBIDDEN_ROOTS = ("sqlalchemy", "alembic", "asyncpg")
FORBIDDEN_PREFIXES = ("app.infrastructure.persistence",)

#: The application and domain layers may not even reach the composition root: a
#: use-case is *handed* its repositories, which is what keeps it testable without
#: a database. Only the HTTP edge names the container, exactly as every other
#: domain router does.
WIRED_LAYERS = ("api",)


def _imported_names(module: Path) -> set[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _admin_modules() -> list[Path]:
    return sorted(ADMIN_PACKAGE.rglob("*.py"))


def test_there_is_an_admin_module_to_guard() -> None:
    """A silently empty package would pass every other test in here."""
    assert {
        module.relative_to(ADMIN_PACKAGE).as_posix() for module in _admin_modules()
    } == {
        "__init__.py",
        "api/__init__.py",
        "api/router.py",
        "api/schemas.py",
        "application/__init__.py",
        "application/service.py",
        "domain/__init__.py",
        "domain/repositories.py",
    }


@pytest.mark.parametrize(
    "module", _admin_modules(), ids=lambda m: m.relative_to(ADMIN_PACKAGE).as_posix()
)
def test_admin_never_reaches_past_the_application_boundaries(module: Path) -> None:
    imported = _imported_names(module)
    illegal = {
        name
        for name in imported
        if name.split(".")[0] in FORBIDDEN_ROOTS
        or name.startswith(FORBIDDEN_PREFIXES)
        or (
            module.relative_to(ADMIN_PACKAGE).parts[0] not in WIRED_LAYERS
            and name.startswith("app.infrastructure")
        )
    }
    assert illegal == set(), f"{module.name} reaches the database directly: {sorted(illegal)}"


def test_the_admin_service_is_handed_its_repository_contracts() -> None:
    """The only door to persistence is the one the composition root opens — and
    it opens the same way for every service in the store."""
    source = (ADMIN_PACKAGE / "application" / "service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    admin_service = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "AdminService"
    )
    init = next(
        node
        for node in admin_service.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    seats = {arg.arg: arg.annotation for arg in init.args.kwonlyargs}
    assert set(seats) == {"products", "orders", "users"}
    # Named by the contracts, not by anything that could be a session.
    assert {str(seat.id) for seat in seats.values() if isinstance(seat, ast.Name)} == {
        "AbstractProductRepository",
        "AbstractOrderRepository",
        "AbstractUserRepository",
    }


def test_the_whole_admin_surface_is_guarded_once() -> None:
    """The guard sits on the router, so no endpoint can be added beside it.

    A per-endpoint `Depends(require_admin)` is a promise every future endpoint
    has to remember; this is one promise covering all of them, and a route cannot
    be reached without passing it.
    """
    assert [guard.dependency for guard in admin_router.dependencies] == [require_admin]


def test_every_admin_route_sits_under_the_guarded_prefix() -> None:
    paths = {route.path for route in admin_router.routes}
    assert paths == {
        "/admin/dashboard",
        "/admin/products",
        "/admin/products/{product_id}",
        "/admin/products/{product_id}/stock",
        "/admin/orders",
        "/admin/users",
    }
