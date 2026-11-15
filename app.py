import os, re, json, hmac, time, hashlib, secrets, sqlite3
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import parse_qsl
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
DB_PATH = os.getenv("DATABASE_PATH", str(BASE / "iran_miner.sqlite3"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"

DAILY_REWARD_TOMAN = 42_000
REFERRAL_REWARD_TOMAN = 15_000
CYCLE_SECONDS = 24 * 60 * 60
MIN_WITHDRAW_TOMAN = 400_000
USDT_RATE_TOMAN = 270_000
WITHDRAW_REVIEW_SECONDS = 48 * 60 * 60

app = FastAPI(title="Iran Miner Demo API", docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          telegram_id TEXT PRIMARY KEY,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          withdrawal_pin_hash TEXT,
          referral_code TEXT NOT NULL UNIQUE,
          referred_by TEXT,
          referral_rewarded INTEGER NOT NULL DEFAULT 0,
          toman_balance INTEGER NOT NULL DEFAULT 0,
          usdt_balance REAL NOT NULL DEFAULT 0,
          mining_started_at INTEGER,
          mining_due_at INTEGER,
          mining_claimable INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS withdrawals(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          telegram_id TEXT NOT NULL REFERENCES users(telegram_id),
          kind TEXT NOT NULL CHECK(kind IN ('toman','usdt')),
          amount REAL NOT NULL,
          destination TEXT NOT NULL,
          owner_name TEXT,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at INTEGER NOT NULL
        );
        """)
init_db()

def now(): return int(time.time())

def secret_hash(value):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode(), salt.encode(), 220_000)
    return salt + "$" + digest.hex()

def secret_ok(value, encoded):
    if not encoded or "$" not in encoded: return False
    salt, digest = encoded.split("$", 1)
    check = hashlib.pbkdf2_hmac("sha256", value.encode(), salt.encode(), 220_000).hex()
    return hmac.compare_digest(check, digest)

def telegram_user(init_data: str):
    if DEMO_MODE and not init_data:
        return {"id": "demo-telegram-10001", "first_name": "Demo", "username": "demo_user"}
    if not BOT_TOKEN or not init_data:
        raise HTTPException(401, "ورود معتبر تلگرام پیدا نشد. مینی‌اپ را از داخل ربات باز کنید.")
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    received = params.pop("hash", None)
    if not received: raise HTTPException(401, "اطلاعات ورود تلگرام نامعتبر است.")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise HTTPException(401, "اعتبارسنجی تلگرام ناموفق بود.")
    auth_date = int(params.get("auth_date", "0"))
    if now() - auth_date > 86400 or auth_date > now() + 60:
        raise HTTPException(401, "نشست تلگرام منقضی شده است؛ مینی‌اپ را دوباره باز کنید.")
    try: return json.loads(params["user"])
    except Exception: raise HTTPException(401, "شناسه کاربر تلگرام دریافت نشد.")

def current_user(authorization):
    raw = authorization.removeprefix("tma ").strip()
    tg = telegram_user(raw)
    with db() as c:
        user = c.execute("SELECT * FROM users WHERE telegram_id=?", (str(tg["id"]),)).fetchone()
    return tg, user

def referral_code(c):
    for _ in range(200):
        code = "R" + f"{secrets.randbelow(1_000_000):06d}"
        if not c.execute("SELECT 1 FROM users WHERE referral_code=?", (code,)).fetchone():
            return code
    raise HTTPException(500, "ساخت کد دعوت ممکن نشد.")

def user_view(u):
    return {
      "registered": True, "username": u["username"], "referral_code": u["referral_code"],
      "toman_balance": int(u["toman_balance"]), "usdt_balance": round(float(u["usdt_balance"]), 6),
      "has_withdrawal_pin": bool(u["withdrawal_pin_hash"]),
      "mining_started_at": u["mining_started_at"], "mining_due_at": u["mining_due_at"],
      "mining_claimable": bool(u["mining_claimable"])
    }

class Register(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=6, max_length=128)
    referral_code: str | None = Field(default=None, max_length=7)

class Credentials(BaseModel):
    username: str
    password: str

class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)

class PinData(BaseModel):
    pin: str = Field(min_length=4, max_length=64)
    confirm_pin: str = Field(min_length=4, max_length=64)

class WithdrawData(BaseModel):
    kind: str
    amount: float = Field(gt=0)
    destination: str = Field(min_length=5, max_length=160)
    owner_name: str | None = Field(default=None, max_length=80)
    pin: str = Field(min_length=4, max_length=64)

@app.get("/")
def index(): return FileResponse(BASE / "static" / "index.html")

@app.get("/api/me")
def me(authorization: str = Header(default="")):
    tg, u = current_user(authorization)
    return user_view(u) if u else {"registered": False, "telegram_name": tg.get("first_name","")}

@app.post("/api/register")
def register(data: Register, authorization: str = Header(default="")):
    tg, existing = current_user(authorization)
    if existing: raise HTTPException(409, "شما قبلاً با همین حساب تلگرام حساب ساخته‌اید ❌")
    ref = (data.referral_code or "").strip().upper() or None
    tid = str(tg["id"])
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE username=?", (data.username,)).fetchone():
            raise HTTPException(409, "این نام کاربری قبلاً انتخاب شده است.")
        inviter = None
        if ref:
            if not re.fullmatch(r"R\d{6}", ref): raise HTTPException(400, "فرمت کد معرف درست نیست.")
            inviter = c.execute("SELECT telegram_id FROM users WHERE referral_code=?", (ref,)).fetchone()
            if not inviter: raise HTTPException(400, "کد معرف پیدا نشد.")
            if inviter["telegram_id"] == tid: raise HTTPException(400, "نمی‌توانید از کد دعوت خودتان استفاده کنید.")
        code = referral_code(c)
        c.execute("""INSERT INTO users(telegram_id,username,password_hash,referral_code,referred_by,created_at)
                     VALUES(?,?,?,?,?,?)""",
                  (tid, data.username, secret_hash(data.password), code,
                   inviter["telegram_id"] if inviter else None, now()))
        # Referral reward is granted once, only on successful first account creation.
        if inviter:
            c.execute("UPDATE users SET toman_balance=toman_balance+? WHERE telegram_id=?",
                      (REFERRAL_REWARD_TOMAN, inviter["telegram_id"]))
        u = c.execute("SELECT * FROM users WHERE telegram_id=?", (tid,)).fetchone()
    return user_view(u)

@app.post("/api/login")
def login(data: Credentials, authorization: str = Header(default="")):
    tg, u = current_user(authorization)
    if not u or u["username"] != data.username or not secret_ok(data.password, u["password_hash"]):
        raise HTTPException(401, "نام کاربری یا رمز اشتباه است.")
    return user_view(u)

@app.post("/api/forgot-password")
def forgot_password(data: Credentials, authorization: str = Header(default="")):
    # Telegram identity is the recovery factor; do not ask for or store Telegram passwords.
    tg, u = current_user(authorization)
    if not u: raise HTTPException(404, "برای این حساب تلگرام حسابی ثبت نشده است.")
    if len(data.password) < 6: raise HTTPException(400, "رمز جدید باید حداقل ۶ کاراکتر باشد.")
    with db() as c:
        c.execute("UPDATE users SET password_hash=? WHERE telegram_id=?", (secret_hash(data.password), str(tg["id"])))
    return {"ok": True, "message": "رمز اختصاصی برنامه تغییر کرد."}

@app.post("/api/password")
def change_password(data: ChangePassword, authorization: str = Header(default="")):
    tg, u = current_user(authorization)
    if not u: raise HTTPException(404, "حسابی پیدا نشد.")
    if not secret_ok(data.current_password, u["password_hash"]): raise HTTPException(400, "رمز فعلی اشتباه است.")
    with db() as c: c.execute("UPDATE users SET password_hash=? WHERE telegram_id=?", (secret_hash(data.new_password), str(tg["id"])))
    return {"ok": True}

@app.post("/api/withdrawal-pin")
def set_pin(data: PinData, authorization: str = Header(default="")):
    tg, u = current_user(authorization)
    if not u: raise HTTPException(404, "حسابی پیدا نشد.")
    if data.pin != data.confirm_pin: raise HTTPException(400, "رمز برداشت و تکرار آن یکسان نیست.")
    with db() as c: c.execute("UPDATE users SET withdrawal_pin_hash=? WHERE telegram_id=?", (secret_hash(data.pin), str(tg["id"])))
    return {"ok": True}

@app.post("/api/mining/start")
def mining_start(authorization: str = Header(default="")):
    tg, u = current_user(authorization)
    if not u: raise HTTPException(404, "ابتدا حساب بسازید.")
    if u["mining_claimable"]: raise HTTPException(409, "ابتدا درآمد دوره قبلی را دریافت کنید.")
    if u["mining_started_at"]: raise HTTPException(409, "استخراج در حال اجراست.")
    start = now()
    with db() as c:
        c.execute("UPDATE users SET mining_started_at=?, mining_due_at=?, mining_claimable=0 WHERE telegram_id=?",
                  (start, start+CYCLE_SECONDS, str(tg["id"])))
    return {"ok": True}

@app.post("/api/mining/stop")
def mining_stop(authorization: str = Header(default="")):
    # Manual stop ends this demo cycle without granting the full 24-hour reward.
    tg, u = current_user(authorization)
    if not u: raise HTTPException(404, "حسابی پیدا نشد.")
    with db() as c:
        c.execute("UPDATE users SET mining_started_at=NULL, mining_due_at=NULL, mining_claimable=0 WHERE telegram_id=?",
                  (str(tg["id"]),))
    return {"ok": True}

@app.post("/api/mining/claim")
def mining_claim(authorization: str = Header(default="")):
    tg, u = current_user(authorization)
    if not u or not u["mining_due_at"]: raise HTTPException(400, "دوره استخراجی برای دریافت وجود ندارد.")
    if now() < u["mining_due_at"]: raise HTTPException(400, "هنوز ۲۴ ساعت کامل نشده است.")
    with db() as c:
        c.execute("""UPDATE users SET toman_balance=toman_balance+?, mining_started_at=NULL,
                     mining_due_at=NULL, mining_claimable=0 WHERE telegram_id=?""",
                  (DAILY_REWARD_TOMAN, str(tg["id"])))
    return {"ok": True, "credited_toman": DAILY_REWARD_TOMAN}

@app.get("/api/withdrawals")
def list_withdrawals(authorization: str = Header(default="")):
    tg, u = current_user(authorization)
    if not u: raise HTTPException(404, "حسابی پیدا نشد.")
    with db() as c:
        # Demo workflow: after 48 hours, update the displayed status.
        # This does NOT perform a bank transfer or blockchain transaction.
        c.execute("UPDATE withdrawals SET status='paid_demo' WHERE telegram_id=? AND status='pending' AND created_at<=?",
                  (str(tg["id"]), now() - WITHDRAW_REVIEW_SECONDS))
        rows = c.execute("SELECT id,kind,amount,destination,owner_name,status,created_at FROM withdrawals WHERE telegram_id=? ORDER BY id DESC",
                         (str(tg["id"]),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["amount_toman"] = int(item["amount"]) if item["kind"] == "toman" else round(float(item["amount"]) * USDT_RATE_TOMAN)
        result.append(item)
    return result

@app.post("/api/withdraw")
def withdraw(data: WithdrawData, authorization: str = Header(default="")):
    tg, u = current_user(authorization)
    if not u: raise HTTPException(404, "حسابی پیدا نشد.")
    if not u["withdrawal_pin_hash"]: raise HTTPException(403, "ابتدا رمز برداشت را تعیین کنید.")
    if not secret_ok(data.pin, u["withdrawal_pin_hash"]): raise HTTPException(403, "رمز برداشت اشتباه است.")
    kind = data.kind.lower()
    if kind not in ("toman", "usdt"): raise HTTPException(400, "نوع برداشت نامعتبر است.")
    # The amount entered in BOTH forms is Toman. Tether withdrawals are
    # converted to USDT at the configured demo rate.
    amount_toman = int(data.amount)
    if amount_toman < MIN_WITHDRAW_TOMAN:
        raise HTTPException(400, "حداقل مبلغ برداشت ۴۰۰٬۰۰۰ تومان است.")
    if kind == "toman":
        if not re.fullmatch(r"\d{16}", data.destination): raise HTTPException(400, "شماره کارت باید ۱۶ رقم باشد.")
        if not data.owner_name: raise HTTPException(400, "نام صاحب کارت را وارد کنید.")
        stored_amount = amount_toman
        if stored_amount > int(u["toman_balance"]): raise HTTPException(400, "موجودی تومانی کافی نیست.")
    else:
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", data.destination): raise HTTPException(400, "آدرس BEP20 معتبر نیست.")
        if data.owner_name: raise HTTPException(400, "برای برداشت تتری نام صاحب کارت لازم نیست.")
        stored_amount = round(amount_toman / USDT_RATE_TOMAN, 6)
        if stored_amount > float(u["usdt_balance"]): raise HTTPException(400, "موجودی تتری کافی نیست.")
    with db() as c:
        if kind == "toman":
            c.execute("UPDATE users SET toman_balance=toman_balance-? WHERE telegram_id=?", (stored_amount, str(tg["id"])))
        else:
            c.execute("UPDATE users SET usdt_balance=usdt_balance-? WHERE telegram_id=?", (stored_amount, str(tg["id"])))
        c.execute("INSERT INTO withdrawals(telegram_id,kind,amount,destination,owner_name,created_at) VALUES(?,?,?,?,?,?)",
                  (str(tg["id"]), kind, stored_amount, data.destination, data.owner_name, now()))
    return {"ok": True, "message": "درخواست نمایشی ثبت شد؛ وضعیت تا ۴۸ ساعت در حال بررسی می‌ماند و انتقال واقعی انجام نمی‌شود."}

@app.post("/api/withdrawals/{wid}/cancel")
def cancel_withdrawal(wid: int, authorization: str = Header(default="")):
    tg, u = current_user(authorization)
    if not u: raise HTTPException(404, "حسابی پیدا نشد.")
    with db() as c:
        row = c.execute("SELECT * FROM withdrawals WHERE id=? AND telegram_id=?", (wid,str(tg["id"]))).fetchone()
        if not row or row["status"] != "pending": raise HTTPException(400, "این درخواست دیگر قابل لغو نیست.")
        if row["kind"] == "toman":
            c.execute("UPDATE users SET toman_balance=toman_balance+? WHERE telegram_id=?", (row["amount"],str(tg["id"])))
        else:
            c.execute("UPDATE users SET usdt_balance=usdt_balance+? WHERE telegram_id=?", (row["amount"],str(tg["id"])))
        c.execute("UPDATE withdrawals SET status='cancelled' WHERE id=?", (wid,))
    return {"ok": True}
