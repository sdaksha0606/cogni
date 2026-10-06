"""Client for the PhishGuard extension: the hosted service behind app-debug.apk.

Endpoints used (taken from the APK's own web code): /api/login, /api/analyze, /api/pay,
/api/pay/confirm, /api/report. Configure with environment variables:
  PHISHGUARD_URL       default https://phishguard-upi.onrender.com
  PHISHGUARD_EMAIL     your PhishGuard account email
  PHISHGUARD_PASSWORD  your PhishGuard account password
  PHISHGUARD_PAY_GATE  1 (default) also asks the extension's pay gate for block/verify decisions.
                       The gate records the payment on the extension's own demo ledger. Set 0 for analyze-only.
"""
import os, time, requests

BASE = os.getenv("PHISHGUARD_URL", "https://phishguard-upi.onrender.com").rstrip("/")
EMAIL, PASSWORD = os.getenv("PHISHGUARD_EMAIL", ""), os.getenv("PHISHGUARD_PASSWORD", "")
PAY_GATE = os.getenv("PHISHGUARD_PAY_GATE", "1") == "1"
_s = {"token": "", "ok": False, "seen": 0.0}


def _call(path, body=None, method="POST", retry=True):
    h = {"Content-Type": "application/json", "Authorization": "Bearer " + _s["token"]}
    r = requests.request(method, BASE + path, json=body, headers=h, timeout=60)  # free hosting can cold-start slowly
    if r.status_code == 401 and retry and not path.startswith("/api/login"):
        login()
        return _call(path, body, method, False)
    data = r.json() if r.content else {}
    if not r.ok: raise RuntimeError(data.get("error") or f"PhishGuard service returned {r.status_code}")
    return data


def login():
    if not (EMAIL and PASSWORD): raise RuntimeError("Set PHISHGUARD_EMAIL and PHISHGUARD_PASSWORD.")
    _s["token"] = _call("/api/login", {"email": EMAIL, "password": PASSWORD}, retry=False)["token"]


def online():
    """Cheap reachability probe, cached for 30 seconds."""
    if time.time() - _s["seen"] < 30: return _s["ok"]
    try:
        requests.get(BASE, timeout=5)
        _s["ok"] = True
    except requests.RequestException:
        _s["ok"] = False
    _s["seen"] = time.time()
    return _s["ok"]


def check(payload, info, amount, note, ctx, src):
    """Ask the extension to judge a payment. Returns a normalized dict, or {"error": ...}."""
    t0 = time.time()
    try:
        if not _s["token"]: login()
        a = _call("/api/analyze", {"type": "link" if payload.lower().startswith("http") else "qr", "value": payload})
        status, ref, extra = "success", None, []
        if PAY_GATE and info["vpa"]:
            p = _call("/api/pay", {"upi_id": info["vpa"], "name": info["name"] or "", "amount": amount, "note": note,
                                   "app": "Zippay", "device": ctx.get("device"), "city": ctx.get("city"), "hour": ctx.get("hour")})
            status, ref, extra = p.get("status", "success"), p.get("pay_ref"), p.get("reasons") or []
        _s["ok"], _s["seen"] = True, time.time()
    except Exception as e:
        _s["ok"], _s["seen"] = False, time.time()
        return {"error": str(e), "ms": int((time.time() - t0) * 1000)}
    score = int(a.get("risk", 0))
    if status == "blocked": score = max(score, 80)
    elif status != "success": score = max(score, 45)
    texts = list(dict.fromkeys((a.get("reasons") or []) + extra))
    return {"id": ref or f"a{int(t0 * 1000)}", "ref": ref, "score": score, "ms": int((time.time() - t0) * 1000),
            "blocked": status == "blocked" or a.get("level") == "High",
            "needs_code": status not in ("success", "blocked") and a.get("level") != "High",
            "reasons": [{"title": t, "why": "Reported by the PhishGuard extension.", "w": max(10, 30 - 5 * i)} for i, t in enumerate(texts)]}


def confirm(ref, code, upi_id, amount):
    return _call("/api/pay/confirm", {"pay_ref": ref, "code": code, "upi_id": upi_id, "amount": amount})


def report(upi_id, category="Phishing QR code", details=""):
    return _call("/api/report", {"upi_id": upi_id, "category": category, "details": details})
