"""Study Arena: 화면과 API."""
from __future__ import annotations

import json
import os
import random
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import auth
from app.db import Store
from app.groups import new_invite_code, rank
from app.ingest import SUPPORTED
from app.llm import LLMClient, grade_short
from app.quiz import grade_mcq
from app.timer import format_duration, is_studying, kst_date, week_start
from app.worker import process_material

HERE = Path(__file__).resolve().parent
MAX_UPLOAD = 30 * 1024 * 1024
WORKER_ALIVE_SECONDS = 30
KIND_LABEL = {"mcq": "객관식", "short": "주관식", "cloze": "빈칸"}


class NotLoggedIn(Exception):
    pass


def create_app(db_path: str | None = None, llm: LLMClient | None = None, now=None,
               inline_jobs: bool | None = None, rng: random.Random | None = None) -> FastAPI:
    """앱을 만든다. 시계·LLM·난수를 인자로 받아 테스트에서 바꿔 끼울 수 있다."""
    store = Store(db_path or os.environ.get("DB_PATH", "data/arena.db"))
    store.migrate()
    llm = llm or LLMClient.from_env()
    now = now or (lambda: datetime.now(timezone.utc))
    rng = rng or random.SystemRandom()
    if inline_jobs is None:
        inline_jobs = os.environ.get("INLINE_JOBS", "1") == "1"

    secret = store.get_meta("session_secret")
    if secret is None:
        secret = secrets.token_hex(32)
        store.set_meta("session_secret", secret)

    app = FastAPI(title="Study Arena", docs_url="/docs", redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=secret, max_age=60 * 60 * 24 * 30, same_site="lax")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["duration"] = format_duration
    templates.env.globals["KIND_LABEL"] = KIND_LABEL
    app.state.store = store
    app.state.llm = llm
    version = os.environ.get("APP_VERSION", "dev")

    # --- 공통 --------------------------------------------------------------

    @app.exception_handler(NotLoggedIn)
    async def _not_logged_in(request: Request, _exc: NotLoggedIn):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    def user_of(request: Request):
        uid = request.session.get("uid")
        user = store.get_user(uid) if uid else None
        if user is None:
            raise NotLoggedIn()
        return user

    def page(request: Request, template: str, user=None, status_code: int = 200, **ctx):
        if user is not None:
            ctx["today_seconds"] = store.seconds_on(user["id"], kst_date(now()))
        return templates.TemplateResponse(request, template, {"user": user, "version": version, **ctx},
                                          status_code=status_code)

    def my_material(user, material_id: int):
        material = store.get_material(material_id)
        if material is None:
            raise HTTPException(404, "자료를 찾을 수 없습니다.")
        if material["user_id"] != user["id"]:
            raise HTTPException(403, "다른 사람의 자료입니다.")
        return material

    def my_group(user, group_id: int):
        group = store.get_group(group_id)
        if group is None:
            raise HTTPException(404, "그룹을 찾을 수 없습니다.")
        if not store.is_member(group_id, user["id"]):
            raise HTTPException(403, "가입하지 않은 그룹입니다.")
        return group

    def ranking_of(group_id: int) -> dict:
        members = store.members(group_id)
        ids = [m["id"] for m in members]
        names = {m["id"]: m["name"] for m in members}
        moment = now()
        today = kst_date(moment)
        monday = week_start(today)
        last = store.last_ticks(ids)
        studying = {names[uid] for uid in ids if is_studying(last.get(uid), moment)}

        def rows(first, final):
            totals = store.seconds_between(ids, first, final)
            return [
                {"rank": r.rank, "name": r.name, "seconds": r.seconds, "studying": r.studying,
                 "label": format_duration(r.seconds)}
                for r in rank({names[uid]: seconds for uid, seconds in totals.items()}, studying)
            ]

        return {"today": rows(today, today), "week": rows(monday, monday + timedelta(days=6))}

    # --- 상태 확인 ----------------------------------------------------------

    @app.get("/health")
    def health():
        try:
            schema = store.schema_version()
            db = "ok"
        except Exception:
            schema, db = 0, "error"
        if inline_jobs:
            worker = "inline"
        else:
            seen = store.get_meta("worker_seen") if db == "ok" else None
            alive = seen and (now() - datetime.fromisoformat(seen)).total_seconds() <= WORKER_ALIVE_SECONDS
            worker = "ok" if alive else "down"
        ok = db == "ok" and worker != "down"
        return {"status": "ok" if ok else "degraded", "db": db, "worker": worker,
                "llm": "enabled" if llm.enabled else "disabled", "schema": schema, "version": version}

    # --- 가입, 로그인 --------------------------------------------------------

    @app.get("/signup")
    def signup_form(request: Request):
        return page(request, "auth.html", mode="signup")

    @app.post("/signup")
    def signup(request: Request, name: str = Form(""), password: str = Form("")):
        name = name.strip()
        error = auth.check_signup(name, password)
        if error is None:
            try:
                uid = store.create_user(name, auth.hash_password(password), now())
            except ValueError as exc:
                error = str(exc)
        if error:
            return page(request, "auth.html", mode="signup", error=error, name=name, status_code=400)
        request.session["uid"] = uid
        return RedirectResponse("/", status_code=303)

    @app.get("/login")
    def login_form(request: Request):
        return page(request, "auth.html", mode="login")

    @app.post("/login")
    def login(request: Request, name: str = Form(""), password: str = Form("")):
        user = store.get_user_by_name(name.strip())
        if user is None or not auth.verify_password(password, user["pw_hash"]):
            return page(request, "auth.html", mode="login", name=name,
                        error="닉네임 또는 비밀번호가 맞지 않습니다.", status_code=400)
        request.session["uid"] = user["id"]
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # --- 대시보드 ------------------------------------------------------------

    @app.get("/")
    def dashboard(request: Request):
        user = user_of(request)
        today = kst_date(now())
        monday = week_start(today)
        week = store.seconds_between([user["id"]], monday, monday + timedelta(days=6))[user["id"]]
        groups = []
        for group in store.list_groups(user["id"]):
            rows = ranking_of(group["id"])["today"]
            mine = next(r for r in rows if r["name"] == user["name"])
            groups.append({"id": group["id"], "name": group["name"], "n_members": group["n_members"],
                           "rank": mine["rank"], "top": rows[0]})
        return page(request, "dashboard.html", user, week_seconds=week, groups=groups,
                    materials=store.list_materials(user["id"])[:4], wrong=len(store.wrong_questions(user["id"])))

    # --- 자료 ----------------------------------------------------------------

    def materials_page(request: Request, user, error: str | None = None, status_code: int = 200):
        return page(request, "materials.html", user, materials=store.list_materials(user["id"]), error=error,
                    status_code=status_code, llm_enabled=llm.enabled)

    @app.get("/materials")
    def materials(request: Request):
        return materials_page(request, user_of(request))

    @app.post("/materials")
    async def upload(request: Request, background: BackgroundTasks, file: UploadFile = File(...)):
        user = user_of(request)
        filename = Path(file.filename or "").name
        if not filename.lower().endswith(SUPPORTED):
            return materials_page(request, user, "지원하지 않는 파일 형식입니다. pptx, pdf, txt만 올릴 수 있습니다.", 400)
        data = await file.read(MAX_UPLOAD + 1)  # 상한보다 1바이트만 더 읽어 초과 여부를 안다
        if not data:
            return materials_page(request, user, "빈 파일입니다.", 400)
        if len(data) > MAX_UPLOAD:
            return materials_page(request, user, "파일이 너무 큽니다. 30MB 이하만 올릴 수 있습니다.", 400)
        material_id = store.add_material(user["id"], filename, data, now())
        if inline_jobs:
            background.add_task(process_material, store, llm, material_id, now())
        else:
            store.enqueue_job(material_id)
        return RedirectResponse(f"/materials/{material_id}", status_code=303, background=background)

    @app.get("/materials/{material_id}")
    def material(request: Request, material_id: int):
        user = user_of(request)
        m = my_material(user, material_id)
        questions = store.list_questions(material_id)
        kinds = {kind: sum(1 for q in questions if q["kind"] == kind) for kind in KIND_LABEL}
        return page(request, "material.html", user, m=m, kinds=kinds, n_questions=len(questions),
                    progress=store.material_progress(user["id"], material_id))

    @app.get("/api/materials/{material_id}")
    def material_status(request: Request, material_id: int):
        m = my_material(user_of(request), material_id)
        return {"status": m["status"]}

    # --- 문제 풀이 ------------------------------------------------------------

    @app.get("/quiz/{material_id}")
    def quiz(request: Request, material_id: int):
        user = user_of(request)
        m = my_material(user, material_id)
        progress = store.material_progress(user["id"], material_id)
        q = store.next_question(user["id"], material_id)
        if q is None:
            return page(request, "done.html", user, m=m, progress=progress)

        choices = json.loads(q["choices"])
        random.Random(q["id"] * 31 + progress["attempts"]).shuffle(choices)
        return page(request, "quiz.html", user, m=m, q=q, choices=choices, progress=progress)

    @app.post("/quiz/answer/{question_id}")
    def answer(request: Request, question_id: int, answer: str = Form("")):
        user = user_of(request)
        row = store.get_question(question_id)
        if row is None:
            raise HTTPException(404, "문제를 찾을 수 없습니다.")
        m = my_material(user, row["material_id"])
        q = store.to_question(row)
        chunk = store.get_chunk(row["chunk_id"])
        if q.kind == "mcq":
            correct, by = grade_mcq(q, answer), "exact"
            feedback = "" if correct else f"정답: {q.answer}"
        else:
            grade = grade_short(q, answer, chunk["text"], llm)
            correct, by, feedback = grade.correct, grade.by, grade.feedback
            if q.kind == "short" and llm.enabled and answer.strip():
                store.log_llm("grade", now(), calls=1, failures=int(by != "llm"), fallback=by != "llm")
        store.add_attempt(user["id"], question_id, answer, correct, feedback, by, now())
        return page(request, "result.html", user, m=m, q=row, answer=answer, correct=correct, feedback=feedback,
                    by=by, chunk=chunk, progress=store.material_progress(user["id"], m["id"]))

    @app.get("/wrong")
    def wrong(request: Request):
        user = user_of(request)
        return page(request, "wrong.html", user, questions=store.wrong_questions(user["id"]))

    # --- 공부 시간 ------------------------------------------------------------

    @app.post("/api/tick")
    def tick(request: Request):
        """공부 중 신호. 요청 본문은 읽지 않는다: 시간은 서버 시계로만 계산한다."""
        user = user_of(request)
        moment = now()
        credited = store.record_tick(user["id"], moment)
        return {"credited": credited, "today_seconds": store.seconds_on(user["id"], kst_date(moment)),
                "studying": True}

    @app.post("/api/pause")
    def pause(request: Request):
        """공부를 멈췄다는 신호. 멈춘 동안의 시간이 인정되지 않게 세션을 끝낸다."""
        store.clear_last_tick(user_of(request)["id"])
        return {"studying": False}

    # --- 그룹 ----------------------------------------------------------------

    def groups_page(request: Request, user, error: str | None = None, status_code: int = 200):
        return page(request, "groups.html", user, groups=store.list_groups(user["id"]), error=error,
                    status_code=status_code)

    @app.get("/groups")
    def groups(request: Request):
        return groups_page(request, user_of(request))

    @app.post("/groups")
    def create_group(request: Request, name: str = Form("")):
        user = user_of(request)
        name = name.strip()
        if not 1 <= len(name) <= 30:
            return groups_page(request, user, "그룹 이름은 1~30자로 입력하세요.", 400)
        code = new_invite_code(rng)
        while store.get_group_by_code(code) is not None:
            code = new_invite_code(rng)
        group_id = store.create_group(user["id"], name, code, now())
        return RedirectResponse(f"/groups/{group_id}", status_code=303)

    @app.post("/groups/join")
    def join_group(request: Request, code: str = Form("")):
        user = user_of(request)
        group = store.get_group_by_code(code.strip().upper())
        if group is None:
            return groups_page(request, user, "초대 코드를 찾을 수 없습니다. 다시 확인해 주세요.", 404)
        store.join_group(group["id"], user["id"])
        return RedirectResponse(f"/groups/{group['id']}", status_code=303)

    @app.get("/groups/{group_id}")
    def group(request: Request, group_id: int):
        user = user_of(request)
        g = my_group(user, group_id)
        return page(request, "group.html", user, g=g, ranking=ranking_of(group_id))

    @app.get("/api/groups/{group_id}/ranking")
    def group_ranking(request: Request, group_id: int):
        my_group(user_of(request), group_id)
        return ranking_of(group_id)

    # --- 운영 현황 ------------------------------------------------------------

    @app.get("/ops")
    def ops(request: Request):
        user = user_of(request)
        return page(request, "ops.html", user, summary=store.llm_summary(), health=health(), model=llm.model)

    return app


def _default_app() -> FastAPI:
    return create_app()


# `uvicorn app.main:app` 으로 실행할 때 쓰는 기본 앱 (모듈을 불러올 때 만들지 않는다)
def __getattr__(name: str):
    if name == "app":
        globals()["app"] = _default_app()
        return globals()["app"]
    raise AttributeError(name)
