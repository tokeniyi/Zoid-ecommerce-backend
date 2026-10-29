"""Centralized runtime configuration.

Every value is read from the environment (or `.env`). No secrets are ever
hardcoded — the defaults below are non-secret local-development placeholders.
Field names map 1:1 (case-insensitively) to the environment variables listed
in the architecture: DATABASE_URL, PAYMENT_PROVIDER, EMAIL_PROVIDER,
STORAGE_PROVIDER, AUTH_SESSION_STRATEGY, JWT_SECRET, COOKIE_DOMAIN,
PAYSTACK_SECRET_KEY, STRIPE_SECRET_KEY, STORE_OWNER_EMAIL, etc.

Provider selection is configuration-driven so implementations can be swapped
without touching business logic.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "Zoid Jerseys API"
    api_v1_prefix: str = "/api/v1"
    app_env: str = "development"
    debug: bool = False

    # --- Database (PostgreSQL via asyncpg) ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/zoid"
    db_echo: bool = False

    # --- Provider selection ---
    payment_provider: str = "paystack"
    email_provider: str = "resend"
    storage_provider: str = "cloudinary"
    auth_session_strategy: str = "jwt_cookie"

    # --- Auth / sessions ---
    jwt_secret: str = Field(default="", repr=False)
    jwt_algorithm: str = "HS256"
    session_ttl_minutes: int = 60 * 24 * 7
    cookie_name: str = "app_session_id"
    cookie_domain: str = ""
    # Dev defaults: cookie_secure=False so HttpOnly cookies work over http://localhost
    cookie_secure: bool = False
    cookie_httponly: bool = True
    cookie_samesite: str = "lax"

    # --- Payment providers ---
    paystack_secret_key: str = Field(default="", repr=False)
    paystack_webhook_secret: str = Field(default="", repr=False)
    stripe_secret_key: str = Field(default="", repr=False)
    stripe_webhook_secret: str = Field(default="", repr=False)
    payment_currency: str = "NGN"
    # Where the provider's hosted checkout returns the customer to.
    # Default matches the Vite dev server (port 3000).
    payment_return_url: str = "http://localhost:3000/checkout"

    # --- Email ---
    resend_api_key: str = Field(default="", repr=False)
    email_from: str = "Zoid <orders@zoid.example>"
    store_owner_email: str = ""

    # --- Storage ---
    # A Cloudinary account is three coordinates. The SDK also understands a
    # single CLOUDINARY_URL environment variable and reads that for itself, so
    # there is no setting to duplicate here.
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = Field(default="", repr=False)
    cloudinary_api_secret: str = Field(default="", repr=False)
    # Anything that speaks the S3 API can be used; a blank endpoint means real
    # Amazon S3. Credentials are optional because a bucket may be reachable
    # through a role the process already holds.
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region: str = ""
    s3_access_key_id: str = Field(default="", repr=False)
    s3_secret_access_key: str = Field(default="", repr=False)

    # --- Rate limiting / Redis ---
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60
    login_rate_limit_per_minute: int = 5
    # Only "memory" exists today (one process); a shared store such as Redis
    # is needed once more than one instance serves traffic.
    rate_limit_backend: Literal["memory"] = "memory"
    # How many reverse proxies in front of the app append to X-Forwarded-For.
    # 0 ignores the header and keys on the socket peer; set it only when the
    # app is reachable solely through that many proxies.
    rate_limit_trusted_proxy_hops: int = Field(default=0, ge=0)

    # --- CORS (comma-separated origins) ---
    cors_origins: str = "http://localhost:3000"
    cors_allow_credentials: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached accessor for the application settings."""
    return Settings()
