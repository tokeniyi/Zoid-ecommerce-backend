"""Archive stories through the real app: submit, review, publish, manage."""

from __future__ import annotations

import secrets
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.security.authentication.session import session_strategy_from_settings

pytestmark = pytest.mark.database

_settings = get_settings()
API = _settings.api_v1_prefix
COOKIE = _settings.cookie_name
PASSWORD = secrets.token_urlsafe(16)  # fresh every run: no credential in the source
BODY = "Watching Ronaldo on a CRT television in Surulere changed how I saw football."
STORY = {"title": "The 1998 Samba Memory", "author": "Tunde O.", "content": BODY,
         "location": "Lagos, Nigeria", "year": "1998"}


def _admin() -> dict[str, str]:
    return {COOKIE: session_strategy_from_settings().issue("1", role="admin")[0]}


def _login(client: TestClient) -> dict[str, str]:
    email = f"zoid-story-{uuid4()}@example.com"
    client.post(f"{API}/auth/signup", json={"name": "Writer", "email": email, "password": PASSWORD})
    token = client.post(
        f"{API}/auth/login", json={"email": email, "password": PASSWORD}
    ).cookies.get(COOKIE)
    client.cookies.clear()  # each caller sends their own cookie explicitly
    return {COOKIE: token}


def _submit(client: TestClient, who: dict[str, str], **overrides: object) -> dict:
    response = client.post(f"{API}/archives", cookies=who, json={**STORY, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def _moderate(client: TestClient, story_id: int, status: str, note: str = ""):
    return client.patch(
        f"{API}/admin/archives/{story_id}/moderation", cookies=_admin(),
        json={"status": status, "note": note},
    )


def test_a_submitted_story_waits_unseen_for_the_shop(client: TestClient) -> None:
    writer = _login(client)

    story = _submit(client, writer)

    assert story["status"] == "pending" and story["title"] == STORY["title"]
    assert client.get(f"{API}/archives").json()["total"] == 0          # not public
    assert client.get(f"{API}/archives/{story['id']}").status_code == 404
    mine = client.get(f"{API}/archives/mine", cookies=writer).json()  # but the author sees it
    assert [s["id"] for s in mine["items"]] == [story["id"]]
    assert mine["items"][0]["status"] == "pending"


def test_the_shop_approves_and_the_public_can_then_read_it(client: TestClient) -> None:
    story = _submit(client, _login(client))

    approved = _moderate(client, story["id"], "approved")

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved" and approved.json()["reviewed_at"]
    listed = client.get(f"{API}/archives").json()
    assert [s["id"] for s in listed["items"]] == [story["id"]]
    assert client.get(f"{API}/archives/{story['id']}").json()["author"] == "Tunde O."


def test_the_public_view_leaks_nothing_about_ownership_or_moderation(
    client: TestClient,
) -> None:
    story = _submit(client, _login(client))
    _moderate(client, story["id"], "approved", "private reviewer note")

    public = client.get(f"{API}/archives/{story['id']}").json()

    assert set(public) == {"id", "title", "author", "location", "year", "category",
                           "content", "image_url", "created_at"}
    assert "private reviewer note" not in client.get(f"{API}/archives").text
    assert "user_id" not in client.get(f"{API}/archives").text


def test_a_rejected_story_stays_private_and_the_note_is_for_the_shop(
    client: TestClient,
) -> None:
    writer = _login(client)
    story = _submit(client, writer)

    _moderate(client, story["id"], "rejected", "Not about football")

    assert client.get(f"{API}/archives/{story['id']}").status_code == 404
    mine = client.get(f"{API}/archives/mine", cookies=writer).json()["items"][0]
    assert mine["status"] == "rejected" and "moderation_note" not in mine  # authors see status only
    admin = client.get(f"{API}/admin/archives", cookies=_admin()).json()["items"][0]
    assert admin["moderation_note"] == "Not about football" and admin["user_id"] is not None


def test_the_review_queue_filters_by_status(client: TestClient) -> None:
    writer = _login(client)
    waiting = _submit(client, writer, title="Waiting")
    done = _submit(client, writer, title="Done")
    _moderate(client, done["id"], "approved")

    def titles(**params: str) -> set[str]:
        body = client.get(f"{API}/admin/archives", cookies=_admin(), params=params).json()
        return {s["title"] for s in body["items"]}

    assert titles() == {"Waiting", "Done"}
    assert titles(status="pending") == {"Waiting"}
    assert titles(status="approved") == {"Done"}
    assert waiting["id"] != done["id"]
    assert client.get(f"{API}/admin/archives", cookies=_admin(),
                      params={"status": "maybe"}).status_code == 422


def test_editing_an_approved_story_takes_it_off_the_public_page_until_re_approved(
    client: TestClient,
) -> None:
    writer = _login(client)
    story = _submit(client, writer)
    _moderate(client, story["id"], "approved")
    assert client.get(f"{API}/archives/{story['id']}").status_code == 200

    edited = client.patch(f"{API}/archives/{story['id']}", cookies=writer,
                          json={"title": "A better title"})

    assert edited.status_code == 200, edited.text
    assert (edited.json()["title"], edited.json()["status"]) == ("A better title", "pending")
    assert client.get(f"{API}/archives/{story['id']}").status_code == 404
    _moderate(client, story["id"], "approved")
    assert client.get(f"{API}/archives/{story['id']}").json()["title"] == "A better title"


def test_an_author_can_delete_their_own_story_and_no_one_elses(client: TestClient) -> None:
    owner, stranger = _login(client), _login(client)
    story = _submit(client, owner)

    assert client.delete(f"{API}/archives/{story['id']}", cookies=stranger).status_code == 404
    assert client.patch(f"{API}/archives/{story['id']}", cookies=stranger,
                        json={"title": "Hijack"}).status_code == 404
    assert client.delete(f"{API}/archives/{story['id']}", cookies=owner).status_code == 204
    assert client.get(f"{API}/archives/mine", cookies=owner).json()["total"] == 0
    assert client.delete(f"{API}/archives/{story['id']}", cookies=owner).status_code == 404


def test_bad_submissions_are_rejected(client: TestClient) -> None:
    writer = _login(client)

    def post(**overrides: object) -> int:
        return client.post(f"{API}/archives", cookies=writer,
                           json={**STORY, **overrides}).status_code

    assert post(title="") == 422
    assert post(content="short") == 422
    assert post(content="x" * 5001) == 422
    assert post(year="98") == 422
    assert post(image_url="javascript:alert(1)") == 422
    assert client.post(f"{API}/archives", cookies=writer, json={"title": "only"}).status_code == 422


def test_submitting_needs_an_account_but_reading_does_not(client: TestClient) -> None:
    assert client.post(f"{API}/archives", json=STORY).status_code == 401
    assert client.get(f"{API}/archives/mine").status_code == 401
    assert client.get(f"{API}/archives").status_code == 200
    assert client.patch(f"{API}/archives/1", json={"title": "x"}).status_code == 401
    assert client.delete(f"{API}/archives/1").status_code == 401


def test_only_an_admin_can_moderate(client: TestClient) -> None:
    writer = _login(client)
    story = _submit(client, writer)
    url = f"{API}/admin/archives/{story['id']}/moderation"

    assert client.patch(url, json={"status": "approved"}).status_code == 401
    assert client.patch(url, cookies=writer, json={"status": "approved"}).status_code == 403
    assert client.get(f"{API}/admin/archives", cookies=writer).status_code == 403
    assert client.get(f"{API}/archives/{story['id']}").status_code == 404  # still not public


def test_moderation_must_decide_and_name_a_real_story(client: TestClient) -> None:
    story = _submit(client, _login(client))

    assert _moderate(client, story["id"], "pending").status_code == 422
    assert _moderate(client, story["id"], "published").status_code == 422
    assert _moderate(client, 999999, "approved").status_code == 404


def test_stories_can_be_filtered_by_category_and_paged(client: TestClient) -> None:
    writer = _login(client)
    for index in range(3):
        story = _submit(client, writer, title=f"Story {index}",
                        category="HERITAGE" if index else "COMMUNITY STORY")
        _moderate(client, story["id"], "approved")

    everything = client.get(f"{API}/archives", params={"page_size": 2}).json()
    assert (everything["total"], len(everything["items"]), everything["total_pages"]) == (3, 2, 2)
    assert everything["items"][0]["title"] == "Story 2"  # newest first
    heritage = client.get(f"{API}/archives", params={"category": "heritage"}).json()
    assert {s["title"] for s in heritage["items"]} == {"Story 1", "Story 2"}
