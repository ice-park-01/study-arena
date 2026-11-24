"""올린 자료를 조각으로 나누고 문제를 만드는 백그라운드 작업."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from app.db import Store
from app.ingest import extract_chunks
from app.llm import LLMClient, generate_questions

log = logging.getLogger("arena.worker")
BATCH_SIZE = 3    # LLM 호출 한 번에 보내는 조각 수
MAX_BATCHES = 6   # 자료 하나당 LLM 호출 상한 (무료 한도 보호)


def pick_chunks(chunks: dict[int, str], limit: int) -> dict[int, str]:
    """내용이 많은 조각을 limit개까지 고르되 원래 순서는 지킨다."""
    if len(chunks) <= limit:
        return chunks
    keep = set(sorted(chunks, key=lambda cid: len(chunks[cid]), reverse=True)[:limit])
    return {cid: text for cid, text in chunks.items() if cid in keep}


def process_material(store: Store, llm: LLMClient, material_id: int, now: datetime | None = None,
                     max_batches: int | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    max_batches = max_batches or int(os.environ.get("MAX_BATCHES", MAX_BATCHES))
    material = store.get_material(material_id)
    store.set_material_status(material_id, "processing")
    try:
        texts = extract_chunks(material["filename"], store.get_upload(material_id))
        if not texts:
            raise ValueError("문제를 만들 만한 내용을 찾지 못했습니다.")
        ids = store.add_chunks(material_id, texts)
        chunks = pick_chunks(dict(zip(ids, texts)), max_batches * BATCH_SIZE)
        items = list(chunks.items())
        discarded, used_fallback, total = 0, False, 0
        for start in range(0, len(items), BATCH_SIZE):
            batch = dict(items[start : start + BATCH_SIZE])
            result = generate_questions(batch, llm)
            store.add_questions(material_id, result.questions)
            store.log_llm("generate", now, calls=result.llm_calls, failures=result.llm_failures,
                          discarded=result.discarded, fallback=result.used_fallback)
            discarded += result.discarded
            used_fallback = used_fallback or result.used_fallback
            total += len(result.questions)
        if total == 0:
            raise ValueError("문제를 만들지 못했습니다.")
        store.set_material_status(material_id, "ready", n_chunks=len(texts), discarded=discarded,
                                  used_fallback=used_fallback)
    except ValueError as exc:
        store.set_material_status(material_id, "failed", error=str(exc))
    except Exception:  # 예상하지 못한 오류도 작업자를 죽이지 않는다
        log.exception("material %s failed", material_id)
        store.set_material_status(material_id, "failed", error="처리 중 오류가 발생했습니다.")
    finally:
        store.finish_job(material_id)


def run_once(store: Store, llm: LLMClient) -> int:
    """대기 중인 작업을 모두 처리하고 처리한 개수를 돌려준다."""
    done = 0
    while (material_id := store.claim_job()) is not None:
        process_material(store, llm, material_id)
        done += 1
    return done


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    store = Store(os.environ.get("DB_PATH", "data/arena.db"))
    store.migrate()
    llm = LLMClient.from_env()
    log.info("worker started (llm %s)", "enabled" if llm.enabled else "disabled")
    if (requeued := store.requeue_interrupted_jobs()):
        log.info("requeued %s interrupted job(s)", requeued)

    def heartbeat() -> None:  # 긴 작업 중에도 /health 가 작업자를 살아 있다고 보게 한다
        while True:
            store.set_meta("worker_seen", datetime.now(timezone.utc).isoformat())
            time.sleep(5)

    threading.Thread(target=heartbeat, daemon=True).start()
    while True:
        if run_once(store, llm):
            log.info("jobs processed")
        time.sleep(2)


if __name__ == "__main__":
    main()
