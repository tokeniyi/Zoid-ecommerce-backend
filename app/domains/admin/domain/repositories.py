"""Persistence contracts the admin capabilities drive.

Administration owns no aggregate of its own: there is one product, one order and
one user in this store, and an administrator is a *role* that acts on them
("There does not need to be a second copy of every order"). So this module states
what administration requires from persistence by naming the existing contracts,
rather than by re-declaring a privileged copy of them that could drift.

Everything an admin can do therefore goes through exactly the same repository
interface a customer-facing service uses — which is what keeps the admin path
from becoming a back door around the rules.
"""

from __future__ import annotations

from app.domains.orders.domain.repositories import (  # re-export: shared contract
    AbstractOrderRepository,
)
from app.domains.products.domain.repositories import (  # re-export: shared contract
    AbstractProductRepository,
)
from app.domains.users.domain.repositories import (  # re-export: shared contract
    AbstractUserRepository,
)

__all__ = [
    "AbstractOrderRepository",
    "AbstractProductRepository",
    "AbstractUserRepository",
]
