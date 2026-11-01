"""Configuration loads from the environment; secrets are never hardcoded."""

from app.config.settings import Settings


def test_settings_read_flat_env_vars(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@host:5432/zoid")
    monkeypatch.setenv("PAYMENT_PROVIDER", "stripe")
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("AUTH_SESSION_STRATEGY", "jwt_cookie")
    monkeypatch.setenv("JWT_SECRET", "a-real-secret")
    monkeypatch.setenv("COOKIE_DOMAIN", ".zoid.example")
    monkeypatch.setenv("STORE_OWNER_EMAIL", "owner@zoid.example")

    settings = Settings(_env_file=None)

    assert settings.database_url.endswith("/zoid")
    assert settings.payment_provider == "stripe"
    assert settings.email_provider == "resend"
    assert settings.auth_session_strategy == "jwt_cookie"
    assert settings.jwt_secret == "a-real-secret"
    assert settings.cookie_domain == ".zoid.example"
    assert settings.store_owner_email == "owner@zoid.example"


def test_secrets_are_not_hardcoded() -> None:
    """With no environment provided, secret fields default to empty strings."""
    settings = Settings(_env_file=None)
    assert settings.jwt_secret == ""
    assert settings.paystack_secret_key == ""
    assert settings.stripe_secret_key == ""
    assert settings.resend_api_key == ""


def test_cookie_name_matches_frontend_contract() -> None:
    settings = Settings(_env_file=None)
    assert settings.cookie_name == "app_session_id"


def test_cors_origin_list_parsing() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a.example, http://b.example")
    assert settings.cors_origin_list == ["http://a.example", "http://b.example"]


# --- The JWT secret outside development -------------------------------------

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

_STRONG = "x" * 32


@pytest.mark.parametrize("env", ["production", "staging"])
@pytest.mark.parametrize(
    "secret",
    [
        "",
        "too-short",
        "change-me-in-production",
        "dev-insecure-secret-change-me-in-production-please",
    ],
)
def test_outside_development_a_missing_or_weak_jwt_secret_refuses_to_load(
    monkeypatch, env: str, secret: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("JWT_SECRET", secret)

    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None)


def test_outside_development_a_strong_jwt_secret_loads(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", _STRONG)

    assert Settings(_env_file=None).jwt_secret == _STRONG


@pytest.mark.parametrize("env", ["development", "test"])
def test_development_and_test_may_run_without_a_jwt_secret(monkeypatch, env: str) -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    assert Settings(_env_file=None).jwt_secret == ""


def test_the_app_does_not_start_in_production_without_a_jwt_secret(monkeypatch) -> None:
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError, match="JWT_SECRET"):
            create_app()
    finally:
        get_settings.cache_clear()
