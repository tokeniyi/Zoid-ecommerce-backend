"""Operator commands: the catalog seed and the admin bootstrap.

These write to the disposable test database through the same Unit of Work the app
uses, then read the result back through the real HTTP API.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.cli.create_admin import AdminOutcome, ensure_admin, validated_email
from app.cli.seed_catalog import build_product, load_catalog, seed
from app.config import get_settings
from app.infrastructure.persistence.sqlalchemy.session import (
    build_sessionmaker,
    create_engine_from_url,
)
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.database

API = get_settings().api_v1_prefix


# ── seed ────────────────────────────────────────────────────────────────


def test_every_catalog_entry_is_a_valid_product() -> None:
    entries = load_catalog()
    assert len(entries) == 21
    for entry in entries:
        product = build_product(entry)
        product.validate()
        assert [image.view for image in product.images] == ["front", "back", "detail"]
        assert product.variants, entry["slug"]
    assert len({entry["slug"] for entry in entries}) == len(entries)


async def test_seeding_twice_creates_nothing_the_second_time(client: TestClient) -> None:
    entries = load_catalog()

    first = await seed(entries)
    second = await seed(entries)

    assert (first.created, first.skipped) == (21, 0)
    assert (second.created, second.updated, second.skipped) == (0, 0, 21)
    body = client.get(f"{API}/products", params={"page_size": 100}).json()
    assert body["total"] == 21


async def test_the_seeded_catalog_matches_the_storefront(client: TestClient) -> None:
    await seed(load_catalog())

    milan = client.get(f"{API}/products/ac-milan-2526").json()
    assert milan["name"] == "AC Milan / 25—26"
    assert milan["category"] == "CURATED JERSEY"
    assert milan["price"] == "58500.00"
    assert milan["original_price"] == "68000.00"
    assert milan["discount_percent"] == 14
    assert milan["sizes"] == ["M", "L", "XL"]
    assert milan["stock"] == {"M": 8, "L": 3, "XL": 6}
    assert milan["is_bestseller"] is True and milan["is_new_arrival"] is True
    assert [image["view"] for image in milan["gallery"]] == ["front", "back", "detail"]

    gym = client.get(f"{API}/products/zoid-pro-gym-set").json()
    assert gym["sizes"] == ["S", "M", "L", "XL"]
    assert client.get(f"{API}/categories").json().__len__() == 6


async def test_update_refreshes_details_but_never_stock(client: TestClient) -> None:
    entries = load_catalog()
    await seed(entries)

    # The shop sells down some stock and the file's copy of the price changes.
    edited = copy.deepcopy(entries)
    milan = next(entry for entry in edited if entry["slug"] == "ac-milan-2526")
    milan["price"] = "55000.00"
    milan["sizes"] = [{"size": "M", "quantity": 999}, {"size": "L", "quantity": 999},
                      {"size": "XL", "quantity": 999}]

    plain = await seed(edited)  # without --update: nothing is touched
    assert plain.skipped == 21
    assert client.get(f"{API}/products/ac-milan-2526").json()["price"] == "58500.00"

    refreshed = await seed(edited, update=True)
    assert refreshed.updated == 21
    after = client.get(f"{API}/products/ac-milan-2526").json()
    assert after["price"] == "55000.00"
    assert after["stock"] == {"M": 8, "L": 3, "XL": 6}  # stock untouched


def test_relative_images_can_be_pointed_at_a_cdn() -> None:
    entry = load_catalog()[0]
    product = build_product(entry, "https://cdn.example.org/")
    assert product.images[0].url == "https://cdn.example.org" + entry["image"]
    absolute = {**entry, "image": "https://other.example.org/x.jpg"}
    assert build_product(absolute, "https://cdn.example.org").images[0].url == absolute["image"]


# ── admin bootstrap ─────────────────────────────────────────────────────


def _login(client: TestClient, email: str, password: str) -> dict[str, object]:
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_created_admin_can_sign_in_and_use_the_admin_api(client: TestClient) -> None:
    engine = create_engine_from_url()
    try:
        outcome = await ensure_admin(
            build_sessionmaker(engine),
            email="  Owner@ZoidJerseys.com ",
            name="Zoid Owner",
            password="a-long-enough-pass",
        )
    finally:
        await engine.dispose()
    assert outcome is AdminOutcome.CREATED

    assert _login(client, "owner@zoidjerseys.com", "a-long-enough-pass")["role"] == "admin"
    assert client.get(f"{API}/admin/dashboard").status_code == 200


async def test_an_existing_customer_is_promoted_and_keeps_their_password(
    client: TestClient,
) -> None:
    signup = client.post(
        f"{API}/auth/signup",
        json={"name": "Ada", "email": "ada@zoidjerseys.com", "password": "customer-pass-1"},
    )
    assert signup.status_code == 201, signup.text
    client.post(f"{API}/auth/logout")
    assert client.get(f"{API}/admin/dashboard").status_code in (401, 403)

    engine = create_engine_from_url()
    try:
        sessions = build_sessionmaker(engine)
        promoted = await ensure_admin(
            sessions, email="ada@zoidjerseys.com", name="ignored", password=None
        )
        again = await ensure_admin(
            sessions, email="ada@zoidjerseys.com", name="ignored", password="another-pass-9"
        )
    finally:
        await engine.dispose()
    assert promoted is AdminOutcome.PROMOTED
    assert again is AdminOutcome.ALREADY_ADMIN

    # Same password as before, new role: the second call did not reset it.
    assert _login(client, "ada@zoidjerseys.com", "customer-pass-1")["role"] == "admin"
    assert client.get(f"{API}/admin/dashboard").status_code == 200


async def test_a_new_admin_needs_a_real_password_and_a_usable_email() -> None:
    engine = create_engine_from_url()
    try:
        sessions = build_sessionmaker(engine)
        with pytest.raises(ValidationError, match="password"):
            await ensure_admin(sessions, email="x@zoidjerseys.com", name="X", password="short")
        with pytest.raises(ValidationError, match="password"):
            await ensure_admin(sessions, email="x@zoidjerseys.com", name="X", password=None)
        with pytest.raises(ValidationError, match="name"):
            await ensure_admin(sessions, email="x@zoidjerseys.com", name=" ",
                               password="long-enough-pass")
    finally:
        await engine.dispose()


def test_an_email_the_login_endpoint_would_refuse_is_refused_here_too() -> None:
    assert validated_email(" Owner@ZoidJerseys.com ") == "owner@zoidjerseys.com"
    for bad in ("owner@zoid.test", "not-an-email", ""):
        with pytest.raises(ValidationError, match="usable email"):
            validated_email(bad)


def test_seed_prices_are_decimals_not_floats() -> None:
    assert all(isinstance(Decimal(entry["price"]), Decimal) for entry in load_catalog())
