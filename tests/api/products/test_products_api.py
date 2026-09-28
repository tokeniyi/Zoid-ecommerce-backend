"""Public catalog endpoints against the configured database.

Seeding uses the product repository over a short-lived engine (writes there are
no public endpoints by design); reads go through the real FastAPI app.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import get_settings
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

API = get_settings().api_v1_prefix


def _make_product() -> Product:
    tag = uuid4().hex[:8]
    return Product(
        id=0,
        slug=f"test-jersey-{tag}",
        name=f"Test Jersey {tag}",
        category=Category(id=0, name="Test Curated", slug="test-curated"),
        price=Decimal("58500.00"),
        currency="NGN",
        images=[
            ProductImage(url="/i/front.jpg", view="front"),
            ProductImage(url="/i/back.jpg", view="back"),
            ProductImage(url="/i/detail.jpg", view="detail"),
        ],
        variants=[
            ProductVariant(
                id=0,
                sku=f"TEST-{tag}-M",
                size="M",
                inventory=Inventory(quantity=8, reserved=2),
            ),
            ProductVariant(id=0, sku=f"TEST-{tag}-L", size="L", inventory=Inventory(quantity=3)),
        ],
        tone="Red / Black",
        is_bestseller=True,
    )


async def _seed(product: Product) -> Product:
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            created = await uow.products.add(product)
            await uow.commit()
            return created
    finally:
        await engine.dispose()


async def test_list_products_includes_seeded(client: TestClient) -> None:
    product = await _seed(_make_product())

    # Page through every result: the shared dev database accumulates rows across
    # runs, so the freshly seeded product is not guaranteed to sit on page 1.
    slugs: set[str] = set()
    page = 1
    while True:
        response = client.get(f"{API}/products", params={"page": page, "page_size": 100})
        assert response.status_code == 200, response.text
        body = response.json()
        slugs |= {item["slug"] for item in body["items"]}
        if page >= body["total_pages"]:
            break
        page += 1

    assert body["total"] >= 1
    assert product.slug in slugs


async def test_get_product_by_slug(client: TestClient) -> None:
    product = await _seed(_make_product())

    response = client.get(f"{API}/products/{product.slug}")

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["slug"] == product.slug
    assert detail["category"] == "Test Curated"
    assert detail["price"] == 58500.0
    assert detail["currency"] == "NGN"
    assert detail["is_bestseller"] is True
    assert len(detail["gallery"]) == 3
    assert detail["sizes"] == ["M", "L"]
    assert detail["stock"] == {"M": 6, "L": 3}  # available counts


async def test_get_product_by_id(client: TestClient) -> None:
    product = await _seed(_make_product())

    response = client.get(f"{API}/products/{product.id}")

    assert response.status_code == 200, response.text
    assert response.json()["slug"] == product.slug


async def test_get_unknown_product_returns_404(client: TestClient) -> None:
    assert client.get(f"{API}/products/does-not-exist-{uuid4().hex}").status_code == 404


async def test_pagination_bounds_are_respected(client: TestClient) -> None:
    await _seed(_make_product())
    await _seed(_make_product())

    response = client.get(f"{API}/products", params={"page": 1, "page_size": 1})

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) <= 1
    assert body["page_size"] == 1


async def test_list_categories_includes_seeded(client: TestClient) -> None:
    await _seed(_make_product())

    response = client.get(f"{API}/categories")

    assert response.status_code == 200, response.text
    slugs = {category["slug"] for category in response.json()}
    assert "test-curated" in slugs
