"""
==============================================
  MEGA.NZ TELEGRAM RENAMER BOT (MegaCMD Engine)
  Features: Auth, Premium, MegaCMD Auto Bypass
==============================================
"""

import os
import re
import time
import asyncio
import logging
import posixpath
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler

# Pyrogram Core
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# MongoDB
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ENV Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
MONGO_URL = os.environ.get("MONGO_URL", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))  # Tomar Telegram ID ekhane dibe ENV theke

# Database Setup
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["mega_enterprise_bot"]
users_col = db["users"]
auth_col = db["authorised"]
session_col = db["sessions"]

app = Client("mega_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

# Threads for fast renaming
CMD_TIMEOUT = 60
WORKERS = 10
_executor = ThreadPoolExecutor(max_workers=WORKERS)
user_states = {}
rename_jobs = {}

# ─── DATABASE FUNCTIONS ─────────────────────────────────────
async def add_user(user_id: int):
    if not await users_col.find_one({"_id": user_id}):
        await users_col.insert_one({"_id": user_id, "lifetime_renamed": 0, "daily_limit": 100, "is_premium": False})

async def is_authorised(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    return await auth_col.find_one({"_id": user_id}) is not None

async def get_user_data(user_id: int):
    return await users_col.find_one({"_id": user_id})

async def add_auth(user_id: int):
    await auth_col.update_one({"_id": user_id}, {"$set": {"_id": user_id}}, upsert=True)

async def remove_auth(user_id: int):
    await auth_col.delete_one({"_id": user_id})

async def set_premium(user_id: int, status: bool):
    await users_col.update_one({"_id": user_id}, {"$set": {"is_premium": status, "daily_limit": 99999 if status else 100}})

# ─── MEGACMD ENGINE FUNCTIONS ───────────────────────────────
QUOTA_ENV = {"MEGA_IGNORE_UPLOAD_QUOTA": "1", "MEGA_FORCE_FULL_ACCOUNT_CACHE": "1"}

def run_cmd(args, timeout=CMD_TIMEOUT, extra_env=None):
    try:
        env = os.environ.copy()
        if extra_env: env.update(extra_env)
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return "", str(e), 1

def mega_login(email, password):
    out, err, code = run_cmd(["mega-login", email, password], extra_env=QUOTA_ENV)
    if code == 0 or "Already logged in" in out or "Already logged in" in err:
        return True, ""
    
    out2, err2, code2 = run_cmd(["mega-login", "--no-ask-for-confirmation", email, password], extra_env=QUOTA_ENV)
    if code2 == 0 or "Already logged in" in out2 or "Already logged in" in err2:
        return True, ""
        
    return False, (err or out or err2 or out2).strip()

def mega_logout():
    run_cmd(["mega-logout", "--keep-session"])

def mega_get_all_files():
    out, err, code = run_cmd(["mega-find", "/", "--type=f"], timeout=CMD_TIMEOUT * 3)
    if code == 0:
        return [line.strip() for line in out.strip().split('\n') if line.strip()]
    return []

def _rename_one_sync(old_path: str, new_name: str):
    if old_path.endswith(new_name): return False
    parent = posixpath.dirname(old_path)
    new_path = f"{parent}/{new_name}" if parent not in ["", "/"] else f"/{new_name}"
    out, err, code = run_cmd(["mega-mv", old_path, new_path])
    if code != 0: raise Exception(err or out)
    return True

def build_new_name(old_name, pattern, replacement, index):
    name, ext = posixpath.splitext(old_name)
    if pattern == "prefix": return f"{replacement}{old_name}"
    elif pattern == "suffix": return f"{name}{replacement}{ext}"
    elif pattern == "replace":
        parts = replacement.split("|", 1)
        return old_name.replace(parts[0], parts[1]) if len(parts) == 2 else old_name
    elif pattern == "number": return f"{str(index).zfill(5)}{ext}"
    return old_name


# ─── MIDDLEWARE ─────────────────────────────────────────────
@app.on_message(filters.private, group=-1)
async def check_access(client, message):
    uid = message.from_user.id
    await add_user(uid)
    if not await is_authorised(uid):
        await message.reply_text(f"🚫 **Access Denied!**\nTumi authorized nou. Owner k bolo permission dite.\nTomar ID: `{uid}`")
        message.stop_propagation()


# ─── ADMIN COMMANDS ─────────────────────────────────────────
@app.on_message(filters.command("auth") & filters.private)
async def cmd_auth(client, message):
    if message.from_user.id != ADMIN_ID: return
    uid = int(message.command[1])
    await add_auth(uid)
    await message.reply_text(f"✅ User `{uid}` authorised!")

@app.on_message(filters.command("unauth") & filters.private)
async def cmd_unauth(client, message):
    if message.from_user.id != ADMIN_ID: return
    uid = int(message.command[1])
    await remove_auth(uid)
    await message.reply_text(f"❌ User `{uid}` removed from auth!")

@app.on_message(filters.command("setpremium") & filters.private)
async def cmd_setpremium(client, message):
    if message.from_user.id != ADMIN_ID: return
    uid = int(message.command[1])
    await set_premium(uid, True)
    await message.reply_text(f"⭐ User `{uid}` ke Premium deya hoyeche! (Unlimited Renames)")


# ─── USER COMMANDS ─────────────────────────────────────────
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    msg = (
        "🚀 **MEGA.NZ BULK RENAMER BOT**\n\n"
        "**📌 Commands:**\n"
        "`/login email password` — Login koro\n"
        "`/logout` — Account theke ber how\n"
        "`/stats` — User stats dekho\n"
        "`/renameall` — Rename engine start\n\n"
    )
    await message.reply_text(msg)

@app.on_message(filters.command("login") & filters.private)
async def login_cmd(client, message):
    uid = message.from_user.id
    args = message.command[1:]
    if len(args) < 2:
        return await message.reply_text("❌ `Usage: /login email password`")
    
    email, password = args[0], args[1]
    wait_msg = await message.reply_text("🔄 **Mega.nz e login hocche (MegaCMD Engine)...**")

    loop = asyncio.get_running_loop()
    success, err = await loop.run_in_executor(None, mega_login, email, password)

    if success:
        await session_col.update_one({"_id": uid}, {"$set": {"email": email}}, upsert=True)
        await wait_msg.edit_text(f"✅ **Login Successful!**\n📧 Account: `{email}`\nEbar `/renameall` command dao.")
    else:
        await wait_msg.edit_text(f"❌ **Login Failed!**\nError: `{err}`")

@app.on_message(filters.command("renameall") & filters.private)
async def renameall_cmd(client, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 Prefix", callback_data="pattern_prefix"), InlineKeyboardButton("🔡 Suffix", callback_data="pattern_suffix")],
        [InlineKeyboardButton("🔄 Replace", callback_data="pattern_replace"), InlineKeyboardButton("🔢 Number", callback_data="pattern_number")]
    ])
    await message.reply_text("🎯 **Select Rename Method:**", reply_markup=keyboard)

@app.on_callback_query()
async def callback_handler(client, query):
    uid = query.from_user.id
    data = query.data

    if data.startswith("pattern_"):
        pattern = data.replace("pattern_", "")
        user_states[uid] = {"rename_pattern": pattern, "awaiting_input": pattern != "number"}

        if pattern == "number":
            user_states[uid]["rename_replacement"] = ""
            await query.message.edit_text("🔢 Sob file `00001.ext`, `00002.ext` evabe hobe.\nStart korte `/startrenaming` daw.")
        else:
            await query.message.edit_text("✏️ **Input daw:** (Prefix/Suffix/Replace er jonno ki text dite chao seta lekho)")

@app.on_message(filters.text & filters.private & ~filters.command(["start", "login", "logout", "stats", "renameall", "startrenaming"]))
async def input_handler(client, message):
    uid = message.from_user.id
    if user_states.get(uid, {}).get("awaiting_input"):
        user_states[uid]["rename_replacement"] = message.text.strip()
        user_states[uid]["awaiting_input"] = False
        await message.reply_text("✅ Input saved! Ebar `/startrenaming` command daw.")

@app.on_message(filters.command("startrenaming") & filters.private)
async def startrenaming_cmd(client, message):
    uid = message.from_user.id
    state = user_states.get(uid)
    if not state:
        return await message.reply_text("❌ Age `/renameall` diye setup koro.")

    user_data = await get_user_data(uid)
    if user_data['daily_limit'] <= 0 and not user_data['is_premium']:
        return await message.reply_text("❌ Tomar Daily Limit Sesh! Premium er jonno Owner k bolo.")

    status_msg = await message.reply_text("⏳ **Files fetch kora hocche...**")
    
    loop = asyncio.get_running_loop()
    files = await loop.run_in_executor(None, mega_get_all_files)
    total = len(files)

    if total == 0:
        return await status_msg.edit_text("📂 Kono file pawa jayni.")

    limit = total if user_data['is_premium'] else min(total, user_data['daily_limit'])
    files_to_rename = files[:limit]

    done, failed = 0, 0
    pattern = state["rename_pattern"]
    replacement = state["rename_replacement"]
    sem = asyncio.Semaphore(WORKERS)

    await status_msg.edit_text(f"🚀 **Renaming {limit} files in background...** (Wait koro)")

    async def rename_task(file_path, idx):
        nonlocal done, failed
        async with sem:
            try:
                new_name = build_new_name(posixpath.basename(file_path), pattern, replacement, idx)
                success = await loop.run_in_executor(_executor, _rename_one_sync, file_path, new_name)
                if success: done += 1
            except Exception:
                failed += 1

    tasks = [rename_task(fp, i+1) for i, fp in enumerate(files_to_rename)]
    await asyncio.gather(*tasks)

    await users_col.update_one({"_id": uid}, {"$inc": {"lifetime_renamed": done, "daily_limit": -done}})
    
    await status_msg.edit_text(f"🎉 **Rename Complete!**\n\n✅ Success: `{done}`\n❌ Failed: `{failed}`")


# ─── KOYEB HEALTH CHECK ──────────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args): pass   

def start_health_server():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8000))), HealthHandler).serve_forever()

if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    app.run()
