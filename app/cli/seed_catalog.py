"""Load the storefront catalog into the database — safe to run again.

    uv run python -m app.cli.seed_catalog                  # add what is missing
    uv run python -m app.cli.seed_catalog --update         # also refresh details/prices/flags
    uv run python -m app.cli.seed_catalog --image-base-url https://cdn.example.com

The data (``data/catalog.json``) is the storefront's own product list, converted
once from its ``catalog.ts`` so the shop opens with the catalog the frontend was
designed around. Re-running never duplicates anything: a product is identified by
its slug.

* **Default:** products that already exist are skipped, so live stock and any
  admin edits survive a re-seed.
* **``--update``:** existing products get their descriptive fields, prices and
  flags refreshed from the file. Stock is *never* touched: quantity belongs to
  the shop floor, not to a seed file.
* **``--image-base-url``:** prefixes relative image paths (``/jerseys/x.jpg``),
  for when the images are hosted on a CDN/bucket rather than by the frontend.
  Absolute URLs are left alone.

Nothing here depends on a running API; it talks to the database the same way the
app does, through the Unit of Work.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

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

DATA_FILE = Path(__file__).parent / "data" / "catalog.json"

#: The storefront shows the same photo as front, back and close-up (it varies the
#: crop in CSS), so the seed records the three views the gallery expects.
_GALLERY_VIEWS = ("front", "back", "detail")

#: Fields an ``--update`` refreshes on an existing product (never stock).
_REFRESHED = (
    "name", "price", "original_price", "tone", "style", "color", "fit", "fit_note",
    "details", "delivery", "is_bestseller", "is_special", "is_new_arrival",
)


@dataclass
class SeedReport:
    created: int = 0
    updated: int = 0
    skipped: int = 0

    def __str__(self) -> str:
        return f"created {self.created}, updated {self.updated}, skipped {self.skipped}"


def load_catalog(path: Path = DATA_FILE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _image_url(url: str, base: str | None) -> str:
    if not base or url.startswith(("http://", "https://")):
        return url
    return f"{base.rstrip('/')}/{url.lstrip('/')}"


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def build_product(entry: dict[str, Any], image_base_url: str | None = None) -> Product:
    image = _image_url(entry["image"], image_base_url)
    category = entry["category"]
    return Product(
        id=0,
        slug=entry["slug"],
        name=entry["name"],
        category=Category(id=0, name=category["name"], slug=category["slug"]),
        price=Decimal(entry["price"]),
        original_price=_decimal(entry.get("original_price")),
        images=[ProductImage(url=image, view=view) for view in _GALLERY_VIEWS],
        variants=[
            ProductVariant(
                id=0,
                sku=f"{entry['slug']}-{size['size']}".upper(),
                size=size["size"],
                inventory=Inventory(quantity=size["quantity"]),
            )
            for size in entry["sizes"]
        ],
        tone=entry["tone"],
        style=entry["style"],
        color=entry["color"],
        fit=entry["fit"],
        fit_note=entry["fit_note"],
        details=entry["details"],
        delivery=entry["delivery"],
        is_bestseller=entry["is_bestseller"],
        is_special=entry["is_special"],
        is_new_arrival=entry["is_new_arrival"],
    )


async def seed(
    entries: list[dict[str, Any]],
    *,
    update: bool = False,
    image_base_url: str | None = None,
) -> SeedReport:
    """Insert (or with ``update`` refresh) every entry, in one transaction."""
    report = SeedReport()
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            for entry in entries:
                wanted = build_product(entry, image_base_url)
                wanted.validate()
                existing = await uow.products.get_by_slug(wanted.slug)
                if existing is None:
                    await uow.products.add(wanted)
                    report.created += 1
                elif update:
                    # One atomic edit: price and sale price are checked together.
                    existing.apply_details({name: getattr(wanted, name) for name in _REFRESHED})
                    await uow.products.save(existing)
                    report.updated += 1
                else:
                    report.skipped += 1
            await uow.commit()
    finally:
        await engine.dispose()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--update", action="store_true",
                        help="refresh details/prices/flags of existing products (never stock)")
    parser.add_argument("--image-base-url", default=None,
                        help="prefix for relative image paths, e.g. a CDN origin")
    parser.add_argument("--file", type=Path, default=DATA_FILE, help="catalog JSON to load")
    args = parser.parse_args(argv)

    report = asyncio.run(
        seed(load_catalog(args.file), update=args.update, image_base_url=args.image_base_url)
    )
    print(f"Catalog seed: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
