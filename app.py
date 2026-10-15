import os, re, time, random, statistics, datetime, requests
import ipaddress
from urllib.parse import urlparse, parse_qs, unquote
from flask import Flask, jsonify, request, send_from_directory
import extension_client as ext

app = Flask(__name__)
DEMO_ALERTS = os.getenv("DEMO_ALERTS", "1") == "1"
ME = {"name": "Arjun Kumar", "mobile": "98765 43210", "vpa": "arjun@oksbi", "app_pin": "2580",
      "upi_pin": "1234", "limit": 100000, "guard": True, "tries": 0, "avatar": ""}
DEMO_BANK = "Zippay Demo Bank ••0001"   # play-money account: nothing here is real
BANKS = {DEMO_BANK: 250000.0, "SBI ••1234": 48250.0, "HDFC ••5678": 12600.0}
START = dict(BANKS)
RECV, RECV_BANK = {}, "Demo Bank ••7788"  # fake receiving accounts, keyed by UPI ID


def recv_bal(vpa):
    """Starting play-money balance of the payee's fake bank account (stable per UPI ID)."""
    return RECV.setdefault(vpa, float(5000 + sum(map(ord, vpa)) % 40000))
CONTACTS = [{"name": "Amma", "vpa": "amma@oksbi"}, {"name": "Ramesh", "vpa": "ramesh@okaxis"},
            {"name": "DMart", "vpa": "dmart@okicici"}, {"name": "TNEB Bill", "vpa": "tneb.bills@sbi"}]
NAMES = {"amma@oksbi": "Lakshmi Kumar", "ramesh@okaxis": "Ramesh S", "dmart@okicici": "Avenue Supermarts Ltd",
         "tneb.bills@sbi": "TANGEDCO", "sharma.store@okaxis": "Sharma General Store",
         "dmart-help@okxyz": "R Kumar Traders", "rewards@paytmx": "Rewards Desk", "tneb.biils@sbi": "S Mohan", "iyer.rent@okaxis": "Mr Iyer (Rent)"}
CATS = ("Bills", "Grocery", "Misc", "Rent", "EMI")


def categorize(name, vpa="", note=""):
    """Guess Bills / Grocery / Rent from the payee; everything else is Misc."""
    s = f"{name} {vpa} {note}".lower()
    if re.search(r"\bemi\b|loan|finance|instal", s): return "EMI"
    for cat, keys in (("Rent", ("rent", "landlord")),
                      ("Bills", ("bill", "tneb", "electric", "recharge", "gas", "water", "dth", "broadband")),
                      ("Grocery", ("mart", "grocery", "store", "supermarket", "vegetable", "basket"))):
        if any(k in s for k in keys): return cat
    return "Misc"


HIST = [{"id": i, "name": n, "vpa": v, "amount": a, "bank": "SBI ••1234", "utr": u, "time": t, "status": "Success",
         "note": "", "ts": time.time() - 86400 * d, "dr": True, "cat": categorize(n, v)}
        for i, (n, v, a, u, t, d) in enumerate([("Amma", "amma@oksbi", 500, "428193746215", "28 Sep, 06:12 PM", 5),
                                                ("DMart", "dmart@okicici", 640, "428377120934", "30 Sep, 07:40 PM", 3),
                                                ("TNEB Bill", "tneb.bills@sbi", 1200, "428590013377", "01 Oct, 10:05 AM", 2),
                                                ("Mr Iyer (Rent)", "iyer.rent@okaxis", 6500, "428111902244", "29 Sep, 09:15 AM", 4),
                                                ("Ramesh", "ramesh@okaxis", 350, "428730045512", "02 Oct, 08:20 PM", 1.6)], 1)]
HIST.sort(key=lambda h: -h["ts"])
SENT = []  # money requests the user has sent (demo): Pending -> Paid / Cancelled
COLLECT = [{"id": 1, "from": "Refund Desk", "vpa": "rewards@paytmx", "amount": 4999, "note": "Refund pending. Approve to receive.",
            "payload": "upi://pay?pa=rewards@paytmx&pn=Refund Desk&am=4999"},
           {"id": 2, "from": "Ramesh", "vpa": "ramesh@okaxis", "amount": 500, "note": "Dinner split",
            "payload": "upi://pay?pa=ramesh@okaxis&pn=Ramesh&am=500"}]
COLLECT.append({"id": 3, "from": "QuickCash Loans", "vpa": "quickcash.loan@okaxis", "amount": 2999,
                "note": "Loan approved. Pay the processing fee to release Rs 50,000.",
                "payload": "upi://pay?pa=quickcash.loan@okaxis&pn=QuickCash Loans&am=2999"})
NAMES.update({"bajajfin.emi@okicici": "Bajaj Finance Ltd", "hdfcbank.emi@okhdfcbank": "HDFC Bank Ltd",
              "tatacapital.emi@okaxis": "Tata Capital Financial Services Ltd", "cmwssb.water@sbi": "Chennai Metro Water",
              "airtel.broadband@okicici": "Bharti Airtel Ltd", "instaloan.fee@paytmx": "Rahul Verma",
              "quickcash.loan@okaxis": "QuickCash Services"})

# ---------- Fake loan detection ----------
LENDERS = {"bajajfin.emi@okicici": "Bajaj Finance Ltd", "hdfcbank.emi@okhdfcbank": "HDFC Bank Ltd",
           "tatacapital.emi@okaxis": "Tata Capital Financial Services Ltd"}   # demo list of registered lenders
LENDER_CHIPS = [{"name": "Bajaj Finance", "vpa": "bajajfin.emi@okicici"}, {"name": "HDFC Bank", "vpa": "hdfcbank.emi@okhdfcbank"},
                {"name": "Tata Capital", "vpa": "tatacapital.emi@okaxis"}]
BILLERS = [{"name": "TNEB Bill", "vpa": "tneb.bills@sbi"}, {"name": "Chennai Water", "vpa": "cmwssb.water@sbi"},
           {"name": "Airtel Broadband", "vpa": "airtel.broadband@okicici"}]
LOAN_RX = re.compile(r"loan|lending|\blender\b|instacash|quickcash|pre-?approved|pre approved|disburs|cibil|credit (?:limit|line)|\bnbfc\b|\bemi\b", re.I)
FEE_RX = re.compile(r"processing|insurance|\bgst\b|stamp|verification|registration|security deposit|advance|\bnoc\b|service charge|\bfee|charges|activation|release|unlock|\bdeposit", re.I)
URGENT_RX = re.compile(r"urgent|today only|last chance|immediately|limited time|expires?", re.I)
COMPANY_RX = re.compile(r"\b(ltd|limited|pvt|private|bank|finance|capital|llp|inc|corp)\b", re.I)


def loan_risks(info, note="", payload=""):
    """Fake-loan signs: loan wording plus an advance fee, an unregistered lender, or a personal account."""
    out = {"flag": False, "extra_high": False, "reasons": [], "status": "No loan signs"}
    vpa = info.get("vpa") or ""
    if vpa in LENDERS:
        out["status"] = "Registered lender"
        return out
    text = " ".join([info.get("name") or "", vpa, note or "", payload or ""])
    if not LOAN_RX.search(text): return out
    known = vpa in {c["vpa"] for c in CONTACTS}
    fee = bool(FEE_RX.search(text))
    if known and not fee: return out   # e.g. paying back a friend
    R = [{"title": "Loan payment detected", "why": "The payee, note or link talks about a loan.", "w": 10}]
    if fee: R.append({"title": "Fee asked before the loan", "why": "Real lenders take fees out of the loan. They never ask you to pay first.", "w": 50})
    if known:
        out.update(reasons=R, status="Fee mentioned, check it")
        return out
    R.append({"title": "Lender not on the registered list", "why": "This payee is not among the registered banks and lenders we know.", "w": 25})
    reg = info.get("registered")
    if not reg: R.append({"title": "Payee name not verified by bank", "why": "No bank-verified name for this UPI ID.", "w": 15})
    elif not COMPANY_RX.search(reg): R.append({"title": "Money goes to a person, not a company", "why": f"The account belongs to {reg}.", "w": 20})
    if URGENT_RX.search(text): R.append({"title": "Pressure to act fast", "why": "Scam lenders rush you so you do not check.", "w": 10})
    out.update(flag=True, extra_high=fee, reasons=R, status="Possible fake loan")
    return out


# ---------- Autopay for bills and EMIs ----------
AUTOPAY, AUTOPAY_CAP = {"on": True}, 15000
MANDATES = [{"id": 1, "kind": "Bill", "name": "TNEB Bill", "vpa": "tneb.bills@sbi", "amount": 1200, "day": 5, "bank": "SBI ••1234", "on": True},
            {"id": 2, "kind": "EMI", "name": "Bajaj Finance", "vpa": "bajajfin.emi@okicici", "amount": 4250, "day": 18, "bank": "SBI ••1234", "on": True},
            {"id": 3, "kind": "Bill", "name": "Chennai Water", "vpa": "cmwssb.water@sbi", "amount": 420, "day": 20, "bank": "SBI ••1234", "on": False}]


def next_due(m):
    today = datetime.date.today()
    due = today.replace(day=m["day"])
    if m.get("paid_month") == today.strftime("%Y-%m") or due < today:
        y, mo = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        due = datetime.date(y, mo, m["day"])
    return due


def autopay_view():
    today, items = datetime.date.today(), []
    for m in MANDATES:
        due = next_due(m)
        items.append({**{k: m[k] for k in ("id", "kind", "name", "vpa", "amount", "day", "bank", "on")},
                      "next": due.strftime("%d %b"), "days": (due - today).days, "last": m.get("last")})
    return {"on": AUTOPAY["on"], "items": items, "billers": BILLERS, "lenders": LENDER_CHIPS, "cap": AUTOPAY_CAP}


GLOG, PRE = [], {}
def behavior(info, amt, ctx):
    """Signals only this app can see: the user's own history, device, city and time."""
    ok = [h for h in HIST if h.get("dr") and h["status"] == "Success"]
    avg = statistics.mean([h["amount"] for h in ok] or [850])
    known = {c["vpa"] for c in CONTACTS} | {h["vpa"] for h in ok}
    R = []
    if amt > avg * 8: R.append({"title": "Amount is much higher than your normal pattern", "why": f"Rs {amt:,.0f} vs usual Rs {avg:,.0f}.", "w": 40})
    if info["vpa"] and info["vpa"] not in known: R.append({"title": "Recipient has limited transaction history", "why": "First payment to this ID.", "w": 12})
    if ctx["device"] != "Pixel 7": R.append({"title": "Payment from an unrecognised device", "why": ctx["device"], "w": 15})
    if ctx["city"] != "Chennai": R.append({"title": "Unusual location", "why": f"{ctx['city']} instead of Chennai.", "w": 10})
    if int(ctx["hour"]) not in range(6, 23): R.append({"title": "Unusual time of day", "why": f"{ctx['hour']}:00 is outside your usual hours.", "w": 10})
    return R


def detect_url_risks(payload):
    if not payload.lower().startswith(("http://", "https://")):
        return [], False, None

    try:
        parsed = urlparse(payload)
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return [{"title": "Extra-high URL risk", "why": "The payment URL is malformed and its destination cannot be verified.", "w": 60}], True, None
    reasons = [{"title": "Payment URL detected", "why": f"Review the payment website: {host or 'unknown host'}.", "w": 10}]
    indicators = []
    if parsed.scheme.lower() != "https":
        indicators.append("The link does not use secure HTTPS.")
    if parsed.username or parsed.password:
        indicators.append("The link hides its destination behind user information.")
    if host.startswith("xn--") or any(label.startswith("xn--") for label in host.split(".")):
        indicators.append("The website uses an internationalized domain that may imitate another address.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        indicators.append("The website uses a raw IP address instead of a normal domain.")

    suspicious_terms = ("kyc", "verify", "refund", "reward", "claim", "secure", "bank", "upi", "login", "support")
    matched_terms = [term for term in suspicious_terms if term in host]
    if matched_terms:
        indicators.append(f"The domain contains a sensitive-payment term: {', '.join(matched_terms[:3])}.")
    if len(host.split(".")) > 4:
        indicators.append("The website uses an unusually nested domain.")

    extra_high = bool(parsed.username or parsed.password or host.startswith("xn--")
                      or any(label.startswith("xn--") for label in host.split("."))
                      or matched_terms or len(host.split(".")) > 4)
    if indicators:
        reasons.append({"title": "Extra-high URL risk" if extra_high else "URL security concern",
                        "why": " ".join(indicators), "w": 60 if extra_high else 30})
    return reasons, extra_high, host or None


def local_guard(info, amt, ctx, payload, elapsed_ms, note=""):
    reasons = [{"title": "Demo safety alert", "why": "This simulated warning demonstrates the review flow; it is not a real fraud assessment.", "w": 25}]
    reasons.extend(behavior(info, amt, ctx))
    url_reasons, extra_high, url_host = detect_url_risks(payload)
    reasons.extend(url_reasons)
    loan = loan_risks(info, note, payload)
    reasons.extend(loan["reasons"])
    extra_high = extra_high or loan["extra_high"]
    reasons.sort(key=lambda reason: -reason["w"])
    score = min(100, sum(reason["w"] for reason in reasons))
    if loan["flag"]:
        score = max(score, 60)
    if extra_high:
        score = max(score, 90)
    gid = f"local-{time.time_ns()}"
    return {"id": gid, "ref": None, "score": score, "ms": elapsed_ms, "blocked": extra_high or score >= 55,
            "needs_code": False, "level": "extra-high" if extra_high else "high" if score >= 55 else "medium" if score >= 25 else "low",
            "reasons": reasons, "source": "demo" if DEMO_ALERTS else "local",
            "payload": payload, "amount": amt, "auto_stopped": False,
            "loan": {"flag": loan["flag"], "status": loan["status"]},
            "verify": {"Recipient ID": info["vpa"] or "None",
                       "Registered name": info["registered"] or "Not verified by bank",
                       "Name on QR": info["name"], "Amount": f"Rs {amt:,.0f}",
                       "Context": f"{ctx['device']}, {ctx['city']}, {ctx['hour']}:00",
                       **({"Payment URL host": url_host} if url_host else {}), "Loan check": loan["status"]}}


def resolve(t):
    t = (t or "").strip()
    info = {"vpa": None, "name": None, "amount": None}
    if t.lower().startswith(("upi://", "http")):
        try:
            q = {k: unquote(v[0]) for k, v in parse_qs(urlparse(t).query).items()}
            info.update(vpa=q.get("pa", "").lower() or None, name=q.get("pn"), amount=q.get("am"))
        except ValueError:
            info["name"] = "Unverifiable payment URL"
    elif t.isdigit() and len(t) == 10:
        info["vpa"] = t + "@ybl"
    else:
        info["vpa"] = t.lower() or None
    info["registered"] = NAMES.get(info["vpa"])
    info["name"] = info["name"] or next((c["name"] for c in CONTACTS if c["vpa"] == info["vpa"]), None) or info["registered"] or info["vpa"] or "Unknown"
    return info


def spent():
    return sum(h["amount"] for h in HIST if h.get("dr") and h["status"] == "Success" and time.time() - h["ts"] < 86400)


def record_stopped_payment(info, amt, bank, demo=False, loan=False):
    HIST.insert(0, {"id": len(HIST) + 1, "name": info["name"], "vpa": info["vpa"] or "unknown",
                    "amount": amt, "bank": bank or "", "utr": "-", "time": time.strftime("%d %b, %I:%M %p"),
                    "status": "Stopped · fake loan suspected" if loan else "Stopped automatically · demo alert" if demo else "Stopped by PhishGuard",
                    "note": "Fake loan signs found" if loan else "Simulated high-risk warning" if demo else "High-risk payment blocked",
                    "ts": time.time(), "dr": False})


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
    return jsonify(autopay=autopay_view(), name=ME["name"], vpa=ME["vpa"], mobile=ME["mobile"], contacts=CONTACTS, banks=list(BANKS),
                   hist=HIST[:30], collect=COLLECT, sent=SENT[:20], avatar=ME.get("avatar", ""), limit=ME["limit"], spent=int(spent()),
                   guard={"on": ME["guard"], "online": True if DEMO_ALERTS else ext.online(), "demo": DEMO_ALERTS})


@app.post("/api/balance")
def balance():
    if request.json.get("pin") != ME["upi_pin"]: return jsonify(ok=False, msg="Incorrect UPI PIN.")
    return jsonify(ok=True, bal=BANKS)


@app.post("/api/resolve")
def api_resolve():
    info = resolve(request.json.get("payload"))
    info["cat"] = categorize(info["name"] or "", info["vpa"] or "")
    return jsonify(info)


@app.post("/api/contacts/add")
def add_contact():
    d = request.json or {}
    name = re.sub(r"[<>\"'&]", "", (d.get("name") or "").strip())[:30]
    raw = (d.get("to") or "").strip().lower()
    if not name: return jsonify(ok=False, msg="Enter a name.")
    if raw.isdigit() and len(raw) == 10: vpa = raw + "@ybl"
    elif re.fullmatch(r"[a-z0-9._-]{2,}@[a-z]{2,}", raw): vpa = raw
    else: return jsonify(ok=False, msg="Enter a 10-digit mobile number or a UPI ID like name@bank.")
    if any(c["vpa"] == vpa for c in CONTACTS): return jsonify(ok=False, msg="That person is already saved.")
    CONTACTS.append({"name": name, "vpa": vpa})
    NAMES.setdefault(vpa, name)
    return jsonify(ok=True)


@app.post("/api/banks/add")
def add_bank():
    d = request.json or {}
    bank = re.sub(r"[^A-Za-z0-9 &.-]", "", (d.get("bank") or "").strip())[:24]
    last4 = re.sub(r"\D", "", str(d.get("last4") or ""))
    if not bank or len(last4) != 4: return jsonify(ok=False, msg="Enter the bank name and the last 4 digits of the account.")
    try: bal = float(d.get("balance") or 25000)
    except ValueError: return jsonify(ok=False, msg="Enter a valid opening balance.")
    if not 0 <= bal <= 10_000_000: return jsonify(ok=False, msg="Opening balance must be between 0 and 1,00,00,000.")
    key = f"{bank} ••{last4}"
    if key in BANKS: return jsonify(ok=False, msg="That account is already linked.")
    BANKS[key] = START[key] = bal
    return jsonify(ok=True, bank=key)


@app.post("/api/precheck")
def precheck():
    d = request.json
    info = resolve(d["payload"])
    try: amt = float(d["amount"])
    except (TypeError, ValueError): return jsonify(err="Enter a valid amount.")
    if amt <= 0: return jsonify(err="Enter a valid amount.")
    g = None
    if ME["guard"]:
        started = time.time()
        if DEMO_ALERTS:
            g = local_guard(info, amt, d["ctx"], d["payload"], int((time.time() - started) * 1000), d.get("note", ""))
            g["bank"] = d.get("bank")
        else:
            g = ext.check(d["payload"], info, amt, d.get("note", ""), d["ctx"], d.get("src"))
            if "error" in g:
                error = g["error"]
                g = local_guard(info, amt, d["ctx"], d["payload"], int((time.time() - started) * 1000), d.get("note", ""))
                if g:
                    g["source"] = "local"
                    g["bank"] = d.get("bank")
                GLOG.append({"time": time.strftime("%H:%M:%S"), "ms": g["ms"] if g else 0, "ok": False,
                             "vpa": info["vpa"] or "-", "score": g["score"] if g else None,
                             "level": g["level"] if g else None})
                if g:
                    PRE[g["id"]] = g
                return jsonify(info=info, guard=g, offline=True, msg=error)
            seen = {r["title"] for r in g["reasons"]}
            extra = [r for r in behavior(info, amt, d["ctx"]) if r["title"] not in seen]
            g["reasons"] += extra
            url_reasons, extra_high, url_host = detect_url_risks(d["payload"])
            seen.update(r["title"] for r in g["reasons"])
            g["reasons"] += [r for r in url_reasons if r["title"] not in seen]
            loan = loan_risks(info, d.get("note", ""), d["payload"])
            seen.update(r["title"] for r in g["reasons"])
            new_loan = [r for r in loan["reasons"] if r["title"] not in seen]
            g["reasons"] += new_loan
            g["loan"] = {"flag": loan["flag"], "status": loan["status"]}
            extra_high = extra_high or loan["extra_high"]
            g["reasons"].sort(key=lambda r: -r["w"])
            g["score"] = min(100, g["score"] + sum(r["w"] for r in extra) + sum(r["w"] for r in url_reasons) + sum(r["w"] for r in new_loan))
            if loan["flag"]: g["score"] = max(g["score"], 60)
            if extra_high:
                g["score"] = max(g["score"], 90)
                g["blocked"] = True
            g["blocked"] = g["blocked"] or (g["score"] >= 55 and not g["needs_code"])
            g["level"] = "extra-high" if extra_high else "high" if g["score"] >= 55 else "medium" if g["needs_code"] or g["score"] >= 25 else "low"
            g["verify"] = {"Recipient ID": info["vpa"] or "None", "Registered name": info["registered"] or "Not verified by bank",
                           "Name on QR": info["name"], "Amount": f"Rs {amt:,.0f}", "Context": f"{d['ctx']['device']}, {d['ctx']['city']}, {d['ctx']['hour']}:00",
                           **({"Payment URL host": url_host} if url_host else {}), "Loan check": loan["status"]}
        GLOG.append({"time": time.strftime("%H:%M:%S"), "ms": g["ms"], "ok": True,
                     "vpa": info["vpa"] or "-", "score": g["score"], "level": g["level"]})
        if g["blocked"]:
            record_stopped_payment(info, amt, d.get("bank", ""), demo=g.get("source") == "demo", loan=bool((g.get("loan") or {}).get("flag")))
            g["auto_stopped"] = True
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
    if DEMO_ALERTS and (not g or g.get("payload") != d["payload"] or g.get("amount") != amt
                        or g.get("bank") != d["bank"]):
        return fail("U16", "Run a fresh demo safety check before paying. Payment cancelled.")
    if g and (g["blocked"] or (g["needs_code"] and not g.get("ok"))):
        return fail("U16", "High-risk check stopped this payment before PIN entry.")
    if g and g.get("paid"):
        return fail("U16", "This safety check was already used. Start a new payment.")
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
    if g: g["paid"] = True
    before, rb = BANKS[d["bank"]], recv_bal(info["vpa"])
    BANKS[d["bank"]] -= amt
    RECV[info["vpa"]] = rb + amt  # money "arrives" in the fake receiving bank
    t = {"id": len(HIST) + 1, "name": info["name"], "vpa": info["vpa"], "amount": amt, "bank": d["bank"],
         "utr": "".join(random.choices("0123456789", k=12)), "time": time.strftime("%d %b, %I:%M %p"),
         "status": "Success", "note": d.get("note", ""), "ts": time.time(), "dr": True,
        
         "cat": d.get("cat") if d.get("cat") in CATS else categorize(info["name"], info["vpa"], d.get("note", ""))}
    HIST.insert(0, t)
    COLLECT[:] = [c for c in COLLECT if c["id"] != d.get("cid")]
    move = {"amount": amt, "from_bank": d["bank"], "from_before": before, "from_after": BANKS[d["bank"]],
            "to_name": info["name"], "to_vpa": info["vpa"], "to_bank": RECV_BANK, "demo": True}
    return jsonify(ok=True, txn=t, move=move)


@app.post("/api/demo/reset")
def demo_reset():
    BANKS.update(START)
    RECV.clear()
    return jsonify(ok=True)


@app.post("/api/cancel")
def cancel():
    d = request.json
    info = resolve(d["payload"])
    g = PRE.get(d.get("gid"))
    if g and not g.get("auto_stopped"):
        record_stopped_payment(info, float(d.get("amount") or 0), d.get("bank", ""),
                               demo=g.get("source") == "demo", loan=bool((g.get("loan") or {}).get("flag")))
        g["auto_stopped"] = True
    return jsonify(ok=True)


def clean(s, n):
    return " ".join(re.sub(r"[<>\"'&]", "", (s or "").strip()).split())[:n]


@app.post("/api/profile")
def profile():
    d = request.json or {}
    name = clean(d.get("name"), 30)
    if len(name) < 2: return jsonify(ok=False, msg="Enter a name with at least 2 characters.")
    av = d.get("avatar")
    if av:
        if not (isinstance(av, str) and len(av) <= 150_000 and re.fullmatch(r"data:image/jpeg;base64,[A-Za-z0-9+/=]+", av)):
            return jsonify(ok=False, msg="That photo could not be used. Try a different image.")
        ME["avatar"] = av
    elif d.get("remove"):
        ME["avatar"] = ""
    ME["name"] = name
    return jsonify(ok=True)


@app.post("/api/request/create")
def request_create():
    d = request.json or {}
    raw = (d.get("to") or "").strip().lower()
    if raw.isdigit() and len(raw) == 10: vpa = raw + "@ybl"
    elif re.fullmatch(r"[a-z0-9._-]{2,}@[a-z]{2,}", raw): vpa = raw
    else: return jsonify(ok=False, msg="Enter a 10-digit mobile number or a UPI ID like name@bank.")
    if vpa == ME["vpa"]: return jsonify(ok=False, msg="You cannot request money from yourself.")
    try: amt = round(float(d.get("amount")), 2)
    except (TypeError, ValueError): return jsonify(ok=False, msg="Enter an amount.")
    if not 1 <= amt <= 100000: return jsonify(ok=False, msg="Amount must be between Rs 1 and Rs 1,00,000.")
    name = NAMES.get(vpa) or next((c["name"] for c in CONTACTS if c["vpa"] == vpa), None) or vpa.split("@")[0]
    r = {"id": (max([s["id"] for s in SENT]) + 1) if SENT else 1, "name": name, "vpa": vpa, "amount": amt,
         "note": clean(d.get("note"), 60), "status": "Pending", "time": time.strftime("%d %b, %I:%M %p")}
    SENT.insert(0, r)
    return jsonify(ok=True, req=r)


@app.post("/api/request/cancel")
def request_cancel():
    for s in SENT:
        if s["id"] == (request.json or {}).get("id") and s["status"] == "Pending": s["status"] = "Cancelled"
    return jsonify(ok=True)


@app.post("/api/request/settle")
def request_settle():
    """Demo only: pretend the other person paid, so the play-money lands in the demo bank."""
    s = next((s for s in SENT if s["id"] == (request.json or {}).get("id") and s["status"] == "Pending"), None)
    if not s: return jsonify(ok=False, msg="That request is no longer pending.")
    s["status"] = "Paid"
    BANKS[DEMO_BANK] += s["amount"]
    HIST.insert(0, {"id": len(HIST) + 1, "name": s["name"], "vpa": s["vpa"], "amount": s["amount"], "bank": DEMO_BANK,
                    "utr": "".join(random.choices("0123456789", k=12)), "time": time.strftime("%d %b, %I:%M %p"),
                    "status": "Success", "note": s["note"], "ts": time.time(), "dr": False, "cat": None})
    return jsonify(ok=True, amount=s["amount"], name=s["name"], bank=DEMO_BANK)


@app.post("/api/collect/decline")
def decline():
    COLLECT[:] = [c for c in COLLECT if c["id"] != request.json.get("id")]
    return jsonify(ok=True)


@app.post("/api/settings")
def settings():
    ME["guard"] = True if DEMO_ALERTS else bool(request.json.get("guard"))
    return jsonify(ok=True)


@app.post("/api/report")
def report():
    try:
        return jsonify(ok=True, msg=ext.report(request.json.get("vpa", "").strip(), "Phishing QR code", "Reported from Zippay").get("message", "Reported."))
    except Exception as e:
        return jsonify(ok=False, msg=str(e))


@app.get("/api/guardlog")
def guardlog():
    return jsonify(online=True if DEMO_ALERTS else ext.online(), demo=DEMO_ALERTS,
                   log=GLOG[-8:][::-1], url=ext.BASE)


def check_pin(pin):
    if pin == ME["upi_pin"]:
        ME["tries"] = 0
        return None
    ME["tries"] += 1
    left = 3 - ME["tries"]
    if left <= 0:
        ME["tries"] = 0
        return "UPI PIN tries exceeded. Try again after some time."
    return f"Incorrect UPI PIN. {left} attempt{'s' if left > 1 else ''} left."


def find_mandate(i):
    return next((m for m in MANDATES if m["id"] == i), None)


@app.post("/api/autopay/master")
def autopay_master():
    AUTOPAY["on"] = bool((request.json or {}).get("on"))
    return jsonify(ok=True)


@app.post("/api/autopay/toggle")
def autopay_toggle():
    d = request.json or {}
    m = find_mandate(d.get("id"))
    if not m: return jsonify(ok=False, msg="That autopay no longer exists.")
    m["on"] = bool(d.get("on"))
    return jsonify(ok=True)


@app.post("/api/autopay/delete")
def autopay_delete():
    MANDATES[:] = [m for m in MANDATES if m["id"] != (request.json or {}).get("id")]
    return jsonify(ok=True)


@app.post("/api/autopay/add")
def autopay_add():
    d = request.json or {}
    kind = "EMI" if d.get("kind") == "EMI" else "Bill"
    info = resolve(d.get("to"))
    if not info["vpa"] or not re.fullmatch(r"[a-z0-9._-]{2,}@[a-z]{2,}", info["vpa"]):
        return jsonify(ok=False, msg="Enter a UPI ID like name@bank.")
    try: amt = round(float(d.get("amount")), 2)
    except (TypeError, ValueError): return jsonify(ok=False, msg="Enter an amount.")
    if not 1 <= amt <= AUTOPAY_CAP: return jsonify(ok=False, msg=f"Autopay is limited to Rs {AUTOPAY_CAP:,} per payment. Pay larger amounts yourself.")
    try: day = int(d.get("day"))
    except (TypeError, ValueError): day = 0
    if not 1 <= day <= 28: return jsonify(ok=False, msg="Pick a day between 1 and 28.")
    if d.get("bank") not in BANKS: return jsonify(ok=False, msg="Pick a linked bank account.")
    loan = loan_risks(info)
    if loan["flag"]:
        return jsonify(ok=False, loan=True, msg="Autopay blocked. This payee shows signs of a fake loan: real lenders never ask for money first.")
    if kind == "EMI" and info["vpa"] not in LENDERS:
        return jsonify(ok=False, loan=True, msg="We could not verify this lender. EMI autopay works only with registered lenders.")
    if any(m["vpa"] == info["vpa"] and m["kind"] == kind for m in MANDATES):
        return jsonify(ok=False, msg="Autopay for this payee is already set up.")
    err = check_pin(d.get("pin"))
    if err: return jsonify(ok=False, msg=err)
    name = next((c["name"] for c in LENDER_CHIPS + BILLERS if c["vpa"] == info["vpa"]), None) or info["name"]
    m = {"id": max([x["id"] for x in MANDATES] or [0]) + 1, "kind": kind, "name": name, "vpa": info["vpa"],
         "amount": amt, "day": day, "bank": d["bank"], "on": True}
    MANDATES.append(m)
    return jsonify(ok=True, name=name)


@app.post("/api/autopay/run")
def autopay_run():
    """Demo only: fast-forward to the due date and pay every active autopay that has not been paid this month."""
    if not AUTOPAY["on"]: return jsonify(ok=False, msg="Autopay is off. Turn it on to run payments.")
    key, res = datetime.date.today().strftime("%Y-%m"), []
    for m in MANDATES:
        if not m["on"] or m.get("paid_month") == key: continue
        info = resolve(m["vpa"])
        info["name"] = m["name"]
        if loan_risks(info)["flag"] or (m["kind"] == "EMI" and m["vpa"] not in LENDERS):
            m["on"] = False
            res.append({"name": m["name"], "status": "paused", "msg": f"{m['name']} was paused: the lender could not be verified."})
            continue
        amt, bank = m["amount"], m["bank"]
        if amt > BANKS.get(bank, 0):
            res.append({"name": m["name"], "status": "failed", "msg": f"{m['name']} failed: not enough money in {bank}."})
            continue
        if spent() + amt > ME["limit"]:
            res.append({"name": m["name"], "status": "failed", "msg": f"{m['name']} failed: daily UPI limit reached."})
            continue
        BANKS[bank] -= amt
        RECV[m["vpa"]] = recv_bal(m["vpa"]) + amt
        HIST.insert(0, {"id": len(HIST) + 1, "name": m["name"], "vpa": m["vpa"], "amount": amt, "bank": bank,
                        "utr": "".join(random.choices("0123456789", k=12)), "time": time.strftime("%d %b, %I:%M %p"),
                        "status": "Success", "note": f"Autopay · {m['kind']}", "ts": time.time(), "dr": True,
                        "cat": "EMI" if m["kind"] == "EMI" else "Bills", "auto": True})
        m["paid_month"], m["last"] = key, time.strftime("%d %b")
        res.append({"name": m["name"], "status": "paid", "amount": amt})
    paid = [r for r in res if r["status"] == "paid"]
    return jsonify(ok=True, results=res, paid=len(paid), total=sum(r["amount"] for r in paid),
                   issue=next((r["msg"] for r in res if r["status"] != "paid"), ""))


@app.post("/api/loancheck")
def loancheck():
    """Standalone loan-offer check: no payment is made."""
    d = request.json or {}
    raw, note = (d.get("to") or "").strip(), clean(d.get("note"), 300)
    if not raw: return jsonify(ok=False, msg="Enter the lender's UPI ID, mobile number or link.")
    info = resolve(raw)
    loan = loan_risks(info, note + " loan", raw if raw.lower().startswith("http") else "")
    url_reasons, url_extra, host = detect_url_risks(raw)
    reasons = sorted(loan["reasons"] + url_reasons, key=lambda r: -r["w"])
    if url_extra or loan["extra_high"]: level = "fake"
    elif loan["flag"] or any(r["w"] >= 30 for r in url_reasons): level = "risky"
    elif loan["status"] == "Registered lender": level = "genuine"
    else: level = "unknown"
    return jsonify(ok=True, level=level, status=loan["status"], reasons=reasons[:5],
                   verify={"Lender ID": info["vpa"] or host or "None", "Bank-verified name": info["registered"] or "Not verified",
                           "Loan check": loan["status"]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
