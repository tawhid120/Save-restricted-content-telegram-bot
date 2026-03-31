# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/aria2dl.py — Aria2c Downloader
#
# Handles:
#   • HTTP / HTTPS / FTP direct links     → /dl <url>
#   • Magnet links                         → /dl <magnet:?...>
#   • .torrent file (reply to file)        → /dl  (reply to .torrent)
#
# ✅ Real-time progress bar (download + upload)
# ✅ Premium / free user limit check
# ✅ Auto-detect media type for Telegram upload
# ✅ Multi-file torrent → zip + send
# ✅ Cleanup temp files after every operation

import os
import json
import asyncio
import zipfile
import tempfile
import base64
from time import time
from datetime import datetime

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pyrogram.handlers import MessageHandler
from pyleaves import Leaves

from config import COMMAND_PREFIX, LOG_GROUP_ID, DEVELOPER_USER_ID
from utils import LOGGER, fileSizeLimit, progressArgs, log_file_to_group
from utils.helper import (
    get_readable_file_size,
    get_readable_time,
    get_video_thumbnail,
)
from core import (
    prem_plan1,
    prem_plan2,
    prem_plan3,
    daily_limit,
    user_activity_collection,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

ARIA2_RPC_URL   = os.environ.get("ARIA2_RPC_URL", "http://localhost:6800/jsonrpc")
ARIA2_SECRET    = os.environ.get("ARIA2_RPC_SECRET", "")
DOWNLOAD_DIR    = os.path.join(tempfile.gettempdir(), "aria2dl_downloads")
PROGRESS_DELAY  = 3          # seconds between progress edits
POLL_INTERVAL   = 2          # seconds between aria2 status polls
MAX_WAIT_SECS   = 3600 * 6   # 6 hours max download time
MAX_FILE_SIZE   = 2 * 1024 ** 3   # 2 GB (Telegram bot limit)
FREE_FILE_LIMIT = 500 * 1024 ** 2  # 500 MB for free users

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# ARIA2 JSON-RPC CLIENT
# ─────────────────────────────────────────────────────────────────────────────

class Aria2Client:
    """Thin async wrapper around aria2c's JSON-RPC API."""

    _counter = 0

    def __init__(self, url: str = ARIA2_RPC_URL, secret: str = ARIA2_SECRET):
        self.url    = url
        self.secret = secret

    def _make_params(self, params: list) -> list:
        if self.secret:
            return [f"token:{self.secret}"] + params
        return params

    async def call(self, method: str, *params) -> dict:
        Aria2Client._counter += 1
        payload = {
            "jsonrpc": "2.0",
            "id":      str(Aria2Client._counter),
            "method":  method,
            "params":  self._make_params(list(params)),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    data = await resp.json(content_type=None)
            if "error" in data:
                raise RuntimeError(data["error"]["message"])
            return data.get("result")
        except aiohttp.ClientConnectorError:
            raise RuntimeError(
                "Aria2c সার্ভারে connect করা যাচ্ছে না!\n"
                "নিশ্চিত করুন `aria2c --enable-rpc` চালু আছে।"
            )

    # ── convenience wrappers ──────────────────────────────────────────────────

    async def add_uri(self, uris: list, options: dict = None) -> str:
        return await self.call("aria2.addUri", uris, options or {})

    async def add_torrent(self, torrent_b64: str, options: dict = None) -> str:
        return await self.call("aria2.addTorrent", torrent_b64, [], options or {})

    async def tell_status(self, gid: str) -> dict:
        fields = [
            "status", "totalLength", "completedLength",
            "downloadSpeed", "errorMessage", "dir",
            "files", "bittorrent", "followedBy",
        ]
        return await self.call("aria2.tellStatus", gid, fields)

    async def remove(self, gid: str):
        for method in ("aria2.remove", "aria2.forceRemove"):
            try:
                await self.call(method, gid)
                return
            except Exception:
                pass

    async def remove_result(self, gid: str):
        try:
            await self.call("aria2.removeDownloadResult", gid)
        except Exception:
            pass

    async def pause(self, gid: str):
        try:
            await self.call("aria2.pause", gid)
        except Exception:
            pass


aria2 = Aria2Client()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _is_premium(user_id: int) -> bool:
    now = datetime.utcnow()
    for col in [prem_plan1, prem_plan2, prem_plan3]:
        doc = await col.find_one({"user_id": user_id})
        if doc and doc.get("expiry_date", now) > now:
            return True
    return False


def _progress_bar(pct: float, length: int = 20) -> str:
    filled = int(length * pct / 100)
    return "▓" * filled + "░" * (length - filled)


def _get_download_path(status: dict) -> str | None:
    """Resolve the primary downloaded file path from aria2 status."""
    files = status.get("files", [])
    if not files:
        return None

    # Single file
    if len(files) == 1:
        path = files[0].get("path", "")
        return path if path and os.path.exists(path) else None

    # Torrent with multiple files → return directory
    dir_path = status.get("dir", "")
    bt      = status.get("bittorrent", {})
    name    = bt.get("info", {}).get("name", "")
    if name:
        folder = os.path.join(dir_path, name)
        if os.path.isdir(folder):
            return folder
    return dir_path if os.path.isdir(dir_path) else None


def _zip_directory(folder: str, zip_path: str):
    """Zip a directory."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(folder):
            for f in files:
                fp  = os.path.join(root, f)
                arc = os.path.relpath(fp, os.path.dirname(folder))
                zf.write(fp, arc)


async def _send_file_to_telegram(
    client: Client,
    chat_id: int,
    file_path: str,
    caption: str,
    status_msg: Message,
    start_ts: float,
):
    """Upload a single file to Telegram with progress bar."""
    file_size = os.path.getsize(file_path)
    ext       = os.path.splitext(file_path)[1].lower()
    start_up  = [time()]
    last_edit = [0.0]

    async def _progress(current: int, total: int):
        now = time()
        if now - last_edit[0] < PROGRESS_DELAY and current < total:
            return
        elapsed = now - start_up[0]
        speed   = current / elapsed if elapsed > 0 else 0
        eta     = (total - current) / speed if speed > 0 else 0
        pct     = (current / total * 100) if total > 0 else 0
        bar     = _progress_bar(pct)
        try:
            await status_msg.edit_text(
                f"📤 **Telegram-এ Upload হচ্ছে...**\n\n"
                f"`[{bar}]` {pct:.1f}%\n\n"
                f"📦 **Uploaded:** `{get_readable_file_size(current)}` / `{get_readable_file_size(total)}`\n"
                f"⚡ **Speed:** `{get_readable_file_size(speed)}/s`\n"
                f"⏳ **ETA:** `{get_readable_time(int(eta))}`\n\n"
                f"📄 `{os.path.basename(file_path)}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            last_edit[0] = now
        except Exception:
            pass

    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}
    audio_exts = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac"}

    try:
        if ext in video_exts:
            thumb = None
            try:
                thumb = await get_video_thumbnail(file_path, None)
            except Exception:
                pass
            await client.send_video(
                chat_id=chat_id,
                video=file_path,
                caption=caption,
                thumb=thumb,
                supports_streaming=True,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )
            if thumb and os.path.exists(thumb):
                os.remove(thumb)

        elif ext in audio_exts:
            await client.send_audio(
                chat_id=chat_id,
                audio=file_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )

        else:
            await client.send_document(
                chat_id=chat_id,
                document=file_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )

        elapsed = get_readable_time(int(time() - start_ts))
        await status_msg.edit_text(
            f"✅ **সফলভাবে পাঠানো হয়েছে!**\n\n"
            f"📦 `{get_readable_file_size(file_size)}`\n"
            f"⏱ সময়: `{elapsed}`",
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        LOGGER.error(f"[Aria2DL] Upload error: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# CORE DOWNLOAD + UPLOAD PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

async def _run_aria2_download(
    client: Client,
    message: Message,
    gid: str,
    status_msg: Message,
    is_premium: bool,
    source_url: str = "",
):
    """
    Poll aria2 until the download finishes, then upload to Telegram.
    Called after a GID has been obtained from aria2.
    """
    user_id   = message.from_user.id
    chat_id   = message.chat.id
    start_ts  = time()
    last_edit = time()

    try:
        # ── Follow redirect GIDs (meta-download for torrents) ────────────────
        for _ in range(30):
            status = await aria2.tell_status(gid)
            if status.get("followedBy"):
                new_gid = status["followedBy"][0]
                LOGGER.info(f"[Aria2DL] Followed GID {gid} → {new_gid}")
                await aria2.remove_result(gid)
                gid = new_gid
                break
            if status.get("status") not in ("waiting",):
                break
            await asyncio.sleep(1)

        # ── Download progress loop ───────────────────────────────────────────
        deadline = time() + MAX_WAIT_SECS

        while time() < deadline:
            status = await aria2.tell_status(gid)
            dl_status = status.get("status", "")

            total     = int(status.get("totalLength", 0))
            completed = int(status.get("completedLength", 0))
            speed     = int(status.get("downloadSpeed", 0))
            pct       = (completed / total * 100) if total > 0 else 0
            elapsed   = time() - start_ts
            eta       = int((total - completed) / speed) if speed > 0 else 0

            # ── Check file size limit ─────────────────────────────────────
            max_allowed = MAX_FILE_SIZE if is_premium else FREE_FILE_LIMIT
            if total > max_allowed and total > 0:
                await aria2.remove(gid)
                try:
                    await status_msg.edit_text(
                        f"❌ **ফাইল অনেক বড়!**\n\n"
                        f"📦 ফাইল: `{get_readable_file_size(total)}`\n"
                        f"🚫 সীমা: `{get_readable_file_size(max_allowed)}`\n\n"
                        f"{'💎 Premium' if not is_premium else 'আপগ্রেড: /plans'}",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass
                return

            # ── Update progress message ───────────────────────────────────
            if time() - last_edit >= PROGRESS_DELAY:
                bar = _progress_bar(pct)
                try:
                    await status_msg.edit_text(
                        f"⬇️ **Download হচ্ছে...**\n\n"
                        f"`[{bar}]` {pct:.1f}%\n\n"
                        f"📥 **Downloaded:** `{get_readable_file_size(completed)}` / `{get_readable_file_size(total)}`\n"
                        f"⚡ **Speed:** `{get_readable_file_size(speed)}/s`\n"
                        f"⏳ **ETA:** `{get_readable_time(eta) if eta else '...'}`\n"
                        f"⏱ **Elapsed:** `{get_readable_time(int(elapsed))}`",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⛔ বাতিল", callback_data=f"aria2_cancel_{gid}")]
                        ]),
                    )
                    last_edit = time()
                except Exception:
                    pass

            # ── Check completion ──────────────────────────────────────────
            if dl_status == "complete":
                break
            elif dl_status == "error":
                err = status.get("errorMessage", "Unknown error")
                try:
                    await status_msg.edit_text(
                        f"❌ **Download ব্যর্থ হয়েছে!**\n\n`{err}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass
                await aria2.remove_result(gid)
                return
            elif dl_status == "removed":
                try:
                    await status_msg.edit_text(
                        "⛔ **Download বাতিল করা হয়েছে।**",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass
                return

            await asyncio.sleep(POLL_INTERVAL)

        else:
            # Timeout
            await aria2.remove(gid)
            try:
                await status_msg.edit_text(
                    "⏰ **Timeout!** Download সম্পন্ন হয়নি।",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            return

        # ── Resolve downloaded path ───────────────────────────────────────────
        status    = await aria2.tell_status(gid)
        dl_path   = _get_download_path(status)

        if not dl_path:
            await status_msg.edit_text(
                "❌ Downloaded ফাইল খুঁজে পাওয়া যায়নি।",
                parse_mode=ParseMode.MARKDOWN,
            )
            await aria2.remove_result(gid)
            return

        await status_msg.edit_text(
            f"✅ **Download সম্পন্ন!**\n\n"
            f"📤 Telegram-এ Upload করা হচ্ছে...",
            parse_mode=ParseMode.MARKDOWN,
        )

        # ── Handle directory (zip it) ─────────────────────────────────────────
        if os.path.isdir(dl_path):
            zip_path = dl_path.rstrip("/") + ".zip"
            await asyncio.get_event_loop().run_in_executor(
                None, _zip_directory, dl_path, zip_path
            )
            upload_path = zip_path
        else:
            upload_path = dl_path

        file_size = os.path.getsize(upload_path)
        max_allowed = MAX_FILE_SIZE if is_premium else FREE_FILE_LIMIT

        if file_size > max_allowed:
            await status_msg.edit_text(
                f"❌ **ফাইল অনেক বড়!**\n\n"
                f"📦 `{get_readable_file_size(file_size)}` > `{get_readable_file_size(max_allowed)}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            name    = os.path.basename(upload_path)
            caption = (
                f"📄 **{name}**\n"
                f"📦 `{get_readable_file_size(file_size)}`"
                + (f"\n🔗 `{source_url}`" if source_url else "")
            )
            await _send_file_to_telegram(
                client, chat_id, upload_path, caption, status_msg, start_ts
            )

        # ── Cleanup ───────────────────────────────────────────────────────────
        for p in [upload_path, dl_path]:
            try:
                if os.path.isfile(p):
                    os.remove(p)
                elif os.path.isdir(p):
                    import shutil
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
        await aria2.remove_result(gid)

    except Exception as e:
        LOGGER.error(f"[Aria2DL] Pipeline error for user {user_id}: {e}")
        try:
            await status_msg.edit_text(
                f"❌ **Error:**\n`{str(e)[:300]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        try:
            await aria2.remove(gid)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def setup_aria2dl_handler(app: Client):

    @app.on_message(
        filters.command(["dl", "mirror"], prefixes=COMMAND_PREFIX)
        & (filters.private | filters.group)
    )
    async def aria2_dl_command(client: Client, message: Message):
        user_id    = message.from_user.id
        is_premium = await _is_premium(user_id)

        # ── Determine input ───────────────────────────────────────────────────
        torrent_bytes = None
        url           = ""

        # Replied to a .torrent file?
        if message.reply_to_message:
            replied = message.reply_to_message
            doc = replied.document
            if doc and (doc.mime_type == "application/x-bittorrent"
                        or (doc.file_name or "").endswith(".torrent")):
                status_msg = await message.reply_text(
                    "⬇️ **.torrent ফাইল download হচ্ছে...**",
                    parse_mode=ParseMode.MARKDOWN,
                )
                torrent_path = await replied.download()
                with open(torrent_path, "rb") as f:
                    torrent_bytes = f.read()
                os.remove(torrent_path)
            else:
                url = (replied.text or "").strip()

        # URL from command argument
        if not torrent_bytes and not url:
            parts = message.text.split(None, 1)
            if len(parts) > 1:
                url = parts[1].strip()

        if not torrent_bytes and not url:
            await message.reply_text(
                "**📥 Aria2 Downloader**\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "**ব্যবহার:**\n"
                "`/dl <URL>`\n"
                "`/dl <magnet:?xt=...>`\n"
                "`.torrent` ফাইলে reply করে `/dl`\n\n"
                "**Supported:**\n"
                "• HTTP / HTTPS / FTP direct links\n"
                "• Magnet links\n"
                "• .torrent files",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        status_msg = await message.reply_text(
            "🔄 **Aria2c-এ download যোগ করা হচ্ছে...**",
            parse_mode=ParseMode.MARKDOWN,
        )

        # ── Default aria2 options ─────────────────────────────────────────────
        user_dir = os.path.join(DOWNLOAD_DIR, str(user_id))
        os.makedirs(user_dir, exist_ok=True)

        options = {
            "dir": user_dir,
            "max-connection-per-server": "16",
            "split": "16",
            "min-split-size": "5M",
            "max-tries": "5",
            "retry-wait": "5",
        }

        try:
            # ── Add to aria2 ─────────────────────────────────────────────────
            if torrent_bytes:
                gid = await aria2.add_torrent(
                    base64.b64encode(torrent_bytes).decode(), options
                )
                source = "torrent file"
            else:
                gid    = await aria2.add_uri([url], options)
                source = url

            await status_msg.edit_text(
                f"✅ **Download Queue-এ যোগ হয়েছে!**\n\n"
                f"🆔 GID: `{gid}`\n"
                f"📡 Source: `{source[:80]}`\n\n"
                "⏳ শুরু হচ্ছে...",
                parse_mode=ParseMode.MARKDOWN,
            )

            LOGGER.info(f"[Aria2DL] User {user_id} added download GID={gid}: {source[:80]}")

            # ── Run download pipeline ─────────────────────────────────────────
            asyncio.create_task(
                _run_aria2_download(
                    client, message, gid, status_msg, is_premium, source
                )
            )

        except Exception as e:
            LOGGER.error(f"[Aria2DL] Failed to add download for {user_id}: {e}")
            try:
                await status_msg.edit_text(
                    f"❌ **Download যোগ করা যায়নি:**\n\n`{str(e)[:300]}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

    # ── Cancel callback ───────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^aria2_cancel_(.+)$"))
    async def aria2_cancel_callback(client, callback_query):
        gid     = callback_query.data.split("_", 2)[-1]
        user_id = callback_query.from_user.id
        try:
            await aria2.remove(gid)
            await callback_query.message.edit_text(
                "⛔ **Download বাতিল করা হয়েছে।**",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            await callback_query.answer(f"Error: {e}", show_alert=True)
            return
        await callback_query.answer("বাতিল সফল!")

    LOGGER.info("[Aria2DL] /dl and /mirror command handler registered.")
