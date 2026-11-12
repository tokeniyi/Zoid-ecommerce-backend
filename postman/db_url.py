"""Print the async SQLAlchemy URL for the throwaway end-to-end database.

Reads the standard libpq variables (PGHOST, PGUSER, PGPASSWORD) and E2E_DB, so the
runner never has to spell a credential out in a script. The user and password are
percent-encoded, which a hand-built URL would get wrong for any password containing
``@``, ``:`` or ``/``. With no PGPASSWORD the URL carries none and the driver falls
back to ``~/.pgpass``.
"""

import os
from urllib.parse import quote

user = quote(os.environ.get("PGUSER", "postgres"), safe="")
password = os.environ.get("PGPASSWORD", "")
auth = user + (f":{quote(password, safe='')}" if password else "")
host = os.environ.get("PGHOST", "localhost")
print(f"postgresql+asyncpg://{auth}@{host}:5432/{os.environ['E2E_DB']}")
