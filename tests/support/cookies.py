"""Send one request with extra cookies, without httpx's deprecated ``cookies=``.

``with_cookies(client, {COOKIE: token}).get(url)`` behaves as
``client.get(url, cookies={COOKIE: token})`` did: the cookies go out with this
request only, alongside whatever the client's jar already holds, and cookies the
response sets are kept in the jar as usual. httpx built a merged copy of the jar
for the request; here the cookies are put into the jar itself for the duration
of the call and taken out again afterwards.
"""

from __future__ import annotations

from http.cookiejar import Cookie
from typing import Any

import httpx
from fastapi.testclient import TestClient


def _unscoped(client: TestClient, name: str) -> Cookie | None:
    # Cookies set with ``Cookies.set(name, value)`` have an empty domain; those
    # the server sets are scoped to its host and are never touched here.
    for cookie in client.cookies.jar:
        if cookie.name == name and cookie.domain == "" and cookie.path == "/":
            return cookie
    return None


class _CookieRequests:
    def __init__(self, client: TestClient, cookies: dict[str, str] | None) -> None:
        self._client = client
        self._cookies = cookies or {}

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        previous = {name: _unscoped(self._client, name) for name in self._cookies}
        for name, value in self._cookies.items():
            self._client.cookies.set(name, value)
        injected = {id(_unscoped(self._client, name)): name for name in self._cookies}
        try:
            return self._client.request(method, url, **kwargs)
        finally:
            # Rebuild rather than delete: the jar sends cookies grouped by domain
            # in insertion order, and a deleted cookie leaves its domain's slot
            # behind. Rebuilding keeps every later request's Cookie header in
            # the order it would have had if the cookies had never been added.
            rebuilt = httpx.Cookies()
            for cookie in self._client.cookies.jar:
                if id(cookie) not in injected:
                    rebuilt.jar.set_cookie(cookie)
                elif (prior := previous[injected[id(cookie)]]) is not None:
                    rebuilt.jar.set_cookie(prior)
            self._client.cookies = rebuilt

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)


def with_cookies(client: TestClient, cookies: dict[str, str] | None) -> _CookieRequests:
    """Requests through ``client`` that also carry ``cookies``."""
    return _CookieRequests(client, cookies)
