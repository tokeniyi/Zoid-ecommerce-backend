"""Phase 18 — the closing architecture audit, kept enforceable.

The roadmap's final phase asks for a manual sweep for forbidden coupling and
correct dependency direction. A sweep that only exists in the transcript of the
day it was run is not much of a guarantee, so the same checks live here as tests:
they read the real source with the ``ast`` parser and assert the dependency
direction the architecture promises. Each one is the machine form of a line in
the audit checklist, so the invariant survives the next change instead of rotting
until someone re-runs the audit by hand.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.config import get_settings

_APP = Path(__file__).resolve().parents[2] / "app"

#: The external provider SDKs. Paystack ships no SDK -- its adapter speaks httpx
#: -- so it is deliberately absent: there is nothing to import by mistake.
_PROVIDER_SDKS = frozenset({"stripe", "resend", "cloudinary", "boto3"})


def _imports(path: Path) -> set[str]:
    """Every module a file imports, as dotted names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _tops(names: set[str]) -> set[str]:
    return {name.split(".", 1)[0] for name in names}


def _under(*segments: str) -> list[Path]:
    root = _APP.joinpath(*segments) if segments else _APP
    return sorted(root.rglob("*.py"))


def _layer(path: Path) -> set[str]:
    """The layer directory names a module sits under, relative to ``app``."""
    return set(path.relative_to(_APP).parts)


def _app_names(names: set[str]) -> set[str]:
    return {name for name in names if name == "app" or name.startswith("app.")}


# --- forbidden coupling (each MUST NOT exist) --------------------------------


def test_domain_and_application_code_never_import_sqlalchemy() -> None:
    """Domain -> SQLAlchemy, Application -> SQLAlchemy, Router -> SQLAlchemy.

    The sweep covers all of ``app/domains`` at once: persistence is reachable
    only from the infrastructure layer, never from a domain, service or router.
    """
    for path in _under("domains"):
        assert "sqlalchemy" not in _tops(_imports(path)), path


def test_fastapi_is_confined_to_the_http_layer() -> None:
    """Domain -> FastAPI. HTTP is an edge detail; only the api layer touches it."""
    for path in _under("domains"):
        if "fastapi" in _tops(_imports(path)):
            assert "api" in _layer(path), f"{path} reaches FastAPI from outside api/"


def test_the_domain_layer_reaches_outward_to_nothing() -> None:
    """A domain module may depend only on the shared kernel and on other domains'
    domain contracts -- never on api, application, infrastructure or integrations.
    """
    for path in _under("domains"):
        if "domain" not in _layer(path):
            continue
        for name in _app_names(_imports(path)):
            allowed = name.startswith("app.shared") or ".domain" in name
            assert allowed, f"{path} imports {name}"


def test_provider_sdks_live_only_in_their_adapters() -> None:
    """Domain/Application -> Stripe / Resend / Cloudinary / boto3.

    A provider library is importable from exactly one place: the integration
    adapter that knows how to speak to it.
    """
    for path in _under():
        if "integrations" in _layer(path):
            continue
        assert _tops(_imports(path)).isdisjoint(_PROVIDER_SDKS), path


def test_the_application_layer_wires_nothing_it_should_be_told_about() -> None:
    """Services are handed their collaborators; they do not import the container,
    the HTTP layer or a persistence library to fetch them itself.
    """
    for path in _under("domains"):
        if "application" not in _layer(path):
            continue
        names = _imports(path)
        assert _tops(names).isdisjoint({"fastapi", "sqlalchemy"}), path
        outward = {n for n in _app_names(names) if n.startswith(("app.infrastructure", "app.api"))}
        assert not outward, f"{path} imports {outward}"


# --- configuration-driven selection (verify it is present) -------------------


def test_provider_selection_is_driven_by_configuration() -> None:
    """The four selectors the architecture names are real settings, and the
    genuinely multi-provider factories key off theirs.

    Auth is asserted only as *built from settings*: a single session strategy is
    implemented, so -- rather than invent alternatives the design does not specify
    -- this checks the seam exists, not that it branches.
    """
    settings = get_settings()
    selectors = ("payment_provider", "email_provider", "storage_provider", "auth_session_strategy")
    for selector in selectors:
        assert isinstance(getattr(settings, selector), str)
        assert getattr(settings, selector)

    for factory, selector in (
        ("integrations/payments/factory.py", "payment_provider"),
        ("integrations/email/factory.py", "email_provider"),
        ("integrations/storage/factory.py", "storage_provider"),
    ):
        source = _APP.joinpath(*factory.split("/")).read_text(encoding="utf-8")
        assert selector in source, factory

    session_source = (_APP / "security" / "authentication" / "session.py").read_text(
        encoding="utf-8"
    )
    assert "get_settings()" in session_source
