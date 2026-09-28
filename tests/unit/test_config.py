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
