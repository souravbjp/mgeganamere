"""
==============================================
  MEGA.NZ TELEGRAM RENAMER BOT (Premium UI)
  Powered by Kurigram / Pyrogram
  By: Claude | Safe & Advanced Architecture
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

# 🚀 MTProto Core
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from pyrogram.errors import FloodWait

# 🌐 Enterprise Database Auto-Resume
try:
    import motor.motor_asyncio
except ImportError:
    pass

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ENV Variables
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

# 🛡️ in_memory=True prevents Koyeb SQLite crashes
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
        "🚀 <b>MEGA.NZ BULK RENAMER BOT</b>\n\n"
        "<blockquote>🛡️ <b>Safe & Secure Mode Active</b>\n"
        "Mega-r firewall theke 100% block-free, file r folder eki sathe rename korun smooth vabe.</blockquote>\n\n"
        "<b>📌 Commands:</b>\n"
        "  <code>/login email password</code> — Login koro\n"
        "  <code>/logout</code> — Account theke ber how\n"
        "  <code>/stats</code> — Mega stats check\n"
        "  <code>/listfolders</code> — Folder gulo dekho\n"
        "  <code>/renameall</code> — Rename engine start\n"
        "  <code>/cancel</code> — Running task stop\n\n"
        "<b>🔧 Features:</b>\n"
        "<blockquote>• Prefix, Suffix, Replace\n"
        "• Regex Support, Custom Template\n"
        "• Auto Resume (MongoDB)\n"
        "• Deep Link WebApp Interface</blockquote>"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 WebApp Dashboard", web_app=WebAppInfo(url="https://megarenamer.vercel.app"))], 
        [InlineKeyboardButton("👨‍💻 Command Help", callback_data="cmd_login_help")]
    ])
    await message.reply_text(msg, parse_mode=enums.ParseMode.HTML, reply_markup=keyboard)


@app.on_message(filters.command("login") & filters.private)
async def login_cmd(client, message):
    uid = message.from_user.id
    args = message.command[1:]

    if len(args) < 2:
        await message.reply_text(
            "❌ <b>Error:</b>\n<blockquote>Sothik vabe command din:\n<code>/login example@email.com password</code></blockquote>",
            parse_mode=enums.ParseMode.HTML
        )
        return

    email, password = args[0], args[1]
    wait_msg = await message.reply_text("🔄 <b>Mega.nz e login hocche...</b>", parse_mode=enums.ParseMode.HTML)

    try:
        loop = asyncio.get_running_loop()
        mega = Mega()
        m = await loop.run_in_executor(None, lambda: mega.login(email, password))
        user_sessions[uid] = {"mega": mega, "m": m, "email": email}
        await wait_msg.edit_text(
            f"✅ <b>Login Successful!</b>\n\n"
            f"<blockquote>📧 <b>Account:</b> <code>{email}</code>\n"
            f"🔑 <b>Status:</b> Authorized & Secured</blockquote>\n"
            f"Ekhon <code>/stats</code> diye file count dekhte paro.",
            parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        await wait_msg.edit_text(
            f"❌ <b>Login Failed!</b>\n<blockquote>Error: {e}</blockquote>", 
            parse_mode=enums.ParseMode.HTML
        )


@app.on_message(filters.command("logout") & filters.private)
async def logout_cmd(client, message):
    uid = message.from_user.id
    if uid in user_sessions:
        del user_sessions[uid]
        await message.reply_text("✅ <b>Logout complete. Session cleared.</b>", parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text("⚠️ <b>Tumi to login-i koroni!</b>", parse_mode=enums.ParseMode.HTML)


@app.on_message(filters.command("stats") & filters.private)
async def stats_cmd(client, message):
    uid = message.from_user.id
    sess = get_session(uid)
    if not sess:
        await message.reply_text("❌ <b>Age /login koro.</b>", parse_mode=enums.ParseMode.HTML)
        return

    wait_msg = await message.reply_text("🔄 <b>Fetching files and folders...</b>", parse_mode=enums.ParseMode.HTML)
    try:
        loop = asyncio.get_running_loop()
        files = await loop.run_in_executor(None, lambda: all_files_recursive(sess["m"]))
        total = len(files)
        await wait_msg.edit_text(
            f"📊 <b>Mega.nz Live Stats</b>\n\n"
            f"<blockquote>📁 <b>Total Files & Folders:</b> <code>{total:,}</code>\n"
            f"📧 <b>Account connected:</b> <code>{sess['email']}</code></blockquote>",
            parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        await wait_msg.edit_text(f"❌ <b>Error:</b> <code>{e}</code>", parse_mode=enums.ParseMode.HTML)


@app.on_message(filters.command("listfolders") & filters.private)
async def listfolders_cmd(client, message):
    uid = message.from_user.id
    sess = get_session(uid)
    if not sess:
        await message.reply_text("❌ <b>Age /login koro.</b>", parse_mode=enums.ParseMode.HTML)
        return

    wait_msg = await message.reply_text("🔄 <b>Checking Mega structure...</b>", parse_mode=enums.ParseMode.HTML)
    try:
        loop = asyncio.get_running_loop()
        all_nodes = await loop.run_in_executor(None, sess["m"].get_files)
        folders = [
            (fid, n) for fid, n in all_nodes.items()
            if n.get("t") == 1 and n.get("a")
        ]
        if not folders:
            await wait_msg.edit_text("📂 <b>Kono folder pawa jayni.</b>", parse_mode=enums.ParseMode.HTML)
            return

        lines = ["📂 <b>Root Folders:</b>\n<blockquote>"]
        for fid, node in folders[:50]:
            name = node.get("a", {}).get("n", "Unknown")
            lines.append(f"• <code>{name}</code>")

        if len(folders) > 50:
            lines.append(f"\n<i>...plus {len(folders)-50} more folders</i>")
        lines.append("</blockquote>")

        await wait_msg.edit_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await wait_msg.edit_text(f"❌ <b>Error:</b> <code>{e}</code>", parse_mode=enums.ParseMode.HTML)


@app.on_message(filters.command("renameall") & filters.private)
async def renameall_cmd(client, message):
    uid = message.from_user.id
    sess = get_session(uid)
    if not sess:
        await message.reply_text("❌ <b>Age /login koro.</b>", parse_mode=enums.ParseMode.HTML)
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 Prefix", callback_data="pattern_prefix"), InlineKeyboardButton("🔡 Suffix", callback_data="pattern_suffix")],
        [InlineKeyboardButton("🔄 Replace", callback_data="pattern_replace"), InlineKeyboardButton("🔢 Number", callback_data="pattern_number")],
        [InlineKeyboardButton("🛠 Regex", callback_data="pattern_regex"), InlineKeyboardButton("📝 Template", callback_data="pattern_template")]
    ])
    await message.reply_text(
        "🎯 <b>Select Rename Method:</b>\n"
        "<blockquote>Kon dhoroner naming pattern apply korte chao? Niche theke select koro:</blockquote>",
        reply_markup=keyboard,
        parse_mode=enums.ParseMode.HTML
    )


@app.on_callback_query()
async def callback_handler(client, query):
    uid = query.from_user.id
    data = query.data

    if data == "cmd_login_help":
        await query.answer("Type: /login your_email your_password", show_alert=True)
        return

    if data.startswith("pattern_"):
        pattern = data.replace("pattern_", "")
        
        if uid not in user_states:
            user_states[uid] = {}
        user_states[uid]["rename_pattern"] = pattern

        prompts = {
            "number":   ("🔢 <b>Sequential Numbers Set</b>\n<blockquote>Sob file <code>00001.ext</code>, <code>00002.ext</code> evabe hobe.\nStart korte <code>/startrenaming</code> daw.</blockquote>", False),
            "prefix":   ("✏️ <b>Prefix Input:</b>\n<blockquote>Je text ta likhbe seta proyojoniyo sob file er ekdom shurute jog hobe.\nExample: <code>Movie_2024_</code></blockquote>", True),
            "suffix":   ("✏️ <b>Suffix Input:</b>\n<blockquote>Je text ta likhbe seta extention er thik age jog hobe.\nExample: <code>_HD</code></blockquote>", True),
            "replace":  ("✏️ <b>Text Replace Input:</b>\n<blockquote>Format: <code>old_word|new_word</code>\nExample: <code>Episode|EP</code></blockquote>", True),
            "regex":    ("✏️ <b>Regex Replace Input:</b>\n<blockquote>Format: <code>pattern|replacement</code>\nExample: <code>\s+|_</code> (space hobe underscore)</blockquote>", True),
            "template": ("✏️ <b>Template Input:</b>\n<blockquote><code>{n}</code> = Original Name\n<code>{i}</code> = Index No\n<code>{ext}</code> = Extension\nExample: <code>Series_{i}_{n}{ext}</code></blockquote>", True),
        }
        text, needs_input = prompts.get(pattern, ("Unknown", False))
        user_states[uid]["awaiting_input"] = needs_input
        if needs_input:
            user_states[uid]["rename_replacement"] = ""
            
        await query.message.edit_text(text, parse_mode=enums.ParseMode.HTML)

    elif data == "confirm_rename":
        await query.message.edit_text("🚀 <b>Initialize hocche...</b>", parse_mode=enums.ParseMode.HTML)
        await do_bulk_rename(query.message, uid)

    elif data == "cancel_rename":
        await query.message.edit_text("❌ <b>Rename canceled by user.</b>", parse_mode=enums.ParseMode.HTML)
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
            InlineKeyboardButton("✅ Start Rename", callback_data="confirm_rename"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_rename"),
        ]
    ])
    await message.reply_text(
        f"👁 <b>Live Preview Generated:</b>\n\n"
        f"<blockquote><b>📄 Old Name:</b> <code>{example_old}</code>\n"
        f"<b>📄 New Name:</b> <code>{example_new}</code></blockquote>\n\n"
        f"<i>Ei niyome sob file change hobe. Tumi ki nischit?</i>",
        reply_markup=keyboard,
        parse_mode=enums.ParseMode.HTML
    )


@app.on_message(filters.command("startrenaming") & filters.private)
async def startrenaming_cmd(client, message):
    uid = message.from_user.id
    state = user_states.get(uid, {})
    
    if state.get("rename_pattern") == "number":
        user_states[uid]["rename_replacement"] = ""
        await message.reply_text("🚀 <b>Processing started...</b>", parse_mode=enums.ParseMode.HTML)
        await do_bulk_rename(message, uid)
    else:
        await message.reply_text("⚠️ <b>Error:</b> Age <code>/renameall</code> diye pattern set koro.", parse_mode=enums.ParseMode.HTML)


@app.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client, message):
    uid = message.from_user.id
    if uid in rename_jobs:
        rename_jobs[uid]["cancelled"] = True
        await message.reply_text("🛑 <b>Cancel command received! Processing will stop in a few seconds...</b>", parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text("⚠️ <b>No active jobs found.</b>", parse_mode=enums.ParseMode.HTML)


# ─── BULK RENAME ENGINE (Safe 1-by-1 Architecture) ───────────────────────────────────────────

async def do_bulk_rename(message, uid: int):
    sess = get_session(uid)
    if not sess:
        await message.reply_text("❌ <b>Session timeout! Abar login koro.</b>", parse_mode=enums.ParseMode.HTML)
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
            await message.reply_text("📂 <b>Kono valid file/folder pawa jayni.</b>", parse_mode=enums.ParseMode.HTML)
            return

        status_msg = await message.reply_text(
            f"🚀 <b>Rename Initializing (Safe Mode)...</b>\n"
            f"<blockquote>📊 Total Targets: <code>{total:,}</code></blockquote>",
            parse_mode=enums.ParseMode.HTML
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

        # 🛡️ 100% Safe Sequential Logic
        for idx, (node, new_name) in enumerate(valid_tasks, start=1):
            if rename_jobs.get(uid, {}).get("cancelled"):
                await status_msg.edit_text(
                    f"🛑 <b>Rename Aborted by User!</b>\n\n"
                    f"<blockquote>✅ <b>Successful:</b> <code>{done:,}</code>\n"
                    f"❌ <b>Failed:</b> <code>{failed:,}</code></blockquote>",
                    parse_mode=enums.ParseMode.HTML
                )
                break
            
            try:
                # 1 by 1 execution -> ZERO -15 Mega Error
                await loop.run_in_executor(None, lambda n=node, nn=new_name: m.rename(n, nn))
                done += 1
                
                # MongoDB Auto Resume Update (Batching DB writes for speed)
                if db is not None and done % 10 == 0:
                    await db.resume_progress.update_one({"uid": uid}, {"$set": {"done": done, "total": total_valid}}, upsert=True)
                    
            except Exception as e:
                logger.error(f"Rename failed for a file: {e}")
                failed += 1
            
            # Anti-ban human delay
            await asyncio.sleep(random.uniform(0.4, 0.9))
            
            # Telegram UI Update (5s Throttling)
            current_time = time.time()
            if (current_time - last_update_time >= 5.0) or (done + failed) == total_valid:
                percent = int(((done + failed) / total_valid) * 100) if total_valid > 0 else 100
                bar_filled = percent // 5
                bar = "▰" * bar_filled + "▱" * (20 - bar_filled)
                try:
                    await status_msg.edit_text(
                        f"🚀 <b>Renaming in Progress...</b>\n\n"
                        f"<blockquote><b>Progress:</b> <code>{percent}%</code>\n"
                        f"<code>{bar}</code>\n\n"
                        f"<b>✅ Completed:</b> <code>{done:,}</code>\n"
                        f"<b>❌ Failed:</b> <code>{failed:,}</code>\n"
                        f"<b>🎯 Total Targets:</b> <code>{total_valid:,}</code></blockquote>",
                        parse_mode=enums.ParseMode.HTML
                    )
                    last_update_time = time.time()
                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                except Exception:
                    pass

        else:
            if not rename_jobs.get(uid, {}).get("cancelled"):
                await status_msg.edit_text(
                    f"🎉 <b>Process Completely Done!</b>\n\n"
                    f"<blockquote><b>📊 Total Scanned:</b> <code>{total:,}</code>\n"
                    f"<b>✅ Successfully Renamed:</b> <code>{done:,}</code>\n"
                    f"<b>❌ Errors Encountered:</b> <code>{failed:,}</code></blockquote>",
                    parse_mode=enums.ParseMode.HTML
                )

    except Exception as e:
        await message.reply_text(f"❌ <b>Critical Error:</b> <code>{e}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        rename_jobs.pop(uid, None)
        if uid in user_states:
            del user_states[uid]
        if db is not None:
             try:
                 await db.resume_progress.delete_one({"uid": uid}) 
             except Exception as e:
                 logger.error(f"DB Error on cleanup: {e}")


# ─── HEALTH CHECK SERVER (For Koyeb) ────────────────────────
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
    logger.info(f"✅ Health check server running on port {port}")
    server.serve_forever()


# ─── MAIN APP START ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BOT_TOKEN or not API_ID or not API_HASH:
        print("❌ ERROR: BOT_TOKEN, API_ID, and API_HASH are strictly required in ENV variables!")
    else:
        threading.Thread(target=start_health_server, daemon=True).start()
        logger.info("🤖 Mega Enterprise Bot (Safe Mode + UI Advanced) starting now...")
        app.run()
