# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/gdl.py — Google Drive Downloader via /gdl + Auto-detect ALL Drive links
#
# ✅ NO user account / phone number required — BOT_TOKEN only
# ✅ Uses Pyrofork MTProto directly → up to 2 GB upload
# ✅ Downloads the file to disk from Google Drive, then uploads via MTProto
# ✅ Supports single files AND full folders (recursive)
# ✅ Real-time progress bar for both download and upload phases
# ✅ Cleans up temp files after every operation
# ✅ AUTO-DETECTS Drive links in:
#       - Plain URL entities (MessageEntityType.URL)
#       - Hyperlinked text (MessageEntityType.TEXT_LINK)
#       - Raw text (regex fallback)
#       - Forwarded messages
#       - Caption text
# ✅ SMART UPLOAD — photo/video/audio/animation/document based on MIME type
# ✅ Fallback to document if specific media upload fails
# ✅ /drive/folders/ AND /folders/ both supported
# ✅ Plugs straight into the existing project structure

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
from pyrogram.handlers import MessageHandler

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
        "[GDL] google-api-python-client not installed — /gdl will be disabled."
    )

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_ACCOUNT_FILE = "service_account_key.json"   # place in project root
DOWNLOAD_DIR         = "gdl_downloads"               # temp directory
MAX_FILE_SIZE_BYTES  = 2 * 1024 * 1024 * 1024        # 2 GB hard limit
PROGRESS_UPDATE_SEC  = 3                              # seconds between edits

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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

# Telegram sends photos only up to 10 MB
PHOTO_SIZE_LIMIT = 10 * 1024 * 1024

# ─────────────────────────────────────────────────────────────────────────────
# DRIVE URL REGEX — matches all known Google Drive / Docs URL formats
# ─────────────────────────────────────────────────────────────────────────────

_DRIVE_URL_RE = re.compile(
    r"https?://(?:drive|docs)\.google\.com/\S+",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# ★ FIX: DRIVE ID + FOLDER DETECTION
#   Handles ALL known URL formats including /drive/folders/ variant
#
#   Supported URL formats:
#   • https://drive.google.com/file/d/<ID>/view
#   • https://drive.google.com/drive/folders/<ID>        ← এটা আগে মিস হতো!
#   • https://drive.google.com/folders/<ID>
#   • https://drive.google.com/open?id=<ID>
#   • https://drive.google.com/drive/u/0/folders/<ID>    ← user-index variant
#   • https://docs.google.com/document/d/<ID>/edit
# ─────────────────────────────────────────────────────────────────────────────

def _extract_drive_id(url: str) -> str | None:
    """
    Extract the file or folder ID from ANY Google Drive / Docs URL.

    Pattern priority (most specific → least specific):
    1. /file/d/<ID>
    2. /folders/<ID>         — catches both /folders/ and /drive/folders/
                               and /drive/u/0/folders/ etc.
    3. ?id=<ID> or &id=<ID>
    4. /open?id=<ID>
    5. /d/<ID>               — generic docs pattern
    """
    patterns = [
        # Single file: /file/d/<ID>
        r"/file/d/([a-zA-Z0-9_-]{10,})",

        # ★ KEY FIX: folder — matches /folders/<ID> with ANY prefix path
        #   covers: /folders/, /drive/folders/, /drive/u/0/folders/, etc.
        r"/folders/([a-zA-Z0-9_-]{10,})",

        # Query param: ?id=<ID> or &id=<ID>
        r"[?&]id=([a-zA-Z0-9_-]{10,})",

        # Open link: /open?id=<ID>
        r"/open\?id=([a-zA-Z0-9_-]{10,})",

        # Generic Google Docs: /document/d/<ID>, /spreadsheets/d/<ID>, etc.
        r"/d/([a-zA-Z0-9_-]{10,})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _is_folder_url(url: str) -> bool:
    """
    Detect if a Drive URL points to a folder.

    Handles all variants:
    • /folders/<ID>
    • /drive/folders/<ID>
    • /drive/u/0/folders/<ID>
    • /drive/u/1/folders/<ID>
    """
    return bool(re.search(r"/folders/", url, re.IGNORECASE))


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — readable sizes / times / bar
# ─────────────────────────────────────────────────────────────────────────────

def _readable_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def _readable_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m {secs}s"


def _progress_bar(pct: float, length: int = 20) -> str:
    filled = int(length * pct / 100)
    return "▓" * filled + "░" * (length - filled)


# ─────────────────────────────────────────────────────────────────────────────
# MEDIA TYPE DETECTION + METADATA
# ─────────────────────────────────────────────────────────────────────────────

def _detect_media_type(file_path: str, mime_type: str = "") -> str:
    """
    Return one of: photo, video, audio, animation, document
    based on extension + MIME type.
    """
    ext = os.path.splitext(file_path)[1].lower()

    # GIF / animation
    if ext in ANIMATION_EXTENSIONS or mime_type in ANIMATION_MIMES:
        return "animation"

    # Photo (must be ≤ 10 MB for Telegram)
    if ext in PHOTO_EXTENSIONS or mime_type in PHOTO_MIMES:
        try:
            if os.path.getsize(file_path) <= PHOTO_SIZE_LIMIT:
                return "photo"
        except OSError:
            pass
        return "document"

    # Video
    if ext in VIDEO_EXTENSIONS or mime_type.startswith("video/"):
        return "video"

    # Audio
    if ext in AUDIO_EXTENSIONS or mime_type.startswith("audio/"):
        return "audio"

    return "document"


def _get_video_metadata(file_path: str) -> dict:
    """Extract duration / width / height via ffprobe (graceful fail)."""
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
    """Extract audio duration via ffprobe (graceful fail)."""
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
    """Generate a video thumbnail via ffmpeg (returns path or None)."""
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
# ★ UNIVERSAL DRIVE URL EXTRACTOR
#   Checks (in order):
#   1. TEXT_LINK entities  → hyperlinked text (e.g. "Tawhid" → drive url)
#   2. URL entities        → plain urls that Telegram auto-linked
#   3. Regex on raw text   → urls Telegram didn't entity-fy
#
#   ★ Also strips trailing punctuation that can corrupt URLs
# ─────────────────────────────────────────────────────────────────────────────

def _clean_url(url: str) -> str:
    """
    Strip trailing characters that are NOT part of a URL
    but may have been captured by regex or entity extraction.
    """
    # Strip trailing punctuation: ) ] > . , ; ! ? " '
    return re.sub(r"[)>\].,;!?\"']+$", "", url.strip())


def _extract_all_drive_urls(message: Message) -> list[str]:
    """
    Extract every unique Google Drive / Docs URL from a message using
    all three methods: TEXT_LINK entities, URL entities, regex on raw text.
    Works on normal text, captions, and forwarded messages.

    ★ TEXT_LINK entities are prioritised — this is how hyperlinks like
      'Tawhid' pointing to a Drive folder URL are captured.
    """
    seen: set[str] = set()
    urls: list[str] = []

    def _add(url: str) -> None:
        url = _clean_url(url)
        if not url:
            return
        if url in seen:
            return
        if "drive.google.com" in url or "docs.google.com" in url:
            seen.add(url)
            urls.append(url)
            LOGGER.debug(f"[GDL] URL extracted: {url}")

    # ── Gather entities from both text and caption ───────────────────────
    entities = []
    if message.entities:
        entities.extend(message.entities)
    if message.caption_entities:
        entities.extend(message.caption_entities)

    text = message.text or message.caption or ""

    # ── 1. TEXT_LINK — hyperlinked text (highest priority) ───────────────
    #   Example: "Tawhid" with URL drive.google.com/drive/folders/...
    for entity in entities:
        if entity.type == MessageEntityType.TEXT_LINK:
            if entity.url:
                _add(entity.url)

    # ── 2. URL entity — plain URL Telegram auto-detected ─────────────────
    for entity in entities:
        if entity.type == MessageEntityType.URL:
            chunk = text[entity.offset: entity.offset + entity.length]
            _add(chunk)

    # ── 3. Regex fallback — catches anything missed above ─────────────────
    #   (forwarded messages, bot-API payloads, non-entity URLs, etc.)
    for match in _DRIVE_URL_RE.finditer(text):
        _add(match.group(0))

    return urls


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE DRIVE UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _build_drive_service():
    """Build an authenticated Google Drive service from service account."""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f"Service account key not found: {SERVICE_ACCOUNT_FILE}\n"
            "Place your Google service account JSON in the project root."
        )
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds)


def _get_file_metadata(service, file_id: str) -> dict:
    return service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size",
        supportsAllDrives=True,
    ).execute()


def _list_folder_recursive(
    service, folder_id: str, parent_path: str = "",
) -> list[dict]:
    """Recursively list all non-folder files inside a Drive folder."""
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
    Returns (is_google_doc, export_mime, extension).
    Google Workspace files must be exported rather than downloaded directly.
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
    Download one Drive file to local_path.
    Returns (final_local_path, effective_mime_type).
    """
    is_doc, export_mime, ext = _is_google_doc(mime_type)
    effective_mime = mime_type

    if is_doc:
        if not file_name.endswith(ext):
            file_name += ext
        local_path     = os.path.splitext(local_path)[0] + ext
        request        = service.files().export_media(
            fileId=file_id, mimeType=export_mime,
        )
        effective_mime = export_mime
    else:
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
                    f"📥 **Downloading from Google Drive…**\n\n"
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
    Upload local_path to Telegram using the correct send method
    based on the detected media type.
    Falls back to send_document if the specific type fails.
    """
    media_type = _detect_media_type(local_path, mime_type)
    start_ts   = [time()]
    last_edit  = [0.0]

    LOGGER.info(
        f"[GDL] Uploading '{file_name}' as {media_type} "
        f"(mime={mime_type}, ext={os.path.splitext(file_name)[1]})"
    )

    # ── progress callback ────────────────────────────────────────────────
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
                f"📤 **Uploading to Telegram…** `[{media_type}]`\n\n"
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

    # ── send helper ──────────────────────────────────────────────────────
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

        else:  # document (default)
            await client.send_document(
                chat_id=chat_id,
                document=local_path,
                file_name=file_name,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )

    # ── try specific type → fallback to document ─────────────────────────
    try:
        await _send(media_type)
        return True

    except Exception as e:
        LOGGER.warning(
            f"[GDL] Upload as '{media_type}' failed for "
            f"'{file_name}': {e}"
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
# CORE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def _process_gdl(client: Client, message: Message, url: str):
    """Full pipeline: validate → metadata → download → upload → cleanup."""
    user_id = (
        message.from_user.id if message.from_user
        else message.sender_chat.id if message.sender_chat
        else message.chat.id
    )
    chat_id = message.chat.id

    # ── Validate Google API ───────────────────────────────────────────────
    if not GDRIVE_AVAILABLE:
        await message.reply_text(
            "❌ **Google Drive support is not available.**\n\n"
            "Install required packages:\n"
            "`pip install google-api-python-client google-auth-oauthlib`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── Determine if folder ───────────────────────────────────────────────
    is_folder = _is_folder_url(url)

    # ── Extract Drive ID ──────────────────────────────────────────────────
    file_id = _extract_drive_id(url)
    if not file_id:
        LOGGER.error(f"[GDL] Failed to extract ID from URL: {url}")
        await message.reply_text(
            "❌ **Could not extract a Google Drive ID from the link.**\n\n"
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

    # ── Build Drive service ───────────────────────────────────────────────
    try:
        service = await asyncio.get_event_loop().run_in_executor(
            None, _build_drive_service,
        )
    except FileNotFoundError as e:
        await message.reply_text(
            f"❌ **Service account key not found!**\n\n`{e}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    except Exception as e:
        await message.reply_text(
            f"❌ **Failed to authenticate with Google Drive.**\n\n`{e}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = await message.reply_text(
        "🔍 **Fetching file info from Google Drive…**",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        if is_folder:
            # ── FOLDER mode ───────────────────────────────────────────────
            folder_meta = await asyncio.get_event_loop().run_in_executor(
                None, _get_file_metadata, service, file_id,
            )
            folder_name = folder_meta.get("name", "Untitled Folder")

            await status_msg.edit_text(
                f"📁 **Scanning folder:** `{folder_name}`\n"
                "Please wait…",
                parse_mode=ParseMode.MARKDOWN,
            )

            files = await asyncio.get_event_loop().run_in_executor(
                None, _list_folder_recursive, service, file_id, folder_name,
            )

            if not files:
                await status_msg.edit_text(
                    f"🤷 **Folder `{folder_name}` is empty.**",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            total_size = sum(int(f.get("size", 0)) for f in files)
            if total_size > MAX_FILE_SIZE_BYTES:
                await status_msg.edit_text(
                    f"❌ **Folder is too large to send.**\n\n"
                    f"Total size: `{_readable_size(total_size)}`\n"
                    f"Limit: `{_readable_size(MAX_FILE_SIZE_BYTES)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            await status_msg.edit_text(
                f"📁 **Folder:** `{folder_name}`\n"
                f"📊 **Files found:** `{len(files)}`\n"
                f"📦 **Total size:** `{_readable_size(total_size)}`\n\n"
                "Starting download…",
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
                        f"[GDL] Failed to process '{item_name}': {item_err}"
                    )
                    fail_count += 1
                    await message.reply_text(
                        f"⚠️ **Skipped** `{item_name}`\n"
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
                f"✅ **Folder download complete!**\n\n"
                f"📁 `{folder_name}`\n"
                f"✅ Sent: `{success_count}`\n"
                f"❌ Failed: `{fail_count}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        else:
            # ── SINGLE FILE mode ──────────────────────────────────────────
            meta      = await asyncio.get_event_loop().run_in_executor(
                None, _get_file_metadata, service, file_id,
            )
            file_name = meta.get("name", "downloaded_file")
            mime_type = meta.get("mimeType", "application/octet-stream")
            file_size = int(meta.get("size", 0))

            is_doc, _, _ = _is_google_doc(mime_type)
            if not is_doc and file_size > MAX_FILE_SIZE_BYTES:
                await status_msg.edit_text(
                    f"❌ **File is too large to send via Telegram.**\n\n"
                    f"Size: `{_readable_size(file_size)}`\n"
                    f"Limit: `{_readable_size(MAX_FILE_SIZE_BYTES)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            await status_msg.edit_text(
                f"📄 **{file_name}**\n"
                f"📦 Size: `{_readable_size(file_size)}`\n\n"
                "Downloading from Google Drive…",
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
                        f"❌ **Exported file is too large:** "
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
                        f"✅ **Done!** `{os.path.basename(local_path)}`\n"
                        f"📦 `{_readable_size(actual_size)}` — "
                        f"sent as **{detected}**",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await status_msg.edit_text(
                        "❌ **Upload to Telegram failed.** Please try again.",
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
                f"❌ **An error occurred:**\n`{str(e)[:300]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND + AUTO-DETECT HANDLER SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_gdl_handler(app: Client):

    # ─── 1. /gdl <link>  command ─────────────────────────────────────────
    @app.on_message(
        filters.command("gdl", prefixes=COMMAND_PREFIX)
        & (filters.private | filters.group)
    )
    async def gdl_command(client: Client, message: Message):
        """
        /gdl <Google Drive link>

        Also works if the link is hidden inside a hyperlink
        or sent as a reply to a message containing a Drive link.
        """
        url = None

        # A) Try plain-text command argument
        if len(message.command) >= 2:
            candidate = message.command[1].strip()
            if (
                "drive.google.com" in candidate
                or "docs.google.com" in candidate
            ):
                url = candidate

        # B) Try ALL entity types + regex in this message
        if not url:
            found = _extract_all_drive_urls(message)
            if found:
                url = found[0]

        # C) Try replied-to message — ALL methods
        if not url and message.reply_to_message:
            found = _extract_all_drive_urls(message.reply_to_message)
            if found:
                url = found[0]

        # D) No URL found → show usage
        if not url:
            await message.reply_text(
                "**📥 Google Drive Downloader**\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "**Usage:** `/gdl <Google Drive link>`\n\n"
                "**Supported links:**\n"
                "• `https://drive.google.com/file/d/<ID>/view`\n"
                "• `https://drive.google.com/folders/<ID>`\n"
                "• `https://drive.google.com/drive/folders/<ID>`\n"
                "• `https://drive.google.com/open?id=<ID>`\n\n"
                "**Features:**\n"
                "• Max file size: `2 GB`\n"
                "• Google Docs → Office format\n"
                "• Smart upload: video/audio/photo/animation/document\n"
                "• Reply to a message with a Drive link\n"
                "• Auto-detects hyperlinks, plain URLs, raw text!\n\n"
                "**Example:**\n"
                "`/gdl https://drive.google.com/file/d/1BxiM.../view`",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            return

        if "drive.google.com" not in url and "docs.google.com" not in url:
            await message.reply_text(
                "❌ **That doesn't look like a Google Drive link.**\n\n"
                "Please send a valid `drive.google.com` URL.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        LOGGER.info(
            f"[GDL] /gdl from user "
            f"{getattr(message.from_user, 'id', '?')}: {url}"
        )
        await _process_gdl(client, message, url)

    # ─── 2. Auto-detect Drive links in ANY message ────────────────────────
    _has_text_or_entities = filters.create(
        lambda _, __, m: bool(
            m.text or m.caption
            or m.entities or m.caption_entities
        )
    )

    @app.on_message(
        _has_text_or_entities
        & (filters.private | filters.group)
        & ~filters.command("gdl", prefixes=COMMAND_PREFIX),
        group=1,
    )
    async def auto_detect_drive_links(client: Client, message: Message):
        """
        Automatically detect Google Drive URLs in any message:
        - Plain Drive URLs (URL entity or raw text)
        - Hyperlinked Drive URLs (TEXT_LINK entity)   ← Tawhid-style links
        - Forwarded messages containing Drive URLs
        """
        if message.from_user and message.from_user.is_self:
            return

        urls = _extract_all_drive_urls(message)
        if not urls:
            return

        sender = getattr(message.from_user, "id", "?")
        LOGGER.info(
            f"[GDL] Auto-detected {len(urls)} Drive URL(s) "
            f"from user {sender}: {urls}"
        )

        for url in urls:
            await _process_gdl(client, message, url)

    LOGGER.info(
        "[GDL] /gdl command + universal auto-detect handlers registered."
    )
