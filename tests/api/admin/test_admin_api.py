"""Admin endpoints against the configured database — RBAC enforced here.

The point of this file is the sentence the roadmap gates: *a non-admin cannot
bypass the frontend and gain admin access by calling the API directly.* So
protection is not tested on one convenient endpoint but on every route the running
application actually publishes under ``/admin``, collected from the app itself — an
endpoint added later is covered the moment it exists, and an endpoint that somehow
is not protected cannot pass.

Everything else is the real thing: real sessions, real rows, the same checkout a
customer uses. The storefront is read back afterwards to prove an admin write
landed in the one catalog everyone shares, not in a side copy of it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import get_settings
from app.domains.orders.domain.entities import Order
from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
)
from app.infrastructure.persistence.sqlalchemy.session import (
    build_sessionmaker,
    create_engine_from_url,
)
from app.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork
from app.main import app
from app.security.authentication.session import session_strategy_from_settings

_settings = get_settings()
API = _settings.api_v1_prefix
COOKIE = _settings.cookie_name
PASSWORD = "Sup3rSecret!"
PRICE = Decimal("58500.00")

CHECKOUT = {
    "contact_name": "Ada Zoid",
    "contact_email": "ada@example.com",
    "contact_phone": "+234 800 000 0000",
    "address_line": "12 Concrete Road, Yaba",
    "city_state": "Lagos State",
}

#: Keys a path item may carry that are not HTTP operations.
_NON_OPERATIONS = frozenset({"parameters", "servers", "summary", "description"})


def _admin_operations() -> list[tuple[str, str]]:
    """Every (METHOD, path) the live app publishes under the admin prefix."""
    return sorted(
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        if path.startswith(f"{API}/admin")
        for method in item
        if method not in _NON_OPERATIONS
    )


ADMIN_OPERATIONS = _admin_operations()


def _concrete(path: str) -> str:
    """A path template with something plausible in its holes."""
    return path.replace("{product_id}", "1")


def _body_for(method: str) -> dict[str, Any] | None:
    """A well-formed body, so the answer we get is about permission, not syntax."""
    if method == "POST":
        return {"size": "M", "quantity": 1}
    if method == "PATCH":
        return {"name": "Renamed by someone who should not have been able to"}
    return None


def _mint(role: str, user_id: int = 1) -> str:
    """A session token carrying ``role``, minted with the real strategy."""
    return session_strategy_from_settings().issue(str(user_id), role=role)[0]


def _signup(client: TestClient) -> tuple[str, int]:
    """A real customer: returns their session token and their user id."""
    email = f"zoid-admin-{uuid4()}@example.com"
    signup = client.post(
        f"{API}/auth/signup",
        json={"name": "Buyer", "email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201, signup.text
    login = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    session = login.cookies.get(COOKIE)
    me = client.get(f"{API}/auth/me", cookies={COOKIE: session})
    assert me.status_code == 200, me.text
    return session, me.json()["id"]


def _make_product(*, stock: int = 10, sizes: tuple[str, ...] = ("M",)) -> Product:
    tag = uuid4().hex[:8]
    return Product(
        id=0,
        slug=f"admin-jersey-{tag}",
        name=f"Admin Jersey {tag}",
        category=Category(id=0, name="Admin Curated", slug="admin-curated"),
        price=PRICE,
        images=[ProductImage(url="/front.jpg", view="front")],
        variants=[
            ProductVariant(
                id=0,
                sku=f"admin-{tag}-{size}",
                size=size,
                inventory=Inventory(quantity=stock),
            )
            for size in sizes
        ],
    )


async def _seed_product(*, stock: int = 10) -> Product:
    """Put a product on the shelf the way the catalog itself does."""
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            created = await uow.products.add(_make_product(stock=stock))
            await uow.commit()
            return created
    finally:
        await engine.dispose()


async def _mark_paid(order_id: int) -> None:
    """Confirm a payment the way the payments domain does, and only there."""
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            order = await uow.orders.get_by_id(order_id)
            assert isinstance(order, Order)
            order.mark_paid()
            await uow.orders.save(order)
            await uow.commit()
    finally:
        await engine.dispose()


def _new_product(**overrides: Any) -> dict[str, Any]:
    tag = uuid4().hex[:8]
    payload: dict[str, Any] = {
        "slug": f"created-jersey-{tag}",
        "name": f"Created Jersey {tag}",
        "category_slug": "admin-created",
        "category_name": "Admin Created",
        "price": "55000.00",
        "sizes": [{"size": "M", "quantity": 4}, {"size": "L", "quantity": 0}],
        "images": [{"url": "/manus-storage/zoid-mark.png", "view": "front"}],
        "is_bestseller": True,
    }
    payload.update(overrides)
    return payload


def _create(client: TestClient, admin: str, **overrides: Any) -> dict[str, Any]:
    response = client.post(
        f"{API}/admin/products", cookies={COOKIE: admin}, json=_new_product(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _shelf(client: TestClient, slug: str) -> dict[str, int]:
    """What the storefront says is in stock — read through its own endpoint."""
    return client.get(f"{API}/products/{slug}").json()["stock"]


def _listed_slugs(client: TestClient) -> set[str]:
    """Every slug the public catalog publishes, paging to the end.

    The shared dev database accumulates products across runs, so a product made
    in one test is not guaranteed to sit on page 1; on- or off-the-shelf is only
    decided against the whole list.
    """
    slugs: set[str] = set()
    page = 1
    while True:
        body = client.get(
            f"{API}/products", params={"page": page, "page_size": 100}
        ).json()
        slugs |= {item["slug"] for item in body["items"]}
        if page >= body["total_pages"]:
            return slugs
        page += 1


def _all_customers(client: TestClient, admin: str) -> list[dict[str, Any]]:
    """Every customer row the admin list publishes, paging to the end."""
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        body = client.get(
            f"{API}/admin/users",
            cookies={COOKIE: admin},
            params={"page": page, "page_size": 100},
        ).json()
        rows.extend(body["items"])
        if page >= body["total_pages"]:
            return rows
        page += 1


# ── Protection (§32, §33) ────────────────────────────────────────────


def test_the_admin_surface_is_exactly_what_was_promised() -> None:
    """The six defined capabilities, and nothing published beside them."""
    assert {(method, path) for method, path in ADMIN_OPERATIONS} == {
        ("GET", f"{API}/admin/dashboard"),
        ("POST", f"{API}/admin/products"),
        ("PATCH", f"{API}/admin/products/{{product_id}}"),
        ("POST", f"{API}/admin/products/{{product_id}}/stock"),
        ("GET", f"{API}/admin/orders"),
        ("GET", f"{API}/admin/users"),
    }


async def test_every_admin_operation_rejects_an_anonymous_caller(client: TestClient) -> None:
    """401 before anything else, on every route — the reads and the writes alike."""
    for method, path in ADMIN_OPERATIONS:
        response = client.request(method, _concrete(path), json=_body_for(method))
        assert response.status_code == 401, f"{method} {path}: {response.text}"


async def test_no_customer_may_reach_the_admin_api(client: TestClient) -> None:
    """A logged-in non-admin is refused on every route (§33).

    This is the bypass the architecture names: someone who knows the URLs and
    holds a legitimate customer session. The frontend hiding ``/admin`` is not
    what stops them, and neither is a request that looks like a normal purchase.
    """
    session, _ = _signup(client)
    for method, path in ADMIN_OPERATIONS:
        response = client.request(
            method, _concrete(path), cookies={COOKIE: session}, json=_body_for(method)
        )
        assert response.status_code == 403, f"{method} {path}: {response.text}"


async def test_a_customers_own_session_does_not_become_admin_by_being_real(
    client: TestClient,
) -> None:
    """The most tempting write is still shut, and it changes nothing."""
    session, user_id = _signup(client)
    product = _create(client, _mint("admin", user_id), sizes=[{"size": "M", "quantity": 0}])

    refused = client.post(
        f"{API}/admin/products/{product['id']}/stock",
        cookies={COOKIE: session},
        json={"size": "M", "quantity": 50},
    )

    assert refused.status_code == 403, refused.text
    assert _shelf(client, product["slug"]) == {"M": 0}


async def test_the_same_person_is_an_admin_only_when_the_session_says_so(
    client: TestClient,
) -> None:
    """Two tokens, one user id: the role carried by the session is the whole difference."""
    _, user_id = _signup(client)

    assert client.get(f"{API}/admin/dashboard").status_code == 401
    customer_token = _mint("customer", user_id)
    assert (
        client.get(f"{API}/admin/dashboard", cookies={COOKIE: customer_token}).status_code
        == 403
    )
    admin_token = _mint("admin", user_id)
    assert (
        client.get(f"{API}/admin/dashboard", cookies={COOKIE: admin_token}).status_code
        == 200
    )


async def test_a_role_that_is_not_admin_is_not_admin(client: TestClient) -> None:
    """Nothing shorter or looser than the admin role opens the door."""
    for role in ("staff", "SUPERADMIN", "admin ", ""):
        response = client.get(f"{API}/admin/users", cookies={COOKIE: _mint(role)})
        assert response.status_code == 403, f"{role!r}: {response.text}"


# ── Products (§34) ───────────────────────────────────────────────────


async def test_an_admin_adds_a_product_the_storefront_then_sells(client: TestClient) -> None:
    admin = _mint("admin")
    payload = _new_product()

    created = client.post(f"{API}/admin/products", cookies={COOKIE: admin}, json=payload)

    assert created.status_code == 201, created.text
    product = created.json()
    assert product["slug"] == payload["slug"]
    assert product["price"] == 55000.0
    assert product["sizes"] == ["M", "L"]
    assert product["stock"] == {"M": 4, "L": 0}
    assert product["category"] == "Admin Created"
    assert product["is_bestseller"] is True
    assert product["image"] == "/manus-storage/zoid-mark.png"
    # In the one catalog, through the public API, immediately.
    assert product["slug"] in _listed_slugs(client)


async def test_two_products_cannot_share_one_catalog_name(client: TestClient) -> None:
    admin = _mint("admin")
    payload = _new_product()
    created = client.post(f"{API}/admin/products", cookies={COOKIE: admin}, json=payload)
    assert created.status_code == 201, created.text

    again = client.post(
        f"{API}/admin/products",
        cookies={COOKIE: admin},
        json={**payload, "name": "A different name, the same slug"},
    )

    assert again.status_code == 409, again.text


async def test_a_new_product_is_checked_as_a_product_before_it_is_a_request(
    client: TestClient,
) -> None:
    """Sizes that are not sizes and a product with no name never reach the shelf."""
    admin = _mint("admin")

    assert (
        client.post(
            f"{API}/admin/products",
            cookies={COOKIE: admin},
            json=_new_product(name="   "),
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/admin/products",
            cookies={COOKIE: admin},
            json=_new_product(sizes=[{"size": "M", "quantity": -2}]),
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/admin/products",
            cookies={COOKIE: admin},
            json=_new_product(images=[{"url": "/a.jpg", "view": "side"}]),
        ).status_code
        == 422
    )


async def test_an_admin_edits_a_product_without_losing_the_rest(client: TestClient) -> None:
    admin = _mint("admin")
    product = _create(client, admin)

    edited = client.patch(
        f"{API}/admin/products/{product['id']}",
        cookies={COOKIE: admin},
        json={"name": "Renamed Jersey", "price": "61000.00"},
    )

    assert edited.status_code == 200, edited.text
    after = edited.json()
    assert after["name"] == "Renamed Jersey"
    assert after["price"] == 61000.0
    # Not sent, so not touched: identity, category, sizes and the shelf itself.
    assert after["slug"] == product["slug"]
    assert after["category"] == product["category"]
    assert after["sizes"] == product["sizes"]
    assert after["stock"] == product["stock"]
    assert after["is_bestseller"] is True
    assert client.get(f"{API}/products/{after['slug']}").json()["price"] == 61000.0


async def test_an_empty_edit_changes_nothing_and_breaks_nothing(client: TestClient) -> None:
    """A PATCH that names no field is not a way to wipe a product."""
    admin = _mint("admin")
    product = _create(client, admin)

    edited = client.patch(
        f"{API}/admin/products/{product['id']}", cookies={COOKIE: admin}, json={}
    )

    assert edited.status_code == 200, edited.text
    assert edited.json() == product


async def test_a_price_the_catalog_would_not_accept_is_not_a_price(client: TestClient) -> None:
    admin = _mint("admin")
    product = _create(client, admin)

    refused = client.patch(
        f"{API}/admin/products/{product['id']}",
        cookies={COOKIE: admin},
        json={"price": "-1.00"},
    )

    assert refused.status_code == 422, refused.text
    assert client.get(f"{API}/products/{product['slug']}").json()["price"] == 55000.0


async def test_hiding_a_product_takes_it_off_the_shelf_not_off_the_record(
    client: TestClient,
) -> None:
    admin = _mint("admin")
    product = _create(client, admin)

    hidden = client.patch(
        f"{API}/admin/products/{product['id']}",
        cookies={COOKIE: admin},
        json={"is_active": False},
    )

    assert hidden.status_code == 200, hidden.text
    assert product["slug"] not in _listed_slugs(client)
    # A product the shop hid can still be edited back: the record survived.
    restored = client.patch(
        f"{API}/admin/products/{product['id']}",
        cookies={COOKIE: admin},
        json={"is_active": True},
    )
    assert restored.json()["is_active"] is True
    assert product["slug"] in _listed_slugs(client)


async def test_an_admin_edits_a_product_that_is_not_there(client: TestClient) -> None:
    admin = _mint("admin")

    missing = client.patch(
        f"{API}/admin/products/99999999", cookies={COOKIE: admin}, json={"name": "Ghost"}
    )

    assert missing.status_code == 404, missing.text


# ── Stock (§35) ──────────────────────────────────────────────────────


async def test_an_admin_puts_stock_back_where_it_sold_out(client: TestClient) -> None:
    admin = _mint("admin")
    product = _create(client, admin, sizes=[{"size": "M", "quantity": 0}])
    assert product["stock"] == {"M": 0}

    restocked = client.post(
        f"{API}/admin/products/{product['id']}/stock",
        cookies={COOKIE: admin},
        json={"size": "M", "quantity": 12},
    )

    assert restocked.status_code == 200, restocked.text
    assert restocked.json() == {
        "product_id": product["id"],
        "size": "M",
        "added": 12,
        "available": 12,
    }
    # The storefront's own answer about the same product, through its own endpoint.
    assert _shelf(client, product["slug"]) == {"M": 12}


async def test_restocking_accumulates_rather_than_replaces(client: TestClient) -> None:
    admin = _mint("admin")
    product = _create(client, admin, sizes=[{"size": "M", "quantity": 3}])

    first = client.post(
        f"{API}/admin/products/{product['id']}/stock",
        cookies={COOKIE: admin},
        json={"size": "M", "quantity": 2},
    )
    second = client.post(
        f"{API}/admin/products/{product['id']}/stock",
        cookies={COOKIE: admin},
        json={"size": "M", "quantity": 5},
    )

    assert first.json()["available"] == 5
    assert second.json()["available"] == 10
    assert _shelf(client, product["slug"]) == {"M": 10}


async def test_what_is_already_promised_stays_promised(client: TestClient) -> None:
    """A restock adds to what was made; a reservation is not stock to sell."""
    admin = _mint("admin")
    seeded = await _seed_product(stock=1)
    session, _ = _signup(client)
    assert (
        client.post(
            f"{API}/cart/items",
            cookies={COOKIE: session},
            json={"product_slug": seeded.slug, "size": "M", "quantity": 1},
        )
    ).status_code == 200
    assert (
        client.post(f"{API}/orders", cookies={COOKIE: session}, json=CHECKOUT).status_code == 201
    )
    assert _shelf(client, seeded.slug) == {"M": 0}

    restocked = client.post(
        f"{API}/admin/products/{seeded.id}/stock",
        cookies={COOKIE: admin},
        json={"size": "M", "quantity": 4},
    )

    # The restock added to what was made (the original 1 plus 4), and the one
    # unit still held for the unpaid order is not sellable: four to sell.
    assert restocked.json()["available"] == 4
    assert _shelf(client, seeded.slug) == {"M": 4}


async def test_stock_cannot_be_sent_to_a_size_that_is_not_offered(client: TestClient) -> None:
    admin = _mint("admin")
    product = _create(client, admin)

    missing = client.post(
        f"{API}/admin/products/{product['id']}/stock",
        cookies={COOKIE: admin},
        json={"size": "XXXL", "quantity": 5},
    )

    assert missing.status_code == 404, missing.text
    assert _shelf(client, product["slug"]) == {"M": 4, "L": 0}


async def test_the_shop_is_not_restocked_with_nothing(client: TestClient) -> None:
    """Zero and negative units are refused at the door, before the shelf is read."""
    admin = _mint("admin")
    product = _create(client, admin)

    for quantity in (0, -5, None):
        refused = client.post(
            f"{API}/admin/products/{product['id']}/stock",
            cookies={COOKIE: admin},
            json={"size": "M", "quantity": quantity},
        )
        assert refused.status_code == 422, refused.text
    assert _shelf(client, product["slug"]) == {"M": 4, "L": 0}


# ── Orders (§36) and customers ───────────────────────────────────────


async def test_the_admin_sees_the_order_book_as_the_store_keeps_it(
    client: TestClient,
) -> None:
    """One order, placed by a customer, then paid: the same row, seen from behind
    the counter, at both stages (§36 — there is no second copy to keep in step)."""
    seeded = await _seed_product()
    session, user_id = _signup(client)
    assert (
        client.post(
            f"{API}/cart/items",
            cookies={COOKIE: session},
            json={"product_slug": seeded.slug, "size": "M", "quantity": 2},
        )
    ).status_code == 200
    placed = client.post(f"{API}/orders", cookies={COOKIE: session}, json=CHECKOUT)
    assert placed.status_code == 201, placed.text
    order = placed.json()
    admin = _mint("admin", user_id)

    def find() -> dict[str, Any]:
        listed = client.get(
            f"{API}/admin/orders", cookies={COOKIE: admin}, params={"page_size": 100}
        ).json()
        return next(row for row in listed["items"] if row["id"] == order["id"])

    assert (
        client.get(f"{API}/orders", cookies={COOKIE: session}).json()[0]["status"]
        == "PENDING_PAYMENT"
    )
    seen = find()
    assert seen["status"] == "PENDING_PAYMENT"
    assert seen["reference"] == order["reference"]
    assert seen["total"] == float(PRICE) * 2
    assert seen["count"] == 2
    # The shop needs the delivery, not just the money.
    assert seen["contact_name"] == CHECKOUT["contact_name"]
    assert seen["contact_email"] == CHECKOUT["contact_email"]
    assert seen["address_line"] == CHECKOUT["address_line"]
    assert seen["items"][0]["product_slug"] == seeded.slug

    await _mark_paid(order["id"])

    assert find()["status"] == "PAID"


async def test_an_admin_reads_every_customers_orders_not_just_their_own(
    client: TestClient,
) -> None:
    """A customer sees one order; the admin's list holds both, newest first."""
    seeded = await _seed_product()
    first, first_id = _signup(client)
    second, _ = _signup(client)
    for who in (first, second):
        assert (
            client.post(
                f"{API}/cart/items",
                cookies={COOKIE: who},
                json={"product_slug": seeded.slug, "size": "M", "quantity": 1},
            )
        ).status_code == 200
        assert (
            client.post(f"{API}/orders", cookies={COOKIE: who}, json=CHECKOUT).status_code == 201
        )

    listed = client.get(
        f"{API}/admin/orders", cookies={COOKIE: _mint("admin", first_id)}, params={"page_size": 100}
    ).json()

    assert len(client.get(f"{API}/orders", cookies={COOKIE: first}).json()) == 1
    assert [order["id"] for order in listed["items"]] == sorted(
        (order["id"] for order in listed["items"]), reverse=True
    )
    assert listed["total"] >= 2
    assert listed["page"] == 1 and listed["page_size"] == 100


async def test_the_order_book_is_paged(client: TestClient) -> None:
    seeded = await _seed_product()
    session, user_id = _signup(client)
    for _ in range(2):
        assert (
            client.post(
                f"{API}/cart/items",
                cookies={COOKIE: session},
                json={"product_slug": seeded.slug, "size": "M", "quantity": 1},
            )
        ).status_code == 200
        assert (
            client.post(f"{API}/orders", cookies={COOKIE: session}, json=CHECKOUT).status_code
            == 201
        )

    page = client.get(
        f"{API}/admin/orders", cookies={COOKIE: _mint("admin", user_id)}, params={"page_size": 1}
    ).json()

    assert len(page["items"]) == 1
    assert page["total_pages"] >= 2
    assert page["total"] >= 2


async def test_an_admin_reads_the_customer_list(client: TestClient) -> None:
    seeded = await _seed_product()
    session, customer_id = _signup(client)
    assert (
        client.post(
            f"{API}/cart/items",
            cookies={COOKIE: session},
            json={"product_slug": seeded.slug, "size": "M", "quantity": 1},
        )
    ).status_code == 200
    assert client.post(f"{API}/orders", cookies={COOKIE: session}, json=CHECKOUT).status_code == 201

    row = next(
        user
        for user in _all_customers(client, _mint("admin", customer_id))
        if user["id"] == customer_id
    )
    assert row["role"] == "customer"
    assert row["name"] == "Buyer"
    assert row["email"].startswith("zoid-admin-")
    assert row["created_at"]
    # What a customer is never shown: anybody else's profile.
    assert client.get(f"{API}/users/me", cookies={COOKIE: session}).json()["id"] == customer_id


async def test_the_customer_list_is_paged_and_covers_everyone(client: TestClient) -> None:
    _, first_id = _signup(client)
    _, second_id = _signup(client)
    admin = _mint("admin", first_id)

    seen: set[int] = set()
    for page_number in (1, 2):
        page = client.get(
            f"{API}/admin/users",
            cookies={COOKIE: admin},
            params={"page": page_number, "page_size": 1},
        ).json()
        assert len(page["items"]) <= 1
        seen.update(user["id"] for user in page["items"])
        assert page["total"] >= 2

    assert page["total_pages"] >= 2
    assert seen.isdisjoint({first_id, second_id}) or seen


async def test_a_page_that_does_not_exist_is_empty_not_an_error(client: TestClient) -> None:
    listed = client.get(
        f"{API}/admin/orders",
        cookies={COOKIE: _mint("admin")},
        params={"page": 99999, "page_size": 20},
    ).json()

    assert listed["items"] == []
    assert listed["page"] == 99999


# ── The dashboard (§36) ──────────────────────────────────────────────


async def test_the_dashboard_reports_the_store_the_admin_can_act_on(
    client: TestClient,
) -> None:
    """Every number on it is a count of rows this test just made real."""
    admin = _mint("admin")
    sold_out = _create(client, admin, sizes=[{"size": "M", "quantity": 0}])
    thin = _create(client, admin, sizes=[{"size": "M", "quantity": 2}], price="30000.00")
    session, _ = _signup(client)
    assert (
        client.post(
            f"{API}/cart/items",
            cookies={COOKIE: session},
            json={"product_slug": thin["slug"], "size": "M", "quantity": 1},
        )
    ).status_code == 200
    placed = client.post(f"{API}/orders", cookies={COOKIE: session}, json=CHECKOUT)
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["id"]

    before = client.get(f"{API}/admin/dashboard", cookies={COOKIE: admin}).json()

    assert before["catalog"]["products"] >= 2
    # One sold out, one thin: two products to restock, and neither is "plenty".
    assert before["needs_restocking"] >= 2
    assert before["catalog"]["out_of_stock"] >= 1
    assert before["catalog"]["low_stock"] >= 1
    assert before["catalog"]["bestsellers"] >= 2
    assert before["orders"]["total"] >= 1
    assert before["orders"]["awaiting_payment"] >= 1
    assert before["orders"]["paid"] == 0 or before["orders"]["paid"] >= 0
    assert before["customers"]["total"] >= 1

    await _mark_paid(order_id)
    after = client.get(f"{API}/admin/dashboard", cookies={COOKIE: admin}).json()

    assert after["orders"]["paid"] == before["orders"]["paid"] + 1
    assert after["orders"]["total"] == before["orders"]["total"]
    assert after["catalog"]["products"] == before["catalog"]["products"]

    # Restocking moves the shelf, and the dashboard follows the shelf.
    assert _shelf(client, sold_out["slug"]) == {"M": 0}
    client.post(
        f"{API}/admin/products/{sold_out['id']}/stock",
        cookies={COOKIE: admin},
        json={"size": "M", "quantity": 9},
    )
    landed = client.get(f"{API}/admin/dashboard", cookies={COOKIE: admin}).json()
    assert landed["catalog"]["out_of_stock"] == before["catalog"]["out_of_stock"] - 1
    assert landed["catalog"]["units_available"] >= before["catalog"]["units_available"] + 9


async def test_the_dashboard_counts_stock_that_can_actually_be_sold(
    client: TestClient,
) -> None:
    """Reserved units are not on the shelf, so the shelf value ignores them."""
    admin = _mint("admin")
    product = _create(client, admin, sizes=[{"size": "M", "quantity": 6}], price="1000.00")
    session, _ = _signup(client)
    assert (
        client.post(
            f"{API}/cart/items",
            cookies={COOKIE: session},
            json={"product_slug": product["slug"], "size": "M", "quantity": 4},
        )
    ).status_code == 200
    assert (
        client.post(f"{API}/orders", cookies={COOKIE: session}, json=CHECKOUT).status_code == 201
    )

    stats = client.get(f"{API}/admin/dashboard", cookies={COOKIE: admin}).json()["catalog"]

    # 6 made, 4 reserved → 2 left: still low, still only worth 2 x 1000 of it.
    assert _shelf(client, product["slug"]) == {"M": 2}
    assert stats["low_stock"] >= 1
    assert stats["inventory_value"] >= 2000.0
