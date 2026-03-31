# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/qbtdl.py — qBittorrent Downloader
#
# Handles:
#   • /qbt <magnet link>       → Magnet download
#   • /qbt <torrent URL>       → Torrent URL download
#   • /qbt (reply to .torrent) → .torrent file download
#
# ✅ Real-time progress bar (download + seeding)
# ✅ Premium / free file size check
# ✅ Auto file detection & Telegram upload after download
# ✅ Cancel button support
# ✅ Cleanup after every operation

import os
import asyncio
import tempfile
import shutil
from time import time
from datetime import datetime

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pyrogram.handlers import MessageHandler

from config import COMMAND_PREFIX, LOG_GROUP_ID
from utils import LOGGER, fileSizeLimit, progressArgs, log_file_to_group
from utils.helper import get_readable_file_size, get_readable_time, get_video_thumbnail
from core import (
    prem_plan1, prem_plan2, prem_plan3,
    daily_limit, user_activity_collection,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG  (set these in your .env or config.py)
# ─────────────────────────────────────────────────────────────────────────────

QBT_URL      = os.environ.get("QBT_URL",      "http://localhost:8090")
QBT_USERNAME = os.environ.get("QBT_USERNAME", "mltb")
QBT_PASSWORD = os.environ.get("QBT_PASSWORD", "mltbmltb")

DOWNLOAD_DIR    = os.path.join(tempfile.gettempdir(), "qbtdl_downloads")
PROGRESS_DELAY  = 4      # seconds between progress edits
POLL_INTERVAL   = 3      # seconds between qBittorrent status polls
MAX_WAIT_SECS   = 3600 * 6
MAX_FILE_SIZE   = 2 * 1024 ** 3    # 2 GB (premium)
FREE_FILE_LIMIT = 500 * 1024 ** 2  # 500 MB (free)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Active cancel flags: { hash: True }
_cancel_flags: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# qBittorrent Web API CLIENT
# ─────────────────────────────────────────────────────────────────────────────

class QBittorrentClient:
    """Thin async wrapper around qBittorrent WebUI API v2."""

    def __init__(self, url: str = QBT_URL, username: str = QBT_USERNAME, password: str = QBT_PASSWORD):
        self.url      = url.rstrip("/")
        self.username = username
        self.password = password
        self._cookie  = None

    async def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(),
            timeout=aiohttp.ClientTimeout(total=30),
        )

    async def login(self) -> bool:
        async with await self._session() as session:
            try:
                resp = await session.post(
                    f"{self.url}/api/v2/auth/login",
                    data={"username": self.username, "password": self.password},
                )
                text = await resp.text()
                if text.strip() == "Ok.":
                    self._cookie = session.cookie_jar.filter_cookies(self.url)
                    return True
                return False
            except Exception as e:
                raise RuntimeError(f"qBittorrent login failed: {e}") from e

    async def _request(self, method: str, endpoint: str, **kwargs):
        cookies = self._cookie or {}
        async with await self._session() as session:
            session.cookie_jar.update_cookies(cookies)
            try:
                fn = session.post if method == "POST" else session.get
                resp = await fn(f"{self.url}/api/v2/{endpoint}", **kwargs)
                return resp
            except aiohttp.ClientConnectorError:
                raise RuntimeError(
                    "qBittorrent WebUI-তে connect করা যাচ্ছে না!\n"
                    "নিশ্চিত করুন qBittorrent চালু আছে।"
                )

    async def add_magnet(self, magnet: str, save_path: str) -> str:
        await self.login()
        await self._request("POST", "torrents/add",
                             data={"urls": magnet, "savepath": save_path, "autoTMM": "false"})
        # Return hash from magnet URI
        import re
        m = re.search(r"xt=urn:btih:([a-fA-F0-9]+|[a-zA-Z2-7]{32})", magnet)
        if m:
            h = m.group(1).lower()
            if len(h) == 32:  # Base32 → hex
                import base64
                h = base64.b32decode(h.upper()).hex()
            return h
        return ""

    async def add_torrent_file(self, file_path: str, save_path: str) -> str:
        await self.login()
        with open(file_path, "rb") as f:
            torrent_data = f.read()
        import aiohttp as ah
        form = ah.FormData()
        form.add_field("torrents", torrent_data, filename="file.torrent",
                       content_type="application/x-bittorrent")
        form.add_field("savepath", save_path)
        form.add_field("autoTMM", "false")
        await self._request("POST", "torrents/add", data=form)
        await asyncio.sleep(1)
        # Find the newly added torrent
        resp = await self._request("GET", "torrents/info")
        torrents = await resp.json()
        if torrents:
            return torrents[0]["hash"]
        return ""

    async def add_torrent_url(self, url: str, save_path: str) -> str:
        return await self.add_magnet(url, save_path)

    async def get_torrent_info(self, torrent_hash: str) -> dict | None:
        await self.login()
        resp = await self._request("GET", "torrents/info",
                                   params={"hashes": torrent_hash})
        data = await resp.json()
        return data[0] if data else None

    async def get_torrent_files(self, torrent_hash: str) -> list:
        await self.login()
        resp = await self._request("GET", "torrents/files",
                                   params={"hash": torrent_hash})
        return await resp.json()

    async def remove_torrent(self, torrent_hash: str, delete_files: bool = True):
        await self.login()
        await self._request("POST", "torrents/delete",
                             data={"hashes": torrent_hash,
                                   "deleteFiles": "true" if delete_files else "false"})

    async def pause_torrent(self, torrent_hash: str):
        await self.login()
        await self._request("POST", "torrents/pause", data={"hashes": torrent_hash})


qbt = QBittorrentClient()


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


def _state_label(state: str) -> str:
    labels = {
        "downloading":      "⬇️ Downloading",
        "stalledDL":        "⏳ Stalled",
        "metaDL":           "🔍 Fetching Metadata",
        "checkingDL":       "🔎 Checking",
        "checkingResumeData": "🔎 Checking Resume",
        "queuedDL":         "📋 Queued",
        "pausedDL":         "⏸ Paused",
        "error":            "❌ Error",
        "missingFiles":     "❓ Missing Files",
        "uploading":        "🌱 Seeding",
        "stalledUP":        "🌱 Seeding (Stalled)",
        "forcedDL":         "⬇️ Forced Download",
    }
    return labels.get(state, f"🔄 {state.capitalize()}")


def _find_largest_file(save_path: str, files_info: list) -> str | None:
    """Return path of the largest downloaded file."""
    best = None
    best_size = 0
    for f in files_info:
        rel_path = f.get("name", "")
        full_path = os.path.join(save_path, rel_path)
        if os.path.exists(full_path):
            sz = os.path.getsize(full_path)
            if sz > best_size:
                best_size = sz
                best = full_path
    return best


# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD HELPER
# ─────────────────────────────────────────────────────────────────────────────

async def _upload_to_telegram(
    client: Client,
    chat_id: int,
    file_path: str,
    caption: str,
    status_msg: Message,
    start_ts: float,
    thumbnail_path: str | None = None,
):
    file_size = os.path.getsize(file_path)
    ext       = os.path.splitext(file_path)[1].lower()
    last_edit = [0.0]
    start_up  = [time()]

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
                f"📦 `{get_readable_file_size(current)}` / `{get_readable_file_size(total)}`\n"
                f"⚡ **Speed:** `{get_readable_file_size(speed)}/s`\n"
                f"⏳ **ETA:** `{get_readable_time(int(eta))}`\n\n"
                f"📄 `{os.path.basename(file_path)}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            last_edit[0] = now
        except Exception:
            pass

    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v"}
    audio_exts = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac"}

    try:
        if ext in video_exts:
            thumb = thumbnail_path
            if not thumb:
                try:
                    thumb = await get_video_thumbnail(file_path, None)
                except Exception:
                    thumb = None
            await client.send_video(
                chat_id=chat_id, video=file_path, caption=caption,
                thumb=thumb, supports_streaming=True,
                parse_mode=ParseMode.MARKDOWN, progress=_progress,
            )
            if thumb and thumb != thumbnail_path and os.path.exists(thumb):
                os.remove(thumb)

        elif ext in audio_exts:
            await client.send_audio(
                chat_id=chat_id, audio=file_path, caption=caption,
                thumb=thumbnail_path, parse_mode=ParseMode.MARKDOWN, progress=_progress,
            )
        else:
            await client.send_document(
                chat_id=chat_id, document=file_path, caption=caption,
                thumb=thumbnail_path, parse_mode=ParseMode.MARKDOWN, progress=_progress,
            )

        elapsed = get_readable_time(int(time() - start_ts))
        await status_msg.edit_text(
            f"✅ **সফলভাবে পাঠানো হয়েছে!**\n\n"
            f"📦 `{get_readable_file_size(file_size)}`\n"
            f"⏱ সময়: `{elapsed}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        LOGGER.error(f"[QBTDl] Upload error: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# CORE DOWNLOAD PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

async def _run_qbt_download(
    client: Client,
    message: Message,
    torrent_hash: str,
    save_path: str,
    status_msg: Message,
    is_premium: bool,
    source_label: str = "",
):
    user_id  = message.from_user.id
    chat_id  = message.chat.id
    start_ts = time()
    last_edit = time()

    try:
        # ── Wait for hash to appear ───────────────────────────────────────────
        if not torrent_hash:
            for _ in range(15):
                await asyncio.sleep(1)
                resp = await qbt._request("GET", "torrents/info")
                torrents = await resp.json()
                if torrents:
                    torrent_hash = torrents[0]["hash"]
                    break
            else:
                await status_msg.edit_text(
                    "❌ **Torrent যোগ করা সম্ভব হয়নি!**",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

        deadline = time() + MAX_WAIT_SECS

        while time() < deadline:
            if _cancel_flags.get(torrent_hash):
                _cancel_flags.pop(torrent_hash, None)
                await qbt.remove_torrent(torrent_hash)
                try:
                    await status_msg.edit_text(
                        "⛔ **Download বাতিল করা হয়েছে।**",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass
                return

            info = await qbt.get_torrent_info(torrent_hash)
            if not info:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            state    = info.get("state", "")
            size     = info.get("size", 0)
            dl_bytes = info.get("completed", 0)
            speed    = info.get("dlspeed", 0)
            progress = info.get("progress", 0.0)
            eta      = info.get("eta", 0)
            pct      = progress * 100

            # ── Size check ────────────────────────────────────────────────
            max_allowed = MAX_FILE_SIZE if is_premium else FREE_FILE_LIMIT
            if size > max_allowed and size > 0:
                await qbt.remove_torrent(torrent_hash)
                try:
                    await status_msg.edit_text(
                        f"❌ **ফাইল অনেক বড়!**\n\n"
                        f"📦 ফাইল: `{get_readable_file_size(size)}`\n"
                        f"🚫 সীমা: `{get_readable_file_size(max_allowed)}`\n\n"
                        f"{'💎 Premium এ আপগ্রেড করুন: /plans' if not is_premium else ''}",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass
                return

            # ── Progress update ───────────────────────────────────────────
            if time() - last_edit >= PROGRESS_DELAY:
                bar   = _progress_bar(pct)
                state_text = _state_label(state)
                try:
                    await status_msg.edit_text(
                        f"{state_text}\n\n"
                        f"`[{bar}]` {pct:.1f}%\n\n"
                        f"📥 **Downloaded:** `{get_readable_file_size(dl_bytes)}` / `{get_readable_file_size(size)}`\n"
                        f"⚡ **Speed:** `{get_readable_file_size(speed)}/s`\n"
                        f"⏳ **ETA:** `{get_readable_time(eta) if eta and eta < 8640000 else '...'}`\n"
                        f"⏱ **Elapsed:** `{get_readable_time(int(time() - start_ts))}`",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⛔ বাতিল", callback_data=f"qbt_cancel_{torrent_hash}")
                        ]]),
                    )
                    last_edit = time()
                except Exception:
                    pass

            # ── Completion check ──────────────────────────────────────────
            if state in ("uploading", "stalledUP", "forcedUP", "pausedUP", "queuedUP"):
                break
            elif state == "error":
                err = info.get("comment", "Unknown error")
                try:
                    await status_msg.edit_text(
                        f"❌ **Download ব্যর্থ!**\n\n`{err}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass
                await qbt.remove_torrent(torrent_hash)
                return

            await asyncio.sleep(POLL_INTERVAL)

        else:
            await qbt.remove_torrent(torrent_hash)
            try:
                await status_msg.edit_text(
                    "⏰ **Timeout!** Download সম্পন্ন হয়নি।",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            return

        # ── Locate downloaded file(s) ─────────────────────────────────────
        await status_msg.edit_text(
            "✅ **Download সম্পন্ন!**\n\n📤 Upload করা হচ্ছে...",
            parse_mode=ParseMode.MARKDOWN,
        )

        torrent_files = await qbt.get_torrent_files(torrent_hash)
        info          = await qbt.get_torrent_info(torrent_hash)
        actual_save   = info.get("save_path", save_path) if info else save_path

        upload_path = _find_largest_file(actual_save, torrent_files)
        if not upload_path or not os.path.exists(upload_path):
            # Try the whole save_path directory
            all_files = []
            for root, _, files in os.walk(actual_save):
                for f in files:
                    fp = os.path.join(root, f)
                    all_files.append(fp)
            if all_files:
                upload_path = max(all_files, key=os.path.getsize)
            else:
                await status_msg.edit_text(
                    "❌ Downloaded ফাইল খুঁজে পাওয়া যায়নি।",
                    parse_mode=ParseMode.MARKDOWN,
                )
                await qbt.remove_torrent(torrent_hash)
                return

        # ── Thumbnail ─────────────────────────────────────────────────────
        thumbnail_path = None
        try:
            user_data = await user_activity_collection.find_one({"user_id": user_id})
            thumbnail_path = user_data.get("thumbnail_path") if user_data else None
            if thumbnail_path and not os.path.exists(thumbnail_path):
                thumbnail_path = None
        except Exception:
            thumbnail_path = None

        # ── Upload ────────────────────────────────────────────────────────
        file_sz  = os.path.getsize(upload_path)
        name     = os.path.basename(upload_path)
        caption  = (
            f"📄 **{name}**\n"
            f"📦 `{get_readable_file_size(file_sz)}`"
            + (f"\n🔗 `{source_label}`" if source_label else "")
        )

        max_allowed = MAX_FILE_SIZE if is_premium else FREE_FILE_LIMIT
        if file_sz > max_allowed:
            await status_msg.edit_text(
                f"❌ **ফাইল অনেক বড়!**\n\n"
                f"📦 `{get_readable_file_size(file_sz)}` > `{get_readable_file_size(max_allowed)}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            try:
                await _upload_to_telegram(
                    client, chat_id, upload_path, caption,
                    status_msg, start_ts, thumbnail_path
                )
                if LOG_GROUP_ID:
                    try:
                        await log_file_to_group(
                            bot=client, log_group_id=LOG_GROUP_ID,
                            user=message.from_user, url=source_label,
                            file_path=upload_path, media_type="document",
                            caption_original=caption, channel_name=None,
                            thumbnail_path=thumbnail_path,
                        )
                    except Exception as e:
                        LOGGER.warning(f"[QBTDl] Log error: {e}")
            except Exception as upload_err:
                LOGGER.error(f"[QBTDl] Upload failed: {upload_err}")

        # ── Cleanup ───────────────────────────────────────────────────────
        await qbt.remove_torrent(torrent_hash, delete_files=True)

    except Exception as e:
        LOGGER.error(f"[QBTDl] Pipeline error user={user_id}: {e}")
        try:
            await status_msg.edit_text(
                f"❌ **Error:**\n`{str(e)[:300]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        try:
            await qbt.remove_torrent(torrent_hash)
        except Exception:
            pass
    finally:
        _cancel_flags.pop(torrent_hash, None)
        # Cleanup user temp dir
        user_dir = os.path.join(DOWNLOAD_DIR, str(user_id))
        if os.path.isdir(user_dir):
            try:
                shutil.rmtree(user_dir, ignore_errors=True)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND HANDLER SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_qbtdl_handler(app: Client):

    @app.on_message(
        filters.command(["qbt", "qbittorrent"], prefixes=COMMAND_PREFIX)
        & (filters.private | filters.group)
    )
    async def qbt_dl_command(client: Client, message: Message):
        user_id    = message.from_user.id
        is_premium = await _is_premium(user_id)

        torrent_file_path = None
        source_label      = ""

        # ── Determine input ────────────────────────────────────────────────
        # Priority: replied .torrent file → args magnet/URL

        if message.reply_to_message:
            doc = message.reply_to_message.document
            if doc and (
                doc.mime_type == "application/x-bittorrent"
                or (doc.file_name or "").endswith(".torrent")
            ):
                status_msg = await message.reply_text(
                    "⬇️ **.torrent ফাইল download হচ্ছে...**",
                    parse_mode=ParseMode.MARKDOWN,
                )
                torrent_file_path = await message.reply_to_message.download()
                source_label      = doc.file_name or "torrent file"
            else:
                # Reply text might be magnet/URL
                text = (message.reply_to_message.text or "").strip()
                if text:
                    args_text = text
                else:
                    args_text = ""
        else:
            parts = message.text.split(None, 1)
            args_text = parts[1].strip() if len(parts) > 1 else ""

        if not torrent_file_path:
            if not args_text:
                await message.reply_text(
                    "**🌊 qBittorrent Downloader**\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    "**ব্যবহার:**\n"
                    "`/qbt <magnet link>`\n"
                    "`/qbt <torrent URL>`\n"
                    "`.torrent` ফাইলে reply করে `/qbt`\n\n"
                    "**Supported:**\n"
                    "• Magnet links\n"
                    "• Torrent file URLs\n"
                    "• Direct .torrent files",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            source_label = args_text[:80]

        status_msg = await message.reply_text(
            "🔄 **qBittorrent-এ torrent যোগ করা হচ্ছে...**",
            parse_mode=ParseMode.MARKDOWN,
        )

        # ── Set download directory ─────────────────────────────────────────
        user_dir = os.path.join(DOWNLOAD_DIR, str(user_id))
        os.makedirs(user_dir, exist_ok=True)

        try:
            # ── Add to qBittorrent ─────────────────────────────────────────
            if torrent_file_path:
                torrent_hash = await qbt.add_torrent_file(torrent_file_path, user_dir)
                os.remove(torrent_file_path)
            elif args_text.startswith("magnet:"):
                torrent_hash = await qbt.add_magnet(args_text, user_dir)
            else:
                torrent_hash = await qbt.add_torrent_url(args_text, user_dir)

            await status_msg.edit_text(
                f"✅ **Torrent যোগ হয়েছে!**\n\n"
                f"🔑 Hash: `{torrent_hash[:16]}...`\n"
                f"📡 Source: `{source_label[:60]}`\n\n"
                "⏳ শুরু হচ্ছে...",
                parse_mode=ParseMode.MARKDOWN,
            )

            LOGGER.info(f"[QBTDl] User {user_id} added torrent hash={torrent_hash[:12]}")

            asyncio.create_task(
                _run_qbt_download(
                    client, message, torrent_hash, user_dir,
                    status_msg, is_premium, source_label
                )
            )

        except Exception as e:
            LOGGER.error(f"[QBTDl] Failed to add torrent for {user_id}: {e}")
            try:
                await status_msg.edit_text(
                    f"❌ **Torrent যোগ করা যায়নি:**\n\n`{str(e)[:300]}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            if torrent_file_path and os.path.exists(torrent_file_path):
                os.remove(torrent_file_path)

    # ── Cancel callback ────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^qbt_cancel_(.+)$"))
    async def qbt_cancel_callback(client, callback_query):
        torrent_hash = callback_query.data.split("_", 2)[-1]
        user_id      = callback_query.from_user.id
        _cancel_flags[torrent_hash] = True
        try:
            await callback_query.message.edit_text(
                "⛔ **Cancel সংকেত পাঠানো হয়েছে...**",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        await callback_query.answer("বাতিলের অনুরোধ পাঠানো হয়েছে!")

    LOGGER.info("[QBTDl] /qbt command handler registered.")
