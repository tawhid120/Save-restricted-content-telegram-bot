# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/gdl.py — Google Drive Downloader via /gdl command
#
# ✅ NO user account / phone number required — BOT_TOKEN only
# ✅ Uses Pyrofork MTProto directly → up to 2 GB upload
# ✅ Downloads the file to disk from Google Drive, then uploads via MTProto
# ✅ Supports single files AND full folders (recursive)
# ✅ Real-time progress bar for both download and upload phases
# ✅ Cleans up temp files after every operation
# ✅ Auto-detects Drive links in hyperlinks and message text
# ✅ Uploads based on media type (photo/video/audio/document)

import os
import re
import io
import asyncio
import mimetypes
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, MessageEntity
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
    LOGGER.warning("[GDL] google-api-python-client not installed — /gdl will be disabled.")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_ACCOUNT_FILE = "service_account_key.json"
DOWNLOAD_DIR         = "gdl_downloads"
MAX_FILE_SIZE_BYTES  = 2 * 1024 * 1024 * 1024
PROGRESS_UPDATE_SEC  = 3

# Telegram limits
MAX_PHOTO_SIZE       = 10 * 1024 * 1024      # 10 MB for photos
MAX_THUMBNAIL_SIZE   = 200 * 1024            # 200 KB for thumbnails

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# MEDIA TYPE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

# Supported extensions for each media type
PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.mpeg', '.mpg'}
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.wma', '.opus', '.aiff'}
VOICE_EXTENSIONS = {'.ogg', '.oga'}  # Specifically for voice messages
ANIMATION_EXTENSIONS = {'.gif'}

# MIME type prefixes
PHOTO_MIMES = {'image/jpeg', 'image/png', 'image/webp', 'image/bmp', 'image/tiff'}
VIDEO_MIMES = {'video/mp4', 'video/x-matroska', 'video/avi', 'video/quicktime', 
               'video/x-msvideo', 'video/x-flv', 'video/webm', 'video/3gpp', 'video/mpeg'}
AUDIO_MIMES = {'audio/mpeg', 'audio/mp4', 'audio/wav', 'audio/flac', 'audio/aac', 
               'audio/ogg', 'audio/x-ms-wma', 'audio/opus', 'audio/aiff', 'audio/x-m4a'}
ANIMATION_MIMES = {'image/gif'}


def _get_media_type(file_path: str, mime_type: str = None) -> str:
    """
    Determine the media type based on file extension and MIME type.
    Returns: 'photo', 'video', 'audio', 'animation', or 'document'
    """
    # Get file extension
    _, ext = os.path.splitext(file_path.lower())
    
    # Get MIME type if not provided
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or 'application/octet-stream'
    
    mime_type = mime_type.lower()
    
    # Check for animation (GIF)
    if ext in ANIMATION_EXTENSIONS or mime_type in ANIMATION_MIMES:
        return 'animation'
    
    # Check for photo
    if ext in PHOTO_EXTENSIONS or mime_type in PHOTO_MIMES or mime_type.startswith('image/'):
        # Check file size for photo (Telegram limit is 10MB for photos)
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            if file_size <= MAX_PHOTO_SIZE:
                return 'photo'
            else:
                return 'document'  # Too large for photo, send as document
        return 'photo'
    
    # Check for video
    if ext in VIDEO_EXTENSIONS or mime_type in VIDEO_MIMES or mime_type.startswith('video/'):
        return 'video'
    
    # Check for audio
    if ext in AUDIO_EXTENSIONS or mime_type in AUDIO_MIMES or mime_type.startswith('audio/'):
        return 'audio'
    
    # Default to document
    return 'document'


def _get_video_metadata(file_path: str) -> tuple:
    """
    Try to get video duration, width, height using ffprobe if available.
    Returns (duration, width, height) or (0, 0, 0) if not available.
    """
    try:
        import subprocess
        import json
        
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-show_format', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            
            duration = 0
            width = 0
            height = 0
            
            # Get duration from format
            if 'format' in data and 'duration' in data['format']:
                duration = int(float(data['format']['duration']))
            
            # Get video stream info
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    width = stream.get('width', 0)
                    height = stream.get('height', 0)
                    if 'duration' in stream and duration == 0:
                        duration = int(float(stream['duration']))
                    break
            
            return duration, width, height
    except Exception as e:
        LOGGER.debug(f"[GDL] Could not get video metadata: {e}")
    
    return 0, 0, 0


def _get_audio_metadata(file_path: str) -> tuple:
    """
    Try to get audio duration, title, performer using ffprobe or mutagen.
    Returns (duration, title, performer) or (0, None, None) if not available.
    """
    try:
        import subprocess
        import json
        
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-show_format', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            
            duration = 0
            title = None
            performer = None
            
            # Get info from format
            if 'format' in data:
                fmt = data['format']
                if 'duration' in fmt:
                    duration = int(float(fmt['duration']))
                
                tags = fmt.get('tags', {})
                # Tags might be case-insensitive
                for key, value in tags.items():
                    key_lower = key.lower()
                    if key_lower == 'title':
                        title = value
                    elif key_lower in ('artist', 'performer', 'album_artist'):
                        performer = value
            
            return duration, title, performer
    except Exception as e:
        LOGGER.debug(f"[GDL] Could not get audio metadata: {e}")
    
    return 0, None, None


async def _generate_thumbnail(file_path: str, media_type: str) -> str | None:
    """
    Generate a thumbnail for video/audio files.
    Returns path to thumbnail or None.
    """
    if media_type not in ('video', 'audio'):
        return None
    
    try:
        import subprocess
        
        thumb_path = file_path + "_thumb.jpg"
        
        if media_type == 'video':
            # Extract frame at 1 second
            cmd = [
                'ffmpeg', '-y', '-i', file_path,
                '-ss', '00:00:01', '-vframes', '1',
                '-vf', 'scale=320:-1',
                thumb_path
            ]
        else:
            # For audio, try to extract album art
            cmd = [
                'ffmpeg', '-y', '-i', file_path,
                '-an', '-vcodec', 'mjpeg',
                '-vf', 'scale=320:-1',
                thumb_path
            ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(process.wait(), timeout=30)
        
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            # Check thumbnail size
            if os.path.getsize(thumb_path) <= MAX_THUMBNAIL_SIZE:
                return thumb_path
            else:
                os.remove(thumb_path)
        
    except Exception as e:
        LOGGER.debug(f"[GDL] Could not generate thumbnail: {e}")
    
    return None


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — readable sizes / times
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
# EXTRACT DRIVE LINKS FROM MESSAGE (INCLUDING HYPERLINKS)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_all_drive_links(message: Message) -> list[str]:
    """
    Extract all Google Drive links from a message, including:
    - Plain text links
    - Hyperlinks (text_link entities)
    - URLs in entities
    """
    drive_links = set()
    
    # Pattern to match Google Drive URLs
    drive_pattern = re.compile(
        r'https?://(?:www\.)?(?:drive\.google\.com|docs\.google\.com)[^\s<>\[\]()"\']+'
    )
    
    # 1. Extract from plain text
    text = message.text or message.caption or ""
    for match in drive_pattern.finditer(text):
        drive_links.add(match.group())
    
    # 2. Extract from entities (hyperlinks, URLs)
    entities = message.entities or message.caption_entities or []
    
    for entity in entities:
        # TEXT_LINK - hyperlinked text with a URL
        if entity.type == MessageEntityType.TEXT_LINK:
            url = entity.url
            if url and ('drive.google.com' in url or 'docs.google.com' in url):
                drive_links.add(url)
        
        # URL - plain URL in text
        elif entity.type == MessageEntityType.URL:
            # Extract the URL from text using offset and length
            url = text[entity.offset:entity.offset + entity.length]
            if 'drive.google.com' in url or 'docs.google.com' in url:
                drive_links.add(url)
    
    return list(drive_links)


def _extract_drive_id(url: str) -> str | None:
    """Extract the file or folder ID from any Google Drive URL."""
    patterns = [
        r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/folders/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)",
        r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)",
        r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)",
        r"docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _is_folder_url(url: str) -> bool:
    return "/folders/" in url


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE DRIVE UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _build_drive_service():
    """Build an authenticated Google Drive service from the service account file."""
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


def _list_folder_recursive(service, folder_id: str, parent_path: str = "") -> list[dict]:
    """Recursively list all non-folder files inside a Drive folder."""
    results = []
    query = f"'{folder_id}' in parents and trashed=false"
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
            current_path = os.path.join(parent_path, item["name"]) if parent_path else item["name"]
            if item.get("mimeType") == "application/vnd.google-apps.folder":
                results.extend(_list_folder_recursive(service, item["id"], current_path))
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
        "application/vnd.google-apps.document":     ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
        "application/vnd.google-apps.spreadsheet":  ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
        "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
        "application/vnd.google-apps.drawing":      ("image/png", ".png"),
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
) -> str:
    """
    Download one Drive file to local_path.
    Shows a live progress bar in status_msg.
    Returns the final local file path.
    """
    is_doc, export_mime, ext = _is_google_doc(mime_type)

    if is_doc:
        if not file_name.endswith(ext):
            file_name += ext
        local_path = os.path.splitext(local_path)[0] + ext
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    downloader = MediaIoBaseDownload(io.FileIO(local_path, "wb"), request, chunksize=8 * 1024 * 1024)

    start_ts  = time()
    last_edit = 0.0
    done      = False

    while not done:
        status, done = await asyncio.get_event_loop().run_in_executor(None, downloader.next_chunk)
        pct = status.progress() * 100
        now = time()

        if now - last_edit >= PROGRESS_UPDATE_SEC or done:
            elapsed = now - start_ts
            downloaded = status.resumable_progress
            speed = downloaded / elapsed if elapsed > 0 else 0
            bar = _progress_bar(pct)

            try:
                await status_msg.edit_text(
                    f"📥 **Downloading from Google Drive...**\n\n"
                    f"`[{bar}]` {pct:.1f}%\n\n"
                    f"📦 **Downloaded:** `{_readable_size(downloaded)}`\n"
                    f"⚡ **Speed:** `{_readable_size(speed)}/s`\n"
                    f"⏱ **Elapsed:** `{_readable_time(elapsed)}`\n\n"
                    f"📄 `{file_name}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                last_edit = now
            except Exception:
                pass

    return local_path


# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD A LOCAL FILE → TELEGRAM (MEDIA TYPE AWARE)
# ─────────────────────────────────────────────────────────────────────────────

async def _upload_to_telegram(
    client: Client,
    chat_id: int,
    local_path: str,
    file_name: str,
    caption: str,
    status_msg: Message,
    mime_type: str = None,
) -> bool:
    """
    Upload local_path to Telegram chat using MTProto.
    Automatically detects media type and uploads accordingly.
    Shows a live progress bar. Returns True on success.
    """
    file_size = os.path.getsize(local_path)
    start_ts  = [time()]
    last_edit = [0.0]
    
    # Determine media type
    media_type = _get_media_type(local_path, mime_type)
    
    LOGGER.info(f"[GDL] Uploading {file_name} as {media_type}")

    async def _progress(current: int, total: int):
        now = time()
        if now - last_edit[0] < PROGRESS_UPDATE_SEC and current < total:
            return
        elapsed = now - start_ts[0]
        speed   = current / elapsed if elapsed > 0 else 0
        eta     = (total - current) / speed if speed > 0 else 0
        pct     = (current / total * 100) if total > 0 else 0
        bar     = _progress_bar(pct)
        
        media_emoji = {
            'photo': '🖼',
            'video': '🎬',
            'audio': '🎵',
            'animation': '🎞',
            'document': '📄'
        }.get(media_type, '📄')
        
        try:
            await status_msg.edit_text(
                f"📤 **Uploading as {media_type.upper()}...**\n\n"
                f"`[{bar}]` {pct:.1f}%\n\n"
                f"📦 **Uploaded:** `{_readable_size(current)}` / `{_readable_size(total)}`\n"
                f"⚡ **Speed:** `{_readable_size(speed)}/s`\n"
                f"⏳ **ETA:** `{_readable_time(eta)}`\n\n"
                f"{media_emoji} `{file_name}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            last_edit[0] = now
        except Exception:
            pass

    thumb_path = None
    
    try:
        if media_type == 'photo':
            await client.send_photo(
                chat_id=chat_id,
                photo=local_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )
        
        elif media_type == 'video':
            # Get video metadata
            duration, width, height = _get_video_metadata(local_path)
            
            # Generate thumbnail
            thumb_path = await _generate_thumbnail(local_path, 'video')
            
            await client.send_video(
                chat_id=chat_id,
                video=local_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                duration=duration,
                width=width,
                height=height,
                thumb=thumb_path,
                file_name=file_name,
                supports_streaming=True,
                progress=_progress,
            )
        
        elif media_type == 'audio':
            # Get audio metadata
            duration, title, performer = _get_audio_metadata(local_path)
            
            # Generate thumbnail (album art)
            thumb_path = await _generate_thumbnail(local_path, 'audio')
            
            await client.send_audio(
                chat_id=chat_id,
                audio=local_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                duration=duration,
                title=title or os.path.splitext(file_name)[0],
                performer=performer,
                thumb=thumb_path,
                file_name=file_name,
                progress=_progress,
            )
        
        elif media_type == 'animation':
            await client.send_animation(
                chat_id=chat_id,
                animation=local_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )
        
        else:  # document
            await client.send_document(
                chat_id=chat_id,
                document=local_path,
                file_name=file_name,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                progress=_progress,
            )
        
        return True
        
    except Exception as e:
        LOGGER.error(f"[GDL] Upload as {media_type} failed for {file_name}: {e}")
        
        # Fallback to document if other media type fails
        if media_type != 'document':
            LOGGER.info(f"[GDL] Falling back to document upload for {file_name}")
            try:
                await client.send_document(
                    chat_id=chat_id,
                    document=local_path,
                    file_name=file_name,
                    caption=caption + "\n\n⚠️ _Uploaded as document (fallback)_",
                    parse_mode=ParseMode.MARKDOWN,
                    progress=_progress,
                )
                return True
            except Exception as e2:
                LOGGER.error(f"[GDL] Fallback upload also failed: {e2}")
        
        return False
    
    finally:
        # Clean up thumbnail
        if thumb_path and os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# CORE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def _process_gdl(client: Client, message: Message, url: str):
    """Full pipeline: validate → fetch metadata → download → upload → cleanup."""
    user    = message.from_user
    chat_id = message.chat.id

    if not GDRIVE_AVAILABLE:
        await message.reply_text(
            "❌ **Google Drive support is not available.**\n\n"
            "Please install the required packages:\n"
            "`pip install google-api-python-client google-auth-oauthlib`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    file_id = _extract_drive_id(url)
    if not file_id:
        await message.reply_text(
            "❌ **Could not extract a Google Drive ID from the link.**\n\n"
            "Supported formats:\n"
            "• `https://drive.google.com/file/d/<ID>/view`\n"
            "• `https://drive.google.com/folders/<ID>`\n"
            "• `https://drive.google.com/open?id=<ID>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        service = await asyncio.get_event_loop().run_in_executor(None, _build_drive_service)
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

    is_folder = _is_folder_url(url)
    status_msg = await message.reply_text(
        "🔍 **Fetching file info from Google Drive...**",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        if is_folder:
            # ── FOLDER mode ───────────────────────────────────────────────
            folder_meta = await asyncio.get_event_loop().run_in_executor(
                None, _get_file_metadata, service, file_id
            )
            folder_name = folder_meta.get("name", "Untitled Folder")

            await status_msg.edit_text(
                f"📁 **Scanning folder:** `{folder_name}`\n"
                "Please wait...",
                parse_mode=ParseMode.MARKDOWN,
            )

            files = await asyncio.get_event_loop().run_in_executor(
                None, _list_folder_recursive, service, file_id, folder_name
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
                "Starting download...",
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
                local_path    = os.path.join(DOWNLOAD_DIR, str(user.id), relative_path)

                await status_msg.edit_text(
                    f"📁 **{folder_name}**\n"
                    f"📊 Progress: `{idx}/{len(files)}`\n"
                    f"📄 Current: `{item_name}`\n"
                    f"📦 Size: `{_readable_size(item_size)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

                try:
                    local_path = await _download_drive_file(
                        service, item_id, item_name, item_mime, local_path, status_msg
                    )

                    caption = (
                        f"📄 **{item_name}**\n"
                        f"📁 Path: `{relative_path}`\n"
                        f"📦 Size: `{_readable_size(os.path.getsize(local_path))}`\n"
                        f"🔗 [Google Drive]({url})\n\n"
                        f"_Downloaded by @juktijol Bot_"
                    )

                    ok = await _upload_to_telegram(
                        client, chat_id, local_path,
                        os.path.basename(local_path), caption, status_msg, item_mime
                    )
                    if ok:
                        success_count += 1
                    else:
                        fail_count += 1

                except Exception as item_err:
                    LOGGER.error(f"[GDL] Failed to process '{item_name}': {item_err}")
                    fail_count += 1
                    await message.reply_text(
                        f"⚠️ **Skipped** `{item_name}`\n`{str(item_err)[:150]}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                finally:
                    if os.path.exists(local_path):
                        os.remove(local_path)

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
                None, _get_file_metadata, service, file_id
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
                "Downloading from Google Drive...",
                parse_mode=ParseMode.MARKDOWN,
            )

            local_path = os.path.join(DOWNLOAD_DIR, str(user.id), file_name)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            try:
                local_path = await _download_drive_file(
                    service, file_id, file_name, mime_type, local_path, status_msg
                )

                actual_size = os.path.getsize(local_path)

                if actual_size > MAX_FILE_SIZE_BYTES:
                    await status_msg.edit_text(
                        f"❌ **Exported file is too large:** `{_readable_size(actual_size)}`",
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
                    os.path.basename(local_path), caption, status_msg, mime_type
                )

                if ok:
                    media_type = _get_media_type(local_path, mime_type)
                    await status_msg.edit_text(
                        f"✅ **Done!** `{os.path.basename(local_path)}`\n"
                        f"📦 `{_readable_size(actual_size)}`\n"
                        f"📤 Uploaded as: `{media_type.upper()}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await status_msg.edit_text(
                        "❌ **Upload to Telegram failed.** Please try again.",
                        parse_mode=ParseMode.MARKDOWN,
                    )

            finally:
                if os.path.exists(local_path):
                    os.remove(local_path)

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
# COMMAND HANDLER SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_gdl_handler(app: Client):

    @app.on_message(
        filters.command("gdl", prefixes=COMMAND_PREFIX)
        & (filters.private | filters.group)
    )
    async def gdl_command(client: Client, message: Message):
        """
        /gdl <Google Drive link>
        OR
        /gdl (as reply to a message containing Drive links)

        Downloads the file from Google Drive and uploads it directly to the
        current chat via Pyrofork MTProto (supports up to 2 GB).
        Automatically uploads as the correct media type (photo/video/audio/document).
        """
        urls_to_process = []
        
        # ── Check for URL in command arguments ────────────────────────────
        if len(message.command) >= 2:
            url = message.command[1].strip()
            if 'drive.google.com' in url or 'docs.google.com' in url:
                urls_to_process.append(url)
        
        # ── Check replied message for Drive links (including hyperlinks) ──
        if message.reply_to_message:
            replied_links = _extract_all_drive_links(message.reply_to_message)
            urls_to_process.extend(replied_links)
        
        # ── Also check current message text for embedded links ────────────
        current_links = _extract_all_drive_links(message)
        for link in current_links:
            if link not in urls_to_process:
                urls_to_process.append(link)
        
        # ── Remove duplicates while preserving order ──────────────────────
        seen = set()
        unique_urls = []
        for url in urls_to_process:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # ── No links found ────────────────────────────────────────────────
        if not unique_urls:
            await message.reply_text(
                "**📥 Google Drive Downloader**\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "**Usage:**\n"
                "• `/gdl <Google Drive link>`\n"
                "• Reply to a message containing Drive links with `/gdl`\n\n"
                "**Supported links:**\n"
                "• `https://drive.google.com/file/d/<ID>/view`\n"
                "• `https://drive.google.com/folders/<ID>`\n"
                "• Hyperlinks containing Drive URLs\n\n"
                "**Features:**\n"
                "• 🖼 Photos → sent as photos\n"
                "• 🎬 Videos → sent as videos (with thumbnail)\n"
                "• 🎵 Audio → sent as audio (with metadata)\n"
                "• 📄 Other → sent as documents\n\n"
                "**Limits:** Max file size `2 GB`\n\n"
                "**Example:**\n"
                "`/gdl https://drive.google.com/file/d/1BxiM.../view`",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            return
        
        # ── Process all found links ───────────────────────────────────────
        if len(unique_urls) > 1:
            await message.reply_text(
                f"🔗 **Found {len(unique_urls)} Drive links**\n"
                f"Processing them one by one...",
                parse_mode=ParseMode.MARKDOWN,
            )
        
        for url in unique_urls:
            LOGGER.info(f"[GDL] User {message.from_user.id} requested: {url}")
            await _process_gdl(client, message, url)

    LOGGER.info("[GDL] /gdl command handler registered.")
