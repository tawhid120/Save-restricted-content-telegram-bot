# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/directdl.py  ─  File Hosting Sites Downloader
#
# /ddl <URL>              ─ Download from any supported hosting site
# /ddl <URL>::<password>  ─ Password-protected links
#
# Supported (via utils/direct_links.py):
#   MediaFire (files + folders), GoFile, TeraBox, Pixeldrain, 1Fichier,
#   StreamTape, WeTransfer, SwissTransfer, qiwi.gg, mp4upload,
#   BuzzHeavier, Send.cm, LinkBox, Doodstream family, Racaty,
#   KrakenFiles, Solidfiles, Upload.ee, TmpSend, EasyUpload,
#   StreamVid, StreamHub, pCloud, AkmFiles, Shrdsk, FileLions,
#   StreamWish, HxFile, OneDrive, GitHub Releases, OSDN,
#   Yandex Disk, devuploads, UploadHaven, FuckingFast,
#   Lulacloud, MediaFile, BerkasDrive, Transfer.it  and more.

import os
import asyncio
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from time import time
from datetime import datetime
from urllib.parse import urlparse, unquote

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from pyrogram.handlers import MessageHandler

from config import COMMAND_PREFIX
from utils import LOGGER
from utils.direct_links import generate_direct_link, DirectLinkException, is_supported_site
from utils.helper import get_readable_file_size, get_readable_time, get_video_thumbnail
from core import prem_plan1, prem_plan2, prem_plan3, user_activity_collection

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

DOWNLOAD_DIR    = os.path.join(tempfile.gettempdir(), "directdl_downloads")
MAX_FILE_SIZE   = 2 * 1024 ** 3        # 2 GB  (premium users)
FREE_FILE_LIMIT = 500 * 1024 ** 2      # 500 MB (free users)
PROGRESS_DELAY  = 3                    # seconds between progress message edits
CHUNK_SIZE      = 8 * 1024 * 1024      # 8 MB per read chunk

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Thread pool for running synchronous direct_links.py functions
_THREAD_POOL = ThreadPoolExecutor(max_workers=4)

# ─────────────────────────────────────────────────────────────────────────────
# SUPPORTED SITES DISPLAY TEXT  (for /ddl help message)
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_SITES_TEXT = (
    "**📥 Direct Link File Hosting Downloader**\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "**Usage:**\n"
    "`/ddl <URL>`\n"
    "`/ddl <URL>::<password>`  ← password-protected\n\n"
    "**Supported Sites:**\n"
    "🗂 **Cloud/Storage:** MediaFire · GoFile · TeraBox\n"
    "   OneDrive · pCloud · Yandex Disk\n"
    "💾 **Direct Hosts:** Pixeldrain · KrakenFiles · Solidfiles\n"
    "   Upload.ee · AkmFiles · qiwi.gg\n"
    "📦 **Transfer:** WeTransfer · SwissTransfer · Send.cm\n"
    "   TmpSend · EasyUpload · Transfer.it\n"
    "🎬 **Video Hosts:** Doodstream · StreamTape · StreamHub\n"
    "   StreamVid · StreamWish · FileLions · mp4upload\n"
    "🔧 **Dev/Other:** GitHub Releases · OSDN · HxFile\n"
    "   BuzzHeavier · Shrdsk · LinkBox · Racaty\n"
    "   devuploads · UploadHaven · FuckingFast\n"
    "   Lulacloud · MediaFile · BerkasDrive\n\n"
    "**Examples:**\n"
    "`/ddl https://www.mediafire.com/file/xxx`\n"
    "`/ddl https://gofile.io/d/xxxxx`\n"
    "`/ddl https://1fichier.com/?xxx::mypass`\n"
    "`/ddl https://pixeldrain.com/u/xxxxxxxx`"
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _is_premium(user_id: int) -> bool:
    """Check if user has any active premium plan."""
    now = datetime.utcnow()
    for col in [prem_plan1, prem_plan2, prem_plan3]:
        doc = await col.find_one({"user_id": user_id})
        if doc and doc.get("expiry_date", now) > now:
            return True
    return False


def _progress_bar(pct: float, length: int = 20) -> str:
    """Return a Unicode progress bar string."""
    filled = int(length * pct / 100)
    return "▓" * filled + "░" * (length - filled)


def _parse_headers(raw) -> dict:
    """
    Convert header data from direct_links.py into an aiohttp-compatible dict.

    Accepts:
      • str   → "Cookie: accountToken=xxx" or "User-Agent:Mozilla/5.0"
      • list  → ["Referer: https://...", "Cookie: ..."]
      • dict  → already a valid dict
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)

    items = [raw] if isinstance(raw, str) else list(raw)
    headers = {}
    for item in items:
        item = item.strip()
        if not item or ":" not in item:
            continue
        key, _, value = item.partition(":")
        headers[key.strip()] = value.strip()
    return headers


async def _resolve_link_async(url: str):
    """
    Run the synchronous generate_direct_link() in a thread pool so it
    does not block the event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_THREAD_POOL, generate_direct_link, url)


def _safe_filename(name: str) -> str:
    """Sanitize a filename so it is safe to use on disk."""
    keep = " abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.()"
    return "".join(c if c in keep else "_" for c in name).strip() or "file"


def _guess_filename_from_url(url: str) -> str:
    """Extract a filename from a URL path, URL-decoded."""
    path = urlparse(url).path
    name = unquote(os.path.basename(path))
    return _safe_filename(name) if name else "downloaded_file"


async def _get_user_thumbnail(user_id: int) -> str | None:
    """Return the stored thumbnail path for a user, or None."""
    try:
        doc = await user_activity_collection.find_one({"user_id": user_id})
        if doc:
            tp = doc.get("thumbnail_path")
            if tp and os.path.exists(tp):
                return tp
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD  (aiohttp streaming with live progress)
# ─────────────────────────────────────────────────────────────────────────────

async def _stream_download(
    url: str,
    dest_path: str,
    extra_headers: dict,
    status_msg: Message,
    display_name: str,
    max_size: int,
) -> bool:
    """
    Stream-download *url* to *dest_path* in chunks.
    Edits *status_msg* every PROGRESS_DELAY seconds.
    Returns True on success, False on any failure.
    """
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
            "Gecko/20100101 Firefox/122.0"
        )
    }
    base_headers.update(extra_headers)

    try:
        connector = aiohttp.TCPConnector(ssl=False, limit=10)
        timeout   = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
        ) as session:
            async with session.get(
                url, headers=base_headers, allow_redirects=True
            ) as resp:

                # ── HTTP error check ──────────────────────────────────────────
                if resp.status not in (200, 206):
                    await status_msg.edit_text(
                        f"❌ **Server error:** HTTP `{resp.status}`\n\n"
                        f"URL: `{url[:80]}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return False

                total = int(resp.headers.get("Content-Length", 0))

                # ── Up-front size guard ───────────────────────────────────────
                if total > 0 and total > max_size:
                    await status_msg.edit_text(
                        f"❌ **ফাইল অনেক বড়!**\n\n"
                        f"📦 Size: `{get_readable_file_size(total)}`\n"
                        f"🚫 Limit: `{get_readable_file_size(max_size)}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return False

                downloaded = 0
                start_ts   = time()
                last_edit  = 0.0

                with open(dest_path, "wb") as fh:
                    async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)

                        now = time()
                        if now - last_edit >= PROGRESS_DELAY:
                            elapsed = now - start_ts
                            speed   = downloaded / elapsed if elapsed > 0 else 0
                            eta     = (
                                int((total - downloaded) / speed)
                                if (speed > 0 and total > downloaded)
                                else 0
                            )
                            pct = (downloaded / total * 100) if total > 0 else 0
                            bar = _progress_bar(pct)

                            size_text = (
                                f"`{get_readable_file_size(downloaded)}`"
                                f" / `{get_readable_file_size(total)}`"
                                if total > 0
                                else f"`{get_readable_file_size(downloaded)}`"
                            )
                            try:
                                await status_msg.edit_text(
                                    f"⬇️ **ডাউনলোড হচ্ছে...**\n\n"
                                    f"`[{bar}]`"
                                    + (f" {pct:.1f}%" if total > 0 else "") + "\n\n"
                                    f"📥 **Downloaded:** {size_text}\n"
                                    f"⚡ **Speed:** `{get_readable_file_size(speed)}/s`\n"
                                    f"⏳ **ETA:** `{get_readable_time(eta) if eta else '...'}`\n"
                                    f"⏱ **Elapsed:** `{get_readable_time(int(elapsed))}`\n\n"
                                    f"📄 `{display_name[:60]}`",
                                    parse_mode=ParseMode.MARKDOWN,
                                )
                                last_edit = now
                            except Exception:
                                pass

        return True

    except asyncio.TimeoutError:
        LOGGER.warning(f"[DirectDL] Timeout downloading: {url[:60]}")
        try:
            await status_msg.edit_text(
                "❌ **Download timeout!** আবার চেষ্টা করুন।",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        return False

    except aiohttp.ClientError as e:
        LOGGER.error(f"[DirectDL] Network error for {url[:60]}: {e}")
        try:
            await status_msg.edit_text(
                f"❌ **Network error:**\n`{str(e)[:200]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        return False


# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD  (Pyrogram MTProto with live progress)
# ─────────────────────────────────────────────────────────────────────────────

async def _upload_to_telegram(
    client: Client,
    chat_id: int,
    file_path: str,
    caption: str,
    status_msg: Message,
    start_ts: float,
    thumbnail_path: str | None = None,
) -> None:
    """
    Upload *file_path* to Telegram via MTProto (supports up to 2 GB).
    Shows a live progress bar in *status_msg*.
    """
    file_size = os.path.getsize(file_path)
    ext       = os.path.splitext(file_path)[1].lower()
    last_edit = [0.0]
    up_start  = [time()]

    async def _on_progress(current: int, total: int) -> None:
        now = time()
        if now - last_edit[0] < PROGRESS_DELAY and current < total:
            return
        elapsed = now - up_start[0]
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
                f"⏳ **ETA:** `{get_readable_time(int(eta))}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            last_edit[0] = now
        except Exception:
            pass

    _VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts"}
    _AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac", ".wma"}

    if ext in _VIDEO_EXTS:
        thumb = thumbnail_path
        if not thumb:
            try:
                thumb = await get_video_thumbnail(file_path, None)
            except Exception:
                thumb = None
        await client.send_video(
            chat_id=chat_id,
            video=file_path,
            caption=caption,
            thumb=thumb,
            supports_streaming=True,
            parse_mode=ParseMode.MARKDOWN,
            progress=_on_progress,
        )
        # Remove auto-generated thumbnail (not user's custom one)
        if thumb and thumb != thumbnail_path and os.path.exists(thumb):
            os.remove(thumb)

    elif ext in _AUDIO_EXTS:
        await client.send_audio(
            chat_id=chat_id,
            audio=file_path,
            caption=caption,
            thumb=thumbnail_path,
            parse_mode=ParseMode.MARKDOWN,
            progress=_on_progress,
        )

    else:
        await client.send_document(
            chat_id=chat_id,
            document=file_path,
            caption=caption,
            thumb=thumbnail_path,
            parse_mode=ParseMode.MARKDOWN,
            progress=_on_progress,
        )

    elapsed = get_readable_time(int(time() - start_ts))
    await status_msg.edit_text(
        f"✅ **সফলভাবে পাঠানো হয়েছে!**\n\n"
        f"📦 `{get_readable_file_size(file_size)}` | ⏱ `{elapsed}`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE-FILE PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

async def _download_single(
    client: Client,
    message: Message,
    direct_url: str,
    extra_headers: dict,
    status_msg: Message,
    user_dir: str,
    max_size: int,
    start_ts: float,
    original_url: str,
    thumbnail_path: str | None,
) -> None:
    """Download one file and send it to Telegram."""
    chat_id   = message.chat.id
    file_name = _guess_filename_from_url(direct_url)
    dest_path = os.path.join(user_dir, file_name)

    await status_msg.edit_text(
        f"⬇️ **Download শুরু হচ্ছে...**\n\n"
        f"📄 `{file_name[:60]}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    ok = await _stream_download(
        direct_url, dest_path, extra_headers,
        status_msg, file_name, max_size,
    )
    if not ok:
        return

    if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
        await status_msg.edit_text(
            "❌ **Downloaded ফাইল পাওয়া যায়নি বা file empty।**",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    file_sz = os.path.getsize(dest_path)
    await status_msg.edit_text(
        f"✅ **Download সম্পন্ন!** Upload হচ্ছে...\n\n"
        f"📄 `{file_name[:60]}`\n"
        f"📦 `{get_readable_file_size(file_sz)}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    caption = (
        f"📄 **{file_name[:80]}**\n"
        f"📦 `{get_readable_file_size(file_sz)}`\n"
        f"🔗 `{original_url[:60]}`"
    )
    await _upload_to_telegram(
        client, chat_id, dest_path,
        caption, status_msg, start_ts, thumbnail_path,
    )


# ─────────────────────────────────────────────────────────────────────────────
# FOLDER / MULTI-FILE PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

async def _download_folder(
    client: Client,
    message: Message,
    details: dict,
    status_msg: Message,
    user_dir: str,
    max_size: int,
    start_ts: float,
    thumbnail_path: str | None,
) -> None:
    """
    Download every file in a folder result dict and upload each to Telegram.

    details = {
        "title":       str,
        "total_size":  int,
        "contents":    [{"filename": str, "path": str, "url": str}, ...],
        "header":      str | list | None,   (optional shared headers)
    }
    """
    chat_id  = message.chat.id
    title    = details.get("title", "Folder") or "Folder"
    contents = details.get("contents") or []
    total_sz = int(details.get("total_size") or 0)
    raw_hdr  = details.get("header")

    extra_headers = _parse_headers(raw_hdr)

    if not contents:
        await status_msg.edit_text(
            "❌ **Folder empty — কোনো file নেই।**",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Total size guard
    if total_sz > 0 and total_sz > max_size:
        await status_msg.edit_text(
            f"❌ **Folder অনেক বড়!**\n\n"
            f"📦 `{get_readable_file_size(total_sz)}` > `{get_readable_file_size(max_size)}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await status_msg.edit_text(
        f"📁 **{title[:60]}**\n\n"
        f"📊 Files: `{len(contents)}`\n"
        f"📦 Total: `{get_readable_file_size(total_sz) if total_sz else 'অজানা'}`\n\n"
        "⬇️ Download শুরু হচ্ছে...",
        parse_mode=ParseMode.MARKDOWN,
    )

    success = 0
    failed  = 0

    for idx, item in enumerate(contents, start=1):
        item_url  = (item.get("url") or "").strip()
        item_name = _safe_filename(item.get("filename") or f"file_{idx}")
        item_sub  = item.get("path") or ""

        if not item_url:
            LOGGER.warning(f"[DirectDL] Folder item {idx} has no URL, skipping.")
            failed += 1
            continue

        # Build destination preserving sub-folder structure
        local_folder = os.path.join(user_dir, item_sub) if item_sub else user_dir
        os.makedirs(local_folder, exist_ok=True)
        dest = os.path.join(local_folder, item_name)

        await status_msg.edit_text(
            f"📁 **{title[:50]}**\n"
            f"📊 `{idx} / {len(contents)}`\n\n"
            f"📄 `{item_name[:60]}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        ok = await _stream_download(
            item_url, dest, extra_headers,
            status_msg, item_name, max_size,
        )

        if not ok or not os.path.exists(dest) or os.path.getsize(dest) == 0:
            failed += 1
            await message.reply_text(
                f"⚠️ **Skipped:** `{item_name}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            if os.path.exists(dest):
                os.remove(dest)
            continue

        file_sz = os.path.getsize(dest)
        caption = (
            f"📄 **{item_name[:80]}**\n"
            f"📦 `{get_readable_file_size(file_sz)}`\n"
            f"📁 `{title[:50]}`"
            + (f" › `{item_sub[:40]}`" if item_sub else "")
        )

        try:
            await status_msg.edit_text(
                f"📤 **Uploading {idx}/{len(contents)}...**\n\n"
                f"📄 `{item_name[:60]}`\n"
                f"📦 `{get_readable_file_size(file_sz)}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            await _upload_to_telegram(
                client, chat_id, dest,
                caption, status_msg, start_ts, thumbnail_path,
            )
            success += 1

        except Exception as exc:
            LOGGER.error(f"[DirectDL] Upload failed for '{item_name}': {exc}")
            failed += 1
            await message.reply_text(
                f"⚠️ **Upload failed:** `{item_name}`\n`{str(exc)[:100]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        finally:
            if os.path.exists(dest):
                os.remove(dest)

    # Final summary
    elapsed = get_readable_time(int(time() - start_ts))
    icon    = "✅" if failed == 0 else ("⚠️" if success > 0 else "❌")
    await status_msg.edit_text(
        f"{icon} **সম্পন্ন!**\n\n"
        f"📁 `{title[:60]}`\n"
        f"✅ Sent: `{success}`\n"
        f"❌ Failed: `{failed}`\n"
        f"⏱ Time: `{elapsed}`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE  (resolve → route → download → upload → cleanup)
# ─────────────────────────────────────────────────────────────────────────────

async def _process_ddl(
    client: Client,
    message: Message,
    url: str,
    status_msg: Message,
) -> None:
    """
    Complete pipeline for one /ddl request:
      1. Resolve indirect link via direct_links.py
      2. Determine if result is single file or folder
      3. Download + upload accordingly
      4. Clean up temp directory
    """
    user_id    = message.from_user.id
    is_premium = await _is_premium(user_id)
    max_size   = MAX_FILE_SIZE if is_premium else FREE_FILE_LIMIT
    start_ts   = time()

    user_dir = os.path.join(DOWNLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)

    thumbnail_path = await _get_user_thumbnail(user_id)
    original_url   = url

    try:
        # ── Step 1: Resolve the link ──────────────────────────────────────────
        await status_msg.edit_text(
            f"🔍 **Link resolve করা হচ্ছে...**\n\n"
            f"🔗 `{url[:80]}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            result = await _resolve_link_async(url)
        except DirectLinkException as exc:
            await status_msg.edit_text(
                f"❌ **Link resolve ব্যর্থ!**\n\n`{str(exc)[:400]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        except Exception as exc:
            LOGGER.error(f"[DirectDL] Unexpected resolve error for user={user_id}: {exc}")
            await status_msg.edit_text(
                f"❌ **Unexpected error while resolving:**\n`{str(exc)[:300]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── Step 2: Unpack tuple response (url + headers) ────────────────────
        extra_headers: dict = {}

        if isinstance(result, tuple) and len(result) == 2:
            direct_url, raw_header = result
            extra_headers          = _parse_headers(raw_header)
            result                 = direct_url

        # ── Step 3: Route to single-file or folder handler ───────────────────
        if isinstance(result, dict):
            # Folder / multi-file result (GoFile, TeraBox folder, MediaFire folder …)
            await _download_folder(
                client, message, result, status_msg,
                user_dir, max_size, start_ts, thumbnail_path,
            )
            return

        if not isinstance(result, str) or not result.startswith("http"):
            await status_msg.edit_text(
                "❌ **Valid direct link পাওয়া যায়নি।**\n\n"
                "Link টি সঠিক কিনা যাচাই করুন।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Single direct URL
        await _download_single(
            client, message, result, extra_headers,
            status_msg, user_dir, max_size,
            start_ts, original_url, thumbnail_path,
        )

    except Exception as exc:
        LOGGER.error(f"[DirectDL] Pipeline error user={user_id}: {exc}")
        try:
            await status_msg.edit_text(
                f"❌ **Unexpected error:**\n`{str(exc)[:300]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    finally:
        # Always clean up the user's temp directory
        try:
            shutil.rmtree(user_dir, ignore_errors=True)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND HANDLER SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_directdl_handler(app: Client) -> None:
    """Register /ddl and /directdl command handlers with the Pyrogram app."""

    @app.on_message(
        filters.command(["ddl", "directdl"], prefixes=COMMAND_PREFIX)
        & (filters.private | filters.group)
    )
    async def ddl_command(client: Client, message: Message) -> None:
        """
        /ddl <URL>
        /ddl <URL>::<password>   ← for password-protected file hosting links

        Resolves indirect links from 40+ hosting sites and downloads the
        file(s) directly to the chat via Pyrogram MTProto (up to 2 GB).
        """
        # ── Parse the URL argument ────────────────────────────────────────────
        url = ""

        if len(message.command) > 1:
            # Everything after the command prefix is the URL (may include ::password)
            url = " ".join(message.command[1:]).strip()

        elif message.reply_to_message:
            # Allow replying to a message that contains only the URL
            replied_text = (message.reply_to_message.text or "").strip()
            if replied_text:
                url = replied_text.split()[0]

        # Show help if no URL was provided
        if not url:
            await message.reply_text(
                SUPPORTED_SITES_TEXT,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            return

        # ── Validate: is the site supported? ─────────────────────────────────
        # Strip password part before checking domain
        url_for_check = url.split("::")[0].strip()

        if not is_supported_site(url_for_check):
            await message.reply_text(
                "⚠️ **এই site টি supported নয়।**\n\n"
                "সমস্ত supported site দেখতে শুধু `/ddl` লিখুন।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── Basic URL sanity check ────────────────────────────────────────────
        if not url_for_check.startswith(("http://", "https://")):
            await message.reply_text(
                "❌ **Invalid URL!** `http://` বা `https://` দিয়ে শুরু হওয়া URL দিন।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        LOGGER.info(
            f"[DirectDL] User {message.from_user.id} → {url_for_check[:80]}"
        )

        # ── Send initial status message and start the pipeline ────────────────
        status_msg = await message.reply_text(
            "🔄 **Processing...**",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Run as a background task so the handler returns immediately
        asyncio.create_task(
            _process_ddl(client, message, url, status_msg)
        )

    LOGGER.info("[DirectDL] /ddl and /directdl command handlers registered.")
