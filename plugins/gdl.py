# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/gdl.py — Google Drive Downloader
#
# ✅ Works in 3 ways:
#    1. /gdl <url>          — Give URL directly
#    2. /gdl               — Bot asks for link, then downloads
#    3. reply + /gdl       — Reply to a message that has a Drive link
#
# ❌ Auto-detect without command is fully OFF
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

SERVICE_ACCOUNT_FILE  = "service_account_key.json"   # place in project root
DOWNLOAD_DIR          = "gdl_downloads"               # temp directory
MAX_FILE_SIZE_BYTES   = 2 * 1024 * 1024 * 1024        # 2 GB hard limit
PROGRESS_UPDATE_SEC   = 3                              # progress update interval in seconds
WAIT_FOR_URL_TIMEOUT  = 60                             # wait time for URL input (seconds)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# PENDING USERS TRACKER
# Tracks users who sent /gdl but haven't given a URL yet
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

# Max photo size for Telegram: 10 MB
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
    Pulls out the file/folder ID from any Google Drive / Docs URL.

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
        r"/folders/([a-zA-Z0-9_-]{10,})",          # folder (all variants)
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
    """Returns True if the URL is a folder link."""
    return bool(re.search(r"/folders/", url, re.IGNORECASE))


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _readable_size(size: float) -> str:
    """Converts bytes to a human-readable size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def _readable_time(seconds: float) -> str:
    """Converts seconds to a human-readable time string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m {secs}s"


def _progress_bar(pct: float, length: int = 20) -> str:
    """Builds a simple text progress bar."""
    filled = int(length * pct / 100)
    return "▓" * filled + "░" * (length - filled)


def _clean_url(url: str) -> str:
    """Strips trailing punctuation from a URL."""
    return re.sub(r"[)>\].,;!?\"']+$", "", url.strip())


# ─────────────────────────────────────────────────────────────────────────────
# DRIVE URL EXTRACTOR (from message entities + regex)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_all_drive_urls(message: Message) -> list[str]:
    """
    Finds all Google Drive URLs inside a message.

    Checks in three ways:
    1. TEXT_LINK entity  — hyperlinked text (e.g. "Click here" → drive url)
    2. URL entity        — plain URL auto-detected by Telegram
    3. Regex fallback    — everything else

    ⚠️  Only used inside the /gdl command handler.
        There is no separate auto-detect handler.
    """
    seen: set[str] = set()
    urls: list[str] = []

    def _add(url: str) -> None:
        url = _clean_url(url)
        if not url:
            return
        if url in seen:
            return
        # only keep Drive/Docs URLs
        if "drive.google.com" in url or "docs.google.com" in url:
            seen.add(url)
            urls.append(url)
            LOGGER.debug(f"[GDL] URL found: {url}")

    # get entities from both text and caption
    entities = []
    if message.entities:
        entities.extend(message.entities)
    if message.caption_entities:
        entities.extend(message.caption_entities)

    text = message.text or message.caption or ""

    # ── 1. TEXT_LINK entity (highest priority) ───────────────────────────
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
    Detects file type: photo, video, audio, animation, or document.
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
    """Gets video metadata using ffprobe."""
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
    """Gets audio duration using ffprobe."""
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
    """Creates a video thumbnail using ffmpeg."""
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
    """Authenticates Google Drive using a service account."""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f"Service account key not found: {SERVICE_ACCOUNT_FILE}\n"
            "Please place the Google service account JSON in the project root."
        )
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds)


def _get_file_metadata(service, file_id: str) -> dict:
    """Fetches metadata for a Drive file."""
    return service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size",
        supportsAllDrives=True,
    ).execute()


def _list_folder_recursive(
    service, folder_id: str, parent_path: str = "",
) -> list[dict]:
    """Recursively lists all files in a Drive folder."""
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
    Checks if the file is a Google Workspace file.
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
    Downloads one file from Drive and saves it to local disk.
    Returns: (final_local_path, effective_mime_type)
    """
    is_doc, export_mime, ext = _is_google_doc(mime_type)
    effective_mime = mime_type

    if is_doc:
        # Google Docs need to be exported first
        if not file_name.endswith(ext):
            file_name += ext
        local_path     = os.path.splitext(local_path)[0] + ext
        request        = service.files().export_media(
            fileId=file_id, mimeType=export_mime,
        )
        effective_mime = export_mime
    else:
        # Regular file — download directly
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
                    f"📥 **⚡ Downloading from Google Drive…**\n\n"
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
    Uploads a local file to Telegram.
    Picks the right method based on media type.
    Falls back to document if the specific upload fails.
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
                f"📤 **⚡ Uploading to Telegram…** `[{media_type}]`\n\n"
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
    Full pipeline:
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
            "❌ **Google Drive support is not available.**\n\n"
            "⚡ Please install the required packages:\n"
            "`pip install google-api-python-client google-auth-oauthlib`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    is_folder = _is_folder_url(url)

    # ── Extract Drive ID ──────────────────────────────────────────────────
    file_id = _extract_drive_id(url)
    if not file_id:
        LOGGER.error(f"[GDL] Could not extract ID from URL: {url}")
        await message.reply_text(
            "❌ **Could not find the Google Drive ID.**\n\n"
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
            f"❌ **Could not connect to Google Drive.**\n\n`{e}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = await message.reply_text(
        "🔍 **⚡ Getting file info from Google Drive…**",
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
                f"📁 **Scanning folder:** `{folder_name}`\n"
                "⚡ Please wait…",
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
                    f"❌ **Folder is too big to send.**\n\n"
                    f"Total size: `{_readable_size(total_size)}`\n"
                    f"Limit: `{_readable_size(MAX_FILE_SIZE_BYTES)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            await status_msg.edit_text(
                f"📁 **Folder:** `{folder_name}`\n"
                f"📊 **Files:** `{len(files)}`\n"
                f"📦 **Total size:** `{_readable_size(total_size)}`\n\n"
                "⚡ Starting download…",
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
                        f"__Downloaded by @juktijol Bot__"
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
                        f"⚠️ **Skipped:** `{item_name}`\n"
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
                f"✅ **Folder download done!**\n\n"
                f"📁 `{folder_name}`\n"
                f"✅ Success: `{success_count}`\n"
                f"❌ Failed: `{fail_count}`",
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
                    f"❌ **File is too big to send to Telegram.**\n\n"
                    f"Size: `{_readable_size(file_size)}`\n"
                    f"Limit: `{_readable_size(MAX_FILE_SIZE_BYTES)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            await status_msg.edit_text(
                f"📄 **{file_name}**\n"
                f"📦 Size: `{_readable_size(file_size)}`\n\n"
                "⚡ Downloading from Google Drive…",
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
                        f"❌ **Exported file is too big:** "
                        f"`{_readable_size(actual_size)}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return

                caption = (
                    f"📄 **{os.path.basename(local_path)}**\n"
                    f"📦 Size: `{_readable_size(actual_size)}`\n"
                    f"🔗 [Google Drive]({url})\n\n"
                    f"__Downloaded by @juktijol Bot__"
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
                f"❌ **Something went wrong:**\n`{str(e)[:300]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# USAGE MESSAGE
# ─────────────────────────────────────────────────────────────────────────────

_USAGE_TEXT = """**📥 ⚡ Google Drive Downloader**
━━━━━━━━━━━━━━━━━━

You can use it in 3 easy ways:

**1.** Give the link directly:
`/gdl https://drive.google.com/file/d/<ID>/view`

**2.** Just send the command, bot will ask for the link:
`/gdl` → then send the link

**3.** Reply to a message that has a Drive link:
[Forward the message] → reply with `/gdl`

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
• Full folder download support"""


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_gdl_handler(app: Client):
    """
    Registers all handlers.

    ⚠️  IMPORTANT: Auto-detect is fully OFF.
        Only works via the /gdl command.

    Three methods:
    ① /gdl <url>          — inline URL
    ② /gdl               — bot asks for URL, user sends it
    ③ reply + /gdl        — reply to any message with a Drive link
    """

    # ════════════════════════════════════════════════════════════════════════
    # HANDLER ①②③ — /gdl command (all methods in one handler)
    # ════════════════════════════════════════════════════════════════════════

    @app.on_message(
        filters.command("gdl", prefixes=COMMAND_PREFIX)
        & (filters.private | filters.group)
    )
    async def gdl_command(client: Client, message: Message):
        """
        /gdl command handler.

        Handles three scenarios:
        ① /gdl <url>    → process directly
        ② reply + /gdl  → get URL from reply, then process
        ③ /gdl alone    → ask for URL, wait for it
        """
        user_id = (
            message.from_user.id if message.from_user
            else message.chat.id
        )
        chat_id = message.chat.id

        # ─── cancel any existing pending request, start fresh ────────────
        pending_key = (chat_id, user_id)
        if pending_key in _pending_url_requests:
            old_status = _pending_url_requests.pop(pending_key)
            try:
                await old_status.edit_text(
                    "🔄 **Got a new /gdl command. Cancelled the old one.**",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        url = None

        # ── Method ①: /gdl <url> ─────────────────────────────────────────
        if len(message.command) >= 2:
            candidate = " ".join(message.command[1:]).strip()
            # extract Drive URL from URL entity or raw text
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

        # ── also try entities from this message ───────────────────────────
        if not url:
            found = _extract_all_drive_urls(message)
            if found:
                url = found[0]

        # ── Method ③: get URL from replied message ────────────────────────
        if not url and message.reply_to_message:
            found = _extract_all_drive_urls(message.reply_to_message)
            if found:
                url = found[0]
                LOGGER.info(
                    f"[GDL] URL found in replied message: {url}"
                )

        # ── if URL found, process directly ────────────────────────────────
        if url:
            if "drive.google.com" not in url and "docs.google.com" not in url:
                await message.reply_text(
                    "❌ **This doesn't look like a Google Drive link.**\n\n"
                    "Please send a valid `drive.google.com` URL.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            LOGGER.info(
                f"[GDL] /gdl — user {user_id} — URL: {url}"
            )
            await _process_gdl(client, message, url)
            return

        # ── Method ②: no URL → ask the user for it ───────────────────────
        LOGGER.info(
            f"[GDL] /gdl — user {user_id} — asking for URL"
        )

        ask_msg = await message.reply_text(
            "📎 **⚡ Send me the Google Drive link!**\n\n"
            f"⏳ I'll wait `{WAIT_FOR_URL_TIMEOUT}` seconds for your link.\n\n"
            "❌ To cancel, type `/cancel`.",
            parse_mode=ParseMode.MARKDOWN,
        )

        # register as pending
        _pending_url_requests[pending_key] = ask_msg

        # remove from pending after timeout
        async def _timeout_cleanup():
            await asyncio.sleep(WAIT_FOR_URL_TIMEOUT)
            if pending_key in _pending_url_requests:
                _pending_url_requests.pop(pending_key)
                try:
                    await ask_msg.edit_text(
                        f"⏰ **Time's up!** No link received in "
                        f"`{WAIT_FOR_URL_TIMEOUT}` seconds.\n\n"
                        "Try again with `/gdl`.",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass

        asyncio.create_task(_timeout_cleanup())

    # ════════════════════════════════════════════════════════════════════════
    # HANDLER — Pending URL receiver
    # Catches the message a user sends after the bot asked for a URL
    # ════════════════════════════════════════════════════════════════════════

    @app.on_message(
        (filters.private | filters.group)
        & ~filters.command(
            ["gdl", "cancel", "start", "help"],
            prefixes=COMMAND_PREFIX,
        ),
        group=10,  # low priority — other handlers run first
    )
    async def pending_url_receiver(client: Client, message: Message):
        """
        Catches the URL a user sends after the bot asked for it (via /gdl).

        ⚠️  Only processes messages from users who are in the pending list.
            Ignores everyone else.
        """
        user_id = (
            message.from_user.id if message.from_user
            else message.chat.id
        )
        chat_id  = message.chat.id
        key      = (chat_id, user_id)

        # user is not pending → do nothing
        if key not in _pending_url_requests:
            return

        ask_msg = _pending_url_requests.pop(key)

        # extract Drive URL from the message
        urls = _extract_all_drive_urls(message)

        # if no URL found, check raw text
        if not urls:
            raw = (message.text or message.caption or "").strip()
            if "drive.google.com" in raw or "docs.google.com" in raw:
                cleaned = _clean_url(raw)
                if cleaned:
                    urls = [cleaned]

        if not urls:
            # no URL found → ask again (keep pending)
            _pending_url_requests[key] = ask_msg
            await message.reply_text(
                "❌ **This doesn't look like a Google Drive link.**\n\n"
                "Please send a valid Drive URL.\n"
                "Example:\n"
                "`https://drive.google.com/file/d/<ID>/view`\n\n"
                "❌ To cancel, type `/cancel`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        url = urls[0]

        LOGGER.info(
            f"[GDL] Pending URL received — user {user_id}: {url}"
        )

        # update the ask message
        try:
            await ask_msg.edit_text(
                f"✅ **Got the link!** ⚡ Starting now…\n\n"
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
        Cancels a pending /gdl URL request.
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
                    "❌ **Cancelled.**\n\n"
                    "Type `/gdl` to start again.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            await message.reply_text(
                "✅ **GDL request cancelled.**",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await message.reply_text(
                "ℹ️ **No active GDL request found.**",
                parse_mode=ParseMode.MARKDOWN,
            )

    LOGGER.info(
        "[GDL] Handler registered — /gdl command only mode active.\n"
        "       Auto-detect: DISABLED ✗\n"
        "       Method ①: /gdl <url> ✓\n"
        "       Method ②: /gdl → bot asks → user sends URL ✓\n"
        "       Method ③: reply to message + /gdl ✓"
    )
