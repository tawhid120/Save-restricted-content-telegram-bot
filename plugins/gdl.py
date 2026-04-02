# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/gdl.py — Google Drive Downloader
#
# ✅ তিনটা পদ্ধতিতে কাজ করে:
#    1. /gdl <url>          — সরাসরি URL দিয়ে
#    2. /gdl               — বট লিংক চাইবে, তারপর কাজ করবে
#    3. reply + /gdl       — forwarded/copied মেসেজে reply করে
#
# ❌ Command ছাড়া auto-detect সম্পূর্ণ বন্ধ
# ✅ NO user account / phone number required — BOT_TOKEN only
# ✅ Uses Pyrofork MTProto directly → up to 2 GB upload
# ✅ Downloads the file to disk from Google Drive, then uploads via MTProto
# ✅ Supports single files AND full folders (recursive)
# ✅ Real-time progress bar for both download and upload phases
# ✅ Cleans up temp files after every operation
# ✅ SMART UPLOAD — photo/video/audio/animation/document based on MIME type
# ✅ Fallback to document if specific media upload fails

import os
import re
import io
import json
import asyncio
import subprocess
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode, MessageEntityType

from config import COMMAND_PREFIX
from utils import LOGGER

# ── Google API (service-account auth) ────────────────────────────────────────
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2 import service_account
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False
    LOGGER.warning(
        "[GDL] google-api-python-client not installed — /gdl disabled."
    )

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_ACCOUNT_FILE  = "service_account_key.json"   # project root এ রাখুন
DOWNLOAD_DIR          = "gdl_downloads"               # temp directory
MAX_FILE_SIZE_BYTES   = 2 * 1024 * 1024 * 1024        # 2 GB hard limit
PROGRESS_UPDATE_SEC   = 3                              # সেকেন্ডে progress update
WAIT_FOR_URL_TIMEOUT  = 60                             # URL এর জন্য অপেক্ষা (সেকেন্ড)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# PENDING USERS TRACKER
# যারা /gdl দিয়েছে কিন্তু URL দেয়নি তাদের track করা হয়
# Format: { (chat_id, user_id): status_message }
# ─────────────────────────────────────────────────────────────────────────────

_pending_url_requests: dict[tuple[int, int], Message] = {}

# ─────────────────────────────────────────────────────────────────────────────
# MEDIA TYPE CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

PHOTO_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp",
}
PHOTO_MIMES = {
    "image/jpeg", "image/png", "image/bmp", "image/webp",
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".m4v", ".3gp", ".ts", ".mpg", ".mpeg", ".vob",
}

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a",
    ".wma", ".opus", ".amr",
}

ANIMATION_EXTENSIONS = {".gif"}
ANIMATION_MIMES      = {"image/gif"}

# Telegram ফটো পাঠাতে সর্বোচ্চ 10 MB
PHOTO_SIZE_LIMIT = 10 * 1024 * 1024

# ─────────────────────────────────────────────────────────────────────────────
# DRIVE URL REGEX
# ─────────────────────────────────────────────────────────────────────────────

_DRIVE_URL_RE = re.compile(
    r"https?://(?:drive|docs)\.google\.com/\S+",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# DRIVE ID + FOLDER DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _extract_drive_id(url: str) -> str | None:
    """
    যেকোনো Google Drive / Docs URL থেকে file/folder ID বের করে।

    Supported formats:
    • https://drive.google.com/file/d/<ID>/view
    • https://drive.google.com/folders/<ID>
    • https://drive.google.com/drive/folders/<ID>
    • https://drive.google.com/drive/u/0/folders/<ID>
    • https://drive.google.com/open?id=<ID>
    • https://docs.google.com/document/d/<ID>/edit
    """
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]{10,})",         # single file
        r"/folders/([a-zA-Z0-9_-]{10,})",          # folder (সব variant)
        r"[?&]id=([a-zA-Z0-9_-]{10,})",            # query param
        r"/open\?id=([a-zA-Z0-9_-]{10,})",         # open link
        r"/d/([a-zA-Z0-9_-]{10,})",                # generic docs
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _is_folder_url(url: str) -> bool:
    """URL টি folder এর কিনা বের করে।"""
    return bool(re.search(r"/folders/", url, re.IGNORECASE))


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _readable_size(size: float) -> str:
    """Bytes কে readable format এ convert করে।"""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def _readable_time(seconds: float) -> str:
    """Seconds কে readable format এ convert করে।"""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m {secs}s"


def _progress_bar(pct: float, length: int = 20) -> str:
    """Progress bar তৈরি করে।"""
    filled = int(length * pct / 100)
    return "▓" * filled + "░" * (length - filled)


def _clean_url(url: str) -> str:
    """URL এর শেষে থাকা অদরকারী punctuation সরায়।"""
    return re.sub(r"[)>\].,;!?\"']+$", "", url.strip())


# ─────────────────────────────────────────────────────────────────────────────
# DRIVE URL EXTRACTOR (from message entities + regex)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_all_drive_urls(message: Message) -> list[str]:
    """
    একটি মেসেজ থেকে সব Google Drive URL বের করে।

    তিনটা পদ্ধতিতে check করে:
    1. TEXT_LINK entity  — hyperlinked text (যেমন: "Tawhid" → drive url)
    2. URL entity        — plain URL যা Telegram auto-detect করেছে
    3. Regex fallback    — বাকি সব

    ⚠️  এই function শুধু /gdl command এর ভেতরে ব্যবহার হবে।
        Auto-detect এর জন্য একদম আলাদা কোনো handler নেই।
    """
    seen: set[str] = set()
    urls: list[str] = []

    def _add(url: str) -> None:
        url = _clean_url(url)
        if not url:
            return
        if url in seen:
            return
        # শুধু Drive/Docs URL নেব
        if "drive.google.com" in url or "docs.google.com" in url:
            seen.add(url)
            urls.append(url)
            LOGGER.debug(f"[GDL] URL found: {url}")

    # message এর text + caption উভয় থেকে entities নাও
    entities = []
    if message.entities:
        entities.extend(message.entities)
    if message.caption_entities:
        entities.extend(message.caption_entities)

    text = message.text or message.caption or ""

    # ── 1. TEXT_LINK entity (সর্বোচ্চ priority) ─────────────────────────
    for entity in entities:
        if entity.type == MessageEntityType.TEXT_LINK and entity.url:
            _add(entity.url)

    # ── 2. URL entity ────────────────────────────────────────────────────
    for entity in entities:
        if entity.type == MessageEntityType.URL:
            chunk = text[entity.offset: entity.offset + entity.length]
            _add(chunk)

    # ── 3. Regex fallback ────────────────────────────────────────────────
    for match in _DRIVE_URL_RE.finditer(text):
        _add(match.group(0))

    return urls


# ─────────────────────────────────────────────────────────────────────────────
# MEDIA TYPE DETECTION + METADATA
# ─────────────────────────────────────────────────────────────────────────────

def _detect_media_type(file_path: str, mime_type: str = "") -> str:
    """
    file এর type detect করে: photo, video, audio, animation, document
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in ANIMATION_EXTENSIONS or mime_type in ANIMATION_MIMES:
        return "animation"

    if ext in PHOTO_EXTENSIONS or mime_type in PHOTO_MIMES:
        try:
            if os.path.getsize(file_path) <= PHOTO_SIZE_LIMIT:
                return "photo"
        except OSError:
            pass
        return "document"

    if ext in VIDEO_EXTENSIONS or mime_type.startswith("video/"):
        return "video"

    if ext in AUDIO_EXTENSIONS or mime_type.startswith("audio/"):
        return "audio"

    return "document"


def _get_video_metadata(file_path: str) -> dict:
    """ffprobe দিয়ে video metadata বের করে।"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", file_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        data     = json.loads(result.stdout)
        duration = int(float(data.get("format", {}).get("duration", 0)))
        width = height = 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width  = int(stream.get("width", 0))
                height = int(stream.get("height", 0))
                if not duration:
                    duration = int(float(stream.get("duration", 0)))
                break
        return {"duration": duration, "width": width, "height": height}
    except Exception:
        return {"duration": 0, "width": 0, "height": 0}


def _get_audio_duration(file_path: str) -> int:
    """ffprobe দিয়ে audio duration বের করে।"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", file_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return int(float(data.get("format", {}).get("duration", 0)))
    except Exception:
        return 0


def _generate_thumbnail(file_path: str) -> str | None:
    """ffmpeg দিয়ে video thumbnail তৈরি করে।"""
    thumb = file_path + "_thumb.jpg"
    try:
        subprocess.run(
            [
                "ffmpeg", "-i", file_path, "-ss", "00:00:01",
                "-vframes", "1", "-vf", "scale=320:-1", "-y", thumb,
            ],
            capture_output=True, timeout=30,
        )
        if os.path.exists(thumb) and os.path.getsize(thumb) > 0:
            return thumb
    except Exception:
        pass
    try:
        if os.path.exists(thumb):
            os.remove(thumb)
    except OSError:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE DRIVE UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _build_drive_service():
    """Service account দিয়ে Google Drive authenticate করে।"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f"Service account key পাওয়া যায়নি: {SERVICE_ACCOUNT_FILE}\n"
            "Google service account JSON টি project root এ রাখুন।"
        )
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds)


def _get_file_metadata(service, file_id: str) -> dict:
    """Drive file এর metadata নিয়ে আসে।"""
    return service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size",
        supportsAllDrives=True,
    ).execute()


def _list_folder_recursive(
    service, folder_id: str, parent_path: str = "",
) -> list[dict]:
    """Drive folder এর সব file recursively list করে।"""
    results: list[dict] = []
    query      = f"'{folder_id}' in parents and trashed=false"
    page_token = None

    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType, size)",
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        for item in response.get("files", []):
            current_path = (
                os.path.join(parent_path, item["name"])
                if parent_path else item["name"]
            )
            if item.get("mimeType") == "application/vnd.google-apps.folder":
                results.extend(
                    _list_folder_recursive(service, item["id"], current_path)
                )
            else:
                item["relative_path"] = current_path
                results.append(item)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return results


def _is_google_doc(mime_type: str) -> tuple[bool, str, str]:
    """
    Google Workspace file কিনা check করে।
    Returns: (is_google_doc, export_mime, extension)
    """
    export_map = {
        "application/vnd.google-apps.document": (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document",
            ".docx",
        ),
        "application/vnd.google-apps.spreadsheet": (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet",
            ".xlsx",
        ),
        "application/vnd.google-apps.presentation": (
            "application/vnd.openxmlformats-officedocument"
            ".presentationml.presentation",
            ".pptx",
        ),
        "application/vnd.google-apps.drawing": ("image/png", ".png"),
    }
    if mime_type in export_map:
        export_mime, ext = export_map[mime_type]
        return True, export_mime, ext
    return False, "", ""


# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD A SINGLE FILE FROM DRIVE → DISK
# ─────────────────────────────────────────────────────────────────────────────

async def _download_drive_file(
    service,
    file_id: str,
    file_name: str,
    mime_type: str,
    local_path: str,
    status_msg: Message,
) -> tuple[str, str]:
    """
    Drive থেকে একটি file download করে local disk এ সেভ করে।
    Returns: (final_local_path, effective_mime_type)
    """
    is_doc, export_mime, ext = _is_google_doc(mime_type)
    effective_mime = mime_type

    if is_doc:
        # Google Docs export করতে হবে
        if not file_name.endswith(ext):
            file_name += ext
        local_path     = os.path.splitext(local_path)[0] + ext
        request        = service.files().export_media(
            fileId=file_id, mimeType=export_mime,
        )
        effective_mime = export_mime
    else:
        # সাধারণ file সরাসরি download
        request = service.files().get_media(
            fileId=file_id, supportsAllDrives=True,
        )

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    downloader = MediaIoBaseDownload(
        io.FileIO(local_path, "wb"), request, chunksize=8 * 1024 * 1024,
    )

    start_ts  = time()
    last_edit = 0.0
    done      = False

    while not done:
        status, done = await asyncio.get_event_loop().run_in_executor(
            None, downloader.next_chunk,
        )
        pct = status.progress() * 100
        now = time()

        if now - last_edit >= PROGRESS_UPDATE_SEC or done:
            elapsed    = now - start_ts
            downloaded = status.resumable_progress
            speed      = downloaded / elapsed if elapsed > 0 else 0

            try:
                await status_msg.edit_text(
                    f"📥 **Google Drive থেকে Downloading…**\n\n"
                    f"`[{_progress_bar(pct)}]` {pct:.1f}%\n\n"
                    f"📦 **Downloaded:** `{_readable_size(downloaded)}`\n"
                    f"⚡ **Speed:** `{_readable_size(speed)}/s`\n"
                    f"⏱ **Elapsed:** `{_readable_time(elapsed)}`\n\n"
                    f"📄 `{file_name}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                last_edit = now
            except Exception:
                pass

    return local_path, effective_mime


# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD A LOCAL FILE → TELEGRAM  (SMART — media-type aware)
# ─────────────────────────────────────────────────────────────────────────────

async def _upload_to_telegram(
    client: Client,
    chat_id: int,
    local_path: str,
    file_name: str,
    caption: str,
    status_msg: Message,
    mime_type: str = "",
) -> bool:
    """
    Local file টি Telegram এ upload করে।
    Media type অনুযায়ী সঠিক method ব্যবহার করে।
    ব্যর্থ হলে document হিসেবে fallback করে।
    """
    media_type = _detect_media_type(local_path, mime_type)
    start_ts   = [time()]
    last_edit  = [0.0]

    LOGGER.info(
        f"[GDL] Uploading '{file_name}' as {media_type} "
        f"(mime={mime_type}, ext={os.path.splitext(file_name)[1]})"
    )

    # ── Progress callback ────────────────────────────────────────────────
    async def _progress(current: int, total: int):
        now = time()
        if now - last_edit[0] < PROGRESS_UPDATE_SEC and current < total:
            return
        elapsed = now - start_ts[0]
        speed   = current / elapsed if elapsed > 0 else 0
        eta     = (total - current) / speed if speed > 0 else 0
        pct     = (current / total * 100) if total > 0 else 0
        try:
            await status_msg.edit_text(
                f"📤 **Telegram এ Uploading…** `[{media_type}]`\n\n"
                f"`[{_progress_bar(pct)}]` {pct:.1f}%\n\n"
                f"📦 `{_readable_size(current)}` / "
                f"`{_readable_size(total)}`\n"
                f"⚡ `{_readable_size(speed)}/s`  "
                f"⏳ ETA `{_readable_time(eta)}`\n\n"
                f"📄 `{file_name}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            last_edit[0] = now
        except Exception:
            pass

    thumb_path = None

    # ── Send helper ──────────────────────────────────────────────────────
    async def _send(mtype: str) -> None:
        nonlocal thumb_path

        if mtype == "photo":
            await client.send_photo(
                chat_id=chat_id,
                photo=local_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )

        elif mtype == "video":
            vmeta      = _get_video_metadata(local_path)
            thumb_path = _generate_thumbnail(local_path)
            kwargs = dict(
                chat_id=chat_id,
                video=local_path,
                caption=caption,
                file_name=file_name,
                supports_streaming=True,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )
            if vmeta["duration"]:
                kwargs["duration"] = vmeta["duration"]
            if vmeta["width"]:
                kwargs["width"] = vmeta["width"]
            if vmeta["height"]:
                kwargs["height"] = vmeta["height"]
            if thumb_path:
                kwargs["thumb"] = thumb_path
            await client.send_video(**kwargs)

        elif mtype == "audio":
            dur = _get_audio_duration(local_path)
            kwargs = dict(
                chat_id=chat_id,
                audio=local_path,
                caption=caption,
                file_name=file_name,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )
            if dur:
                kwargs["duration"] = dur
            await client.send_audio(**kwargs)

        elif mtype == "animation":
            await client.send_animation(
                chat_id=chat_id,
                animation=local_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )

        else:
            # Default: document
            await client.send_document(
                chat_id=chat_id,
                document=local_path,
                file_name=file_name,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )

    # ── Try specific type → fallback to document ─────────────────────────
    try:
        await _send(media_type)
        return True

    except Exception as e:
        LOGGER.warning(
            f"[GDL] Upload as '{media_type}' failed for '{file_name}': {e}"
        )
        if media_type != "document":
            try:
                LOGGER.info(
                    f"[GDL] Falling back to 'document' for '{file_name}'"
                )
                start_ts[0]  = time()
                last_edit[0] = 0.0
                await _send("document")
                return True
            except Exception as e2:
                LOGGER.error(f"[GDL] Fallback upload also failed: {e2}")
        return False

    finally:
        if thumb_path and os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except OSError:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# CORE PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

async def _process_gdl(client: Client, message: Message, url: str):
    """
    সম্পূর্ণ pipeline:
    validate → metadata → download → upload → cleanup
    """
    user_id = (
        message.from_user.id if message.from_user
        else message.sender_chat.id if message.sender_chat
        else message.chat.id
    )
    chat_id = message.chat.id

    # ── Google API available? ─────────────────────────────────────────────
    if not GDRIVE_AVAILABLE:
        await message.reply_text(
            "❌ **Google Drive support উপলব্ধ নেই।**\n\n"
            "প্রয়োজনীয় package install করুন:\n"
            "`pip install google-api-python-client google-auth-oauthlib`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    is_folder = _is_folder_url(url)

    # ── Drive ID বের করো ─────────────────────────────────────────────────
    file_id = _extract_drive_id(url)
    if not file_id:
        LOGGER.error(f"[GDL] ID extract করা গেল না URL থেকে: {url}")
        await message.reply_text(
            "❌ **Google Drive ID বের করা যায়নি।**\n\n"
            "Supported formats:\n"
            "• `https://drive.google.com/file/d/<ID>/view`\n"
            "• `https://drive.google.com/folders/<ID>`\n"
            "• `https://drive.google.com/drive/folders/<ID>`\n"
            "• `https://drive.google.com/open?id=<ID>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    LOGGER.info(
        f"[GDL] Resolved — ID: {file_id} | "
        f"Type: {'folder' if is_folder else 'file'} | URL: {url}"
    )

    # ── Drive service তৈরি করো ───────────────────────────────────────────
    try:
        service = await asyncio.get_event_loop().run_in_executor(
            None, _build_drive_service,
        )
    except FileNotFoundError as e:
        await message.reply_text(
            f"❌ **Service account key পাওয়া যায়নি!**\n\n`{e}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    except Exception as e:
        await message.reply_text(
            f"❌ **Google Drive authenticate করা যায়নি।**\n\n`{e}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = await message.reply_text(
        "🔍 **Google Drive থেকে file info নিয়ে আসা হচ্ছে…**",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        if is_folder:
            # ── FOLDER MODE ───────────────────────────────────────────────
            folder_meta = await asyncio.get_event_loop().run_in_executor(
                None, _get_file_metadata, service, file_id,
            )
            folder_name = folder_meta.get("name", "Untitled Folder")

            await status_msg.edit_text(
                f"📁 **Folder scan করা হচ্ছে:** `{folder_name}`\n"
                "অপেক্ষা করুন…",
                parse_mode=ParseMode.MARKDOWN,
            )

            files = await asyncio.get_event_loop().run_in_executor(
                None, _list_folder_recursive, service, file_id, folder_name,
            )

            if not files:
                await status_msg.edit_text(
                    f"🤷 **Folder `{folder_name}` খালি।**",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            total_size = sum(int(f.get("size", 0)) for f in files)
            if total_size > MAX_FILE_SIZE_BYTES:
                await status_msg.edit_text(
                    f"❌ **Folder অনেক বড়, পাঠানো সম্ভব নয়।**\n\n"
                    f"Total size: `{_readable_size(total_size)}`\n"
                    f"Limit: `{_readable_size(MAX_FILE_SIZE_BYTES)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            await status_msg.edit_text(
                f"📁 **Folder:** `{folder_name}`\n"
                f"📊 **Files:** `{len(files)}`\n"
                f"📦 **Total size:** `{_readable_size(total_size)}`\n\n"
                "Download শুরু হচ্ছে…",
                parse_mode=ParseMode.MARKDOWN,
            )

            success_count = 0
            fail_count    = 0

            for idx, item in enumerate(files, 1):
                item_name     = item["name"]
                item_id       = item["id"]
                item_mime     = item.get("mimeType", "")
                item_size     = int(item.get("size", 0))
                relative_path = item.get("relative_path", item_name)
                local_path    = os.path.join(
                    DOWNLOAD_DIR, str(user_id), relative_path,
                )

                await status_msg.edit_text(
                    f"📁 **{folder_name}**\n"
                    f"📊 Progress: `{idx}/{len(files)}`\n"
                    f"📄 Current: `{item_name}`\n"
                    f"📦 Size: `{_readable_size(item_size)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

                try:
                    local_path, eff_mime = await _download_drive_file(
                        service, item_id, item_name,
                        item_mime, local_path, status_msg,
                    )

                    caption = (
                        f"📄 **{os.path.basename(local_path)}**\n"
                        f"📁 Path: `{relative_path}`\n"
                        f"📦 Size: `{_readable_size(os.path.getsize(local_path))}`\n"
                        f"🔗 [Google Drive]({url})\n\n"
                        f"_Downloaded by @juktijol Bot_"
                    )

                    ok = await _upload_to_telegram(
                        client, chat_id, local_path,
                        os.path.basename(local_path), caption,
                        status_msg, mime_type=eff_mime,
                    )
                    if ok:
                        success_count += 1
                    else:
                        fail_count += 1

                except Exception as item_err:
                    LOGGER.error(
                        f"[GDL] '{item_name}' process করতে ব্যর্থ: {item_err}"
                    )
                    fail_count += 1
                    await message.reply_text(
                        f"⚠️ **Skip করা হয়েছে:** `{item_name}`\n"
                        f"`{str(item_err)[:150]}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                finally:
                    if os.path.exists(local_path):
                        try:
                            os.remove(local_path)
                        except OSError:
                            pass

            await status_msg.edit_text(
                f"✅ **Folder download সম্পন্ন!**\n\n"
                f"📁 `{folder_name}`\n"
                f"✅ সফল: `{success_count}`\n"
                f"❌ ব্যর্থ: `{fail_count}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        else:
            # ── SINGLE FILE MODE ──────────────────────────────────────────
            meta      = await asyncio.get_event_loop().run_in_executor(
                None, _get_file_metadata, service, file_id,
            )
            file_name = meta.get("name", "downloaded_file")
            mime_type = meta.get("mimeType", "application/octet-stream")
            file_size = int(meta.get("size", 0))

            is_doc, _, _ = _is_google_doc(mime_type)
            if not is_doc and file_size > MAX_FILE_SIZE_BYTES:
                await status_msg.edit_text(
                    f"❌ **File অনেক বড়, Telegram এ পাঠানো সম্ভব নয়।**\n\n"
                    f"Size: `{_readable_size(file_size)}`\n"
                    f"Limit: `{_readable_size(MAX_FILE_SIZE_BYTES)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            await status_msg.edit_text(
                f"📄 **{file_name}**\n"
                f"📦 Size: `{_readable_size(file_size)}`\n\n"
                "Google Drive থেকে downloading…",
                parse_mode=ParseMode.MARKDOWN,
            )

            local_path = os.path.join(
                DOWNLOAD_DIR, str(user_id), file_name,
            )
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            try:
                local_path, eff_mime = await _download_drive_file(
                    service, file_id, file_name,
                    mime_type, local_path, status_msg,
                )

                actual_size = os.path.getsize(local_path)

                if actual_size > MAX_FILE_SIZE_BYTES:
                    await status_msg.edit_text(
                        f"❌ **Export করা file অনেক বড়:** "
                        f"`{_readable_size(actual_size)}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return

                caption = (
                    f"📄 **{os.path.basename(local_path)}**\n"
                    f"📦 Size: `{_readable_size(actual_size)}`\n"
                    f"🔗 [Google Drive]({url})\n\n"
                    f"_Downloaded by @juktijol Bot_"
                )

                ok = await _upload_to_telegram(
                    client, chat_id, local_path,
                    os.path.basename(local_path), caption,
                    status_msg, mime_type=eff_mime,
                )

                detected = _detect_media_type(local_path, eff_mime)

                if ok:
                    await status_msg.edit_text(
                        f"✅ **সম্পন্ন!** `{os.path.basename(local_path)}`\n"
                        f"📦 `{_readable_size(actual_size)}` — "
                        f"sent as **{detected}**",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await status_msg.edit_text(
                        "❌ **Telegram এ upload ব্যর্থ।** আবার চেষ্টা করুন।",
                        parse_mode=ParseMode.MARKDOWN,
                    )

            finally:
                if os.path.exists(local_path):
                    try:
                        os.remove(local_path)
                    except OSError:
                        pass

    except Exception as e:
        LOGGER.error(f"[GDL] Unhandled error: {e}")
        try:
            await status_msg.edit_text(
                f"❌ **Error হয়েছে:**\n`{str(e)[:300]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# USAGE MESSAGE
# ─────────────────────────────────────────────────────────────────────────────

_USAGE_TEXT = """**📥 Google Drive Downloader**
━━━━━━━━━━━━━━━━━━

তিনটা পদ্ধতিতে ব্যবহার করা যায়:

**১.** সরাসরি লিংক দিয়ে:
`/gdl https://drive.google.com/file/d/<ID>/view`

**২.** শুধু command দিলে বট লিংক চাইবে:
`/gdl` → তারপর লিংক পাঠাও

**৩.** Drive লিংক আছে এমন মেসেজ reply করে:
[মেসেজ forward করো] → `/gdl` reply করো

**Supported links:**
• `drive.google.com/file/d/<ID>/view`
• `drive.google.com/folders/<ID>`
• `drive.google.com/drive/folders/<ID>`
• `drive.google.com/open?id=<ID>`
• `docs.google.com/document/d/<ID>`

**Features:**
• Max: `2 GB`
• Google Docs → Office format auto-convert
• Smart upload: video/audio/photo/animation/doc
• Folder download সম্পূর্ণ support"""


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_gdl_handler(app: Client):
    """
    সব handler register করে।

    ⚠️  IMPORTANT: Auto-detect সম্পূর্ণ বন্ধ।
        শুধুমাত্র /gdl command এর মাধ্যমে কাজ করবে।

    তিনটা পদ্ধতি:
    ① /gdl <url>          — inline URL
    ② /gdl               — bot asks for URL, user sends it
    ③ reply + /gdl        — reply to any message with a Drive link
    """

    # ════════════════════════════════════════════════════════════════════════
    # HANDLER ①②③ — /gdl command (সব পদ্ধতি এক handler এ)
    # ════════════════════════════════════════════════════════════════════════

    @app.on_message(
        filters.command("gdl", prefixes=COMMAND_PREFIX)
        & (filters.private | filters.group)
    )
    async def gdl_command(client: Client, message: Message):
        """
        /gdl command handler।

        তিনটা scenario handle করে:
        ① /gdl <url>    → সরাসরি process
        ② reply + /gdl  → reply থেকে URL নাও, process করো
        ③ /gdl alone    → URL চাও, অপেক্ষা করো
        """
        user_id = (
            message.from_user.id if message.from_user
            else message.chat.id
        )
        chat_id = message.chat.id

        # ─── pending থাকলে cancel করো, নতুন করে শুরু করো ───────────────
        pending_key = (chat_id, user_id)
        if pending_key in _pending_url_requests:
            old_status = _pending_url_requests.pop(pending_key)
            try:
                await old_status.edit_text(
                    "🔄 **নতুন /gdl command পেয়েছি। আগেরটা cancel।**",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        url = None

        # ── পদ্ধতি ①: /gdl <url> ────────────────────────────────────────
        if len(message.command) >= 2:
            candidate = " ".join(message.command[1:]).strip()
            # URL entity বা raw text থেকে Drive URL বের করো
            urls_in_command = []
            for match in _DRIVE_URL_RE.finditer(candidate):
                urls_in_command.append(_clean_url(match.group(0)))
            if urls_in_command:
                url = urls_in_command[0]
            elif (
                "drive.google.com" in candidate
                or "docs.google.com" in candidate
            ):
                url = _clean_url(candidate)

        # ── এই message এর entities থেকেও চেষ্টা ─────────────────────────
        if not url:
            found = _extract_all_drive_urls(message)
            if found:
                url = found[0]

        # ── পদ্ধতি ③: reply করা মেসেজ থেকে URL ─────────────────────────
        if not url and message.reply_to_message:
            found = _extract_all_drive_urls(message.reply_to_message)
            if found:
                url = found[0]
                LOGGER.info(
                    f"[GDL] URL পাওয়া গেল replied message থেকে: {url}"
                )

        # ── URL পাওয়া গেলে সরাসরি process ───────────────────────────────
        if url:
            if "drive.google.com" not in url and "docs.google.com" not in url:
                await message.reply_text(
                    "❌ **এটি Google Drive লিংক মনে হচ্ছে না।**\n\n"
                    "দয়া করে একটি valid `drive.google.com` URL দিন।",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            LOGGER.info(
                f"[GDL] /gdl — user {user_id} — URL: {url}"
            )
            await _process_gdl(client, message, url)
            return

        # ── পদ্ধতি ②: URL নেই → bot জিজ্ঞেস করবে ────────────────────────
        LOGGER.info(
            f"[GDL] /gdl — user {user_id} — URL চাওয়া হচ্ছে"
        )

        ask_msg = await message.reply_text(
            "📎 **Google Drive লিংক পাঠাও!**\n\n"
            f"⏳ তোমার কাছ থেকে লিংকের জন্য "
            f"`{WAIT_FOR_URL_TIMEOUT}` সেকেন্ড অপেক্ষা করব।\n\n"
            "❌ Cancel করতে `/cancel` লেখো।",
            parse_mode=ParseMode.MARKDOWN,
        )

        # pending এ রেজিস্টার করো
        _pending_url_requests[pending_key] = ask_msg

        # Timeout এর পরে pending সরিয়ে দাও
        async def _timeout_cleanup():
            await asyncio.sleep(WAIT_FOR_URL_TIMEOUT)
            if pending_key in _pending_url_requests:
                _pending_url_requests.pop(pending_key)
                try:
                    await ask_msg.edit_text(
                        f"⏰ **Timeout!** `{WAIT_FOR_URL_TIMEOUT}` সেকেন্ডে "
                        "কোনো লিংক পাওয়া যায়নি।\n\n"
                        "আবার `/gdl` command দিয়ে চেষ্টা করো।",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass

        asyncio.create_task(_timeout_cleanup())

    # ════════════════════════════════════════════════════════════════════════
    # HANDLER — Pending URL receiver
    # /gdl দেওয়ার পরে bot URL চাইলে user যে message পাঠায় সেটা catch করে
    # ════════════════════════════════════════════════════════════════════════

    @app.on_message(
        (filters.private | filters.group)
        & ~filters.command(
            ["gdl", "cancel", "start", "help"],
            prefixes=COMMAND_PREFIX,
        ),
        group=10,  # low priority — অন্য handlers আগে চলবে
    )
    async def pending_url_receiver(client: Client, message: Message):
        """
        /gdl দেওয়ার পরে bot URL চাইলে এই handler সেই URL catch করে।

        ⚠️  শুধুমাত্র pending list এ থাকা user এর message process করবে।
            অন্য কারো message এ কোনো কাজ করবে না।
        """
        user_id = (
            message.from_user.id if message.from_user
            else message.chat.id
        )
        chat_id  = message.chat.id
        key      = (chat_id, user_id)

        # এই user pending নয় → কিছু করো না
        if key not in _pending_url_requests:
            return

        ask_msg = _pending_url_requests.pop(key)

        # message থেকে Drive URL বের করো
        urls = _extract_all_drive_urls(message)

        # যদি URL না পাওয়া যায়, raw text চেক করো
        if not urls:
            raw = (message.text or message.caption or "").strip()
            if "drive.google.com" in raw or "docs.google.com" in raw:
                cleaned = _clean_url(raw)
                if cleaned:
                    urls = [cleaned]

        if not urls:
            # URL পাওয়া যায়নি → আবার জিজ্ঞেস করো (pending রাখো)
            _pending_url_requests[key] = ask_msg
            await message.reply_text(
                "❌ **এটি Google Drive লিংক মনে হচ্ছে না।**\n\n"
                "দয়া করে একটি valid Drive URL পাঠাও।\n"
                "উদাহরণ:\n"
                "`https://drive.google.com/file/d/<ID>/view`\n\n"
                "❌ বাতিল করতে `/cancel` লেখো।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        url = urls[0]

        LOGGER.info(
            f"[GDL] Pending URL received — user {user_id}: {url}"
        )

        # Ask message আপডেট করো
        try:
            await ask_msg.edit_text(
                f"✅ **লিংক পেয়েছি!** Processing শুরু হচ্ছে…\n\n"
                f"🔗 `{url}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

        await _process_gdl(client, message, url)

    # ════════════════════════════════════════════════════════════════════════
    # HANDLER — /cancel
    # ════════════════════════════════════════════════════════════════════════

    @app.on_message(
        filters.command("cancel", prefixes=COMMAND_PREFIX)
        & (filters.private | filters.group)
    )
    async def cancel_pending(client: Client, message: Message):
        """
        /gdl এর পরে URL দেওয়া cancel করে।
        """
        user_id = (
            message.from_user.id if message.from_user
            else message.chat.id
        )
        key = (message.chat.id, user_id)

        if key in _pending_url_requests:
            ask_msg = _pending_url_requests.pop(key)
            try:
                await ask_msg.edit_text(
                    "❌ **Cancel করা হয়েছে।**\n\n"
                    "আবার শুরু করতে `/gdl` command দাও।",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            await message.reply_text(
                "✅ **GDL request cancel হয়েছে।**",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await message.reply_text(
                "ℹ️ **কোনো active GDL request নেই।**",
                parse_mode=ParseMode.MARKDOWN,
            )

    LOGGER.info(
        "[GDL] Handler registered — /gdl command only mode active.\n"
        "       Auto-detect: DISABLED ✗\n"
        "       Method ①: /gdl <url> ✓\n"
        "       Method ②: /gdl → bot asks → user sends URL ✓\n"
        "       Method ③: reply to message + /gdl ✓"
    )
