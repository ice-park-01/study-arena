"""실행 중인 서버에 가입하고 강의자료를 올리는 시연용 스크립트.

    python scripts/demo_upload.py --url http://127.0.0.1:8000 --user 성진 --password pw-1234 --dir ~/lectures --match Lecture8
"""
from __future__ import annotations

import argparse
import time
import unicodedata
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--match", default="")
    args = parser.parse_args()

    with httpx.Client(base_url=args.url, timeout=300) as client:
        form = {"name": args.user, "password": args.password}
        if client.post("/signup", data=form).status_code == 400:
            client.post("/login", data=form)
        for path in sorted(Path(args.dir).expanduser().iterdir()):
            name = unicodedata.normalize("NFC", path.name)
            if not name.lower().endswith((".pptx", ".pdf", ".txt")) or name.startswith("~") or args.match not in name:
                continue
            response = client.post("/materials", files={"file": (name, path.read_bytes())}, follow_redirects=False)
            material_id = response.headers["location"].rsplit("/", 1)[-1]
            while client.get(f"/api/materials/{material_id}").json()["status"] in ("queued", "processing"):
                time.sleep(1)
            print(client.get(f"/api/materials/{material_id}").json()["status"], name)


if __name__ == "__main__":
    main()
