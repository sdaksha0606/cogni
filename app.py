import os, time, random, statistics, requests
from urllib.parse import urlparse, parse_qs, unquote
from flask import Flask, jsonify, request, send_from_directory
import extension_client as ext

app = Flask(__name__)
ME = {"name": "Arjun Kumar", "mobile": "98765 43210", "vpa": "arjun@oksbi", "app_pin": "2580",
      "upi_pin": "1234", "limit": 100000, "guard": True, "tries": 0}
BANKS = {"SBI ••1234": 48250.0, "HDFC ••5678": 12600.0}
CONTACTS = [{"name": "Amma", "vpa": "amma@oksbi"}, {"name": "Ramesh", "vpa": "ramesh@okaxis"},
            {"name": "DMart", "vpa": "dmart@okicici"}, {"name": "TNEB Bill", "vpa": "tneb.bills@sbi"}]
NAMES = {"amma@oksbi": "Lakshmi Kumar", "ramesh@okaxis": "Ramesh S", "dmart@okicici": "Avenue Supermarts Ltd",
         "tneb.bills@sbi": "TANGEDCO", "sharma.store@okaxis": "Sharma General Store",
         "dmart-help@okxyz": "R Kumar Traders", "rewards@paytmx": "Rewards Desk", "tneb.biils@sbi": "S Mohan"}
HIST = [{"id": i, "name": n, "vpa": v, "amount": a, "bank": "SBI ••1234", "utr": u, "time": t, "status": "Success",
         "note": "", "ts": time.time() - 86400 * d, "dr": True}
        for i, (n, v, a, u, t, d) in enumerate([("Amma", "amma@oksbi", 500, "428193746215", "28 Sep, 06:12 PM", 5),
                                                ("DMart", "dmart@okicici", 640, "428377120934", "30 Sep, 07:40 PM", 3),
                                                ("TNEB Bill", "tneb.bills@sbi", 1200, "428590013377", "01 Oct, 10:05 AM", 2)], 1)]
COLLECT = [{"id": 1, "from": "Refund Desk", "vpa": "rewards@paytmx", "amount": 4999, "note": "Refund pending. Approve to receive.",
            "payload": "upi://pay?pa=rewards@paytmx&pn=Refund Desk&am=4999"},
           {"id": 2, "from": "Ramesh", "vpa": "ramesh@okaxis", "amount": 500, "note": "Dinner split",
            "payload": "upi://pay?pa=ramesh@okaxis&pn=Ramesh&am=500"}]
GLOG, PRE = [], {}


def behavior(info, amt, ctx):
    """Signals only this app can see: the user's own history, device, city and time."""
    ok = [h for h in HIST if h.get("dr") and h["status"] == "Success"]
    avg = statistics.mean([h["amount"] for h in ok] or [850])
    known = {c["vpa"] for c in CONTACTS} | {h["vpa"] for h in ok}
    R = []
    if amt > avg * 8: R.append({"title": "Amount is higher than your normal pattern", "why": f"Rs {amt:,.0f} vs usual Rs {avg:,.0f}.", "w": 24})
    if info["vpa"] and info["vpa"] not in known: R.append({"title": "Recipient has limited transaction history", "why": "First payment to this ID.", "w": 12})
    if ctx["device"] != "Pixel 7": R.append({"title": "Payment from an unrecognised device", "why": ctx["device"], "w": 15})
    if ctx["city"] != "Chennai": R.append({"title": "Unusual location", "why": f"{ctx['city']} instead of Chennai.", "w": 10})
    if int(ctx["hour"]) not in range(6, 23): R.append({"title": "Unusual time of day", "why": f"{ctx['hour']}:00 is outside your usual hours.", "w": 10})
    return R


def resolve(t):
    t = (t or "").strip()
    info = {"vpa": None, "name": None, "amount": None}
    if t.lower().startswith(("upi://", "http")):
        q = {k: unquote(v[0]) for k, v in parse_qs(urlparse(t).query).items()}
        info.update(vpa=q.get("pa", "").lower() or None, name=q.get("pn"), amount=q.get("am"))
    elif t.isdigit() and len(t) == 10:
        info["vpa"] = t + "@ybl"
    else:
        info["vpa"] = t.lower() or None
    info["registered"] = NAMES.get(info["vpa"])
    info["name"] = info["name"] or next((c["name"] for c in CONTACTS if c["vpa"] == info["vpa"]), None) or info["registered"] or info["vpa"] or "Unknown"
    return info


def spent():
    return sum(h["amount"] for h in HIST if h.get("dr") and h["status"] == "Success" and time.time() - h["ts"] < 86400)


@app.get("/")
def home():
    return send_from_directory(app.root_path, "index.html")


@app.get("/manifest.json")
def manifest():
    return jsonify(name="Zippay UPI", short_name="Zippay", start_url="/", scope="/", display="standalone",
                   background_color="#F4F6FA", theme_color="#245FE8",
                   icons=[{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                          {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
                          {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}])


@app.get("/service-worker.js")
def service_worker():
    return send_from_directory(app.root_path, "service-worker.js", mimetype="application/javascript")


@app.get("/icon.svg")
def icon():
    return send_from_directory(app.root_path, "icon.svg", mimetype="image/svg+xml")


@app.get("/icon-<int:size>.png")
def app_icon(size):
    if size not in (192, 512):
        return jsonify(error="Icon size not found."), 404
    return send_from_directory(app.root_path, f"icon-{size}.png", mimetype="image/png")


@app.post("/api/login")
def login():
    return jsonify(ok=request.json.get("pin") == ME["app_pin"])


@app.get("/api/me")
def me():
    return jsonify(name=ME["name"], vpa=ME["vpa"], mobile=ME["mobile"], contacts=CONTACTS, banks=list(BANKS),
                   hist=HIST[:30], collect=COLLECT, limit=ME["limit"], spent=int(spent()),
                   guard={"on": ME["guard"], "online": ext.online()})


@app.post("/api/balance")
def balance():
    if request.json.get("pin") != ME["upi_pin"]: return jsonify(ok=False, msg="Incorrect UPI PIN.")
    return jsonify(ok=True, bal=BANKS)


@app.post("/api/resolve")
def api_resolve():
    return jsonify(resolve(request.json.get("payload")))


@app.post("/api/precheck")
def precheck():
    d = request.json
    info = resolve(d["payload"])
    try: amt = float(d["amount"])
    except (TypeError, ValueError): return jsonify(err="Enter a valid amount.")
    if amt <= 0: return jsonify(err="Enter a valid amount.")
    g = None
    if ME["guard"]:
        g = ext.check(d["payload"], info, amt, d.get("note", ""), d["ctx"], d.get("src"))
        GLOG.append({"time": time.strftime("%H:%M:%S"), "ms": g["ms"], "ok": "error" not in g, "vpa": info["vpa"] or "-",
                     "score": g.get("score"), "level": None})
        if "error" in g: return jsonify(info=info, guard=None, offline=True, msg=g["error"])
        seen = {r["title"] for r in g["reasons"]}
        extra = [r for r in behavior(info, amt, d["ctx"]) if r["title"] not in seen]
        g["reasons"] += extra
        g["reasons"].sort(key=lambda r: -r["w"])
        g["score"] = min(100, g["score"] + sum(r["w"] for r in extra))
        g["blocked"] = g["blocked"] or (g["score"] >= 55 and not g["needs_code"])
        g["level"] = "high" if g["score"] >= 55 else "medium" if g["needs_code"] or g["score"] >= 25 else "low"
        GLOG[-1]["level"] = g["level"]
        g["verify"] = {"Recipient ID": info["vpa"] or "None", "Registered name": info["registered"] or "Not verified by bank",
                       "Name on QR": info["name"], "Amount": f"Rs {amt:,.0f}", "Context": f"{d['ctx']['device']}, {d['ctx']['city']}, {d['ctx']['hour']}:00"}
        PRE[g["id"]] = g
    return jsonify(info=info, guard=g, offline=ME["guard"] and g is None)


@app.post("/api/gverify")
def gverify():
    d = request.json
    g = PRE.get(d.get("gid"))
    if not g: return jsonify(ok=False, msg="Unknown check.")
    try:
        ext.confirm(g["ref"], str(d.get("code", "")), resolve(d["payload"])["vpa"], float(d["amount"]))
        g["ok"] = True
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, msg=str(e))


@app.post("/api/pay")
def pay():
    d = request.json
    info, gid = resolve(d["payload"]), d.get("gid")
    amt = float(d["amount"])
    fail = lambda code, msg, fatal=True: jsonify(ok=False, code=code, msg=msg, fatal=fatal)
    g = PRE.get(gid)
    if g and (g["blocked"] or (g["needs_code"] and not g.get("ok"))):
        return fail("U16", "PhishGuard did not approve this payment. Payment cancelled.")
    if not info["vpa"]: return fail("U30", "Invalid payee. This QR does not contain a UPI address.")
    if d["pin"] != ME["upi_pin"]:
        ME["tries"] += 1
        left = 3 - ME["tries"]
        if left <= 0:
            ME["tries"] = 0
            return fail("ZM", "UPI PIN tries exceeded. Try again after some time.")
        return fail("ZM", f"Incorrect UPI PIN. {left} attempt{'s' if left > 1 else ''} left.", False)
    ME["tries"] = 0
    if amt > BANKS[d["bank"]]: return fail("Z9", "Insufficient funds in your account.")
    if spent() + amt > ME["limit"]: return fail("U30", "Daily UPI limit of Rs 1,00,000 exceeded.")
    BANKS[d["bank"]] -= amt
    t = {"id": len(HIST) + 1, "name": info["name"], "vpa": info["vpa"], "amount": amt, "bank": d["bank"],
         "utr": "".join(random.choices("0123456789", k=12)), "time": time.strftime("%d %b, %I:%M %p"),
         "status": "Success", "note": d.get("note", ""), "ts": time.time(), "dr": True}
    HIST.insert(0, t)
    COLLECT[:] = [c for c in COLLECT if c["id"] != d.get("cid")]
    return jsonify(ok=True, txn=t)


@app.post("/api/cancel")
def cancel():
    d = request.json
    info = resolve(d["payload"])
    if d.get("gid"):
        HIST.insert(0, {"id": len(HIST) + 1, "name": info["name"], "vpa": info["vpa"] or "unknown", "amount": float(d.get("amount") or 0),
                        "bank": d.get("bank", ""), "utr": "-", "time": time.strftime("%d %b, %I:%M %p"),
                        "status": "Stopped by PhishGuard", "note": "U16 Risk threshold exceeded", "ts": time.time(), "dr": False})
    return jsonify(ok=True)


@app.post("/api/collect/decline")
def decline():
    COLLECT[:] = [c for c in COLLECT if c["id"] != request.json.get("id")]
    return jsonify(ok=True)


@app.post("/api/settings")
def settings():
    ME["guard"] = bool(request.json.get("guard"))
    return jsonify(ok=True)


@app.post("/api/report")
def report():
    try:
        return jsonify(ok=True, msg=ext.report(request.json.get("vpa", "").strip(), "Phishing QR code", "Reported from Zippay").get("message", "Reported."))
    except Exception as e:
        return jsonify(ok=False, msg=str(e))


@app.get("/api/guardlog")
def guardlog():
    return jsonify(online=ext.online(), log=GLOG[-8:][::-1], url=ext.BASE)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
