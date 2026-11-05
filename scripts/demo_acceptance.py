"""Acceptance over real HTTP against a new offline demo process and disposable DB."""

import argparse
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fixture_only": True,
        "real_bank_login": False,
        "real_ocr": False,
        "checks": [],
    }
    session = requests.Session()
    session.trust_env = False

    def check(name, condition):
        report["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    with tempfile.TemporaryDirectory(
        prefix="its-demo-acceptance-", ignore_cleanup_errors=True
    ) as temp:
        folder = Path(temp)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        child = None
        log = (folder / "server.log").open("w", encoding="utf8")

        def start():
            process = subprocess.Popen(
                [
                    sys.executable,
                    "scripts/serve.py",
                    "--demo",
                    "--port",
                    str(port),
                    "--demo-dir",
                    str(folder / "runtime"),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            begun = time.monotonic()
            while time.monotonic() - begun < 30:
                if process.poll() is not None:
                    raise RuntimeError("Demo process exited before readiness")
                try:
                    response = session.get(url + "/readiness", timeout=1)
                    if response.status_code == 200 and response.json().get("status") == "ready":
                        return process, round((time.monotonic() - begun) * 1000, 2)
                except requests.RequestException:
                    pass
                time.sleep(0.1)
            process.terminate()
            process.wait(timeout=10)
            raise RuntimeError("Demo readiness timed out")

        def stop(process):
            if process is not None and process.poll() is None:
                process.terminate()  # This handle was created by this script, never a discovered PID.
                process.wait(timeout=10)

        def login(name, password):
            response = session.post(
                url + "/auth/login", data={"username": name, "password": password}, timeout=8
            )
            check("login_" + name, response.status_code == 200)
            return {"Authorization": "Bearer " + response.json()["access_token"]}

        image = Image.new("RGB", (400, 180), "white")
        ImageDraw.Draw(image).text((40, 65), "59-B1 123.45 - SYNTHETIC DEMO", fill="black")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        picture = stream.getvalue()

        def form(path, user, **values):
            return session.post(
                url + path,
                headers=user,
                data=values,
                files={"file": ("synthetic.png", picture, "image/png")},
                timeout=8,
            )

        try:
            child, report["startup_ms"] = start()
            page = session.get(url + "/", timeout=5)
            check("demo_shell", page.status_code == 200 and 'class="runtime-notice"' in page.text)
            check(
                "no_unconfigured_public_write",
                session.get(url + "/tickets/active", timeout=5).status_code == 401,
            )
            admin = login("admin", "ItsDemo@2026A")
            operator = login("operator", "ItsDemo@2026O")
            viewer = login("viewer", "ItsDemo@2026V")
            check(
                "viewer_cannot_manage_accounts",
                session.get(url + "/admin/users", headers=viewer, timeout=5).status_code == 403,
            )
            check(
                "viewer_cannot_enter_vehicle",
                form(
                    "/vehicle/entry",
                    viewer,
                    plate_text="59-B1 123.45",
                    manual_only="true",
                    ai_review_confirmed="true",
                ).status_code
                == 403,
            )
            ocr = form("/ocr", operator).json()["ocr"]
            check(
                "offline_ocr_abstains_without_provider",
                ocr["ocr_engine"] == "demo-offline" and not ocr["is_usable"] and not ocr["text"],
            )
            tariffs = session.get(url + "/pricing", headers=admin, timeout=5).json()["items"]
            tariff = next(row for row in tariffs if row["vehicle_type"] == "motorcycle")
            fields = (
                "revision",
                "enabled",
                "mode",
                "flat_amount",
                "first_minutes",
                "first_amount",
                "next_minutes",
                "next_amount",
                "daily_cap",
                "grace_minutes",
            )
            policy = {key: tariff[key] for key in fields}
            policy.update(enabled=True, mode="flat", flat_amount=5000, grace_minutes=0)
            check(
                "enable_fixture_tariff",
                session.put(
                    url + "/pricing/motorcycle", headers=admin, json=policy, timeout=5
                ).status_code
                == 200,
            )
            entry = form(
                "/vehicle/entry",
                operator,
                plate_text="59-B1 123.45",
                manual_only="true",
                ai_review_confirmed="true",
            )
            check("entry_created", entry.status_code == 201)
            ticket = entry.json()["result"]["ticket_id"]
            duplicate = form(
                "/vehicle/entry",
                operator,
                plate_text="59-B1 123.45",
                manual_only="true",
                ai_review_confirmed="true",
            )
            check("duplicate_entry_rejected", duplicate.status_code == 409)
            mismatch = form(
                "/vehicle/exit",
                operator,
                ticket_id=ticket,
                plate_text="59-B1 123.46",
                manual_only="true",
                ai_review_confirmed="true",
            )
            check(
                "mismatch_needs_review",
                mismatch.status_code == 200
                and mismatch.json()["result"]["status"] == "NEEDS_REVIEW",
            )
            blocked = session.post(
                url + f"/tickets/{ticket}/payment",
                headers=operator,
                json={
                    "amount": 5000,
                    "quote_id": "0" * 64,
                    "method": "cash",
                    "received_amount": 10000,
                },
                timeout=5,
            )
            check("review_ticket_cannot_be_paid", blocked.status_code == 409)
            resolved = session.post(
                url + f"/tickets/{ticket}/resolve",
                headers=operator,
                data={
                    "resolution": "MARK_MATCH",
                    "note": "Synthetic offline acceptance: visual review completed",
                },
                timeout=5,
            )
            check(
                "review_resolved",
                resolved.status_code == 200 and resolved.json()["result"]["status"] == "COMPLETED",
            )
            finance = session.get(
                url + f"/tickets/{ticket}/finance", headers=operator, timeout=5
            ).json()["finance"]
            payment = {
                "amount": finance["amount"],
                "quote_id": finance["quote_id"],
                "method": "cash",
                "received_amount": 10000,
            }
            receipt = session.post(
                url + f"/tickets/{ticket}/payment", headers=operator, json=payment, timeout=5
            )
            check("cash_payment_recorded", receipt.status_code == 200)
            again = session.post(
                url + f"/tickets/{ticket}/payment", headers=operator, json=payment, timeout=5
            )
            check(
                "payment_retry_is_idempotent",
                again.status_code == 200
                and again.json()["already_paid"] is True
                and again.json()["receipt"]["receipt_id"]
                == receipt.json()["receipt"]["receipt_id"],
            )
            check(
                "bank_connection_disabled",
                session.post(
                    url + "/mb/connect", headers=admin, json={"captcha_mode": "manual"}, timeout=5
                ).status_code
                == 503,
            )
            devices = session.get(url + "/devices/status", headers=operator, timeout=5).json()
            check("device_status_explicitly_simulated", "SIMULATED" in json.dumps(devices))
            stop(child)
            child, report["restart_ms"] = start()
            check(
                "restart_invalidates_demo_session",
                session.get(url + "/auth/me", headers=admin, timeout=5).status_code == 401,
            )
            admin = login("admin", "ItsDemo@2026A")
            persisted = session.get(
                url + f"/tickets/{ticket}/finance", headers=admin, timeout=5
            ).json()["finance"]
            check("restart_preserves_paid_ticket", persisted["state"] == "paid")
            report["passed"] = True
        except Exception as exc:
            report["passed"] = False
            report["failure"] = f"{type(exc).__name__}: {exc}"
        finally:
            stop(child)
            log.close()
            session.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
