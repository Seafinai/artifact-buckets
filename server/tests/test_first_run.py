"""First run on a fresh install: temporary passwords are replaced at first sign-in, and the app says whether a
directory is connected so the pages don't talk about Active Directory when there is none."""
from conftest import ADMIN_PW, PW, login


def me(web):
    return web.get("/api/auth/me").json()


def test_installer_password_is_temporary(app, admin):
    u = me(admin)["user"]
    assert u["must_change_password"] is True and u["chose_password"] is False
    assert me(admin)["directory"] is False
    r = admin.post("/api/auth/password", json={"current": ADMIN_PW, "new": "a-password-only-i-know"})
    assert r.status_code == 200, r.text
    u = me(login(app, "admin", "a-password-only-i-know"))["user"]
    assert u["must_change_password"] is False and u["chose_password"] is True


def test_admin_set_passwords_are_temporary(app, admin, make_user):
    jo = make_user("jo")
    assert me(jo)["user"]["must_change_password"] is True
    assert jo.post("/api/auth/password", json={"current": PW, "new": "jo-picked-this-one"}).status_code == 200
    assert me(jo)["user"]["must_change_password"] is False
    # An admin resetting it hands out a temporary one again.
    uid = next(u["id"] for u in admin.get("/api/users").json()["users"] if u["username"] == "jo")
    assert admin.patch(f"/api/users/{uid}", json={"password": "reset-by-the-admin"}).status_code == 200
    assert me(login(app, "jo", "reset-by-the-admin"))["user"]["must_change_password"] is True


def test_admin_setting_own_password_is_not_temporary(app, admin):
    uid = me(admin)["user"]["id"]
    assert admin.patch(f"/api/users/{uid}", json={"password": "the-admins-own-choice"}).status_code == 200
    assert me(login(app, "admin", "the-admins-own-choice"))["user"]["must_change_password"] is False


def test_mixed_case_names_are_accepted(admin):
    r = admin.post("/api/groups", json={"name": "Finance", "description": ""})
    assert r.status_code in (200, 201), r.text
    assert r.json()["folder"] == "/shared/finance"


def test_overview_days_follow_the_viewers_time_zone(admin):
    import datetime as dt
    utc = admin.get("/api/overview", params={"days": 3}).json()["series"]
    # 14 hours ahead of UTC (getTimezoneOffset -840): its "today" is never earlier than UTC's.
    east = admin.get("/api/overview", params={"days": 3, "tz": -840}).json()["series"]
    assert len(utc) == len(east) == 3
    assert east[-1]["date"] >= utc[-1]["date"]
    assert dt.date.fromisoformat(east[-1]["date"]) - dt.date.fromisoformat(east[0]["date"]) == dt.timedelta(days=2)
