"""Generate the Postman collection and environment for the Zoid backend.

    python postman/build_collection.py --base-url http://localhost:8000 ...

Why generated rather than hand-written: ~230 requests with shared helpers and
expected values derived from the seed data are far easier to review and keep
correct as code than as exported JSON. Standard library only; the output is plain
Postman v2.1 and runs unchanged in the Postman app, Newman or the Postman CLI.

How the collection works
------------------------
* It tells one story in dependency order (catalog -> auth -> carts -> checkout ->
  payments -> admin -> archives -> hygiene) against a freshly seeded database.
* Several people take part (a guest, two customers, an admin) but the runner has a
  single cookie jar, and cookies are kept per host. So each person is given their
  own loopback address (everything in 127.0.0.0/8 reaches the same server); a
  request made "as" someone is sent to their address and carries exactly their
  cookies, which can never leak into anyone else's. No clearing, no races.
* Payments and image storage talk to stand-ins (``mock_services.py``); a test
  plays the customer on the "payment page" by calling the stand-in's ``/__mock``
  routes, and signs webhooks with the same HMAC-SHA512 the real provider uses.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
API = "{{baseUrl}}/api/v1"

#: Each person's own address: cookies are per host, so identities cannot mix.
IDENTITY_HOSTS = {
    "guestA": "127.0.0.11", "custA": "127.0.0.12", "custB": "127.0.0.13",
    "admin": "127.0.0.14", "visitor": "127.0.0.15",
}


def api_base(who: str | None) -> str:
    if who is None:
        return API
    return f"http://{IDENTITY_HOSTS[who]}:{{{{apiPort}}}}/api/v1"
CATALOG = json.loads((ROOT / "app" / "cli" / "data" / "catalog.json").read_text("utf-8"))

# ── JavaScript shared by every script ───────────────────────────────────

PRELUDE = textwrap.dedent(r"""
    const J = () => { try { return pm.response.json(); } catch (e) { return {}; } };
    const status = (code) => pm.test('status is ' + code, () => pm.response.to.have.status(code));
    const v = (k) => pm.variables.get(k);  // sees the environment and the collection
    const set = (k, x) => pm.collectionVariables.set(k, String(x));
    const keep = (who, name) => {
      const c = pm.cookies.get(name);
      if (c && who === 'guestA') set('guestCartId', c);
      return !!c;
    };
    const cents = (s) => Math.round(parseFloat(s) * 100);
    const isMoney = (s) => typeof s === 'string' && /^-?\d+\.\d{2}$/.test(s);
    const slugsOf = (r) => (r.items || []).map((i) => i.slug).sort();
    const sameSet = (got, want) => pm.expect(got.slice().sort()).to.eql(want.slice().sort());
    const detail = () => (J().detail || '') + '';
    const hasHeader = (name) => pm.response.headers.has(name);
    const header = (name) => (pm.response.headers.get(name) || '') + '';
""").strip()

def _lines(script: str) -> list[str]:
    return textwrap.dedent(script).strip("\n").split("\n")


def request(
    name: str,
    method: str,
    path: str,
    *,
    as_: str | None = None,
    body: object | None = None,
    raw: str | None = None,
    file: str | None = None,
    query: str = "",
    headers: dict[str, str] | None = None,
    pre: str | None = None,
    test: str | None = None,
    absolute: bool = False,
) -> dict:
    """One Postman request. ``path`` is under /api/v1 unless ``absolute``."""
    url = (path if absolute else api_base(as_) + path) + (f"?{query}" if query else "")
    header_list = [{"key": k, "value": v} for k, v in (headers or {}).items()]
    req: dict = {"method": method, "header": header_list, "url": url}
    if body is not None:
        header_list.append({"key": "Content-Type", "value": "application/json"})
        req["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2),
                       "options": {"raw": {"language": "json"}}}
    elif raw is not None:
        req["body"] = {"mode": "raw", "raw": raw}
    elif file is not None:
        req["body"] = {"mode": "file", "file": {"src": file}}
    events = []
    if pre:
        events.append({"listen": "prerequest", "script": {
            "type": "text/javascript", "exec": PRELUDE.split("\n") + _lines(pre)}})
    if test:
        events.append({"listen": "test", "script": {
            "type": "text/javascript", "exec": PRELUDE.split("\n") + _lines(test)}})
    item: dict = {"name": name, "request": req}
    if events:
        item["event"] = events
    return item


def folder(name: str, items: list[dict], description: str = "") -> dict:
    out: dict = {"name": name, "item": items}
    if description:
        out["description"] = description
    return out


def status_only(code: int) -> str:
    return f"status({code});"


# ── expected catalog answers, computed from the very data the backend seeds ──

def slugs_where(predicate) -> list[str]:
    return sorted(p["slug"] for p in CATALOG if predicate(p))


def js(value: object) -> str:
    return json.dumps(value)


def stock_of(slug: str) -> dict[str, int]:
    product = next(p for p in CATALOG if p["slug"] == slug)
    return {s["size"]: s["quantity"] for s in product["sizes"]}


MILAN = next(p for p in CATALOG if p["slug"] == "ac-milan-2526")
GYM = next(p for p in CATALOG if p["slug"] == "zoid-pro-gym-set")
MILAN_PRICE = float(MILAN["price"])
GYM_PRICE = float(GYM["price"])
CUSTOM_FEE = 2000.0
STANDARD_FEE = 2500.0


def money(value: float) -> str:
    return f"{value:.2f}"


# ── the folders ─────────────────────────────────────────────────────────

def setup() -> dict:
    return folder("00 Setup", [
        request("API is alive", "GET", "{{baseUrl}}/health", absolute=True,
                pre="set('runId', Date.now().toString(36));",
                test="""
                    status(200);
                    pm.test('reports ok', () => pm.expect(J().status).to.equal('ok'));
                    pm.test('names the service', () => pm.expect(J().service).to.be.a('string'));
                    pm.test('run id assigned', () => pm.expect(v('runId')).to.be.a('string'));
                """),
        request("Stand-in services are alive", "GET", "{{mockUrl}}/__mock/health", absolute=True,
                test="status(200); pm.test('mock up', () => pm.expect(J().status).to.equal(true));"),
        request("Reset stand-ins", "POST", "{{mockUrl}}/__mock/reset", absolute=True,
                test="status(200);"),
        request("OpenAPI contract is published", "GET", "{{baseUrl}}/openapi.json", absolute=True,
                test="""
                    status(200);
                    const paths = J().paths || {};
                    pm.test('lists the API', () => pm.expect(Object.keys(paths).length).to.be.above(30));
                    pm.test('under the versioned prefix', () =>
                      pm.expect(Object.keys(paths)).to.include('/api/v1/products'));
                """),
    ])


def catalog_folder() -> dict:
    gym = slugs_where(lambda p: p["style"] == "Gym Kit")
    black = slugs_where(lambda p: p["color"].lower() == "black")
    size_s = slugs_where(lambda p: any(s["size"] == "S" for s in p["sizes"]))
    bestsellers = slugs_where(lambda p: p["is_bestseller"])
    specials = slugs_where(lambda p: p["is_special"])
    arrivals = slugs_where(lambda p: p["is_new_arrival"])
    on_sale = slugs_where(lambda p: p["original_price"] is not None)
    not_sale = slugs_where(lambda p: p["original_price"] is None)
    red_jersey = slugs_where(lambda p: p["style"] == "Jersey" and p["color"] == "Red")
    in_range = slugs_where(lambda p: 55000 <= float(p["price"]) <= 60000)
    prices_asc = sorted(float(p["price"]) for p in CATALOG)
    categories = sorted({p["category"]["slug"] for p in CATALOG})
    gym_cat = slugs_where(lambda p: p["category"]["slug"] == "gym-kits")

    def listing(name, query, want, extra=""):
        return request(name, "GET", "/products", query=query + "&page_size=100", test=f"""
            status(200);
            pm.test('exactly the expected products', () => sameSet(slugsOf(J()), {js(want)}));
            pm.test('total counts the filtered set', () => pm.expect(J().total).to.equal({len(want)}));
            {extra}
        """)

    return folder("01 Catalog (public)", [
        request("List products: first page", "GET", "/products", test=f"""
            status(200);
            const r = J();
            pm.test('the seeded catalog', () => pm.expect(r.total).to.equal({len(CATALOG)}));
            pm.test('paged by default', () => {{
              pm.expect(r.page).to.equal(1); pm.expect(r.page_size).to.equal(20);
              pm.expect(r.items.length).to.equal(20); pm.expect(r.total_pages).to.equal(2);
            }});
            pm.test('each product has the storefront card fields', () => r.items.forEach((p) => {{
              ['id','slug','name','category','price','original_price','discount_percent',
               'currency','image','sizes','stock','is_bestseller','is_special','is_new_arrival']
                .forEach((k) => pm.expect(p).to.have.property(k));
              pm.expect(isMoney(p.price)).to.equal(true);
              pm.expect(p.currency).to.equal('NGN');
            }}));
            pm.test('oldest first by default', () => {{
              const ids = r.items.map((p) => p.id);
              pm.expect(ids).to.eql(ids.slice().sort((a, b) => a - b));
            }});
        """),
        request("List products: second page", "GET", "/products", query="page=2&page_size=20",
                test=f"""
                    status(200);
                    pm.test('the remainder', () => {{
                      pm.expect(J().items.length).to.equal({len(CATALOG) - 20});
                      pm.expect(J().page).to.equal(2);
                    }});
                """),
        request("Page size above the limit is refused", "GET", "/products",
                query="page_size=101", test="status(422);"),
        request("Page zero is refused", "GET", "/products", query="page=0", test="status(422);"),
        listing("Filter: style", "style=gym%20kit", gym),
        listing("Filter: colour (case-insensitive)", "color=BLACK", black),
        listing("Filter: size offered", "size=S", size_s),
        listing("Filter: category slug", "category=gym-kits", gym_cat),
        listing("Filter: price range", "min_price=55000&max_price=60000", in_range),
        listing("Filter: bestsellers", "bestseller=true", bestsellers),
        listing("Filter: special kits", "special=true", specials),
        listing("Filter: new arrivals", "new_arrival=true", arrivals),
        listing("Filter: on sale", "on_sale=true", on_sale),
        listing("Filter: not on sale", "on_sale=false", not_sale),
        listing("Filters combine", "style=Jersey&color=Red", red_jersey),
        request("Search tolerates a typo", "GET", "/products", query="q=liverpol", test="""
            status(200);
            pm.test('finds Liverpool', () => pm.expect(slugsOf(J())).to.include('liverpool-2526'));
            pm.test('best match first', () => pm.expect(J().items[0].slug).to.equal('liverpool-2526'));
        """),
        request("Search matches a word from the details", "GET", "/products", query="q=gym", test="""
            status(200);
            pm.test('gym kits found', () => pm.expect(slugsOf(J())).to.include('zoid-pro-gym-set'));
        """),
        request("Search with no match", "GET", "/products", query="q=xqzvbnm", test="""
            status(200);
            pm.test('nothing', () => { pm.expect(J().total).to.equal(0); pm.expect(J().items).to.eql([]); });
        """),
        request("Sort by price, lowest first", "GET", "/products",
                query="sort=price_asc&page_size=100", test=f"""
            status(200);
            const prices = J().items.map((p) => parseFloat(p.price));
            pm.test('ascending', () => pm.expect(prices).to.eql({js(prices_asc)}));
        """),
        request("Sort by price, highest first", "GET", "/products",
                query="sort=price_desc&page_size=100", test=f"""
            status(200);
            const prices = J().items.map((p) => parseFloat(p.price));
            pm.test('descending', () => pm.expect(prices).to.eql({js(list(reversed(prices_asc)))}));
        """),
        request("Unknown sort is refused", "GET", "/products", query="sort=sideways",
                test="status(422);"),
        request("Negative price filter is refused", "GET", "/products", query="min_price=-1",
                test="status(422);"),
        request("Hostile search text is just text", "GET", "/products",
                query="q=%27%3B%20DROP%20TABLE%20products%3B--", test="""
            status(200);
            pm.test('an ordinary answer, no error', () => pm.expect(J().items).to.be.an('array'));
        """),
        request("...and the catalog is intact afterwards", "GET", "/products", query="page_size=1",
                test=f"status(200); pm.test('still all of it', () => pm.expect(J().total).to.equal({len(CATALOG)}));"),
        request("Product detail by slug", "GET", "/products/ac-milan-2526", test=f"""
            status(200);
            const p = J();
            pm.test('identity', () => {{ pm.expect(p.slug).to.equal('ac-milan-2526'); set('milanId', p.id); }});
            pm.test('price, original price and a computed discount', () => {{
              pm.expect(p.price).to.equal('{money(MILAN_PRICE)}');
              pm.expect(p.original_price).to.equal('{money(float(MILAN["original_price"]))}');
              pm.expect(p.discount_percent).to.equal(14);
            }});
            pm.test('flags', () => {{
              pm.expect(p.is_bestseller).to.equal({js(MILAN["is_bestseller"])});
              pm.expect(p.is_new_arrival).to.equal({js(MILAN["is_new_arrival"])});
            }});
            pm.test('sizes and live stock', () => {{
              pm.expect(p.sizes).to.eql({js([s["size"] for s in MILAN["sizes"]])});
              pm.expect(p.stock).to.eql({js(stock_of("ac-milan-2526"))});
            }});
            pm.test('three gallery views', () =>
              pm.expect(p.gallery.map((g) => g.view)).to.eql(['front', 'back', 'detail']));
            pm.test('detail fields', () => ['tone','style','color','fit','fit_note','details','delivery']
              .forEach((k) => pm.expect(p[k]).to.be.a('string')));
        """),
        request("Product detail by numeric id", "GET", "/products/{{milanId}}", test="""
            status(200);
            pm.test('same product', () => pm.expect(J().slug).to.equal('ac-milan-2526'));
        """),
        request("Unknown product is not found", "GET", "/products/no-such-jersey", test="""
            status(404);
            pm.test('plain error shape', () => pm.expect(J()).to.have.property('detail'));
        """),
        request("Categories", "GET", "/categories", test=f"""
            status(200);
            pm.test('the six seeded categories', () => {{
              pm.expect(J().map((c) => c.slug).sort()).to.eql({js(categories)});
              J().forEach((c) => ['id','name','slug'].forEach((k) => pm.expect(c).to.have.property(k)));
            }});
        """),
    ])


def delivery_folder() -> dict:
    def quote(name, body, **expect):
        checks = "\n".join(
            f"pm.test('{key}', () => pm.expect(q.{key}).to.equal({js(value)}));"
            for key, value in expect.items()
        )
        return request(name, "POST", "/delivery/quote", body=body, test=f"""
            status(200);
            const q = J();
            {checks}
        """)

    lagos = {"option": "standard", "state": "Lagos State", "city": "Ikeja", "address": "5 Allen Ave"}
    return folder("02 Delivery quotes (public)", [
        quote("Standard delivery in Lagos", lagos, fee="2500.00", support_required=False,
              currency="NGN", is_student=False),
        quote("State typed casually", {**lagos, "state": "lagos"}, fee="2500.00", state="Lagos State"),
        quote("Express costs more", {**lagos, "option": "express"}, fee="4500.00"),
        quote("Ogun State", {**lagos, "state": "Ogun State", "city": "Abeokuta"}, fee="2500.00"),
        quote("Port Harcourt district", {**lagos, "state": "Rivers", "city": "Old GRA"}, fee="2500.00"),
        quote("PH is understood as Port Harcourt", {**lagos, "state": "PH", "city": "Port Harcourt"},
              fee="2500.00", state="Rivers State"),
        quote("Campus delivery is a student order",
              {"option": "standard", "university": "Covenant University, Ota",
               "hostel_room": "Hall 3, Room 12"},
              fee="2500.00", is_student=True, state="Ogun State"),
        quote("Rivers outside Port Harcourt needs the shop",
              {**lagos, "state": "Rivers State", "city": "Bonny"},
              fee=None, support_required=True),
        quote("A town that only looks like a district is not served",
              {**lagos, "state": "Rivers State", "city": "Elele"}, fee=None, support_required=True),
        quote("Far away needs the shop", {**lagos, "state": "Kano", "city": "Kano"},
              fee=None, support_required=True),
        quote("Verified GUO terminal is free and confirmed",
              {"option": "pickup", "state": "Lagos State",
               "terminal": "Ojota Terminal (7 Ikorodu Road, Ojota)"},
              fee="0.00", terminal_pending=False, support_required=False),
        quote("Unlisted terminal is accepted but flagged",
              {"option": "pickup", "state": "Bauchi", "terminal": "Bauchi Motor Park"},
              fee="0.00", terminal_pending=True),
        quote("An enquiry is never priced", {"option": "enquiry", "state": "Lagos"},
              fee=None, support_required=True),
        request("Incomplete form is refused", "POST", "/delivery/quote",
                body={"option": "standard", "state": "Lagos State"}, test="status(422);"),
        request("A home address needs a city", "POST", "/delivery/quote",
                body={**lagos, "city": ""}, test="status(422); pm.test('says what is missing', () => pm.expect(detail()).to.match(/city/));"),
        request("Unknown option is refused", "POST", "/delivery/quote",
                body={"option": "teleport"}, test="status(422);"),
        request("Empty body is refused", "POST", "/delivery/quote", body={}, test="status(422);"),
    ], "Delivery is priced by the server from the shop's rate table; clients never send an amount.")


def auth_folder() -> dict:
    def person(label, who):
        return f"{who}-{{{{runId}}}}@zoidjerseys.com", label

    email_a, email_b = "shopper-a-{{runId}}@zoidjerseys.com", "shopper-b-{{runId}}@zoidjerseys.com"
    return folder("03 Accounts, sessions and profile", [
        request("Sign up shopper A", "POST", "/auth/signup",
                body={"name": "Ada Shopper", "email": email_a, "phone": "+234 801 111 1111",
                      "password": "shopper-a-password"}, test="""
            status(201);
            const u = J();
            pm.test('the new customer', () => {
              pm.expect(u.email).to.equal(pm.variables.replaceIn('shopper-a-{{runId}}@zoidjerseys.com'));
              pm.expect(u.role).to.equal('customer'); pm.expect(u.name).to.equal('Ada Shopper');
              set('userA', u.id);
            });
            pm.test('never echoes a password or hash', () => pm.expect(JSON.stringify(u)).to.not.match(/passw|hash/i));
            pm.test('signup does not sign you in', () => pm.expect(pm.cookies.get('app_session_id')).to.equal(undefined));
        """),
        request("Sign up shopper B", "POST", "/auth/signup",
                body={"name": "Bola Shopper", "email": email_b, "password": "shopper-b-password"},
                test="status(201); set('userB', J().id);"),
        request("Duplicate email is a conflict", "POST", "/auth/signup",
                body={"name": "Ada Again", "email": email_a, "password": "another-password"},
                test="status(409); pm.test('says why', () => pm.expect(detail()).to.match(/already exists/));"),
        request("Duplicate email in other case is still a conflict", "POST", "/auth/signup",
                body={"name": "Ada Again", "email": "{{shopperAUpper}}", "password": "another-password"},
                pre="set('shopperAUpper', ('shopper-a-' + v('runId') + '@zoidjerseys.com').toUpperCase());",
                test="status(409);"),
        request("Invalid email is refused", "POST", "/auth/signup",
                body={"name": "X", "email": "not-an-email", "password": "long-enough-1"},
                test="status(422);"),
        request("Short password is refused", "POST", "/auth/signup",
                body={"name": "X", "email": "x-{{runId}}@zoidjerseys.com", "password": "short"},
                test="status(422);"),
        request("Missing fields are refused", "POST", "/auth/signup", body={"email": "y@zoidjerseys.com"},
                test="status(422);"),
        request("Wrong password", "POST", "/auth/login",
                body={"email": email_a, "password": "not-the-password"}, test="""
            status(401); set('badLoginMessage', detail());
            pm.test('no cookie issued', () => pm.expect(pm.cookies.get('app_session_id')).to.equal(undefined));
        """),
        request("Unknown email says the same thing", "POST", "/auth/login",
                body={"email": "ghost-{{runId}}@zoidjerseys.com", "password": "whatever-123"}, test="""
            status(401);
            pm.test('indistinguishable from a wrong password', () => pm.expect(detail()).to.equal(v('badLoginMessage')));
        """),
        request("Log in as shopper A", "POST", "/auth/login", as_="custA",
                body={"email": email_a, "password": "shopper-a-password"}, test="""
            status(200);
            pm.test('the customer', () => { pm.expect(J().role).to.equal('customer'); pm.expect(J().id).to.equal(parseInt(v('userA'))); });
            pm.test('a session cookie is issued', () => pm.expect(keep('custA', 'app_session_id')).to.equal(true));
            pm.test('cookie is HttpOnly', () => pm.expect(header('Set-Cookie')).to.match(/HttpOnly/i));
        """),
        request("Log in as shopper B", "POST", "/auth/login", as_="custB",
                body={"email": email_b, "password": "shopper-b-password"},
                test="status(200); pm.test('cookie', () => pm.expect(keep('custB', 'app_session_id')).to.equal(true));"),
        request("Log in as the admin", "POST", "/auth/login", as_="admin",
                body={"email": "{{adminEmail}}", "password": "{{adminPassword}}"}, test="""
            status(200);
            pm.test('an administrator', () => pm.expect(J().role).to.equal('admin'));
            pm.test('cookie', () => pm.expect(keep('admin', 'app_session_id')).to.equal(true));
        """),
        request("Who am I (shopper A)", "GET", "/auth/me", as_="custA", test="""
            status(200);
            pm.test('A', () => pm.expect(J().id).to.equal(parseInt(v('userA'))));
        """),
        request("Who am I (anonymous)", "GET", "/auth/me", test="""
            status(401); pm.test('says so', () => pm.expect(detail()).to.match(/Not authenticated/));
        """),
        request("A garbage cookie is not a session", "GET", "/auth/me",
                headers={"Cookie": "app_session_id=not.a.real.token"}, test="status(401);"),
        request("Profile", "GET", "/users/me", as_="custA", test="""
            status(200);
            pm.test('profile shape', () => ['id','name','email','phone','role','created_at']
              .forEach((k) => pm.expect(J()).to.have.property(k)));
        """),
        request("Update profile", "PUT", "/users/me", as_="custA",
                body={"name": "Ada Z. Shopper", "phone": "+234 802 222 2222"}, test="""
            status(200);
            pm.test('changed', () => { pm.expect(J().name).to.equal('Ada Z. Shopper'); pm.expect(J().phone).to.equal('+234 802 222 2222'); });
            pm.test('identity untouched', () => pm.expect(J().role).to.equal('customer'));
        """),
        request("Profile edit cannot make you an admin", "PUT", "/users/me", as_="custA",
                body={"role": "admin", "name": "Ada Z. Shopper"}, test="""
            status(200);
            pm.test('still a customer', () => pm.expect(J().role).to.equal('customer'));
        """),
        request("Profile edit with an empty name is refused", "PUT", "/users/me", as_="custA",
                body={"name": ""}, test="status(422);"),
        request("Log out clears the cookie", "POST", "/auth/logout", as_="custB", test="""
            status(200);
            pm.test('the cookie is expired', () => pm.expect(header('Set-Cookie')).to.match(/app_session_id=""?;.*Max-Age=0/));
        """),
        request("Shopper B logs in again", "POST", "/auth/login", as_="custB",
                body={"email": email_b, "password": "shopper-b-password"},
                test="status(200); keep('custB', 'app_session_id');"),
    ])


def guest_cart_folder() -> dict:
    def add(name, slug, size, qty, text="", expect_status=200, who="guestA", test=""):
        body = {"product_slug": slug, "size": size, "quantity": qty}
        if text:
            body["customization"] = text
        return request(name, "POST", "/cart/items", as_=who, body=body, test=f"""
            status({expect_status});
            {test}
        """)

    keep_guest = "pm.test('guest cookie kept', () => pm.expect(keep('guestA', 'guest_cart_id')).to.equal(true));"
    return folder("04 Guest cart", [
        request("A first visit gets a guest cart", "GET", "/cart", test="""
            status(200);
            pm.test('empty', () => { pm.expect(J().items).to.eql([]); pm.expect(J().count).to.equal(0); pm.expect(J().total).to.equal('0.00'); });
            pm.test('a guest cookie is issued', () => pm.expect(keep('guestA', 'guest_cart_id')).to.equal(true));
        """),
        add("Add a personalised jersey", "ac-milan-2526", "M", 1, "Name: EDDY, #10", test=f"""
            const c = J();
            pm.test('one line with its text', () => {{
              pm.expect(c.items.length).to.equal(1);
              pm.expect(c.items[0].customization).to.equal('Name: EDDY, #10');
              pm.expect(c.items[0].unit_price).to.equal('{money(MILAN_PRICE)}');
            }});
            {keep_guest}
        """),
        add("Same shirt, same text (other case) merges", "ac-milan-2526", "M", 1, "name: eddy, #10",
            test="""
            pm.test('one line, quantity 2', () => {
              pm.expect(J().items.length).to.equal(1); pm.expect(J().items[0].quantity).to.equal(2);
            });
        """),
        add("Same shirt with no text is a separate line", "ac-milan-2526", "M", 1, test="""
            pm.test('two lines', () => pm.expect(J().items.length).to.equal(2));
            pm.test('the plain one has no text', () => pm.expect(J().items.map((i) => i.customization).sort()).to.eql(['', 'Name: EDDY, #10']));
            set('plainLine', J().items.find((i) => i.customization === '').id);
            set('textLine', J().items.find((i) => i.customization !== '').id);
        """),
        add("A gym kit with text (not charged later)", "zoid-pro-gym-set", "L", 1, "Name: ADA, #7",
            test="pm.test('three lines', () => pm.expect(J().items.length).to.equal(3));"),
        request("Change a line's quantity", "PATCH", "/cart/items/{{plainLine}}", as_="guestA",
                body={"quantity": 3}, test=f"""
            status(200);
            pm.test('only that line moved', () => {{
              const line = J().items.find((i) => i.id === parseInt(v('plainLine')));
              pm.expect(line.quantity).to.equal(3);
              pm.expect(line.line_total).to.equal('{money(MILAN_PRICE * 3)}');
              pm.expect(J().count).to.equal(6);
            }});
        """),
        request("Remove a line", "DELETE", "/cart/items/{{plainLine}}", as_="guestA", test=f"""
            status(200);
            pm.test('two lines left', () => {{ pm.expect(J().items.length).to.equal(2); pm.expect(J().count).to.equal(3); }});
            pm.test('total follows', () => pm.expect(J().total).to.equal('{money(MILAN_PRICE * 2 + GYM_PRICE)}'));
        """),
        add("Unknown size is refused", "ac-milan-2526", "XXL", 1, expect_status=422),
        add("Unknown product is not found", "no-such-jersey", "M", 1, expect_status=404),
        add("Quantity zero is refused", "ac-milan-2526", "M", 0, expect_status=422),
        add("Quantity over the cap is refused", "ac-milan-2526", "M", 100, expect_status=422),
        add("Overlong personalisation is refused", "ac-milan-2526", "M", 1, "x" * 101, expect_status=422),
        request("Quantity zero on an existing line is refused", "PATCH", "/cart/items/{{textLine}}",
                as_="guestA", body={"quantity": 0}, test="status(422);"),
        request("A line that is not yours cannot be touched", "PATCH", "/cart/items/{{textLine}}",
                as_="custB", body={"quantity": 9}, test="""
            pm.test('refused, not applied', () => pm.expect(pm.response.code).to.be.oneOf([404, 422]));
        """),
        request("The cart persists across requests", "GET", "/cart", as_="guestA", test="""
            status(200);
            pm.test('same two lines', () => { pm.expect(J().items.length).to.equal(2); pm.expect(J().count).to.equal(3); });
        """),
        request("Another visitor has their own empty cart", "GET", "/cart", as_="visitor", test="""
            status(200); pm.test('empty', () => pm.expect(J().count).to.equal(0));
        """),
        request("Merge needs a login", "POST", "/cart/merge", as_="guestA", test="status(401);"),
    ])


def merge_and_wishlist_folder() -> dict:
    return folder("05 Cart merge and wishlist", [
        request("Signing in folds the guest cart into the shopper's", "POST", "/cart/merge",
                as_="custA", headers={"Cookie": "guest_cart_id={{guestCartId}}"}, test=f"""
            status(200);
            pm.test('the guest lines arrived', () => {{
              pm.expect(J().items.length).to.equal(2); pm.expect(J().count).to.equal(3);
              pm.expect(J().total).to.equal('{money(MILAN_PRICE * 2 + GYM_PRICE)}');
            }});
            pm.test('the guest cookie is retired', () => pm.expect(header('Set-Cookie')).to.match(/guest_cart_id=""?;.*Max-Age=0/));
        """),
        request("Merging the same guest cart again finds nothing", "POST", "/cart/merge",
                as_="custA", headers={"Cookie": "guest_cart_id={{guestCartId}}"}, test="status(404);"),
        request("The shopper's cart now holds the lines", "GET", "/cart", as_="custA", test="""
            status(200); pm.test('three units', () => pm.expect(J().count).to.equal(3));
        """),
        request("Add a plain jersey to the shopper's cart", "POST", "/cart/items", as_="custA",
                body={"product_slug": "ac-milan-2526", "size": "M", "quantity": 1}, test="""
            status(200);
            pm.test('a third line', () => { pm.expect(J().items.length).to.equal(3); pm.expect(J().count).to.equal(4); });
        """),
        request("Wishlist needs a login", "GET", "/wishlist", test="status(401);"),
        request("Save a product", "POST", "/wishlist/items", as_="custA",
                body={"product_slug": "liverpool-2526"}, test="""
            status(200);
            pm.test('saved with its card data', () => {
              pm.expect(J().count).to.equal(1);
              const i = J().items[0];
              pm.expect(i.product_slug).to.equal('liverpool-2526');
              pm.expect(isMoney(i.price)).to.equal(true);
            });
        """),
        request("Saving it twice changes nothing", "POST", "/wishlist/items", as_="custA",
                body={"product_slug": "liverpool-2526"}, test="""
            status(200); pm.test('still one', () => pm.expect(J().count).to.equal(1));
        """),
        request("Save a second product", "POST", "/wishlist/items", as_="custA",
                body={"product_slug": "ac-milan-2526"}, test="status(200); pm.test('two', () => pm.expect(J().count).to.equal(2));"),
        request("Saving an unknown product is not found", "POST", "/wishlist/items", as_="custA",
                body={"product_slug": "no-such-jersey"}, test="status(404);"),
        request("A wishlist is private", "GET", "/wishlist", as_="custB", test="""
            status(200); pm.test('B sees none of A', () => pm.expect(J().count).to.equal(0));
        """),
        request("Read my wishlist", "GET", "/wishlist", as_="custA", test="""
            status(200);
            pm.test('both products', () => pm.expect(J().items.map((i) => i.product_slug).sort()).to.eql(['ac-milan-2526', 'liverpool-2526']));
        """),
        request("Remove a product", "DELETE", "/wishlist/items/liverpool-2526", as_="custA",
                test="status(200); pm.test('one left', () => pm.expect(J().count).to.equal(1));"),
        request("Removing it again is not found", "DELETE", "/wishlist/items/liverpool-2526",
                as_="custA", test="status(404);"),
    ])


CONTACT = {"contact_name": "Ada Shopper", "contact_email": "ada@zoidjerseys.com",
           "contact_phone": "+234 801 111 1111"}
LAGOS_HOME = {"option": "standard", "state": "Lagos State", "city": "Ikeja", "address": "5 Allen Avenue"}


def checkout_folder() -> dict:
    goods = MILAN_PRICE * 3 + GYM_PRICE
    total = goods + CUSTOM_FEE * 2 + STANDARD_FEE

    def refused(name, delivery, who="custA", needle="", extra=None):
        body = {**CONTACT, **(extra or {})}
        if delivery is not None:
            body["delivery"] = delivery
        return request(name, "POST", "/orders", as_=who, body=body, test=f"""
            status(422);
            {f"pm.test('says why', () => pm.expect(detail()).to.match(/{needle}/i));" if needle else ""}
        """)

    return folder("06 Checkout and orders", [
        request("Checkout needs a login", "POST", "/orders", body={**CONTACT, "delivery": LAGOS_HOME},
                test="status(401);"),
        refused("An empty cart cannot be ordered", LAGOS_HOME, who="custB", needle="empty"),
        refused("Delivery is required", None),
        refused("An unserved place is refused", {"option": "standard", "state": "Kano", "city": "Kano",
                                                  "address": "1 Road"}, needle="not available"),
        refused("An enquiry is not a checkout", {"option": "enquiry", "state": "Lagos State"}),
        refused("An incomplete address is refused", {"option": "standard", "state": "Lagos State"}),
        request("Contact details are required", "POST", "/orders", as_="custA",
                body={"delivery": LAGOS_HOME}, test="status(422);"),
        request("Refused checkouts left the cart and stock alone", "GET", "/cart", as_="custA", test="""
            status(200); pm.test('still four units', () => pm.expect(J().count).to.equal(4));
        """),
        request("Stock was not reserved by the refusals", "GET", "/products/ac-milan-2526", test=f"""
            status(200);
            pm.test('unchanged', () => pm.expect(J().stock).to.eql({js(stock_of("ac-milan-2526"))}));
        """),
        request("Check out: the server prices everything", "POST", "/orders", as_="custA",
                body={**CONTACT, "delivery": LAGOS_HOME, "notes": "Call at the gate",
                      "total": "1.00", "delivery_fee": "0"}, test=f"""
            status(201);
            const o = J();
            set('order1', o.id); set('order1Ref', o.reference); set('order1Total', o.total);
            pm.test('starts unpaid and unfulfilled', () => {{
              pm.expect(o.status).to.equal('PENDING_PAYMENT'); pm.expect(o.payment_status).to.equal('pending');
              pm.expect(o.fulfillment_status).to.equal('processing');
              pm.expect(o.payment_reference).to.equal(null);
            }});
            pm.test('goods + personalisation + delivery, as the server priced them', () => {{
              pm.expect(o.subtotal).to.equal('{money(goods)}');
              pm.expect(o.customization_total).to.equal('{money(CUSTOM_FEE * 2)}');
              pm.expect(o.delivery.fee).to.equal('{money(STANDARD_FEE)}');
              pm.expect(o.total).to.equal('{money(total)}');
              pm.expect(cents(o.total)).to.equal(cents(o.subtotal) + cents(o.customization_total) + cents(o.delivery.fee));
            }});
            pm.test('a client-sent total is ignored', () => pm.expect(o.total).to.not.equal('1.00'));
            pm.test('only jerseys are charged for personalisation', () => {{
              const fees = {{}}; o.items.forEach((i) => {{ fees[i.product_slug + '|' + i.customization] = i.customization_fee; }});
              pm.expect(fees['ac-milan-2526|Name: EDDY, #10']).to.equal('2000.00');
              pm.expect(fees['zoid-pro-gym-set|Name: ADA, #7']).to.equal('0.00');
              pm.expect(fees['ac-milan-2526|']).to.equal('0.00');
            }});
            pm.test('records where it goes', () => {{
              pm.expect(o.delivery.option).to.equal('standard'); pm.expect(o.delivery.state).to.equal('Lagos State');
              pm.expect(o.delivery.is_student).to.equal(false);
              pm.expect(o.address_line).to.equal('5 Allen Avenue'); pm.expect(o.city_state).to.equal('Ikeja, Lagos State');
              pm.expect(o.notes).to.equal('Call at the gate');
            }});
            pm.test('has a quotable reference', () => pm.expect(o.reference).to.match(/^ZD-[0-9A-F]{{8}}$/));
        """),
        request("The cart was consumed by the order", "GET", "/cart", as_="custA", test="""
            status(200); pm.test('empty', () => pm.expect(J().count).to.equal(0));
        """),
        request("Stock is now reserved for it", "GET", "/products/ac-milan-2526", test=f"""
            status(200);
            pm.test('M is down by the three ordered', () => pm.expect(J().stock.M).to.equal({stock_of("ac-milan-2526")["M"] - 3}));
        """),
        request("Order history lists it with its lines", "GET", "/orders", as_="custA", test="""
            status(200);
            pm.test('one order, with items', () => {
              pm.expect(J().length).to.equal(1);
              pm.expect(J()[0].id).to.equal(parseInt(v('order1')));
              pm.expect(J()[0].items.length).to.equal(3);
              pm.expect(J()[0].payment_status).to.equal('pending');
            });
        """),
        request("Read one order", "GET", "/orders/{{order1}}", as_="custA", test="""
            status(200); pm.test('mine', () => pm.expect(J().reference).to.equal(v('order1Ref')));
        """),
        request("Someone else's order is not found", "GET", "/orders/{{order1}}", as_="custB",
                test="status(404);"),
        request("An order needs a login to read", "GET", "/orders/{{order1}}", test="status(401);"),
        request("Unknown order", "GET", "/orders/999999", as_="custA", test="status(404);"),
        request("A second shopper's history is empty", "GET", "/orders", as_="custB", test="""
            status(200); pm.test('none', () => pm.expect(J()).to.eql([]));
        """),
    ])


def payments_folder() -> dict:
    gym_total = GYM_PRICE
    mock = "pm.sendRequest({url: v('mockUrl') + '/__mock/%s', method: 'POST'}, (err) => { if (err) throw err; });"

    def hook(event, *, ref_var, amount_expr, event_id, signed=True, secret="v('webhookSecret')",
             provider="paystack", extra=""):
        body = f"""
            const CryptoJS = require('crypto-js');
            const body = JSON.stringify({{event: {js(event)}, data: {{id: {event_id}, reference: {ref_var},
              amount: {amount_expr}, currency: 'NGN', gateway_reference: 'G-{event_id}'{extra}}}}});
            set('hookBody', body);
        """
        if signed:
            body += f"""
            pm.request.headers.upsert({{key: 'paystack-signature',
              value: CryptoJS.HmacSHA512(body, {secret}).toString(CryptoJS.enc.Hex)}});
            """
        return body

    def post_hook(name, pre, test, provider="paystack"):
        return request(name, "POST", f"/payments/webhooks/{provider}", raw="{{hookBody}}",
                       headers={"Content-Type": "application/json"}, pre=pre, test=test)

    return folder("07 Payments (stand-in Paystack)", [
        request("Paying needs a login", "POST", "/payments/initiate", body={"order_id": 1},
                test="status(401);"),
        request("Another shopper cannot pay my order", "POST", "/payments/initiate", as_="custB",
                body={"order_id": "{{order1}}"}, test="status(404);"),
        request("Start paying for order 1", "POST", "/payments/initiate", as_="custA",
                body={"order_id": "{{order1}}"}, test="""
            status(200);
            const p = J();
            set('payRef1', p.payment_id);
            pm.test('the normalised payment result', () => {
              pm.expect(p.success).to.equal(true); pm.expect(p.status).to.equal('pending');
              pm.expect(p.payment_id).to.match(/^PAY-/);
              pm.expect(p.provider).to.equal('paystack'); pm.expect(p.currency).to.equal('NGN');
            });
            pm.test('charges exactly the order total, delivery and personalisation included', () =>
              pm.expect(p.amount).to.equal(v('order1Total')));
            pm.test('the customer is told to redirect', () => {
              pm.expect(p.next_action.type).to.equal('redirect');
              pm.expect(p.next_action.url).to.match(/^https:\\/\\/checkout\\.mock-paystack\\.test\\//);
            });
        """),
        request("Starting again while pending returns the same payment", "POST", "/payments/initiate",
                as_="custA", body={"order_id": "{{order1}}"}, test="""
            status(200); pm.test('same payment', () => pm.expect(J().payment_id).to.equal(v('payRef1')));
        """),
        request("Verify before the customer has paid", "POST", "/payments/verify", as_="custA",
                body={"reference": "{{payRef1}}"}, test="""
            status(200); pm.test('still pending', () => pm.expect(J().status).to.equal('pending'));
        """),
        request("The order is still unpaid", "GET", "/orders/{{order1}}", as_="custA", test="""
            status(200); pm.test('pending', () => pm.expect(J().payment_status).to.equal('pending'));
        """),
        request("Another shopper cannot verify my payment", "POST", "/payments/verify", as_="custB",
                body={"reference": "{{payRef1}}"}, test="status(404);"),
        request("Unknown payment reference", "POST", "/payments/verify", as_="custA",
                body={"reference": "PAY-NOSUCH000000"}, test="status(404);"),
        request("Reference too short", "POST", "/payments/verify", as_="custA",
                body={"reference": "x"}, test="status(422);"),
        request("The customer pays; the shop verifies with the provider", "POST", "/payments/verify",
                as_="custA", body={"reference": "{{payRef1}}"}, pre=mock % "pay/' + v('payRef1') + '", test="""
            status(200);
            pm.test('paid, on the provider confirming it', () => { pm.expect(J().status).to.equal('paid'); pm.expect(J().success).to.equal(true); });
        """),
        request("The order is now paid, with the payment on record", "GET", "/orders/{{order1}}",
                as_="custA", test="""
            status(200);
            pm.test('payment settled', () => {
              pm.expect(J().payment_status).to.equal('paid'); pm.expect(J().status).to.equal('PAID');
              pm.expect(J().payment_reference).to.equal(v('payRef1')); pm.expect(J().paid_at).to.be.a('string');
            });
            pm.test('fulfilment is its own track and has not started', () => pm.expect(J().fulfillment_status).to.equal('processing'));
        """),
        request("A paid order cannot be paid for again", "POST", "/payments/initiate", as_="custA",
                body={"order_id": "{{order1}}"}, test="status(409);"),
        request("Verifying a settled payment is harmless", "POST", "/payments/verify", as_="custA",
                body={"reference": "{{payRef1}}"}, test="status(200); pm.test('still paid', () => pm.expect(J().status).to.equal('paid'));"),

        # ---- order 2: shopper B, pickup at an unverified terminal, settled by a signed webhook
        request("Shopper B bags a gym kit", "POST", "/cart/items", as_="custB",
                body={"product_slug": "zoid-pro-gym-set", "size": "M", "quantity": 1}, test="status(200);"),
        request("Shopper B orders it for terminal pickup", "POST", "/orders", as_="custB",
                body={"contact_name": "Bola Shopper", "contact_email": "bola@zoidjerseys.com",
                      "contact_phone": "+234 803 333 3333",
                      "delivery": {"option": "pickup", "state": "Bauchi", "terminal": "Bauchi Motor Park"}},
                test=f"""
            status(201);
            const o = J(); set('order2', o.id); set('order2Total', o.total); set('order2Ref', o.reference);
            pm.test('pickup is free, unverified terminal flagged', () => {{
              pm.expect(o.delivery.fee).to.equal('0.00'); pm.expect(o.total).to.equal('{money(gym_total)}');
              pm.expect(o.delivery.terminal_pending).to.equal(true);
              pm.expect(o.address_line).to.equal('GUO terminal pickup: Bauchi Motor Park');
            }});
        """),
        request("Start paying for order 2", "POST", "/payments/initiate", as_="custB",
                body={"order_id": "{{order2}}"}, test="""
            status(200); set('payRef2', J().payment_id); set('payAmount2', Math.round(parseFloat(J().amount) * 100));
        """),
        request("The provider confirms a different amount: refused", "POST", "/payments/verify",
                as_="custB", body={"reference": "{{payRef2}}"},
                pre=mock % "pay/' + v('payRef2') + '?amount=100", test="""
            status(409); pm.test('says the amounts disagree', () => pm.expect(detail()).to.match(/different amount/));
        """),
        request("...and the order stays unpaid", "GET", "/orders/{{order2}}", as_="custB", test="""
            status(200); pm.test('pending', () => pm.expect(J().payment_status).to.equal('pending'));
        """),
        request("The customer pays the right amount on the stand-in", "POST", "{{mockUrl}}/__mock/pay/{{payRef2}}",
                absolute=True, test="status(200);"),
        post_hook("Webhook with no signature is rejected",
                  hook("charge.success", ref_var="v('payRef2')", amount_expr="v('payAmount2')", event_id=8001, signed=False),
                  "status(400); pm.test('refused as a bad signature', () => pm.expect(detail()).to.match(/signature/i));"),
        post_hook("Webhook signed with the wrong secret is rejected",
                  hook("charge.success", ref_var="v('payRef2')", amount_expr="v('payAmount2')", event_id=8002,
                       secret="'not-the-secret'"),
                  "status(400);"),
        post_hook("Webhook for an unknown provider",
                  hook("charge.success", ref_var="v('payRef2')", amount_expr="v('payAmount2')", event_id=8003),
                  "status(404);", provider="nopay"),
        post_hook("Signed webhook without an event is refused",
                  "const CryptoJS = require('crypto-js'); const body = JSON.stringify({data: {}}); set('hookBody', body);"
                  " pm.request.headers.upsert({key: 'paystack-signature', value: CryptoJS.HmacSHA512(body, v('webhookSecret')).toString(CryptoJS.enc.Hex)});",
                  "status(422);"),
        post_hook("A genuine payment notice settles the order",
                  hook("charge.success", ref_var="v('payRef2')", amount_expr="v('payAmount2')", event_id=8010),
                  "status(200); pm.test('applied', () => { pm.expect(J().received).to.equal(true); pm.expect(J().outcome).to.equal('applied'); });"),
        post_hook("The same notice delivered again changes nothing",
                  hook("charge.success", ref_var="v('payRef2')", amount_expr="v('payAmount2')", event_id=8010),
                  "status(200); pm.test('a duplicate', () => pm.expect(J().outcome).to.equal('duplicate'));"),
        post_hook("The same news under a new event id changes nothing",
                  hook("charge.success", ref_var="v('payRef2')", amount_expr="v('payAmount2')", event_id=8011),
                  "status(200); pm.test('accepted without harm', () => pm.expect(J().received).to.equal(true));"),
        post_hook("An event the shop does not act on is recorded and ignored",
                  hook("customeridentification.success", ref_var="v('payRef2')", amount_expr="v('payAmount2')", event_id=8012),
                  "status(200); pm.test('ignored', () => pm.expect(J().outcome).to.equal('ignored'));"),
        post_hook("A notice for a payment we never made",
                  hook("charge.success", ref_var="'PAY-NEVERMADE000'", amount_expr="1000", event_id=8013),
                  "status(200); pm.test('unmatched, answered so the provider stops retrying', () => pm.expect(J().outcome).to.equal('unmatched'));"),
        request("Order 2 is paid by the webhook", "GET", "/orders/{{order2}}", as_="custB", test="""
            status(200);
            pm.test('paid', () => { pm.expect(J().payment_status).to.equal('paid'); pm.expect(J().payment_reference).to.equal(v('payRef2')); });
        """),

        # ---- order 3: shopper A, left unpaid; a notice with the wrong amount cannot settle it
        request("Shopper A bags another gym kit", "POST", "/cart/items", as_="custA",
                body={"product_slug": "zoid-pro-gym-set", "size": "M", "quantity": 1}, test="status(200);"),
        request("Shopper A orders it for Lagos delivery", "POST", "/orders", as_="custA",
                body={**CONTACT, "delivery": LAGOS_HOME}, test=f"""
            status(201);
            const o = J(); set('order3', o.id); set('order3Total', o.total);
            pm.test('goods + delivery', () => pm.expect(o.total).to.equal('{money(GYM_PRICE + STANDARD_FEE)}'));
        """),
        request("Start paying for order 3", "POST", "/payments/initiate", as_="custA",
                body={"order_id": "{{order3}}"}, test="status(200); set('payRef3', J().payment_id);"),
        post_hook("A notice with the wrong amount is disputed, not applied",
                  hook("charge.success", ref_var="v('payRef3')", amount_expr="100", event_id=8020),
                  "status(200); pm.test('disputed', () => pm.expect(J().outcome).to.equal('disputed'));"),
        request("Order 3 is still unpaid", "GET", "/orders/{{order3}}", as_="custA", test="""
            status(200); pm.test('pending', () => pm.expect(J().payment_status).to.equal('pending'));
        """),

        # ---- refunds
        request("Refunds are for the shop: shoppers are refused", "POST", "/payments/refunds",
                as_="custA", body={"reference": "{{payRef1}}"}, test="status(403);"),
        request("Refunds need a login", "POST", "/payments/refunds", body={"reference": "{{payRef1}}"},
                test="status(401);"),
        request("Refund of an unknown payment", "POST", "/payments/refunds", as_="admin",
                body={"reference": "PAY-NOSUCH000000"}, test="status(404);"),
        request("An unpaid payment cannot be refunded", "POST", "/payments/refunds", as_="admin",
                body={"reference": "{{payRef3}}"}, test="status(409); pm.test('says why', () => pm.expect(detail()).to.match(/paid payment/));"),
        request("A refund must name a positive amount", "POST", "/payments/refunds", as_="admin",
                body={"reference": "{{payRef1}}", "amount": "-5"}, test="status(422);"),
        request("Refunding more than was paid is a conflict", "POST", "/payments/refunds", as_="admin",
                body={"reference": "{{payRef1}}", "amount": "999999999.00"},
                test="status(409); pm.test('reports what is left', () => pm.expect(detail()).to.match(/left to refund/));"),
        request("A partial refund", "POST", "/payments/refunds", as_="admin",
                body={"reference": "{{payRef1}}", "amount": "1000.00", "reason": "Goodwill"}, test="""
            status(200);
            pm.test('accepted by the provider', () => { pm.expect(J().success).to.equal(true); pm.expect(J().amount).to.equal('1000.00'); });
        """),
        request("The remainder can only go to what is left", "POST", "/payments/refunds", as_="admin",
                body={"reference": "{{payRef1}}", "amount": "999999.00"},
                test="status(409);"),
    ], "The provider is a local stand-in. Webhooks are signed with HMAC-SHA512 over the raw body, "
       "exactly as Paystack does.")


def admin_ops_folder() -> dict:
    today_expr = "new Date().toISOString().slice(0, 10)"
    return folder("08 Admin: orders, fulfilment, analytics", [
        request("Dashboard", "GET", "/admin/dashboard", as_="admin", test=f"""
            status(200);
            const d = J();
            pm.test('catalog', () => {{ pm.expect(d.catalog.products).to.equal({len(CATALOG)}); pm.expect(isMoney(d.catalog.inventory_value)).to.equal(true); }});
            pm.test('order book', () => {{ pm.expect(d.orders.total).to.equal(3); pm.expect(d.orders.paid).to.equal(2); pm.expect(d.orders.awaiting_payment).to.equal(1); }});
            pm.test('customers: A, B and the admin', () => pm.expect(d.customers.total).to.equal(3));
            pm.test('needs_restocking is a count', () => pm.expect(d.needs_restocking).to.be.a('number'));
        """),
        request("The order book lists every customer's orders", "GET", "/admin/orders", as_="admin", test="""
            status(200);
            pm.test('three orders, newest first, with full detail', () => {
              pm.expect(J().total).to.equal(3);
              pm.expect(J().items.map((o) => o.id)).to.eql([order3(), order2(), order1()]);
              pm.expect(J().items[0].items.length).to.be.above(0);
            });
            function order1() { return parseInt(v('order1')); } function order2() { return parseInt(v('order2')); } function order3() { return parseInt(v('order3')); }
        """),
        request("Filter: paid orders", "GET", "/admin/orders", as_="admin", query="payment_status=paid", test="""
            status(200);
            pm.test('orders 1 and 2', () => { pm.expect(J().total).to.equal(2); sameSet(J().items.map((o) => o.id), [parseInt(v('order1')), parseInt(v('order2'))]); });
        """),
        request("Filter: orders awaiting payment", "GET", "/admin/orders", as_="admin", query="payment_status=pending",
                test="status(200); pm.test('order 3', () => { pm.expect(J().total).to.equal(1); pm.expect(J().items[0].id).to.equal(parseInt(v('order3'))); });"),
        request("Filter: pickup orders", "GET", "/admin/orders", as_="admin", query="delivery_option=pickup",
                test="status(200); pm.test('order 2', () => { pm.expect(J().total).to.equal(1); pm.expect(J().items[0].id).to.equal(parseInt(v('order2'))); });"),
        request("Filter: search by reference", "GET", "/admin/orders", as_="admin", query="q={{order1Ref}}",
                test="status(200); pm.test('order 1', () => { pm.expect(J().total).to.equal(1); pm.expect(J().items[0].id).to.equal(parseInt(v('order1'))); });"),
        request("Filter: search by customer name", "GET", "/admin/orders", as_="admin", query="q=bola%20shopper",
                test="status(200); pm.test('order 2', () => pm.expect(J().total).to.equal(1));"),
        request("Filter: a date range with no orders", "GET", "/admin/orders", as_="admin",
                query="date_from=2001-01-01&date_to=2001-01-31",
                test="status(200); pm.test('none', () => pm.expect(J().total).to.equal(0));"),
        request("Filter: today's orders", "GET", "/admin/orders", as_="admin",
                pre=f"set('today', {today_expr});", query="date_from={{today}}&date_to={{today}}",
                test="status(200); pm.test('all three, found by store-time date', () => pm.expect(J().total).to.be.at.least(3));"),
        request("Bad filter values are refused", "GET", "/admin/orders", as_="admin",
                query="payment_status=maybe", test="status(422);"),
        request("Bad delivery filter is refused", "GET", "/admin/orders", as_="admin",
                query="delivery_option=drone", test="status(422);"),
        request("Paging the order book", "GET", "/admin/orders", as_="admin", query="page=1&page_size=2", test="""
            status(200);
            pm.test('two of three', () => { pm.expect(J().items.length).to.equal(2); pm.expect(J().total).to.equal(3); pm.expect(J().total_pages).to.equal(2); });
        """),
        request("The customer list", "GET", "/admin/users", as_="admin", test="""
            status(200);
            pm.test('three people, earliest first, no secrets', () => {
              pm.expect(J().total).to.equal(3);
              pm.expect(J().items.map((u) => u.role).sort()).to.eql(['admin', 'customer', 'customer']);
              pm.expect(JSON.stringify(J())).to.not.match(/passw|hash/i);
            });
        """),

        # ---- fulfilment
        request("An unpaid order cannot be shipped", "PATCH", "/admin/orders/{{order3}}/fulfillment",
                as_="admin", body={"status": "in_transit"},
                test="status(409); pm.test('says why', () => pm.expect(detail()).to.match(/pending/));"),
        request("Ship a paid order", "PATCH", "/admin/orders/{{order1}}/fulfillment", as_="admin",
                body={"status": "in_transit"}, test="""
            status(200);
            pm.test('in transit; payment untouched', () => { pm.expect(J().fulfillment_status).to.equal('in_transit'); pm.expect(J().payment_status).to.equal('paid'); });
        """),
        request("The customer sees the progress", "GET", "/orders/{{order1}}", as_="custA",
                test="status(200); pm.test('in transit', () => pm.expect(J().fulfillment_status).to.equal('in_transit'));"),
        request("Mark it delivered", "PATCH", "/admin/orders/{{order1}}/fulfillment", as_="admin",
                body={"status": "delivered"}, test="status(200); pm.test('delivered', () => pm.expect(J().fulfillment_status).to.equal('delivered'));"),
        request("A wrong tap can be corrected", "PATCH", "/admin/orders/{{order1}}/fulfillment", as_="admin",
                body={"status": "in_transit"}, test="status(200);"),
        request("...and put right again", "PATCH", "/admin/orders/{{order1}}/fulfillment", as_="admin",
                body={"status": "delivered"}, test="status(200); pm.test('delivered', () => pm.expect(J().fulfillment_status).to.equal('delivered'));"),
        request("A home delivery has no terminal to confirm", "PATCH", "/admin/orders/{{order1}}/fulfillment",
                as_="admin", body={"terminal": "Somewhere"}, test="status(409);"),
        request("Confirm the pickup terminal of order 2", "PATCH", "/admin/orders/{{order2}}/fulfillment",
                as_="admin", body={"terminal": "Bauchi Central Terminal"}, test="""
            status(200);
            pm.test('confirmed', () => {
              pm.expect(J().delivery.terminal).to.equal('Bauchi Central Terminal'); pm.expect(J().delivery.terminal_pending).to.equal(false);
              pm.expect(J().address_line).to.equal('GUO terminal pickup: Bauchi Central Terminal');
            });
            pm.test('only the terminal changed', () => pm.expect(J().fulfillment_status).to.equal('processing'));
        """),
        request("The customer sees the confirmed terminal", "GET", "/orders/{{order2}}", as_="custB",
                test="status(200); pm.test('confirmed', () => pm.expect(J().delivery.terminal_pending).to.equal(false));"),
        request("A refused part saves nothing", "PATCH", "/admin/orders/{{order1}}/fulfillment", as_="admin",
                body={"status": "processing", "terminal": "Nope"}, test="status(409);"),
        request("...so order 1 is still delivered", "GET", "/orders/{{order1}}", as_="custA",
                test="status(200); pm.test('delivered', () => pm.expect(J().fulfillment_status).to.equal('delivered'));"),
        request("An empty update is refused", "PATCH", "/admin/orders/{{order1}}/fulfillment", as_="admin",
                body={}, test="status(422);"),
        request("An unknown stage is refused", "PATCH", "/admin/orders/{{order1}}/fulfillment", as_="admin",
                body={"status": "teleported"}, test="status(422);"),
        request("An unknown order is not found", "PATCH", "/admin/orders/999999/fulfillment", as_="admin",
                body={"status": "delivered"}, test="status(404);"),

        # ---- analytics
        request("Analytics for today's trading", "GET", "/admin/analytics", as_="admin",
                pre="const d = new Date(); const day = (n) => new Date(d.getTime() + n * 864e5).toISOString().slice(0, 10);"
                    " set('from', day(-1)); set('to', day(1));",
                query="date_from={{from}}&date_to={{to}}", test=f"""
            status(200);
            const a = J();
            const goods = {money(MILAN_PRICE * 3 + GYM_PRICE + GYM_PRICE)};
            pm.test('the period', () => {{ pm.expect(a.period.days).to.equal(3); pm.expect(a.daily.length).to.equal(3); }});
            pm.test('revenue is money collected: the two paid orders', () => {{
              pm.expect(cents(a.sales.revenue)).to.equal(cents(v('order1Total')) + cents(v('order2Total')));
              pm.expect(a.sales.paid_orders).to.equal(2); pm.expect(a.sales.awaiting_payment_orders).to.equal(1);
              pm.expect(a.sales.orders).to.equal(3);
            }});
            pm.test('the unpaid order is outstanding, not revenue', () => pm.expect(a.accounting.outstanding).to.equal(v('order3Total')));
            pm.test('accounting separates goods, personalisation and delivery', () => {{
              pm.expect(a.accounting.gross_sales).to.equal('{money(MILAN_PRICE * 3 + GYM_PRICE + GYM_PRICE)}');
              pm.expect(a.accounting.customization_charges).to.equal('{money(CUSTOM_FEE * 2)}');
              pm.expect(a.accounting.delivery_charges).to.equal('{money(STANDARD_FEE)}');
              pm.expect(a.accounting.total_collected).to.equal(a.sales.revenue);
            }});
            pm.test('average order value', () => pm.expect(cents(a.sales.average_order_value)).to.equal(Math.round(cents(a.sales.revenue) / 2)));
            pm.test('operations: one delivered, one processing, pickup and home delivery', () => {{
              pm.expect(a.operations.delivered).to.equal(1); pm.expect(a.operations.processing).to.equal(1);
              pm.expect(a.operations.in_transit).to.equal(0);
              pm.expect(a.operations.pickup_orders).to.equal(1); pm.expect(a.operations.hand_delivery_orders).to.equal(2);
              pm.expect(a.operations.pending_terminal_confirmations).to.equal(0);
            }});
            pm.test('best sellers rank by units from paid orders', () => {{
              pm.expect(a.top_products[0].product_slug).to.equal('ac-milan-2526'); pm.expect(a.top_products[0].units_sold).to.equal(3);
              pm.expect(a.top_products[1].product_slug).to.equal('zoid-pro-gym-set'); pm.expect(a.top_products[1].units_sold).to.equal(2);
            }});
            pm.test('the daily trend adds up to the revenue', () => pm.expect(a.daily.reduce((s, p) => s + cents(p.revenue), 0)).to.equal(cents(a.sales.revenue)));
            pm.test('nothing to compare with yet', () => {{ pm.expect(a.sales.previous_revenue).to.equal('0.00'); pm.expect(a.sales.change_percent).to.equal(null); }});
        """),
        request("Analytics default to the current week", "GET", "/admin/analytics", as_="admin", test="""
            status(200);
            pm.test('a full Monday-to-Sunday week', () => {
              pm.expect(J().period.days).to.equal(7);
              pm.expect(new Date(J().period.date_from + 'T00:00:00Z').getUTCDay()).to.equal(1);
            });
        """),
        request("A backwards period is refused", "GET", "/admin/analytics", as_="admin",
                query="date_from=2026-11-08&date_to=2026-11-02", test="status(422);"),
        request("A period over a year is refused", "GET", "/admin/analytics", as_="admin",
                query="date_from=2024-01-01&date_to=2026-11-08", test="status(422);"),
        request("A malformed date is refused", "GET", "/admin/analytics", as_="admin",
                query="date_from=soon", test="status(422);"),
    ])


def admin_catalog_folder() -> dict:
    slug = "e2e-jersey-{{runId}}"
    create_body = {
        "slug": slug, "name": "E2E Test Jersey", "category_slug": "e2e-tests",
        "category_name": "E2E Tests", "price": "40000.00", "original_price": "50000.00",
        "sizes": [{"size": "M", "quantity": 5}, {"size": "L", "quantity": 0}],
        "images": [{"url": "{{uploadedUrl}}", "view": "front"}],
        "tone": "Green / White", "style": "Jersey", "color": "Green", "fit": "True to size",
        "fit_note": "Fits as expected.", "details": "A jersey made by the end-to-end tests.",
        "delivery": "Delivered in 2 weeks", "is_bestseller": True, "is_new_arrival": True,
    }

    def refused(label, **overrides):
        return request(label, "POST", "/admin/products", as_="admin",
                       body={**create_body, "slug": slug + "-x", **overrides}, test="status(422);")

    big = "pm.request.body.update('x'.repeat(250000));"
    return folder("09 Admin: catalog, images and stock", [
        request("Upload an image (raw bytes, stored through S3)", "POST", "/admin/products/images",
                as_="admin", headers={"Content-Type": "image/png"}, file="fixtures/pixel.png", test="""
            status(201);
            const r = J();
            set('uploadedUrl', r.url); set('uploadedKey', r.key);
            pm.test('type read from the bytes', () => { pm.expect(r.content_type).to.equal('image/png'); pm.expect(r.size).to.be.above(0); });
            pm.test('server-chosen name', () => pm.expect(r.key).to.match(/^products\\/[0-9a-f]{32}\\.png$/));
            pm.test('a public address', () => pm.expect(r.url).to.equal(v('mockUrl') + '/zoid-e2e/' + r.key));
        """),
        request("The uploaded image can be fetched back, byte for byte", "GET", "{{uploadedUrl}}", absolute=True,
                test="""
            status(200);
            pm.test('served as a PNG', () => pm.expect(header('Content-Type')).to.equal('image/png'));
            pm.test('not corrupted by the transfer', () => pm.expect(pm.response.stream.slice(0, 8).toString('hex')).to.equal('89504e470d0a1a0a'));
        """),
        request("An HTML page labelled as an image is refused", "POST", "/admin/products/images", as_="admin",
                headers={"Content-Type": "image/png"}, raw="<html><script>alert(1)</script></html>",
                test="status(422); pm.test('says what is accepted', () => pm.expect(detail()).to.match(/JPEG, PNG, GIF and WebP/));"),
        request("SVG is refused", "POST", "/admin/products/images", as_="admin",
                headers={"Content-Type": "image/svg+xml"},
                raw='<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', test="status(422);"),
        request("An empty upload is refused", "POST", "/admin/products/images", as_="admin",
                headers={"Content-Type": "image/png"}, raw="", test="status(422);"),
        request("An oversized upload is refused", "POST", "/admin/products/images", as_="admin",
                headers={"Content-Type": "image/png"}, raw="x", pre=big,
                test="status(422); pm.test('says too large', () => pm.expect(detail()).to.match(/too large/));"),
        request("Create a product on sale", "POST", "/admin/products", as_="admin", body=create_body, test="""
            status(201);
            const p = J(); set('e2eId', p.id); set('e2eSlug', p.slug);
            pm.test('stored as sent', () => { pm.expect(p.name).to.equal('E2E Test Jersey'); pm.expect(p.is_active).to.equal(true); pm.expect(p.sizes).to.eql(['M', 'L']); });
            pm.test('the discount is computed, not stored', () => { pm.expect(p.original_price).to.equal('50000.00'); pm.expect(p.discount_percent).to.equal(20); });
            pm.test('shelf stock', () => pm.expect(p.stock).to.eql({M: 5, L: 0}));
            pm.test('uses the uploaded picture', () => pm.expect(p.gallery[0].url).to.equal(v('uploadedUrl')));
        """),
        request("The same slug is a conflict", "POST", "/admin/products", as_="admin", body=create_body,
                test="status(409);"),
        refused("A negative price is refused", price="-1.00"),
        refused("A sale price must be a real markdown", original_price="30000.00"),
        refused("Duplicate sizes are refused", sizes=[{"size": "M", "quantity": 1}, {"size": "m", "quantity": 1}]),
        refused("A bad image address is refused", images=[{"url": "", "view": "front"}]),
        refused("A name is required", name=""),
        request("The storefront now sells it", "GET", "/products/" + slug, test="""
            status(200); pm.test('on the shelf with the picture', () => { pm.expect(J().stock.M).to.equal(5); pm.expect(J().gallery.length).to.equal(1); });
        """),
        request("The shop's product list sees it", "GET", "/admin/products", as_="admin",
                query="q=E2E%20Test&page_size=100", test="""
            status(200);
            pm.test('found by the forgiving search, with admin-only fields', () => { pm.expect(J().total).to.equal(1); pm.expect(J().items[0].is_active).to.equal(true); });
        """),
        request("Low stock filter", "GET", "/admin/products", as_="admin", query="stock=low_stock&page_size=100", test="""
            status(200); pm.test('includes it (5 units)', () => pm.expect(J().items.map((p) => p.slug)).to.include(v('e2eSlug')));
        """),
        request("Edit price and name", "PATCH", "/admin/products/{{e2eId}}", as_="admin",
                body={"name": "E2E Test Jersey II", "price": "45000.00"}, test="""
            status(200);
            pm.test('changed what was named', () => { pm.expect(J().name).to.equal('E2E Test Jersey II'); pm.expect(J().price).to.equal('45000.00'); pm.expect(J().discount_percent).to.equal(10); });
            pm.test('left the rest alone', () => { pm.expect(J().slug).to.equal(v('e2eSlug')); pm.expect(J().stock).to.eql({M: 5, L: 0}); });
        """),
        request("A price above the old price needs the sale ended too", "PATCH", "/admin/products/{{e2eId}}",
                as_="admin", body={"price": "60000.00"}, test="status(422);"),
        request("...and the refused edit changed nothing", "GET", "/products/" + slug,
                test="status(200); pm.test('price kept', () => pm.expect(J().price).to.equal('45000.00'));"),
        request("Ending the sale (explicit null) while raising the price", "PATCH", "/admin/products/{{e2eId}}",
                as_="admin", body={"price": "60000.00", "original_price": None}, test="""
            status(200);
            pm.test('no longer on sale', () => { pm.expect(J().original_price).to.equal(null); pm.expect(J().discount_percent).to.equal(null); pm.expect(J().price).to.equal('60000.00'); });
        """),
        request("An empty edit changes nothing", "PATCH", "/admin/products/{{e2eId}}", as_="admin", body={},
                test="status(200); pm.test('same', () => pm.expect(J().price).to.equal('60000.00'));"),
        request("Editing an unknown product", "PATCH", "/admin/products/999999", as_="admin",
                body={"name": "x"}, test="status(404);"),
        request("Archive the product", "PATCH", "/admin/products/{{e2eId}}", as_="admin",
                body={"is_active": False}, test="status(200); pm.test('hidden', () => pm.expect(J().is_active).to.equal(false));"),
        request("Archived: gone from the storefront page", "GET", "/products/" + slug, test="status(404);"),
        request("Archived: gone from the storefront list", "GET", "/products", query="q=E2E%20Test%20Jersey",
                test="status(200); pm.test('absent', () => pm.expect(J().items.map((p) => p.slug)).to.not.include(v('e2eSlug')));"),
        request("Archived: cannot be added to a bag", "POST", "/cart/items", as_="custB",
                body={"product_slug": slug, "size": "M", "quantity": 1}, test="status(404);"),
        request("Archived: the shop can still see it", "GET", "/admin/products", as_="admin",
                query="active=false&page_size=100", test="""
            status(200); pm.test('listed as inactive', () => pm.expect(J().items.map((p) => p.slug)).to.include(v('e2eSlug')));
        """),
        request("Unarchive", "PATCH", "/admin/products/{{e2eId}}", as_="admin", body={"is_active": True},
                test="status(200);"),
        request("Back on the storefront", "GET", "/products/" + slug, test="status(200);"),

        # ---- stock
        request("Restock a sold-out size", "POST", "/admin/products/{{e2eId}}/stock", as_="admin",
                body={"size": "L", "quantity": 4}, test="""
            status(200); pm.test('four on the shelf', () => { pm.expect(J().added).to.equal(4); pm.expect(J().available).to.equal(4); });
        """),
        request("A restock must add something", "POST", "/admin/products/{{e2eId}}/stock", as_="admin",
                body={"size": "L", "quantity": 0}, test="status(422);"),
        request("Restocking a size that is not offered", "POST", "/admin/products/{{e2eId}}/stock",
                as_="admin", body={"size": "XXL", "quantity": 1}, test="status(404);"),
        request("Correct stock downwards", "PATCH", "/admin/products/{{e2eId}}/stock", as_="admin",
                body={"size": "M", "delta": -2}, test="""
            status(200);
            pm.test('three left', () => { pm.expect(J().change).to.equal(-2); pm.expect(J().quantity).to.equal(3); pm.expect(J().available).to.equal(3); });
        """),
        request("A stock-take sets the count", "PATCH", "/admin/products/{{e2eId}}/stock", as_="admin",
                body={"size": "L", "set_to": 10}, test="status(200); pm.test('ten', () => { pm.expect(J().quantity).to.equal(10); pm.expect(J().change).to.equal(6); });"),
        request("Stock can't go below zero", "PATCH", "/admin/products/{{e2eId}}/stock", as_="admin",
                body={"size": "M", "delta": -99}, test="status(422);"),
        request("Send a change or a count, not both", "PATCH", "/admin/products/{{e2eId}}/stock", as_="admin",
                body={"size": "M", "delta": 1, "set_to": 5}, test="status(422);"),
        request("Send one of them", "PATCH", "/admin/products/{{e2eId}}/stock", as_="admin",
                body={"size": "M"}, test="status(422);"),
        request("A zero change is refused", "PATCH", "/admin/products/{{e2eId}}/stock", as_="admin",
                body={"size": "M", "delta": 0}, test="status(422);"),
        request("Stock correction for an unknown size", "PATCH", "/admin/products/{{e2eId}}/stock", as_="admin",
                body={"size": "XXL", "delta": 1}, test="status(404);"),
        request("A customer reserves two units at checkout", "POST", "/cart/items", as_="custB",
                body={"product_slug": slug, "size": "M", "quantity": 2}, test="status(200);"),
        request("...by ordering them", "POST", "/orders", as_="custB",
                body={"contact_name": "Bola Shopper", "contact_email": "bola@zoidjerseys.com",
                      "contact_phone": "+234 803 333 3333",
                      "delivery": {"option": "pickup", "state": "Lagos State", "terminal": "Ojota Terminal (7 Ikorodu Road, Ojota)"}},
                test="status(201); set('order4', J().id);"),
        request("Stock cannot be taken from under a promised order", "PATCH", "/admin/products/{{e2eId}}/stock",
                as_="admin", body={"size": "M", "set_to": 1}, test="""
            status(422); pm.test('says why', () => pm.expect(detail()).to.match(/reserved/));
        """),
        request("...but can come down to exactly what is promised", "PATCH", "/admin/products/{{e2eId}}/stock",
                as_="admin", body={"size": "M", "set_to": 2}, test="""
            status(200);
            pm.test('nothing left to sell', () => { pm.expect(J().reserved).to.equal(2); pm.expect(J().available).to.equal(0); });
        """),
        request("Dashboard reflects the catalog", "GET", "/admin/dashboard", as_="admin", test=f"""
            status(200); pm.test('one more product', () => pm.expect(J().catalog.products).to.equal({len(CATALOG) + 1}));
        """),
    ])


def archives_folder() -> dict:
    story = {"title": "The 1998 Samba Memory", "author": "Tunde O.",
             "content": "Watching Ronaldo on a CRT television in Surulere changed how I saw football.",
             "location": "Lagos, Nigeria", "year": "1998", "category": "COMMUNITY STORY"}

    def moderate(name, status_value, as_="admin", note="", expect=200, test=""):
        return request(name, "PATCH", "/admin/archives/{{storyId}}/moderation", as_=as_,
                       body={"status": status_value, "note": note}, test=f"status({expect}); {test}")

    return folder("10 Archives (community stories)", [
        request("The public list starts empty", "GET", "/archives", test="""
            status(200); pm.test('nothing approved yet', () => { pm.expect(J().total).to.equal(0); pm.expect(J().items).to.eql([]); });
        """),
        request("Submitting needs an account", "POST", "/archives", body=story, test="status(401);"),
        request("Submit a story", "POST", "/archives", as_="custA", body=story, test="""
            status(201);
            const s = J(); set('storyId', s.id);
            pm.test('waits for the shop', () => { pm.expect(s.status).to.equal('pending'); pm.expect(s.title).to.equal('The 1998 Samba Memory'); });
        """),
        request("Pending stories are invisible to the public", "GET", "/archives/{{storyId}}",
                test="status(404);"),
        request("...and absent from the public list", "GET", "/archives",
                test="status(200); pm.test('empty', () => pm.expect(J().total).to.equal(0));"),
        request("The author sees their own pending story", "GET", "/archives/mine", as_="custA", test="""
            status(200);
            pm.test('with its status', () => { pm.expect(J().total).to.equal(1); pm.expect(J().items[0].status).to.equal('pending'); });
        """),
        request("Another shopper's list is separate", "GET", "/archives/mine", as_="custB",
                test="status(200); pm.test('empty', () => pm.expect(J().total).to.equal(0));"),
        request("A story needs real content", "POST", "/archives", as_="custA",
                body={**story, "content": "short"}, test="status(422);"),
        request("A story needs a title", "POST", "/archives", as_="custA", body={**story, "title": ""}, test="status(422);"),
        request("The year must be four digits", "POST", "/archives", as_="custA", body={**story, "year": "98"}, test="status(422);"),
        request("A script address is not an image", "POST", "/archives", as_="custA",
                body={**story, "image_url": "javascript:alert(1)"}, test="status(422);"),
        request("Moderation is for admins: anonymous", "PATCH", "/admin/archives/{{storyId}}/moderation",
                body={"status": "approved"}, test="status(401);"),
        moderate("Moderation is for admins: a shopper", "approved", as_="custA", expect=403),
        request("The review queue", "GET", "/admin/archives", as_="admin", query="status=pending", test="""
            status(200);
            pm.test('shows the story with its owner', () => { pm.expect(J().total).to.equal(1); pm.expect(J().items[0].user_id).to.equal(parseInt(v('userA'))); });
        """),
        moderate("A story cannot be moderated back to pending", "pending", expect=422),
        moderate("Reject it, with a private note", "rejected", note="Not about football", test="""
            pm.test('decision and note recorded', () => { pm.expect(J().status).to.equal('rejected'); pm.expect(J().moderation_note).to.equal('Not about football'); pm.expect(J().reviewed_at).to.be.a('string'); });
        """),
        request("A rejected story stays private", "GET", "/archives/{{storyId}}", test="status(404);"),
        request("The author sees the status but never the note", "GET", "/archives/mine", as_="custA", test="""
            status(200);
            pm.test('rejected, note hidden', () => { pm.expect(J().items[0].status).to.equal('rejected'); pm.expect(JSON.stringify(J())).to.not.match(/Not about football/); });
        """),
        request("The author corrects it: back to pending", "PATCH", "/archives/{{storyId}}", as_="custA",
                body={"title": "The 1998 Samba Memory (revised)"}, test="""
            status(200); pm.test('resubmitted for review', () => { pm.expect(J().status).to.equal('pending'); pm.expect(J().title).to.match(/revised/); });
        """),
        request("Someone else cannot edit it", "PATCH", "/archives/{{storyId}}", as_="custB",
                body={"title": "Hijacked"}, test="status(404);"),
        moderate("Approve it", "approved", test="pm.test('approved', () => pm.expect(J().status).to.equal('approved'));"),
        request("Now the public can read it", "GET", "/archives/{{storyId}}", test="""
            status(200);
            pm.test('the story', () => { pm.expect(J().title).to.match(/revised/); pm.expect(J().author).to.equal('Tunde O.'); });
            pm.test('with nothing about its owner or review', () => pm.expect(Object.keys(J()).sort()).to.eql(
              ['author','category','content','created_at','id','image_url','location','title','year']));
        """),
        request("...and it is in the public list", "GET", "/archives", test="""
            status(200); pm.test('one story', () => { pm.expect(J().total).to.equal(1); pm.expect(JSON.stringify(J())).to.not.match(/user_id|moderation|status/); });
        """),
        request("The public list filters by category", "GET", "/archives", query="category=community%20story",
                test="status(200); pm.test('found', () => pm.expect(J().total).to.equal(1));"),
        request("...and by another category finds none", "GET", "/archives", query="category=heritage",
                test="status(200); pm.test('none', () => pm.expect(J().total).to.equal(0));"),
        request("Editing an approved story takes it off the page", "PATCH", "/archives/{{storyId}}", as_="custA",
                body={"content": "Watching Ronaldo on a CRT television in Surulere changed everything for me."},
                test="status(200); pm.test('pending again', () => pm.expect(J().status).to.equal('pending'));"),
        request("...so the public no longer sees it", "GET", "/archives/{{storyId}}", test="status(404);"),
        request("Someone else cannot delete it", "DELETE", "/archives/{{storyId}}", as_="custB", test="status(404);"),
        request("The author deletes it", "DELETE", "/archives/{{storyId}}", as_="custA", test="status(204);"),
        request("It is gone", "GET", "/archives/mine", as_="custA", test="status(200); pm.test('none', () => pm.expect(J().total).to.equal(0));"),
        request("Deleting it again is not found", "DELETE", "/archives/{{storyId}}", as_="custA", test="status(404);"),
        request("The review queue is empty", "GET", "/admin/archives", as_="admin", test="status(200); pm.test('none', () => pm.expect(J().total).to.equal(0));"),
        request("An unknown status filter is refused", "GET", "/admin/archives", as_="admin",
                query="status=maybe", test="status(422);"),
        request("Moderating a story that does not exist", "PATCH", "/admin/archives/999999/moderation", as_="admin",
                body={"status": "approved"}, test="status(404);"),
    ])


ADMIN_ENDPOINTS = [
    ("GET", "/admin/dashboard", None), ("GET", "/admin/analytics", None),
    ("GET", "/admin/products", None), ("GET", "/admin/orders", None),
    ("GET", "/admin/users", None), ("GET", "/admin/archives", None),
    ("POST", "/admin/products", {"slug": "x", "name": "x", "category_slug": "x", "category_name": "x", "price": "1.00"}),
    ("POST", "/admin/products/images", None),
    ("POST", "/admin/products/1/stock", {"size": "M", "quantity": 1}),
    ("PATCH", "/admin/products/1", {"name": "x"}),
    ("PATCH", "/admin/products/1/stock", {"size": "M", "delta": 1}),
    ("PATCH", "/admin/orders/1/fulfillment", {"status": "delivered"}),
    ("PATCH", "/admin/archives/1/moderation", {"status": "approved"}),
    ("POST", "/payments/refunds", {"reference": "PAY-ANYTHING0000"}),
]

CUSTOMER_ENDPOINTS = [
    ("GET", "/auth/me", None), ("GET", "/users/me", None), ("PUT", "/users/me", {"name": "x"}),
    ("GET", "/wishlist", None), ("POST", "/wishlist/items", {"product_slug": "ac-milan-2526"}),
    ("DELETE", "/wishlist/items/ac-milan-2526", None), ("GET", "/orders", None),
    ("POST", "/orders", {**CONTACT, "delivery": LAGOS_HOME}), ("GET", "/orders/1", None),
    ("POST", "/payments/initiate", {"order_id": 1}), ("POST", "/payments/verify", {"reference": "PAY-ANYTHING0000"}),
    ("GET", "/archives/mine", None), ("POST", "/archives", {"title": "t", "author": "a", "content": "ten chars!!"}),
    ("PATCH", "/archives/1", {"title": "t"}), ("DELETE", "/archives/1", None), ("POST", "/cart/merge", None),
]


def security_folder() -> dict:
    items = []
    for method, path, body in ADMIN_ENDPOINTS:
        kwargs = {"body": body} if body is not None else {}
        items.append(request(f"{method} {path}: anonymous", method, path, test="status(401);", **kwargs))
    for method, path, body in ADMIN_ENDPOINTS:
        kwargs = {"body": body} if body is not None else {}
        items.append(request(f"{method} {path}: a customer", method, path, as_="custA",
                             test="status(403); pm.test('names the missing role', () => pm.expect(detail()).to.match(/admin|permission/i));",
                             **kwargs))
    for method, path, body in CUSTOMER_ENDPOINTS:
        kwargs = {"body": body} if body is not None else {}
        items.append(request(f"{method} {path}: anonymous", method, path, test="status(401);", **kwargs))
    return folder("11 Access control sweep", items,
                  "Every admin route refuses anonymous callers (401) and customers (403); "
                  "every customer route refuses anonymous callers (401).")


def hygiene_folder() -> dict:
    return folder("12 Transport hygiene and error shape", [
        request("Security headers on every response", "GET", "{{baseUrl}}/health", absolute=True, test="""
            status(200);
            pm.test('no sniffing', () => pm.expect(header('X-Content-Type-Options')).to.equal('nosniff'));
            pm.test('no framing', () => pm.expect(header('X-Frame-Options')).to.equal('DENY'));
            pm.test('no referrer', () => pm.expect(header('Referrer-Policy')).to.equal('no-referrer'));
            pm.test('no caching of responses', () => pm.expect(header('Cache-Control')).to.match(/no-store/));
        """),
        request("CORS: the storefront's origin may call with cookies", "OPTIONS", "/products",
                headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}, test="""
            status(200);
            pm.test('that origin, with credentials', () => {
              pm.expect(header('Access-Control-Allow-Origin')).to.equal('http://localhost:3000');
              pm.expect(header('Access-Control-Allow-Credentials')).to.equal('true');
            });
        """),
        request("CORS: a real request from the storefront", "GET", "/products", query="page_size=1",
                headers={"Origin": "http://localhost:3000"}, test="""
            status(200);
            pm.test('allowed with credentials', () => { pm.expect(header('Access-Control-Allow-Origin')).to.equal('http://localhost:3000'); pm.expect(header('Access-Control-Allow-Credentials')).to.equal('true'); });
        """),
        request("CORS: another origin is not allowed", "OPTIONS", "/products",
                headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"}, test="""
            pm.test('refused', () => pm.expect(pm.response.code).to.equal(400));
            pm.test('never echoes the foreign origin', () => pm.expect(header('Access-Control-Allow-Origin')).to.not.equal('http://evil.example'));
        """),
        request("CORS: a foreign origin gets no allowance on a real request", "GET", "/products", query="page_size=1",
                headers={"Origin": "http://evil.example"}, test="""
            pm.test('no allow-origin for it', () => pm.expect(header('Access-Control-Allow-Origin')).to.not.equal('http://evil.example'));
        """),
        request("Malformed JSON is a clean 422", "POST", "/auth/login", raw="{bad",
                headers={"Content-Type": "application/json"}, test="""
            status(422);
            pm.test('a message, no stack trace', () => { pm.expect(J()).to.have.property('detail'); pm.expect(pm.response.text()).to.not.match(/Traceback|File "/); });
        """),
        request("Unknown route", "GET", "/no-such-endpoint", test="status(404);"),
        request("Wrong method", "DELETE", "/products", test="status(405);"),
        request("A huge search term is refused, not processed", "GET", "/products", query="q=" + "a" * 101,
                test="status(422);"),
        request("Errors share one shape", "GET", "/products/no-such-jersey", test="""
            status(404);
            pm.test('JSON with a detail', () => { pm.expect(header('Content-Type')).to.match(/application\\/json/); pm.expect(J().detail).to.be.a('string'); });
        """),
        request("Hostile text is stored as text and returned as JSON", "POST", "/archives", as_="custA",
                body={"title": "<script>alert(1)</script>", "author": "<img src=x onerror=alert(1)>",
                      "content": "A perfectly ordinary story with <b>markup</b> in it."},
                test="""
            status(201);
            pm.test('JSON, not sniffable HTML', () => { pm.expect(header('Content-Type')).to.match(/application\\/json/); pm.expect(header('X-Content-Type-Options')).to.equal('nosniff'); });
            pm.test('returned verbatim for the client to escape', () => pm.expect(J().title).to.equal('<script>alert(1)</script>'));
            set('xssStory', J().id);
        """),
        request("...and cleaned up", "DELETE", "/archives/{{xssStory}}", as_="custA", test="status(204);"),
    ])


def cleanup_folder() -> dict:
    return folder("13 Cleanup", [
        request("Shopper A logs out", "POST", "/auth/logout", as_="custA", test="status(200);"),
        request("Shopper B logs out", "POST", "/auth/logout", as_="custB", test="status(200);"),
        request("Admin logs out", "POST", "/auth/logout", as_="admin", test="status(200);"),
        request("The API is still healthy after the run", "GET", "{{baseUrl}}/health", absolute=True,
                test="status(200); pm.test('ok', () => pm.expect(J().status).to.equal('ok'));"),
    ])


def build(args: argparse.Namespace) -> dict:
    folders = [setup(), catalog_folder(), delivery_folder(), auth_folder(), guest_cart_folder(),
               merge_and_wishlist_folder(), checkout_folder(), payments_folder(), admin_ops_folder(),
               admin_catalog_folder(), archives_folder(), security_folder(), hygiene_folder(),
               cleanup_folder()]
    return {
        "info": {
            "name": "Zoid backend: end-to-end API suite",
            "description": __doc__,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": folders,
    }


def environment(args: argparse.Namespace) -> dict:
    def entry(key: str, value: str, secret: bool = False) -> dict:
        return {"key": key, "value": value, "type": "secret" if secret else "default", "enabled": True}

    return {
        "name": "Zoid local end-to-end",
        "values": [
            entry("baseUrl", args.base_url), entry("apiPort", str(args.api_port)),
            entry("mockUrl", args.mock_url),
            entry("adminEmail", args.admin_email), entry("adminPassword", args.admin_password, True),
            entry("webhookSecret", args.webhook_secret, True),
        ],
        "_postman_variable_scope": "environment",
    }


def count_requests(items: list[dict]) -> int:
    return sum(count_requests(i["item"]) if "item" in i else 1 for i in items)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--mock-url", default="http://127.0.0.1:9100")
    parser.add_argument("--admin-email", default="owner@zoidjerseys.com")
    parser.add_argument("--admin-password", default="change-me")
    parser.add_argument("--webhook-secret", default="whsec_e2e_mock")
    parser.add_argument("--out-dir", type=Path, default=HERE,
                        help="where to write the collection and environment (default: here)")
    args = parser.parse_args()

    collection = build(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "zoid-backend.postman_collection.json").write_text(
        json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "local.postman_environment.json").write_text(
        json.dumps(environment(args), indent=2) + "\n", encoding="utf-8")
    print(f"collection: {count_requests(collection['item'])} requests "
          f"in {len(collection['item'])} folders -> {args.out_dir}")


if __name__ == "__main__":
    main()
