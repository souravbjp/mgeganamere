"""
==============================================
  MEGA.NZ TELEGRAM RENAMER BOT (MTProto Version)
  Powered by Kurigram / Pyrogram
  By: Claude | Safe Enterprise Architecture
==============================================
"""

import logging
import asyncio
import re
import os
import threading
import time
import random
from http.server import HTTPServer, BaseHTTPRequestHandler
from mega import Mega

# 🚀 MTProto Core (Kurigram / Pyrogram)
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from pyrogram.errors import FloodWait

# 🌐 Enterprise Database Auto-Resume System
try:
    import motor.motor_asyncio
except ImportError:
    pass

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ENV Variables required for MTProto
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_ID = int(os.environ.get("API_ID", "0"))      
API_HASH = os.environ.get("API_HASH", "")        
MONGO_URL = os.environ.get("MONGO_URL", "")

db = None
if MONGO_URL:
    try:
        mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
        db = mongo_client["mega_enterprise_bot"]
        logger.info("✅ MongoDB Connected Automatically!")
    except Exception as e:
        logger.warning(f"MongoDB connection failed: {e}")

# 🛡️ in_memory=True prevents SQLite locked/read-only errors on Koyeb
app = Client(
    "mega_enterprise_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

user_sessions = {}
rename_jobs = {}
user_states = {} 

def get_session(user_id):
    return user_sessions.get(user_id)

def all_files_recursive(m):
    files = m.get_files()
    result = []
    for fid, node in files.items():
        if node.get("t") in (0, 1): 
            result.append((fid, node))
    return result

def build_new_name(old_name: str, pattern: str, replacement: str, index: int) -> str:
    name, ext = os.path.splitext(old_name)

    if pattern == "prefix":
        return f"{replacement}{old_name}"
    elif pattern == "suffix":
        return f"{name}{replacement}{ext}"
    elif pattern == "replace":
        parts = replacement.split("|", 1)
        if len(parts) == 2:
            return old_name.replace(parts[0], parts[1])
        return old_name
    elif pattern == "regex":
        parts = replacement.split("|", 1)
        if len(parts) == 2:
            try:
                return re.sub(parts[0], parts[1], old_name)
            except re.error:
                return old_name
        return old_name
    elif pattern == "template":
        return (replacement
                .replace("{n}", name)
                .replace("{i}", str(index))
                .replace("{ext}", ext))
    elif pattern == "number":
        return f"{str(index).zfill(5)}{ext}"

    return old_name


# ─── COMMANDS ────────────────────────────────────────────────────

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    msg = (
        "🚀 *MEGA.NZ BULK RENAMER BOT (SAFE MODE)*\n\n"
        "এই bot দিয়ে Mega.nz এর হাজার হাজার file একসাথে rename করো!\n\n"
        "📌 *Commands:*\n"
        "  `/login email password` — Mega.nz login\n"
        "  `/logout` — Logout\n"
        "  `/stats` — Total files count\n"
        "  `/listfolders` — Folder list দেখো\n"
        "  `/renameall` — সব file rename করো\n"
        "  `/cancel` — চলমান rename বন্ধ করো\n\n"
        "🔧 *Rename Patterns:*\n"
        "  `prefix:MyName_` → সব file এর আগে যোগ করো\n"
        "  `suffix:_HD` → সব file এর পরে যোগ করো\n"
        "  `replace:old|new` → নাম replace করো\n"
        "  `regex:pattern|repl` → Regex দিয়ে rename\n"
        "  `template:{n}_{i}{ext}` → Custom template\n"
        "  `number` → Sequential numbers (00001.mp4)\n"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 WebApp Theke Login Koro", web_app=WebAppInfo(url="https://telegram.org"))], 
        [InlineKeyboardButton("👨‍💻 Command Diye Login", callback_data="cmd_login_help")]
    ])
    await message.reply_text(msg, reply_markup=keyboard)


@app.on_message(filters.command("login") & filters.private)
async def login_cmd(client, message):
    uid = message.from_user.id
    args = message.command[1:]

    if len(args) < 2:
        await message.reply_text("❌ Usage: `/login email password`")
        return

    email, password = args[0], args[1]
    wait_msg = await message.reply_text("🔄 Mega.nz এ login হচ্ছে...")

    try:
        loop = asyncio.get_running_loop()
        mega = Mega()
        m = await loop.run_in_executor(None, lambda: mega.login(email, password))
        user_sessions[uid] = {"mega": mega, "m": m, "email": email}
        await wait_msg.edit_text(f"✅ *Login সফল!*\n📧 {email}\n\nএখন `/stats` দিয়ে file count দেখো।")
    except Exception as e:
        await wait_msg.edit_text(f"❌ Login ব্যর্থ!\nError: `{e}`")


@app.on_message(filters.command("logout") & filters.private)
async def logout_cmd(client, message):
    uid = message.from_user.id
    if uid in user_sessions:
        del user_sessions[uid]
        await message.reply_text("✅ Logout হয়ে গেছে।")
    else:
        await message.reply_text("⚠️ আপনি login করেননি।")


@app.on_message(filters.command("stats") & filters.private)
async def stats_cmd(client, message):
    uid = message.from_user.id
    sess = get_session(uid)
    if not sess:
        await message.reply_text("❌ আগে `/login email password` করো।")
        return

    wait_msg = await message.reply_text("🔄 File count করা হচ্ছে...")
    try:
        loop = asyncio.get_running_loop()
        files = await loop.run_in_executor(None, lambda: all_files_recursive(sess["m"]))
        total = len(files)
        await wait_msg.edit_text(
            f"📊 *Mega.nz Stats*\n\n"
            f"📁 Total Files & Folders: `{total:,}`\n"
            f"📧 Account: `{sess['email']}`"
        )
    except Exception as e:
        await wait_msg.edit_text(f"❌ Error: `{e}`")


@app.on_message(filters.command("listfolders") & filters.private)
async def listfolders_cmd(client, message):
    uid = message.from_user.id
    sess = get_session(uid)
    if not sess:
        await message.reply_text("❌ আগে `/login` করো।")
        return

    wait_msg = await message.reply_text("🔄 Fetching folders...")
    try:
        loop = asyncio.get_running_loop()
        all_nodes = await loop.run_in_executor(None, sess["m"].get_files)
        folders = [
            (fid, n) for fid, n in all_nodes.items()
            if n.get("t") == 1 and n.get("a")
        ]
        if not folders:
            await wait_msg.edit_text("📂 কোনো folder পাওয়া যায়নি।")
            return

        lines = ["📂 *Folder List:*\n"]
        for fid, node in folders[:50]:
            name = node.get("a", {}).get("n", "Unknown")
            lines.append(f"• `{name}`")

        if len(folders) > 50:
            lines.append(f"\n_...এবং আরো {len(folders)-50}টি folder_")

        await wait_msg.edit_text("\n".join(lines))
    except Exception as e:
        await wait_msg.edit_text(f"❌ Error: `{e}`")


@app.on_message(filters.command("renameall") & filters.private)
async def renameall_cmd(client, message):
    uid = message.from_user.id
    sess = get_session(uid)
    if not sess:
        await message.reply_text("❌ আগে `/login` করো।")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 Prefix যোগ করো",    callback_data="pattern_prefix")],
        [InlineKeyboardButton("🔡 Suffix যোগ করো",    callback_data="pattern_suffix")],
        [InlineKeyboardButton("🔄 Text Replace",       callback_data="pattern_replace")],
        [InlineKeyboardButton("🔢 Sequential Numbers", callback_data="pattern_number")],
        [InlineKeyboardButton("🛠 Regex Replace",      callback_data="pattern_regex")],
        [InlineKeyboardButton("📝 Custom Template",    callback_data="pattern_template")]
    ])
    await message.reply_text("🎯 *কোন ধরনের Rename করতে চাও?*", reply_markup=keyboard)


@app.on_callback_query()
async def callback_handler(client, query):
    uid = query.from_user.id
    data = query.data

    if data == "cmd_login_help":
        await query.answer("Example: /login email password", show_alert=True)
        return

    if data.startswith("pattern_"):
        pattern = data.replace("pattern_", "")
        
        if uid not in user_states:
            user_states[uid] = {}
        user_states[uid]["rename_pattern"] = pattern

        prompts = {
            "number":   ("🔢 সব file/folder কে `00001.ext`, `00002.ext` ... এভাবে rename করা হবে।\n\nশুরু করতে `/startrenaming` দাও।", False),
            "prefix":   ("✏️ Prefix টাইপ করো:\n\nExample: `Movie_2024_`\n\n_(এই text সব file/folder এর নামের আগে যোগ হবে)_", True),
            "suffix":   ("✏️ Suffix টাইপ করো:\n\nExample: `_HD`\n\n_(Extension এর আগে যোগ হবে)_", True),
            "replace":  ("✏️ Format: `পুরনো_text|নতুন_text`\n\nExample: `Episode|EP`", True),
            "regex":    ("✏️ Regex Format: `pattern|replacement`\n\nExample: `\\s+|_` (space কে underscore করবে)", True),
            "template": ("✏️ Template লেখো:\n\n`{n}` = original name\n`{i}` = index number\n`{ext}` = extension\n\nExample: `Series_{i}_{n}{ext}`", True),
        }
        text, needs_input = prompts.get(pattern, ("Unknown pattern", False))
        user_states[uid]["awaiting_input"] = needs_input
        if needs_input:
            user_states[uid]["rename_replacement"] = ""
            
        await query.message.edit_text(text)

    elif data == "confirm_rename":
        await query.message.edit_text("🚀 Rename শুরু হচ্ছে...")
        await do_bulk_rename(query.message, uid)

    elif data == "cancel_rename":
        await query.message.edit_text("❌ Rename বাতিল করা হয়েছে।")
        if uid in user_states:
            del user_states[uid]


@app.on_message(filters.text & filters.private & ~filters.command(["start", "login", "logout", "stats", "listfolders", "renameall", "startrenaming", "cancel"]))
async def message_handler(client, message):
    uid = message.from_user.id
    state = user_states.get(uid, {})
    
    if not state.get("awaiting_input"):
        return

    text = message.text.strip()
    user_states[uid]["rename_replacement"] = text
    user_states[uid]["awaiting_input"] = False

    pattern = user_states[uid].get("rename_pattern", "")
    example_old = "My_Movie_Episode_01.mp4"
    example_new = build_new_name(example_old, pattern, text, 1)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ শুরু করো!", callback_data="confirm_rename"),
            InlineKeyboardButton("❌ বাতিল",     callback_data="cancel_rename"),
        ]
    ])
    await message.reply_text(
        f"👁 *Preview:*\n\n"
        f"📄 আগে: `{example_old}`\n"
        f"📄 পরে: `{example_new}`\n\n"
        f"সব file/folder এই নিয়মে rename হবে। নিশ্চিত?",
        reply_markup=keyboard
    )


@app.on_message(filters.command("startrenaming") & filters.private)
async def startrenaming_cmd(client, message):
    uid = message.from_user.id
    state = user_states.get(uid, {})
    
    if state.get("rename_pattern") == "number":
        user_states[uid]["rename_replacement"] = ""
        await message.reply_text("🚀 Rename শুরু হচ্ছে...")
        await do_bulk_rename(message, uid)
    else:
        await message.reply_text("⚠️ আগে `/renameall` দিয়ে pattern সেট করো।")


@app.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client, message):
    uid = message.from_user.id
    if uid in rename_jobs:
        rename_jobs[uid]["cancelled"] = True
        await message.reply_text("🛑 Rename job বন্ধ করার request পাঠানো হয়েছে...")
    else:
        await message.reply_text("⚠️ কোনো চলমান job নেই।")


# ─── BULK RENAME ENGINE (Original Safe Architecture) ───────────────────────────────────────────

async def do_bulk_rename(message, uid: int):
    sess = get_session(uid)
    if not sess:
        await message.reply_text("❌ Session শেষ হয়ে গেছে। আবার `/login` করো।")
        return

    state = user_states.get(uid, {})
    pattern     = state.get("rename_pattern", "prefix")
    replacement = state.get("rename_replacement", "")
    m           = sess["m"]

    rename_jobs[uid] = {"running": True, "cancelled": False}

    try:
        loop = asyncio.get_running_loop()
        files = await loop.run_in_executor(None, lambda: all_files_recursive(m))
        total = len(files)

        if total == 0:
            await message.reply_text("📂 কোনো file/folder পাওয়া যায়নি।")
            return

        status_msg = await message.reply_text(
            f"🚀 *Rename শুরু হয়েছে!*\n\n"
            f"📊 Total Targets: `{total:,}`\n"
            f"✅ Done: `0`\n"
            f"❌ Failed: `0`\n\n"
            f"_/cancel দিয়ে বন্ধ করতে পারো_"
        )

        valid_tasks = []
        for idx, (fid, node) in enumerate(files, start=1):
            old_name = node.get("a", {}).get("n", "")
            if not old_name:
                continue
            new_name = build_new_name(old_name, pattern, replacement, idx)
            if new_name != old_name:
                valid_tasks.append((node, new_name))

        total_valid = len(valid_tasks)
        done = 0
        failed = 0
        last_update_time = time.time()

        # 🛡️ 100% Safe Original Logic (Sequential) - No Batching
        for idx, (node, new_name) in enumerate(valid_tasks, start=1):
            if rename_jobs.get(uid, {}).get("cancelled"):
                await status_msg.edit_text(
                    f"🛑 *Rename বন্ধ করা হয়েছে!*\n\n"
                    f"✅ Done: `{done:,}`\n"
                    f"❌ Failed: `{failed:,}`"
                )
                break
            
            try:
                # 🚀 1 by 1 Execution (Prevents Mega API -15 Error entirely)
                await loop.run_in_executor(None, lambda n=node, nn=new_name: m.rename(n, nn))
                done += 1
                
                # 💾 MongoDB Auto Save Progress (Updates every 10 files to save DB bandwidth)
                if db is not None and done % 10 == 0:
                    await db.resume_progress.update_one({"uid": uid}, {"$set": {"done": done, "total": total_valid}}, upsert=True)
                    
            except Exception as e:
                logger.error(f"Rename failed: {e}")
                failed += 1
            
            # 🛡️ Safe Jitter Delay
            await asyncio.sleep(random.uniform(0.3, 0.7))
            
            # MTProto Telegram Anti-ban (5 seconds Throttling)
            current_time = time.time()
            if (current_time - last_update_time >= 5.0) or (done + failed) == total_valid:
                percent = int(((done + failed) / total_valid) * 100) if total_valid > 0 else 100
                bar_filled = percent // 5
                bar = "█" * bar_filled + "░" * (20 - bar_filled)
                try:
                    await status_msg.edit_text(
                        f"🚀 *Renaming (Safe Mode)...*\n\n"
                        f"`{bar}` {percent}%\n\n"
                        f"📊 Total Targets: `{total_valid:,}`\n"
                        f"✅ Done: `{done:,}`\n"
                        f"❌ Failed: `{failed:,}`"
                    )
                    last_update_time = time.time()
                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                except Exception:
                    pass

        else:
            if not rename_jobs.get(uid, {}).get("cancelled"):
                await status_msg.edit_text(
                    f"🎉 *Rename সম্পন্ন!*\n\n"
                    f"📊 Total Targets: `{total:,}`\n"
                    f"✅ Successfully Renamed: `{done:,}`\n"
                    f"❌ Failed: `{failed:,}`"
                )

    except Exception as e:
        await message.reply_text(f"❌ Critical Error: `{e}`")
    finally:
        rename_jobs.pop(uid, None)
        if uid in user_states:
            del user_states[uid]
        if db is not None:
             try:
                 await db.resume_progress.delete_one({"uid": uid}) 
             except Exception as e:
                 logger.error(f"DB Error on complete: {e}")


# ─── HEALTH CHECK SERVER (Koyeb এর জন্য) ────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass   

def start_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"✅ Health check server on port {port}")
    server.serve_forever()


# ─── MAIN ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BOT_TOKEN or not API_ID or not API_HASH:
        print("❌ BOT_TOKEN, API_ID and API_HASH environment variables are required!")
    else:
        threading.Thread(target=start_health_server, daemon=True).start()
        logger.info("🤖 Mega Enterprise Bot (Kurigram Edition) চালু হচ্ছে...")
        app.run()
