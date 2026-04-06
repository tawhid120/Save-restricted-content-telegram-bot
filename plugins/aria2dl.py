# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/aria2dl.py — Aria2c Downloader (Azure Safe — No RPC)
#
# Commands:
#   /dl  <URL / magnet link>       → Direct link or magnet download
#   /dl  (reply to .torrent file)  → Torrent file download
#   /mirror <same as /dl>          → Alias command
#
# ✅ NO localhost/RPC dependency — Azure safe (subprocess mode)
# ✅ Real-time progress via aria2c stdout parsing
# ✅ Multi-file torrent → uploads separately (NO ZIP)
# ✅ Strict 2 GB Telegram upload limit (per file)
# ✅ Files >2GB are skipped, user is notified
# ✅ HTTP links: pre-check size before downloading
# ✅ FloodWait + MessageNotModified safe edits
# ✅ Premium / Free user restriction + 5-min cooldown
# ✅ Safe cancel via asyncio.Event (no race condition)
# ✅ Python 3.9+ compatible

import asyncio
import os
import re
import shutil
import tempfile
from datetime import datetime
from time import time
from typing import Optional, List, Tuple

import aiohttp
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import COMMAND_PREFIX, LOG_GROUP_ID
from core import (
    daily_limit,
    prem_plan1,
    prem_plan2,
    prem_plan3,
    user_activity_collection,
)
from utils import LOGGER
from utils.helper import (
    get_readable_file_size,
    get_readable_time,
    get_video_thumbnail,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

DOWNLOAD_DIR    = os.path.join(tempfile.gettempdir(), "aria2dl_downloads")
PROGRESS_DELAY  = 3                      # Seconds between progress edits
MAX_WAIT_SECS   = 3600 * 6              # Max 6 hours per download
TELEGRAM_MAX    = 2  * 1024 ** 3        # 2 GB — Telegram strict limit
FREE_FILE_LIMIT = 500 * 1024 ** 2       # 500 MB — Free users
FREE_COOLDOWN   = 300                   # 5 minutes cooldown for free users
DB_TIMEOUT      = 5.0                   # Max seconds for DB response

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Cancel events — { message_id: asyncio.Event }
_cancel_events: dict[int, asyncio.Event] = {}

# ─────────────────────────────────────────────────────────────────────────────
# ARIA2C STDOUT PARSER
# ─────────────────────────────────────────────────────────────────────────────

# Matches: [#a1b2c3 10MiB/100MiB(10%) CN:16 DL:5.0MiB ETA:18s]
_PROGRESS_RE = re.compile(
    r"\[.*?"
    r"(?P<done>[0-9.]+[KMGT]?i?B)/"
    r"(?P<total>[0-9.]+[KMGT]?i?B)"
    r"\((?P<pct>\d+)%\)"
    r".*?DL:(?P<speed>[0-9.]+[KMGT]?i?B)/s"
    r"(?:.*?ETA:(?P<eta>[^\]\s]+))?"
    r".*?\]",
    re.IGNORECASE
)

def _parse_progress(line: str) -> Optional[dict]:
    m = _PROGRESS_RE.search(line)
    if not m:
        return None
    return {
        "done":  m.group("done"),
        "total": m.group("total"),
        "pct":   int(m.group("pct")),
        "speed": m.group("speed"),
        "eta":   m.group("eta") or "...",
    }

def _size_to_bytes(size_str: str) -> int:
    """Convert aria2 size string (e.g., '1.2GiB', '500MiB') to bytes."""
    s = size_str.upper().strip()
    s = s.replace("IB", "").replace("B", "").strip()
    try:
        if "K" in s: return int(float(s.replace("K","")) * 1024)
        if "M" in s: return int(float(s.replace("M","")) * 1024**2)
        if "G" in s: return int(float(s.replace("G","")) * 1024**3)
        if "T" in s: return int(float(s.replace("T","")) * 1024**4)
        return int(float(s))
    except (ValueError, TypeError):
        return 0

# ─────────────────────────────────────────────────────────────────────────────
# PREMIUM / COOLDOWN / LOG HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _is_premium(user_id: int) -> bool:
    now = datetime.utcnow()
    for col in [prem_plan1, prem_plan2, prem_plan3]:
        try:
            doc = await asyncio.wait_for(
                col.find_one({"user_id": user_id}), timeout=DB_TIMEOUT
            )
            if doc and doc.get("expiry_date", now) > now:
                return True
        except Exception:
            pass
    return False

async def _check_and_set_cooldown(user_id: int) -> Optional[str]:
    now = time()
    try:
        doc = await asyncio.wait_for(
            daily_limit.find_one({"user_id": user_id}), timeout=DB_TIMEOUT
        )
        if doc:
            last_dl = doc.get("last_aria2dl_download", 0)
            elapsed = now - last_dl
            if elapsed < FREE_COOLDOWN:
                remaining = int(FREE_COOLDOWN - elapsed)
                return (
                    f"⏳ Please wait **{remaining // 60}m {remaining % 60}s** "
                    f"before your next download.\n\nUpgrade: /plans"
                )
        await asyncio.wait_for(
            daily_limit.update_one(
                {"user_id": user_id},
                {"$set": {"last_aria2dl_download": now}},
                upsert=True,
            ),
            timeout=DB_TIMEOUT,
        )
    except Exception:
        pass
    return None

async def _increment_download_count(user_id: int):
    try:
        await asyncio.wait_for(
            daily_limit.update_one(
                {"user_id": user_id}, {"$inc": {"total_downloads": 1}}, upsert=True
            ), timeout=DB_TIMEOUT
        )
    except Exception:
        pass

async def _log_to_group(client: Client, user, source_url: str, 
                        file_name: str, file_size: int, is_premium: bool, 
                        success: bool, error_msg: str = ""):
    if not LOG_GROUP_ID: return
    try:
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username  = f"@{user.username}" if user.username else "N/A"
        plan      = "💎 Premium" if is_premium else "🆓 Free"
        status    = "✅ Success" if success else "❌ Failed"
        size      = get_readable_file_size(file_size) if file_size > 0 else "N/A"

        text = (
            f"📥 **Aria2DL Log**\n{'─'*30}\n"
            f"👤 **User:** [{full_name}](tg://user?id={user.id}) | `{user.id}`\n"
            f"📋 **Plan:** {plan} | {username}\n"
            f"📄 **File:** `{file_name}` | `{size}`\n"
            f"📊 **Status:** {status}\n"
        )
        if error_msg: text += f"❌ **Error:** `{error_msg[:200]}`\n"

        markup = None
        if source_url and source_url.startswith(("http", "magnet:")):
            btn_url = source_url if source_url.startswith("http") else "https://t.me"
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Source", url=btn_url)]])

        await client.send_message(
            LOG_GROUP_ID, text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup, disable_web_page_preview=True
        )
    except Exception as e:
        LOGGER.warning(f"[Aria2DL] Log failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _progress_bar(pct: float, length: int = 20) -> str:
    filled = int(length * pct / 100)
    return "▓" * filled + "░" * (length - filled)

def _get_file_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".mp4", ".mkv", ".avi", ".mov", ".webm"}: return "🎬 Video"
    if ext in {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav"}: return "🎵 Audio"
    return "📁 File"

async def _safe_edit(msg: Message, text: str, markup=None):
    try:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, 
                           reply_markup=markup, disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except FloodWait as fw:
        await asyncio.sleep(fw.value + 1)
        try:
            await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, 
                               reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# PRE-CHECK HTTP SIZE (Avoid downloading >2GB files)
# ─────────────────────────────────────────────────────────────────────────────

async def _check_http_size(url: str, max_allowed: int) -> Optional[str]:
    """Returns error message if file is too large, else None."""
    if not url.startswith("http"): return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    length = int(resp.headers.get("Content-Length", 0))
                    if length > 0 and length > max_allowed:
                        return (
                            f"❌ **File too large!**\n\n"
                            f"📦 Size: `{get_readable_file_size(length)}`\n"
                            f"🚫 Limit: `{get_readable_file_size(max_allowed)}`"
                        )
    except Exception:
        pass
    return None

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM UPLOAD (SINGLE FILE WITH PROGRESS)
# ─────────────────────────────────────────────────────────────────────────────

async def _upload_file(
    client: Client, chat_id: int, file_path: str, 
    caption: str, status_msg: Message, file_num: int, total_files: int
):
    file_size = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    last_edit = [0.0]
    start = [time()]

    async def _progress(current: int, total: int):
        now = time()
        if now - last_edit[0] < PROGRESS_DELAY and current < total:
            return
        pct = (current / total * 100) if total > 0 else 0
        speed = current / (now - start[0]) if (now - start[0]) > 0 else 0
        eta = int((total - current) / speed) if speed > 0 else 0
        bar = _progress_bar(pct)

        header = f"📤 **Uploading ({file_num}/{total_files})...**\n\n"
        if total_files == 1:
            header = "📤 **Uploading...**\n\n"

        await _safe_edit(
            status_msg,
            f"{header}"
            f"`[{bar}]` {pct:.1f}%\n\n"
            f"📦 `{get_readable_file_size(current)}` / `{get_readable_file_size(total)}`\n"
            f"⚡ **Speed:** `{get_readable_file_size(speed)}/s`\n"
            f"⏳ **ETA:** `{get_readable_time(eta)}`"
        )
        last_edit[0] = now

    VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v"}
    AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac"}

    thumb = None
    if ext in VIDEO_EXTS:
        try: thumb = await get_video_thumbnail(file_path, None)
        except: pass
        await client.send_video(
            chat_id=chat_id, video=file_path, caption=caption, thumb=thumb,
            supports_streaming=True, parse_mode=ParseMode.MARKDOWN, progress=_progress
        )
        if thumb and os.path.exists(thumb): os.remove(thumb)
    elif ext in AUDIO_EXTS:
        await client.send_audio(
            chat_id=chat_id, audio=file_path, caption=caption,
            parse_mode=ParseMode.MARKDOWN, progress=_progress
        )
    else:
        await client.send_document(
            chat_id=chat_id, document=file_path, caption=caption,
            parse_mode=ParseMode.MARKDOWN, progress=_progress
        )

    return file_size

# ─────────────────────────────────────────────────────────────────────────────
# CORE DOWNLOAD PIPELINE (SUBPROCESS — NO RPC)
# ─────────────────────────────────────────────────────────────────────────────

async def _run_download(
    client: Client, message: Message, source_url: str,
    torrent_path: Optional[str], status_msg: Message, 
    is_premium: bool, cancel_event: asyncio.Event
):
    user_id  = message.from_user.id
    chat_id  = message.chat.id
    start_ts = time()
    max_allowed = TELEGRAM_MAX if is_premium else FREE_FILE_LIMIT
    user_dir = os.path.join(DOWNLOAD_DIR, str(user_id), str(int(time())))
    os.makedirs(user_dir, exist_ok=True)

    final_name = ""
    final_size = 0
    success    = False
    error      = ""

    try:
        # ── 1. BUILD COMMAND ─────────────────────────────────────────────
        cmd = [
            "aria2c",
            "--enable-rpc=false",           # NO RPC — Azure safe
            "--show-console-readout=true",
            "--console-log-level=notice",
            "--summary-interval=1",
            "--max-connection-per-server=16",
            "--split=16",
            "--min-split-size=5M",
            "--max-tries=5",
            "--retry-wait=5",
            "--continue=true",
            "--bt-enable-lpd=true",
            "--enable-dht=true",
            "--bt-save-metadata=true",
            f"--dir={user_dir}",
        ]

        if torrent_path:
            cmd.append(torrent_path)  # aria2c auto-detects .torrent files
        else:
            cmd.append(source_url)

        # ── 2. RUN SUBPROCESS ────────────────────────────────────────────
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        last_edit_ts = 0.0
        error_lines = []

        await _safe_edit(status_msg, "⬇️ **Downloading...**\n\n`Connecting...`")

        while True:
            if cancel_event.is_set():
                try: process.kill()
                except: pass
                await _safe_edit(status_msg, "⛔ **Download cancelled.**")
                error = "Cancelled"
                return

            try:
                raw = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
                if not raw: 
                    # Check if process ended
                    if process.returncode is not None:
                        break
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
            except asyncio.TimeoutError:
                continue

            if not line: continue
            LOGGER.debug(f"[Aria2DL] {line}")

            if "FAILED" in line.upper() or "error" in line.lower():
                error_lines.append(line)

            prog = _parse_progress(line)
            if prog:
                # Size limit check from progress
                total_bytes = _size_to_bytes(prog["total"])
                if total_bytes > 0 and total_bytes > max_allowed:
                    try: process.kill()
                    except: pass
                    error = f"File too large: {prog['total']} (Limit: {get_readable_file_size(max_allowed)})"
                    await _safe_edit(
                        status_msg,
                        f"❌ **File too large!**\n\n"
                        f"📦 **Size:** `{prog['total']}`\n"
                        f"🚫 **Limit:** `{get_readable_file_size(max_allowed)}`\n\n"
                        + ("" if is_premium else "💎 Upgrade: /plans")
                    )
                    return

                now = time()
                if now - last_edit_ts >= PROGRESS_DELAY:
                    bar = _progress_bar(prog["pct"])
                    elapsed = int(now - start_ts)
                    cancel_btn = InlineKeyboardMarkup([[
                        InlineKeyboardButton("⛔ Cancel", callback_data=f"aria2_cancel_{status_msg.id}")
                    ]])
                    await _safe_edit(
                        status_msg,
                        f"⬇️ **Downloading...**\n\n"
                        f"`[{bar}]` {prog['pct']}%\n\n"
                        f"📥 `{prog['done']}` / `{prog['total']}`\n"
                        f"⚡ **Speed:** `{prog['speed']}/s`\n"
                        f"⏳ **ETA:** `{prog['eta']}`\n"
                        f"⏱ **Elapsed:** `{get_readable_time(elapsed)}`",
                        markup=cancel_btn
                    )
                    last_edit_ts = now

        # Process finished
        if process.returncode != 0:
            err = " | ".join(error_lines[-2:]) if error_lines else f"Exit code: {process.returncode}"
            await _safe_edit(status_msg, f"❌ **Download failed!**\n\n`{err[:300]}`")
            error = err
            return

        # ── 3. FIND DOWNLOADED FILES ─────────────────────────────────────
        await _safe_edit(status_msg, "✅ **Download complete!**\n\n📦 Scanning files...")

        files_to_upload: List[Tuple[str, int]] = []
        skipped_files: List[Tuple[str, int]] = []

        for root, _, fnames in os.walk(user_dir):
            for f in fnames:
                if f.endswith((".aria2", ".torrent")): continue
                fp = os.path.join(root, f)
                sz = os.path.getsize(fp)
                if sz > TELEGRAM_MAX:
                    skipped_files.append((f, sz))
                else:
                    files_to_upload.append((fp, sz))

        if not files_to_upload and not skipped_files:
            await _safe_edit(status_msg, "❌ **No files found after download.**")
            error = "No files found"
            return

        # ── 4. UPLOAD FILES ONE BY ONE ───────────────────────────────────
        total_valid = len(files_to_upload)
        total_uploaded_size = 0

        for i, (fp, sz) in enumerate(sorted(files_to_upload), 1):
            if cancel_event.is_set():
                error = "Cancelled during upload"
                await _safe_edit(status_msg, "⛔ **Upload cancelled.**")
                return

            name = os.path.basename(fp)
            caption = (
                f"📄 **{name}**\n"
                f"📦 `{get_readable_file_size(sz)}`"
                + (f"\n📎 File `{i}/{total_valid}`" if total_valid > 1 else "")
            )

            try:
                await _upload_file(
                    client, chat_id, fp, caption, status_msg, i, total_valid
                )
                total_uploaded_size += sz
                success = True
            except Exception as upload_err:
                LOGGER.error(f"[Aria2DL] Upload error: {upload_err}")
                error = str(upload_err)

        # ── 5. SEND FINAL REPORT ─────────────────────────────────────────
        elapsed = get_readable_time(int(time() - start_ts))
        report = f"✅ **Done!** ({elapsed})\n\n"

        if total_valid > 0:
            report += f"📤 Uploaded: **{total_valid}** file(s)\n"
            report += f"📦 Total: `{get_readable_file_size(total_uploaded_size)}`\n"

        if skipped_files:
            report += f"\n⚠️ **Skipped (>2GB Telegram limit):**\n"
            for sf_name, sf_sz in skipped_files:
                report += f"• `{sf_name}` ({get_readable_file_size(sf_sz)})\n"

        await _safe_edit(status_msg, report)

        if total_valid > 0:
            asyncio.create_task(_increment_download_count(user_id))

        final_name = ", ".join([os.path.basename(fp) for fp, _ in files_to_upload])
        final_size = total_uploaded_size

    except Exception as e:
        LOGGER.error(f"[Aria2DL] Pipeline error: {e}")
        error = str(e)
        await _safe_edit(status_msg, f"❌ **Error!**\n\n`{str(e)[:300]}`")
    finally:
        asyncio.create_task(
            _log_to_group(client, message.from_user, source_url, 
                         final_name, final_size, is_premium, success, error)
        )
        _cancel_events.pop(status_msg.id, None)
        if os.path.isdir(user_dir):
            shutil.rmtree(user_dir, ignore_errors=True)
        if torrent_path and os.path.exists(torrent_path):
            try: os.remove(torrent_path)
            except: pass

# ─────────────────────────────────────────────────────────────────────────────
# COMMAND HANDLER REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────

def setup_aria2dl_handler(app: Client):

    @app.on_message(
        filters.command(["dl", "mirror"], prefixes=COMMAND_PREFIX)
        & (filters.private | filters.group)
    )
    async def aria2_dl_command(client: Client, message: Message):
        user_id = message.from_user.id

        if not shutil.which("aria2c"):
            await message.reply_text(
                "❌ **aria2c is not installed!**\n\nContact admin: `sudo apt install aria2`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        is_premium = await _is_premium(user_id)
        max_allowed = TELEGRAM_MAX if is_premium else FREE_FILE_LIMIT

        if not is_premium:
            cd = await _check_and_set_cooldown(user_id)
            if cd:
                await message.reply_text(cd, parse_mode=ParseMode.MARKDOWN)
                return

        torrent_path = None
        source_url = ""
        args_text = ""

        if message.reply_to_message:
            doc = message.reply_to_message.document
            replied_text = (message.reply_to_message.text or "").strip()

            if doc and (
                doc.mime_type == "application/x-bittorrent"
                or (doc.file_name or "").endswith(".torrent")
            ):
                init_msg = await message.reply_text("⬇️ **Fetching .torrent file...**", parse_mode=ParseMode.MARKDOWN)
                torrent_path = await message.reply_to_message.download()
                source_url = doc.file_name or "torrent"
                try: await init_msg.delete()
                except: pass
            elif replied_text:
                args_text = replied_text

        if not torrent_path and not args_text:
            parts = message.text.split(None, 1)
            args_text = parts[1].strip() if len(parts) > 1 else ""

        if not torrent_path and not args_text:
            plan_info = (
                f"💎 **Premium:** `{get_readable_file_size(TELEGRAM_MAX)}`"
                if is_premium else
                f"🆓 **Free:** `{get_readable_file_size(FREE_FILE_LIMIT)}` (5m cooldown)"
            )
            await message.reply_text(
                "🌊 **Aria2 Downloader**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
                "**Usage:**\n"
                "`/dl <URL>` — HTTP/HTTPS/FTP\n"
                "`/dl <magnet>` — Magnet link\n"
                "Reply to `.torrent` with `/dl`\n\n"
                f"{plan_info}\n\n"
                "__Multi-file torrents are uploaded separately.__",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if not source_url and args_text:
            source_url = args_text

        # Pre-check HTTP size
        if not torrent_path and source_url.startswith("http"):
            size_err = await _check_http_size(source_url, max_allowed)
            if size_err:
                await message.reply_text(size_err, parse_mode=ParseMode.MARKDOWN)
                return

        status_msg = await message.reply_text("🔄 **Starting download...**", parse_mode=ParseMode.MARKDOWN)

        cancel_event = asyncio.Event()
        _cancel_events[status_msg.id] = cancel_event

        asyncio.create_task(
            _run_download(client, message, source_url, torrent_path, 
                         status_msg, is_premium, cancel_event)
        )

    # ── Cancel callback ──────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^aria2_cancel_(\d+)$"))
    async def aria2_cancel_callback(client: Client, callback_query):
        msg_id = int(callback_query.data.split("_")[-1])
        event = _cancel_events.get(msg_id)
        if event:
            event.set()
            await callback_query.answer("⛔ Cancelling...")
            await _safe_edit(callback_query.message, "⛔ **Cancelling download...**")
        else:
            await callback_query.answer("No active download found.", show_alert=True)

    LOGGER.info("[Aria2DL] /dl and /mirror registered (Azure Safe — No RPC Mode).")
