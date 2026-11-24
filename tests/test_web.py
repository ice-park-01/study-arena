import re

from fastapi.testclient import TestClient

from tests.conftest import signup, upload


def test_health_reports_ok(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["llm"] == "disabled"


def test_pages_require_login(client):
    for path in ("/", "/materials", "/groups", "/wrong"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login", path
    assert client.post("/api/tick").status_code == 401


def test_signup_login_logout(app):
    c = signup(app, "성진")
    assert "성진" in c.get("/").text
    c.post("/logout")
    assert c.get("/", follow_redirects=False).status_code == 303
    bad = c.post("/login", data={"name": "성진", "password": "wrong"})
    assert "닉네임 또는 비밀번호" in bad.text
    ok = c.post("/login", data={"name": "성진", "password": "pw-1234"}, follow_redirects=False)
    assert ok.status_code == 303


def test_signup_rejects_duplicates_and_short_passwords(app):
    signup(app, "성진")
    c = TestClient(app)
    assert "이미 사용 중" in c.post("/signup", data={"name": "성진", "password": "pw-1234"}).text
    assert "6자 이상" in c.post("/signup", data={"name": "가현", "password": "123"}).text


def test_passwords_are_not_stored_in_plain_text(app):
    signup(app, "성진", "pw-1234")
    row = app.state.store.get_user_by_name("성진")
    assert "pw-1234" not in row["pw_hash"]


def test_upload_generates_cloze_questions_without_an_api_key(app):
    c = signup(app, "성진")
    mid = upload(c)
    page = c.get(f"/materials/{mid}").text
    assert "강의노트.txt" in page
    assert "빈칸 문제로 대체" in page
    assert len(app.state.store.list_questions(mid)) == 3


def test_unsupported_upload_shows_an_error(app):
    c = signup(app, "성진")
    r = c.post("/materials", files={"file": ("과제.hwp", b"...", "application/octet-stream")})
    assert "지원하지 않는 파일 형식" in r.text


def test_solve_right_and_wrong_and_see_wrong_list(app):
    c = signup(app, "성진")
    mid = upload(c)
    store = app.state.store

    page = c.get(f"/quiz/{mid}").text
    qid = int(re.search(r'action="/quiz/answer/(\d+)"', page).group(1))
    answer = store.get_question(qid)["answer"]
    right = c.post(f"/quiz/answer/{qid}", data={"answer": answer}).text
    assert "정답입니다" in right
    assert "근거" in right

    page = c.get(f"/quiz/{mid}").text
    qid2 = int(re.search(r'action="/quiz/answer/(\d+)"', page).group(1))
    assert qid2 != qid
    wrong = c.post(f"/quiz/answer/{qid2}", data={"answer": "모르겠어요"}).text
    assert "오답입니다" in wrong
    assert store.get_question(qid2)["prompt"].split("\n")[-1][:10] in c.get("/wrong").text


def test_other_users_cannot_open_my_material(app):
    mine = signup(app, "성진")
    mid = upload(mine)
    other = signup(app, "가현")
    assert other.get(f"/materials/{mid}").status_code == 403
    assert other.get(f"/quiz/{mid}").status_code == 403


def test_ticks_add_up_study_time(app, clock):
    c = signup(app, "성진")
    assert c.post("/api/tick").json()["credited"] == 0
    clock.tick(30)
    assert c.post("/api/tick").json() == {"credited": 30, "today_seconds": 30, "studying": True}
    clock.tick(30)
    assert c.post("/api/tick").json()["today_seconds"] == 60
    clock.tick(600)  # 자리를 비웠다
    assert c.post("/api/tick").json()["today_seconds"] == 60


def test_client_cannot_claim_extra_time(app, clock):
    c = signup(app, "성진")
    c.post("/api/tick")
    clock.tick(30)
    r = c.post("/api/tick", json={"seconds": 99999, "at": "2020-01-01T00:00:00Z"})
    assert r.json()["today_seconds"] == 30


def test_invite_code_join_and_ranking(app, clock):
    owner = signup(app, "성진")
    r = owner.post("/groups", data={"name": "오픈소스 스터디"}, follow_redirects=False)
    gid = int(r.headers["location"].split("/")[-1])
    code = app.state.store.get_group(gid)["code"]
    assert code in owner.get(f"/groups/{gid}").text

    friend = signup(app, "가현")
    j = friend.post("/groups/join", data={"code": code.lower()}, follow_redirects=False)
    assert j.headers["location"] == f"/groups/{gid}"

    for c, rounds in ((owner, 2), (friend, 4)):
        c.post("/api/tick")
        for _ in range(rounds):
            clock.tick(30)
            c.post("/api/tick")
    rows = owner.get(f"/api/groups/{gid}/ranking").json()["today"]
    assert [(r["rank"], r["name"], r["seconds"]) for r in rows] == [(1, "가현", 120), (2, "성진", 60)]
    assert rows[0]["studying"] is True


def test_joining_twice_does_not_duplicate(app):
    owner = signup(app, "성진")
    r = owner.post("/groups", data={"name": "스터디"}, follow_redirects=False)
    gid = int(r.headers["location"].split("/")[-1])
    code = app.state.store.get_group(gid)["code"]
    friend = signup(app, "가현")
    friend.post("/groups/join", data={"code": code})
    friend.post("/groups/join", data={"code": code})
    names = [r["name"] for r in friend.get(f"/api/groups/{gid}/ranking").json()["today"]]
    assert sorted(names) == ["가현", "성진"]


def test_wrong_invite_code_and_outsiders(app):
    owner = signup(app, "성진")
    r = owner.post("/groups", data={"name": "스터디"}, follow_redirects=False)
    gid = int(r.headers["location"].split("/")[-1])
    outsider = signup(app, "민수")
    assert "초대 코드를 찾을 수 없습니다" in outsider.post("/groups/join", data={"code": "ZZZZZZ"}).text
    assert outsider.get(f"/groups/{gid}").status_code == 403
    assert outsider.get(f"/api/groups/{gid}/ranking").status_code == 403


def test_ops_page_shows_llm_counters(app):
    c = signup(app, "성진")
    upload(c)
    page = c.get("/ops").text
    assert "LLM 호출" in page and "버린 문제" in page


def test_paused_time_is_not_credited(app, clock):
    c = signup(app, "성진")
    c.post("/api/tick")
    clock.tick(30)
    c.post("/api/tick")
    assert c.post("/api/pause").json() == {"studying": False}
    clock.tick(60)  # 멈춘 채로 1분
    assert c.post("/api/tick").json()["today_seconds"] == 30
    assert TestClient(app).post("/api/pause").status_code == 401


def test_pausing_removes_the_studying_badge(app, clock):
    owner = signup(app, "성진")
    r = owner.post("/groups", data={"name": "스터디"}, follow_redirects=False)
    gid = int(r.headers["location"].split("/")[-1])
    owner.post("/api/tick")
    assert owner.get(f"/api/groups/{gid}/ranking").json()["today"][0]["studying"] is True
    owner.post("/api/pause")
    assert owner.get(f"/api/groups/{gid}/ranking").json()["today"][0]["studying"] is False


def test_oversized_upload_is_rejected(app, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "MAX_UPLOAD", 100)
    c = signup(app, "성진")
    r = c.post("/materials", files={"file": ("big.txt", b"x" * 500, "text/plain")})
    assert "파일이 너무 큽니다" in r.text
    assert app.state.store.list_materials(1) == []
