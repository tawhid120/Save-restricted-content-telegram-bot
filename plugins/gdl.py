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
# ✅ Plugs straight into the existing project structure

import os
import re
import io
import asyncio
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
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

SERVICE_ACCOUNT_FILE = "service_account_key.json"   # place in project root
DOWNLOAD_DIR         = "gdl_downloads"               # temp directory
MAX_FILE_SIZE_BYTES  = 2 * 1024 * 1024 * 1024        # 2 GB hard limit
PROGRESS_UPDATE_SEC  = 3                             # seconds between edits

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


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


def _extract_drive_id(url: str) -> str | None:
    """Extract the file or folder ID from any Google Drive URL."""
    patterns = [
        r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/folders/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _is_folder_url(url: str) -> bool:
    return "/folders/" in url


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
        # Google Workspace file → export
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
# UPLOAD A LOCAL FILE → TELEGRAM (via Pyrofork MTProto — up to 2 GB)
# ─────────────────────────────────────────────────────────────────────────────

async def _upload_to_telegram(
    client: Client,
    chat_id: int,
    local_path: str,
    file_name: str,
    caption: str,
    status_msg: Message,
) -> bool:
    """
    Upload local_path to Telegram chat using MTProto.
    Shows a live progress bar.  Returns True on success.
    """
    file_size = os.path.getsize(local_path)
    start_ts  = [time()]
    last_edit = [0.0]

    async def _progress(current: int, total: int):
        now = time()
        if now - last_edit[0] < PROGRESS_UPDATE_SEC and current < total:
            return
        elapsed = now - start_ts[0]
        speed   = current / elapsed if elapsed > 0 else 0
        eta     = (total - current) / speed if speed > 0 else 0
        pct     = (current / total * 100) if total > 0 else 0
        bar     = _progress_bar(pct)
        try:
            await status_msg.edit_text(
                f"📤 **Uploading to Telegram...**\n\n"
                f"`[{bar}]` {pct:.1f}%\n\n"
                f"📦 **Uploaded:** `{_readable_size(current)}` / `{_readable_size(total)}`\n"
                f"⚡ **Speed:** `{_readable_size(speed)}/s`\n"
                f"⏳ **ETA:** `{_readable_time(eta)}`\n\n"
                f"📄 `{file_name}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            last_edit[0] = now
        except Exception:
            pass

    try:
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
        LOGGER.error(f"[GDL] Upload failed for {file_name}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# CORE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def _process_gdl(client: Client, message: Message, url: str):
    """Full pipeline: validate → fetch metadata → download → upload → cleanup."""
    user   = message.from_user
    chat_id = message.chat.id

    # ── Validate Google API availability ──────────────────────────────────
    if not GDRIVE_AVAILABLE:
        await message.reply_text(
            "❌ **Google Drive support is not available.**\n\n"
            "Please install the required packages:\n"
            "`pip install google-api-python-client google-auth-oauthlib`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── Extract Drive ID ──────────────────────────────────────────────────
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

    # ── Build Drive service ───────────────────────────────────────────────
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

            # Size guard
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
                item_name    = item["name"]
                item_id      = item["id"]
                item_mime    = item.get("mimeType", "")
                item_size    = int(item.get("size", 0))
                relative_path = item.get("relative_path", item_name)
                local_path   = os.path.join(DOWNLOAD_DIR, str(user.id), relative_path)

                await status_msg.edit_text(
                    f"📁 **{folder_name}**\n"
                    f"📊 Progress: `{idx}/{len(files)}`\n"
                    f"📄 Current: `{item_name}`\n"
                    f"📦 Size: `{_readable_size(item_size)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

                try:
                    # Download
                    local_path = await _download_drive_file(
                        service, item_id, item_name, item_mime, local_path, status_msg
                    )

                    # Build caption
                    caption = (
                        f"📄 **{item_name}**\n"
                        f"📁 Path: `{relative_path}`\n"
                        f"📦 Size: `{_readable_size(os.path.getsize(local_path))}`\n"
                        f"🔗 [Google Drive]({url})\n\n"
                        f"_Downloaded by @juktijol Bot_"
                    )

                    # Upload
                    ok = await _upload_to_telegram(
                        client, chat_id, local_path,
                        os.path.basename(local_path), caption, status_msg
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

            # Size guard (skip for Google Docs since we don't know export size)
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

                # Second size check after download (important for exported Google Docs)
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
                    os.path.basename(local_path), caption, status_msg
                )

                if ok:
                    await status_msg.edit_text(
                        f"✅ **Done!** `{os.path.basename(local_path)}`\n"
                        f"📦 `{_readable_size(actual_size)}`",
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

        Downloads the file from Google Drive and uploads it directly to the
        current chat via Pyrofork MTProto (supports up to 2 GB).
        """
        # ── Parse argument ────────────────────────────────────────────────
        if len(message.command) < 2:
            await message.reply_text(
                "**📥 Google Drive Downloader**\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "**Usage:** `/gdl <Google Drive link>`\n\n"
                "**Supported links:**\n"
                "• `https://drive.google.com/file/d/<ID>/view`\n"
                "• `https://drive.google.com/folders/<ID>`\n"
                "• `https://drive.google.com/open?id=<ID>`\n\n"
                "**Limits:**\n"
                "• Max file size: `2 GB`\n"
                "• Google Workspace files are exported to Office format\n\n"
                "**Example:**\n"
                "`/gdl https://drive.google.com/file/d/1BxiM.../view`",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            return

        url = message.command[1].strip()

        # Rudimentary URL validation
        if "drive.google.com" not in url and "docs.google.com" not in url:
            await message.reply_text(
                "❌ **That doesn't look like a Google Drive link.**\n\n"
                "Please send a valid `drive.google.com` URL.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        LOGGER.info(f"[GDL] User {message.from_user.id} requested: {url}")
        await _process_gdl(client, message, url)

    LOGGER.info("[GDL] /gdl command handler registered.")
