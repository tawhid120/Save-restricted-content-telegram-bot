# Copyright @juktijol
# Channel t.me/juktijol

"""
Multi-User YouTube Direct Upload Handler
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Features:
  • প্রতিটি User তাদের নিজস্ব YouTube Channel-এ আপলোড করতে পারবে
  • Per-user OAuth token MongoDB-তে সেভ থাকবে
  • Mode 1: Telegram Video Reply → YouTube Upload
  • Mode 2: যেকোনো Website URL → yt-dlp → YouTube Upload
  • Privacy control: public / private / unlisted
  • Custom title, description support
  • Referer / HLS / CDN protected stream support
  • Professional tracking & logging

Commands:
  /ytconnect              — নিজের YouTube Channel Connect করো
  /ytdisconnect           — YouTube Channel Disconnect করো
  /ytme                   — Connected Channel Info দেখো
  /ytupload <url>         — URL থেকে YouTube-এ আপলোড
  /ytupload <url> --private
  /ytupload <url> --unlisted
  /ytupload <url> --title "Custom Title"
  /ytupload <url> referer:<site>
  [Video reply] /ytsend   — Telegram ভিডিও → YouTube
  [Video reply] /ytsend --private
  [Video reply] /ytsend --title "Custom Title"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import re
import json
import asyncio
import tempfile
from io import BytesIO
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from pyrogram.enums import ParseMode
from pyrogram.handlers import MessageHandler

from config import COMMAND_PREFIX, LOG_GROUP_ID
from utils.logging_setup import LOGGER
from utils.helper import get_readable_file_size, get_readable_time
from core import db, prem_plan1, prem_plan2, prem_plan3

# ── ytdl.py থেকে shared functions import ─────────────────────────────────────
from plugins.ytdl import (
    download_single_video,
    get_single_video_info,
    parse_url_and_referer,
    is_hls_url,
    is_protected_cdn_url,
    cleanup_stale_files,
    _is_warp_available,
    _friendly_error,
    _make_progress_bar,
    _ytdl_progress_updater,
    DOWNLOAD_DIR,
    MAX_FILE_SIZE,
)

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    LOGGER.error(
        "[ytupload] Google API library নেই!\n"
        "Run: pip install google-api-python-client "
        "google-auth-oauthlib google-auth-httplib2"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONSTANTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCOPES           = ["https://www.googleapis.com/auth/youtube.upload",
                    "https://www.googleapis.com/auth/youtube.readonly"]
CREDENTIALS_FILE = "yt_credentials.json"   # Google Cloud OAuth credentials
YT_TITLE_MAX     = 100
YT_DESC_MAX      = 5000
YT_TAG_MAX       = 10
YT_CHUNK_SIZE    = 5 * 1024 * 1024         # 5MB resumable chunk
SESSION_EXPIRY   = 900                      # 15 মিনিট
PRIVACY_OPTIONS  = ["public", "private", "unlisted"]

# ── MongoDB Collections ──────────────────────────────────────────────────────
# db থেকে collection নাও
yt_tokens_col   = db["yt_user_tokens"]    # Per-user YouTube OAuth token
yt_uploads_col  = db["yt_upload_logs"]    # Upload history log

# ── In-memory session stores ─────────────────────────────────────────────────
ytup_sessions:   dict = {}   # chat_id → upload session
oauth_sessions:  dict = {}   # user_id → OAuth flow state


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MONGODB — TOKEN MANAGER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _save_user_token(user_id: int, creds: "Credentials", channel_info: dict):
    """
    User-এর YouTube OAuth token MongoDB-তে সেভ করে।

    Schema (yt_user_tokens):
    ────────────────────────
    {
        user_id      : int       — Telegram user ID
        token        : str       — JSON serialized token
        channel_id   : str       — YouTube Channel ID
        channel_name : str       — YouTube Channel Title
        connected_at : datetime  — প্রথম connect-এর সময়
        updated_at   : datetime  — শেষবার token refresh-এর সময়
    }
    """
    token_json = creds.to_json()   # Credentials → JSON string
    now        = datetime.utcnow()

    await yt_tokens_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "token":        token_json,
                "channel_id":   channel_info.get("id", ""),
                "channel_name": channel_info.get("title", "Unknown"),
                "updated_at":   now,
            },
            "$setOnInsert": {"connected_at": now},
        },
        upsert=True,
    )
    LOGGER.info(f"[ytupload] Token saved for user {user_id} ✅")


async def _load_user_token(user_id: int) -> "Credentials | None":
    """
    MongoDB থেকে user-এর token load করে।
    Expired হলে auto-refresh করে re-save করে।

    Returns
    ───────
    Credentials | None
    """
    if not GOOGLE_API_AVAILABLE:
        return None

    rec = await yt_tokens_col.find_one({"user_id": user_id})
    if not rec or not rec.get("token"):
        return None

    try:
        creds = Credentials.from_authorized_user_info(
            json.loads(rec["token"]), SCOPES
        )
    except Exception as e:
        LOGGER.warning(f"[ytupload] Token parse error for {user_id}: {e}")
        return None

    # ── Auto-refresh expired token ────────────────────────────────────────
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Refreshed token re-save করো
                await yt_tokens_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"token": creds.to_json(), "updated_at": datetime.utcnow()}},
                )
                LOGGER.info(f"[ytupload] Token refreshed for user {user_id} ✅")
            except Exception as e:
                LOGGER.warning(f"[ytupload] Token refresh failed for {user_id}: {e}")
                return None
        else:
            return None

    return creds


async def _delete_user_token(user_id: int) -> bool:
    """User-এর token MongoDB থেকে delete করে।"""
    result = await yt_tokens_col.delete_one({"user_id": user_id})
    return result.deleted_count > 0


async def _get_user_channel_info(user_id: int) -> dict | None:
    """MongoDB থেকে user-এর channel info নিয়ে আসে।"""
    rec = await yt_tokens_col.find_one(
        {"user_id": user_id},
        {"channel_id": 1, "channel_name": 1, "connected_at": 1, "updated_at": 1},
    )
    return rec if rec else None


async def _is_youtube_connected(user_id: int) -> bool:
    """User YouTube connect করেছে কিনা check করে।"""
    creds = await _load_user_token(user_id)
    return creds is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OAUTH FLOW MANAGER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _create_oauth_flow() -> "Flow | None":
    """
    Google OAuth 2.0 Flow তৈরি করে।
    credentials.json file থেকে client secret পড়ে।
    OOB (Out-Of-Band) flow ব্যবহার করে — user auth code copy-paste করবে।
    """
    if not os.path.exists(CREDENTIALS_FILE):
        LOGGER.error(f"[ytupload] {CREDENTIALS_FILE} not found!")
        return None
    try:
        flow = Flow.from_client_secrets_file(
            CREDENTIALS_FILE,
            scopes=SCOPES,
            redirect_uri="urn:ietf:wg:oauth:2.0:oob",  # OOB — code copy করতে হবে
        )
        return flow
    except Exception as e:
        LOGGER.error(f"[ytupload] OAuth flow creation error: {e}")
        return None


def _get_youtube_service_from_creds(creds: "Credentials"):
    """Credentials থেকে YouTube API service object তৈরি করে।"""
    try:
        return build("youtube", "v3", credentials=creds)
    except Exception as e:
        LOGGER.error(f"[ytupload] YouTube service build error: {e}")
        return None


async def _fetch_channel_info(creds: "Credentials") -> dict:
    """
    YouTube API থেকে user-এর channel info fetch করে।

    Returns
    ───────
    {"id": str, "title": str, "subscribers": int}
    """
    try:
        youtube  = _get_youtube_service_from_creds(creds)
        response = youtube.channels().list(
            part="snippet,statistics",
            mine=True,
        ).execute()

        items = response.get("items", [])
        if not items:
            return {"id": "", "title": "Unknown Channel"}

        item = items[0]
        return {
            "id":          item.get("id", ""),
            "title":       item["snippet"].get("title", "Unknown"),
            "subscribers": int(
                item.get("statistics", {}).get("subscriberCount", 0) or 0
            ),
            "url": f"https://youtube.com/channel/{item.get('id', '')}",
        }
    except Exception as e:
        LOGGER.warning(f"[ytupload] Channel info fetch error: {e}")
        return {"id": "", "title": "Unknown Channel"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# YOUTUBE UPLOAD CORE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _upload_file_to_youtube_sync(
    creds:          "Credentials",
    filepath:       str,
    title:          str,
    description:    str   = "",
    tags:           list  = None,
    privacy_status: str   = "public",
    category_id:    str   = "22",
    progress_cb=None,
) -> tuple:
    """
    User-এর credentials দিয়ে তাদের YouTube channel-এ ভিডিও আপলোড করে।
    (synchronous — asyncio executor-এ চালাতে হবে)

    Parameters
    ──────────
    creds          : User-এর Google OAuth Credentials।
    filepath       : আপলোড করার file path।
    title          : YouTube video title।
    description    : YouTube video description।
    tags           : YouTube tags list।
    privacy_status : "public" | "private" | "unlisted"।
    category_id    : YouTube category (22 = People & Blogs)।
    progress_cb    : (uploaded_bytes, total_bytes) → None।

    Returns
    ───────
    (success: bool, video_id_or_error: str)
    """
    youtube = _get_youtube_service_from_creds(creds)
    if not youtube:
        return False, "YouTube service তৈরি করা যায়নি।"

    # ── Sanitize inputs ───────────────────────────────────────────────────
    title       = (title or "Untitled")[:YT_TITLE_MAX]
    description = (description or "")[:YT_DESC_MAX]
    tags        = (tags or [])[:YT_TAG_MAX]

    body = {
        "snippet": {
            "title":       title,
            "description": description,
            "tags":        tags,
            "categoryId":  category_id,
        },
        "status": {
            "privacyStatus":          privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    try:
        media = MediaFileUpload(
            filepath,
            mimetype="video/mp4",
            resumable=True,
            chunksize=YT_CHUNK_SIZE,
        )
        request  = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress_cb:
                try:
                    progress_cb(status.resumable_progress, status.total_size)
                except Exception:
                    pass

        video_id = response.get("id", "")
        if not video_id:
            return False, "YouTube response-এ video ID নেই।"

        LOGGER.info(f"[ytupload] Uploaded → https://youtu.be/{video_id} ✅")
        return True, video_id

    except Exception as e:
        err = str(e)
        LOGGER.error(f"[ytupload] Upload error: {err}")

        if "quotaExceeded" in err:
            return False, "📊 YouTube API Quota শেষ! কাল আবার চেষ্টা করুন।"
        if "forbidden" in err.lower() or "403" in err:
            return False, "🔒 YouTube permission denied। /ytconnect দিয়ে reconnect করুন।"
        if "uploadLimitExceeded" in err:
            return False, "🚫 YouTube daily upload limit exceeded।"
        if "invalidTitle" in err:
            return False, "❌ Invalid video title।"
        return False, f"YouTube API error: {err[:200]}"


def _upload_bytes_to_youtube_sync(
    creds:          "Credentials",
    file_bytes:     bytes,
    filename:       str,
    title:          str,
    description:    str  = "",
    tags:           list = None,
    privacy_status: str  = "public",
    category_id:    str  = "22",
    progress_cb=None,
) -> tuple:
    """
    Memory (bytes) থেকে সরাসরি YouTube-এ আপলোড করে।
    Telegram video download করে disk-এ না রেখে stream করতে ব্যবহার।

    Returns
    ───────
    (success: bool, video_id_or_error: str)
    """
    youtube = _get_youtube_service_from_creds(creds)
    if not youtube:
        return False, "YouTube service তৈরি করা যায়নি।"

    title       = (title or "Untitled")[:YT_TITLE_MAX]
    description = (description or "")[:YT_DESC_MAX]
    tags        = (tags or [])[:YT_TAG_MAX]

    body = {
        "snippet": {
            "title":      title,
            "description": description,
            "tags":       tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus":           privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    try:
        # BytesIO থেকে MediaIoBaseUpload
        fh    = BytesIO(file_bytes)
        media = MediaIoBaseUpload(
            fh,
            mimetype="video/mp4",
            resumable=True,
            chunksize=YT_CHUNK_SIZE,
        )
        request  = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress_cb:
                try:
                    progress_cb(status.resumable_progress, status.total_size)
                except Exception:
                    pass

        video_id = response.get("id", "")
        if not video_id:
            return False, "YouTube response-এ video ID নেই।"

        LOGGER.info(f"[ytupload] Bytes upload → https://youtu.be/{video_id} ✅")
        return True, video_id

    except Exception as e:
        err = str(e)
        LOGGER.error(f"[ytupload] Bytes upload error: {err}")
        return False, f"YouTube API error: {err[:200]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# INPUT PARSER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_upload_flags(raw: str) -> dict:
    """
    Command flags parse করে।

    Supported:
        --private | --unlisted | --public (default)
        --title "Custom Title"
        referer:<url>

    Returns
    ───────
    {
        "url":          str | None,
        "referer":      str | None,
        "privacy":      str,
        "custom_title": str | None,
    }
    """
    raw = raw.strip()

    # ── Privacy flags ─────────────────────────────────────────────────────
    privacy = "public"
    for flag, val in [("--private", "private"), ("--unlisted", "unlisted"), ("--public", "public")]:
        if flag in raw:
            privacy = val
            raw     = raw.replace(flag, "").strip()

    # ── Custom title: --title "..." ───────────────────────────────────────
    custom_title = None
    for pattern in [r'--title\s+"([^"]+)"', r"--title\s+'([^']+)'"]:
        m = re.search(pattern, raw, re.IGNORECASE)
        if m:
            custom_title = m.group(1).strip()
            raw = (raw[: m.start()] + raw[m.end():]).strip()
            break

    # ── URL + Referer (ytdl.py function) ─────────────────────────────────
    url, referer = parse_url_and_referer(raw) if raw else (None, None)

    return {
        "url":          url,
        "referer":      referer,
        "privacy":      privacy,
        "custom_title": custom_title,
    }


def _parse_ytsend_flags(raw: str) -> dict:
    """
    /ytsend command flags parse করে (URL নেই, শুধু flags)।

    Returns
    ───────
    {"privacy": str, "custom_title": str | None}
    """
    parsed = _parse_upload_flags(raw)
    return {
        "privacy":      parsed["privacy"],
        "custom_title": parsed["custom_title"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PREMIUM CHECK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _is_premium(user_id: int) -> bool:
    """MongoDB-তে premium plan check করে।"""
    now = datetime.utcnow()
    for col in [prem_plan1, prem_plan2, prem_plan3]:
        plan = await col.find_one({"user_id": user_id})
        if plan and plan.get("expiry_date", now) > now:
            return True
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UPLOAD LOG — MongoDB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _save_upload_log(
    user_id:      int,
    user_name:    str,
    source_type:  str,     # "url" | "telegram"
    source_url:   str,
    yt_video_id:  str,
    yt_title:     str,
    privacy:      str,
    file_size:    int,
    status:       str,     # "success" | "failed"
    error_msg:    str = "",
    channel_id:   str = "",
    channel_name: str = "",
    elapsed_sec:  float = 0,
):
    """
    প্রতিটি upload-এর log MongoDB-তে সেভ করে।

    Schema (yt_upload_logs):
    ────────────────────────
    {
        user_id      : int       — Telegram user ID
        user_name    : str       — Telegram username/name
        source_type  : str       — "url" বা "telegram"
        source_url   : str       — Source URL (Telegram-এর জন্য file_id)
        yt_video_id  : str       — YouTube video ID
        yt_title     : str       — YouTube ভিডিওর title
        yt_url       : str       — YouTube ভিডিওর full URL
        channel_id   : str       — User-এর YouTube channel ID
        channel_name : str       — User-এর YouTube channel name
        privacy      : str       — public/private/unlisted
        file_size    : int       — bytes
        status       : str       — "success" | "failed"
        error_msg    : str       — error থাকলে
        elapsed_sec  : float     — সময় (সেকেন্ড)
        uploaded_at  : datetime  — আপলোড সময়
    }
    """
    try:
        await yt_uploads_col.insert_one({
            "user_id":      user_id,
            "user_name":    user_name,
            "source_type":  source_type,
            "source_url":   source_url[:500] if source_url else "",
            "yt_video_id":  yt_video_id,
            "yt_title":     yt_title[:200] if yt_title else "",
            "yt_url":       f"https://youtu.be/{yt_video_id}" if yt_video_id else "",
            "channel_id":   channel_id,
            "channel_name": channel_name,
            "privacy":      privacy,
            "file_size":    file_size,
            "status":       status,
            "error_msg":    error_msg[:500] if error_msg else "",
            "elapsed_sec":  round(elapsed_sec, 2),
            "uploaded_at":  datetime.utcnow(),
        })
    except Exception as e:
        LOGGER.warning(f"[ytupload log] DB save error: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROGRESS UPDATER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _yt_upload_progress_updater(msg, progress_data: dict):
    """YouTube upload real-time progress updater।"""
    last_text = ""
    while not progress_data.get("done"):
        await asyncio.sleep(4)
        if progress_data.get("done"):
            break
        uploaded = progress_data.get("uploaded", 0)
        total    = progress_data.get("total", 0)
        pct      = min((uploaded / total) * 100, 100) if total > 0 else 0
        pbar     = _make_progress_bar(pct)
        text = (
            f"📤 **Uploading to YouTube...**\n\n"
            f"`{pbar}`\n"
            f"**{pct:.1f}%** | "
            f"{get_readable_file_size(uploaded)}/{get_readable_file_size(total)}"
        )
        if text != last_text:
            try:
                await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
                last_text = text
            except Exception:
                pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOG GROUP NOTIFIER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _notify_log_group(
    client,
    user,
    source_type:  str,
    source_url:   str,
    video_title:  str,
    yt_video_id:  str,
    channel_name: str,
    privacy:      str,
    file_size:    int,
    status:       str,
    elapsed_sec:  float = 0,
    error_msg:    str   = "",
):
    """LOG_GROUP_ID-তে admin notification পাঠায়।"""
    if not LOG_GROUP_ID:
        return
    try:
        user_id   = getattr(user, "id", "?")
        fname     = getattr(user, "first_name", "") or ""
        lname     = getattr(user, "last_name", "")  or ""
        full_name = f"{fname} {lname}".strip() or "Unknown"
        username  = f"@{user.username}" if getattr(user, "username", None) else "N/A"
        user_link = f"[{full_name}](tg://user?id={user_id})"

        status_icon  = "✅" if status == "success" else "❌"
        src_icon     = "📨 Telegram" if source_type == "telegram" else "🌐 URL"
        privacy_map  = {"public": "🌐 Public", "private": "🔒 Private", "unlisted": "🔗 Unlisted"}
        privacy_txt  = privacy_map.get(privacy, privacy)
        elapsed_str  = get_readable_time(int(elapsed_sec)) if elapsed_sec > 0 else "N/A"
        size_str     = get_readable_file_size(file_size) if file_size > 0 else "N/A"
        yt_url       = f"https://youtu.be/{yt_video_id}" if yt_video_id else "N/A"

        text = (
            f"📤 **YT Upload** {status_icon}\n"
            f"{'─' * 28}\n\n"
            f"**👤 User**\n"
            f"• {user_link} | `{username}` | `{user_id}`\n\n"
            f"**📺 Channel:** `{channel_name}`\n"
            f"**📌 Source:** `{src_icon}`\n"
            f"**🎬 Title:** `{video_title[:80]}`\n"
            f"**🔒 Privacy:** {privacy_txt}\n"
            f"**📦 Size:** `{size_str}`\n"
            f"**⏱ Time:** `{elapsed_str}`\n"
        )
        if status == "failed" and error_msg:
            text += f"**❌ Error:** `{error_msg[:150]}`\n"
        if yt_url != "N/A":
            text += f"\n**🔗 YouTube:** {yt_url}"

        buttons = []
        if yt_url != "N/A":
            buttons.append([InlineKeyboardButton("▶️ YouTube-এ দেখুন", url=yt_url)])

        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
            disable_web_page_preview=True,
        )
    except Exception as e:
        LOGGER.warning(f"[ytupload notify] Failed: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KEYBOARD BUILDERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _privacy_keyboard(chat_id: int, prefix: str = "ytup") -> InlineKeyboardMarkup:
    """Privacy selection keyboard।"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 Public",   callback_data=f"{prefix}_pub_{chat_id}"),
            InlineKeyboardButton("🔒 Private",  callback_data=f"{prefix}_prv_{chat_id}"),
            InlineKeyboardButton("🔗 Unlisted", callback_data=f"{prefix}_unl_{chat_id}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"{prefix}_cancel_{chat_id}")],
    ])


PRIVACY_FROM_CB = {"pub": "public", "prv": "private", "unl": "unlisted"}
PRIVACY_LABELS  = {"public": "🌐 Public", "private": "🔒 Private", "unlisted": "🔗 Unlisted"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN SETUP FUNCTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def setup_ytupload_handler(app: Client):
    """
    সমস্ত handler register করে।
    bot startup-এ একবার call করতে হবে।
    """

    # ═════════════════════════════════════════════════════════════════════
    # /ytconnect — YouTube Account Connect
    # ═════════════════════════════════════════════════════════════════════

    async def ytconnect_command(client: Client, message: Message):
        """
        User-এর YouTube account connect করে।

        Flow:
          1. OAuth flow তৈরি করো
          2. Auth URL user-কে পাঠাও
          3. User authorization code copy করে /ytcode <code> দিয়ে paste করবে
          4. Token exchange করো
          5. Channel info fetch করো
          6. MongoDB-তে সেভ করো
        """
        user_id = message.from_user.id

        if not GOOGLE_API_AVAILABLE:
            await message.reply_text(
                "❌ **Google API library ইনস্টল নেই!**\n\n"
                "```\npip install google-api-python-client "
                "google-auth-oauthlib google-auth-httplib2\n```",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if not os.path.exists(CREDENTIALS_FILE):
            await message.reply_text(
                "❌ **Bot setup হয়নি!**\n\n"
                "Admin-কে জানান: `yt_credentials.json` file দরকার।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── ইতিমধ্যে connected থাকলে জানাও ─────────────────────────────
        existing = await _get_user_channel_info(user_id)
        if existing and existing.get("channel_name"):
            await message.reply_text(
                f"✅ **আপনি ইতিমধ্যে connected!**\n\n"
                f"📺 **Channel:** `{existing['channel_name']}`\n\n"
                f"নতুন channel connect করতে আগে /ytdisconnect করুন।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── OAuth flow তৈরি করো ──────────────────────────────────────────
        flow = _create_oauth_flow()
        if not flow:
            await message.reply_text(
                "❌ **OAuth setup error!** Admin-কে জানান।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        # ── Session-এ flow সেভ করো ───────────────────────────────────────
        oauth_sessions[user_id] = {
            "flow":       flow,
            "created_at": time(),
        }

        await message.reply_text(
            "🔐 **YouTube Account Connect করুন**\n\n"
            "**Step 1:** নিচের লিংকে ক্লিক করুন:\n"
            f"[👉 Google এ Login করুন]({auth_url})\n\n"
            "**Step 2:** Google Account দিয়ে Login করুন\n"
            "এবং YouTube permission Allow করুন\n\n"
            "**Step 3:** দেখানো **Authorization Code** copy করুন\n\n"
            "**Step 4:** নিচের command দিন:\n"
            "`/ytcode <আপনার_code>`\n\n"
            "⏳ _এই session 15 মিনিট পর expire হবে_",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )

    # ═════════════════════════════════════════════════════════════════════
    # /ytcode — OAuth Code Submit
    # ═════════════════════════════════════════════════════════════════════

    async def ytcode_command(client: Client, message: Message):
        """User-এর authorization code receive করে token exchange করে।"""
        user_id = message.from_user.id

        if len(message.command) < 2:
            await message.reply_text(
                "**Usage:** `/ytcode <authorization_code>`\n\n"
                "আগে /ytconnect দিয়ে code পান।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        session = oauth_sessions.get(user_id)
        if not session:
            await message.reply_text(
                "❌ **Session নেই বা Expire হয়েছে!**\n\n"
                "আবার /ytconnect দিয়ে শুরু করুন।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Session expiry check (15 মিনিট)
        if time() - session["created_at"] > SESSION_EXPIRY:
            oauth_sessions.pop(user_id, None)
            await message.reply_text(
                "⏰ **Session Expired!**\n\nআবার /ytconnect করুন।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        auth_code = message.command[1].strip()
        flow      = session["flow"]

        status_msg = await message.reply_text(
            "🔄 **Verifying code...**",
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            loop = asyncio.get_event_loop()
            # Token exchange (synchronous → executor-এ)
            await loop.run_in_executor(
                None,
                lambda: flow.fetch_token(code=auth_code),
            )
            creds = flow.credentials

            # Channel info fetch
            await status_msg.edit_text(
                "📺 **Channel info নেওয়া হচ্ছে...**",
                parse_mode=ParseMode.MARKDOWN,
            )
            channel_info = await loop.run_in_executor(
                None,
                lambda: asyncio.run(_fetch_channel_info(creds))
                if asyncio.get_event_loop().is_running()
                else _fetch_channel_info(creds),
            )

            # ── async ভেতরে sync call সমস্যা এড়াতে ──────────────────────
            try:
                channel_info = _fetch_channel_info_sync(creds)
            except Exception:
                channel_info = {"id": "", "title": "Unknown Channel"}

            # MongoDB-তে সেভ করো
            await _save_user_token(user_id, creds, channel_info)
            oauth_sessions.pop(user_id, None)

            ch_name = channel_info.get("title", "Unknown")
            ch_id   = channel_info.get("id", "")
            ch_url  = f"https://youtube.com/channel/{ch_id}" if ch_id else ""

            await status_msg.edit_text(
                f"✅ **YouTube Successfully Connected!**\n\n"
                f"📺 **Channel:** `{ch_name}`\n"
                f"{'🔗 ' + ch_url if ch_url else ''}\n\n"
                f"এখন আপনি ব্যবহার করতে পারবেন:\n"
                f"• `/ytupload <url>` — যেকোনো সাইট থেকে আপলোড\n"
                f"• ভিডিও reply করে `/ytsend` — Telegram থেকে আপলোড",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )

        except Exception as e:
            LOGGER.error(f"[ytupload] OAuth token exchange error for {user_id}: {e}")
            oauth_sessions.pop(user_id, None)
            await status_msg.edit_text(
                f"❌ **Code Verification Failed!**\n\n"
                f"Error: `{str(e)[:150]}`\n\n"
                f"আবার /ytconnect দিয়ে চেষ্টা করুন।",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ═════════════════════════════════════════════════════════════════════
    # /ytdisconnect — YouTube Disconnect
    # ═════════════════════════════════════════════════════════════════════

    async def ytdisconnect_command(client: Client, message: Message):
        """User-এর YouTube token MongoDB থেকে delete করে।"""
        user_id = message.from_user.id
        deleted = await _delete_user_token(user_id)

        if deleted:
            await message.reply_text(
                "✅ **YouTube Disconnected!**\n\n"
                "আপনার সব token মুছে ফেলা হয়েছে।\n"
                "আবার connect করতে: /ytconnect",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await message.reply_text(
                "ℹ️ **আপনি connected ছিলেন না।**\n\n"
                "Connect করতে: /ytconnect",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ═════════════════════════════════════════════════════════════════════
    # /ytme — Connected Channel Info
    # ═════════════════════════════════════════════════════════════════════

    async def ytme_command(client: Client, message: Message):
        """User-এর connected YouTube channel info দেখায়।"""
        user_id = message.from_user.id
        info    = await _get_user_channel_info(user_id)

        if not info or not info.get("channel_name"):
            await message.reply_text(
                "❌ **আপনি কোনো YouTube channel connect করেননি।**\n\n"
                "Connect করতে: /ytconnect",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Token validity check
        creds = await _load_user_token(user_id)
        is_valid = creds is not None

        ch_name  = info.get("channel_name", "Unknown")
        ch_id    = info.get("channel_id", "")
        ch_url   = f"https://youtube.com/channel/{ch_id}" if ch_id else "N/A"
        conn_at  = info.get("connected_at")
        conn_str = conn_at.strftime("%d %b %Y, %H:%M UTC") if conn_at else "N/A"
        upd_at   = info.get("updated_at")
        upd_str  = upd_at.strftime("%d %b %Y, %H:%M UTC") if upd_at else "N/A"

        # Upload count
        upload_count = await yt_uploads_col.count_documents(
            {"user_id": user_id, "status": "success"}
        )

        await message.reply_text(
            f"📺 **Your YouTube Channel**\n"
            f"{'─' * 28}\n\n"
            f"**Channel:** `{ch_name}`\n"
            f"**Channel ID:** `{ch_id}`\n"
            f"**URL:** {ch_url}\n\n"
            f"**🔑 Token Status:** {'✅ Valid' if is_valid else '❌ Invalid (reconnect করুন)'}\n"
            f"**📅 Connected:** `{conn_str}`\n"
            f"**🔄 Last Updated:** `{upd_str}`\n\n"
            f"**📊 Total Uploads:** `{upload_count}`\n\n"
            f"• `/ytupload <url>` — URL থেকে আপলোড\n"
            f"• Reply + `/ytsend` — Telegram ভিডিও আপলোড\n"
            f"• /ytdisconnect — Disconnect",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )

    # ═════════════════════════════════════════════════════════════════════
    # /ytupload — URL থেকে YouTube Upload
    # ═════════════════════════════════════════════════════════════════════

    async def ytupload_command(client: Client, message: Message):
        """
        যেকোনো website URL থেকে yt-dlp দিয়ে ডাউনলোড করে
        user-এর নিজের YouTube channel-এ আপলোড করে।

        Supported:
          /ytupload <url>
          /ytupload <url> --private
          /ytupload <url> --unlisted
          /ytupload <url> --title "Custom Title"
          /ytupload <url> referer:<site>
        """
        user_id = message.from_user.id

        # ── Dependencies check ────────────────────────────────────────────
        if not GOOGLE_API_AVAILABLE:
            await message.reply_text(
                "❌ **Google API library ইনস্টল নেই!**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── Usage help ────────────────────────────────────────────────────
        if len(message.command) < 2:
            await message.reply_text(
                "📤 **YouTube Direct Uploader**\n\n"
                "যেকোনো সাইট থেকে ভিডিও ডাউনলোড করে নিজের YouTube Channel-এ আপলোড!\n\n"
                "**Usage:**\n"
                "`/ytupload <URL>`\n"
                "`/ytupload <URL> --private`\n"
                "`/ytupload <URL> --unlisted`\n"
                "`/ytupload <URL> --title \"Custom Title\"`\n"
                "`/ytupload <URL> referer:<site_url>`\n\n"
                "**📺 নিজের Channel Connect করুন:** /ytconnect\n"
                "**📊 Channel Info দেখুন:** /ytme",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── YouTube Connection check ──────────────────────────────────────
        if not await _is_youtube_connected(user_id):
            await message.reply_text(
                "❌ **YouTube Channel Connect করা নেই!**\n\n"
                "প্রথমে আপনার YouTube channel connect করুন:\n"
                "/ytconnect",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── Input parse ───────────────────────────────────────────────────
        text_parts = message.text.split(None, 1)
        raw        = text_parts[1].strip() if len(text_parts) > 1 else ""
        parsed     = _parse_upload_flags(raw)

        url          = parsed["url"]
        referer      = parsed["referer"]
        privacy      = parsed["privacy"]
        custom_title = parsed["custom_title"]

        if not url:
            await message.reply_text(
                "❌ **Valid URL দিন।**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── HLS/CDN warning ───────────────────────────────────────────────
        if is_hls_url(url) and not referer:
            await message.reply_text(
                "⚠️ **HLS Stream Detected!**\n"
                "Error হলে Referer দিন:\n"
                f"`/ytupload {url} referer:<website_url>`\n\n"
                "⏳ _Referer ছাড়াই চেষ্টা হচ্ছে..._",
                parse_mode=ParseMode.MARKDOWN,
            )
        elif is_protected_cdn_url(url) and not referer:
            await message.reply_text(
                "⚠️ **Protected CDN Detected!**\n"
                "Error হলে Referer সহ চেষ্টা করুন।\n\n"
                "⏳ _চেষ্টা হচ্ছে..._",
                parse_mode=ParseMode.MARKDOWN,
            )

        # ── Video info fetch ──────────────────────────────────────────────
        warp_ok    = _is_warp_available()
        status_msg = await message.reply_text(
            f"🔍 **Analyzing URL...**\n"
            f"_{'🟢 WARP' if warp_ok else '🟡 Direct'}"
            f"{' | 🔗 Referer Active' if referer else ''}_",
            parse_mode=ParseMode.MARKDOWN,
        )

        loop = asyncio.get_event_loop()
        info, err = await loop.run_in_executor(
            None,
            lambda: get_single_video_info(url, referer),
        )

        if not info:
            err_low = (err or "").lower()
            if (is_hls_url(url) or is_protected_cdn_url(url)) and (
                "403" in err_low or "forbidden" in err_low
            ) and not referer:
                await status_msg.edit_text(
                    "❌ **403 Forbidden!**\n\n"
                    "Referer সহ আবার চেষ্টা করুন:\n"
                    f"`/ytupload {url} referer:<website_url>`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await status_msg.edit_text(
                    f"❌ **Video info পাওয়া যায়নি!**\n\n"
                    f"{_friendly_error(err) if err else 'Unknown error'}",
                    parse_mode=ParseMode.MARKDOWN,
                )
            return

        # ── Session store করো ─────────────────────────────────────────────
        title    = (custom_title or info.get("title") or "Untitled")[:YT_TITLE_MAX]
        duration = int(info.get("duration", 0) or 0)
        uploader = (info.get("uploader") or info.get("channel") or "Unknown")[:50]
        dur_str  = get_readable_time(duration) if duration else "Unknown"

        ytup_sessions[message.chat.id] = {
            "mode":         "url",           # URL mode
            "user_id":      user_id,
            "url":          url,
            "referer":      referer,
            "info":         info,
            "privacy":      privacy,
            "custom_title": custom_title,
            "title":        title,
            "created_at":   time(),
            "user_obj":     message.from_user,
        }

        # ── Privacy flag দেওয়া থাকলে keyboard skip করো ──────────────────
        if privacy != "public":
            await status_msg.edit_text(
                f"📹 **{title[:60]}**\n\n"
                f"👤 **Channel:** {uploader}\n"
                f"⏱ **Duration:** {dur_str}\n"
                f"🔒 **Privacy:** {PRIVACY_LABELS[privacy]}"
                f"{chr(10) + '🔗 Referer Active' if referer else ''}\n\n"
                f"👇 **YouTube-এ আপলোড করবো?**",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"✅ Upload ({PRIVACY_LABELS[privacy]})",
                        callback_data=f"ytup_confirm_{message.chat.id}",
                    )],
                    [InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data=f"ytup_cancel_{message.chat.id}",
                    )],
                ]),
                disable_web_page_preview=True,
            )
        else:
            # Privacy keyboard দেখাও
            await status_msg.edit_text(
                f"📹 **{title[:60]}**\n\n"
                f"👤 **Channel:** {uploader}\n"
                f"⏱ **Duration:** {dur_str}"
                f"{chr(10) + '🔗 Referer Active' if referer else ''}\n\n"
                f"👇 **YouTube Privacy বেছে নিন:**",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_privacy_keyboard(message.chat.id, "ytup"),
                disable_web_page_preview=True,
            )

    # ═════════════════════════════════════════════════════════════════════
    # /ytsend — Telegram Video Reply → YouTube Upload
    # ═════════════════════════════════════════════════════════════════════

    async def ytsend_command(client: Client, message: Message):
        """
        Telegram-এর কোনো ভিডিও-তে reply করে এই command দিলে
        সেই ভিডিও user-এর YouTube channel-এ আপলোড হবে।

        Usage:
          [ভিডিওতে reply করে] /ytsend
          [ভিডিওতে reply করে] /ytsend --private
          [ভিডিওতে reply করে] /ytsend --unlisted
          [ভিডিওতে reply করে] /ytsend --title "Custom Title"
        """
        user_id = message.from_user.id

        if not GOOGLE_API_AVAILABLE:
            await message.reply_text(
                "❌ **Google API library ইনস্টল নেই!**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── YouTube connection check ──────────────────────────────────────
        if not await _is_youtube_connected(user_id):
            await message.reply_text(
                "❌ **YouTube Channel Connect করা নেই!**\n\n"
                "প্রথমে: /ytconnect",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── Reply check ───────────────────────────────────────────────────
        replied = message.reply_to_message
        if not replied:
            await message.reply_text(
                "❌ **কোনো ভিডিওতে Reply করে command দিন!**\n\n"
                "**Usage:**\n"
                "১. যে ভিডিওটি আপলোড করতে চান সেটিতে reply করুন\n"
                "২. লিখুন: `/ytsend`\n"
                "৩. বা: `/ytsend --private`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── Replied message-এ video আছে কিনা check ───────────────────────
        media = (
            replied.video
            or replied.document
            or replied.animation
        )

        if not media:
            await message.reply_text(
                "❌ **Replied message-এ কোনো Video নেই!**\n\n"
                "Video, Document (video file), বা GIF-এ reply করুন।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── Flags parse ───────────────────────────────────────────────────
        text_parts = message.text.split(None, 1)
        raw        = text_parts[1].strip() if len(text_parts) > 1 else ""
        parsed     = _parse_ytsend_flags(raw)
        privacy      = parsed["privacy"]
        custom_title = parsed["custom_title"]

        # ── File info ─────────────────────────────────────────────────────
        file_size  = getattr(media, "file_size", 0) or 0
        file_name  = getattr(media, "file_name", None) or ""
        mime_type  = getattr(media, "mime_type", "video/mp4") or "video/mp4"
        duration   = getattr(media, "duration", 0) or 0
        file_id    = media.file_id

        # ── Title নির্ধারণ করো ────────────────────────────────────────────
        tg_caption = (replied.caption or replied.text or "")[:80]
        auto_title = (
            custom_title
            or (file_name.rsplit(".", 1)[0] if file_name else "")
            or tg_caption
            or f"Telegram Video {datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        )[:YT_TITLE_MAX]

        # ── 2GB size check ────────────────────────────────────────────────
        if file_size > MAX_FILE_SIZE:
            await message.reply_text(
                f"❌ **File অনেক বড়!**\n"
                f"📦 `{get_readable_file_size(file_size)}` > "
                f"Limit `{get_readable_file_size(MAX_FILE_SIZE)}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── Session store ─────────────────────────────────────────────────
        ytup_sessions[message.chat.id] = {
            "mode":         "telegram",      # Telegram mode
            "user_id":      user_id,
            "file_id":      file_id,
            "file_size":    file_size,
            "mime_type":    mime_type,
            "duration":     duration,
            "file_name":    file_name,
            "privacy":      privacy,
            "custom_title": custom_title,
            "title":        auto_title,
            "created_at":   time(),
            "user_obj":     message.from_user,
        }

        dur_str   = get_readable_time(duration) if duration else "Unknown"
        size_str  = get_readable_file_size(file_size) if file_size else "Unknown"
        mime_icon = "🎬" if "video" in mime_type else "📄"

        if privacy != "public":
            # Flag দেওয়া → সরাসরি confirm
            await message.reply_text(
                f"{mime_icon} **Telegram Video → YouTube**\n\n"
                f"📝 **Title:** `{auto_title[:60]}`\n"
                f"⏱ **Duration:** {dur_str}\n"
                f"📦 **Size:** {size_str}\n"
                f"🔒 **Privacy:** {PRIVACY_LABELS[privacy]}\n\n"
                f"👇 **YouTube-এ আপলোড করবো?**",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"✅ Upload ({PRIVACY_LABELS[privacy]})",
                        callback_data=f"ytup_confirm_{message.chat.id}",
                    )],
                    [InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data=f"ytup_cancel_{message.chat.id}",
                    )],
                ]),
            )
        else:
            await message.reply_text(
                f"{mime_icon} **Telegram Video → YouTube**\n\n"
                f"📝 **Title:** `{auto_title[:60]}`\n"
                f"⏱ **Duration:** {dur_str}\n"
                f"📦 **Size:** {size_str}\n\n"
                f"👇 **Privacy বেছে নিন:**",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_privacy_keyboard(message.chat.id, "ytup"),
            )

    # ═════════════════════════════════════════════════════════════════════
    # CORE: URL Mode Download + Upload
    # ═════════════════════════════════════════════════════════════════════

    async def _execute_url_upload(
        client,
        callback_query: CallbackQuery,
        session:        dict,
        privacy:        str,
    ):
        """
        URL থেকে yt-dlp দিয়ে ডাউনলোড করে
        user-এর YouTube channel-এ আপলোড করে।
        """
        chat_id  = callback_query.message.chat.id
        user_id  = session["user_id"]
        url      = session["url"]
        referer  = session.get("referer")
        info     = session.get("info", {})
        title    = session.get("title", "Untitled")
        user_obj = session.get("user_obj", callback_query.from_user)

        description = (info.get("description") or "")[:YT_DESC_MAX]
        tags        = (info.get("tags") or [])[:YT_TAG_MAX]

        # ── User credentials load করো ─────────────────────────────────────
        creds = await _load_user_token(user_id)
        if not creds:
            await callback_query.message.edit_text(
                "❌ **YouTube token invalid!**\n\n"
                "আবার /ytconnect করুন।",
                parse_mode=ParseMode.MARKDOWN,
            )
            ytup_sessions.pop(chat_id, None)
            return

        # ── Channel info নাও ──────────────────────────────────────────────
        ch_info  = await _get_user_channel_info(user_id)
        ch_name  = (ch_info or {}).get("channel_name", "Unknown")
        ch_id    = (ch_info or {}).get("channel_id", "")

        overall_start = time()
        warp_ok       = _is_warp_available()

        # Step 1: Download
        user_dir = os.path.join(DOWNLOAD_DIR, f"ytup_{user_id}")
        os.makedirs(user_dir, exist_ok=True)

        await callback_query.message.edit_text(
            f"📥 **Downloading...**\n"
            f"_{'🟢 WARP' if warp_ok else '🟡 Direct'}"
            f"{' | 🔗 Referer' if referer else ''}_\n\n"
            f"🎬 `{title[:50]}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        loop          = asyncio.get_event_loop()
        progress_data = {"downloaded": 0, "total": 0, "speed": 0, "eta": 0, "done": False}
        prog_task     = asyncio.create_task(
            _ytdl_progress_updater(callback_query.message, progress_data)
        )

        try:
            dl_ok, dl_result = await loop.run_in_executor(
                None,
                lambda: download_single_video(
                    url, user_dir,
                    None,       # format → best auto
                    False,      # audio_only → False
                    progress_data,
                    True,       # noplaylist
                    referer,    # Referer ✅
                ),
            )
        finally:
            progress_data["done"] = True
            try:
                await prog_task
            except Exception:
                pass

        if not dl_ok:
            await callback_query.message.edit_text(
                f"❌ **Download failed!**\n\n{_friendly_error(dl_result)}",
                parse_mode=ParseMode.MARKDOWN,
            )
            _cleanup_dir(user_dir)
            ytup_sessions.pop(chat_id, None)
            asyncio.create_task(_save_upload_log(
                user_id, _user_display(user_obj), "url", url,
                "", title, privacy, 0, "failed", _friendly_error(dl_result),
                ch_id, ch_name, time() - overall_start,
            ))
            return

        filepath  = dl_result
        file_size = os.path.getsize(filepath)

        # 2GB check
        if file_size > MAX_FILE_SIZE:
            os.remove(filepath)
            await callback_query.message.edit_text(
                f"❌ **File অনেক বড়!** `{get_readable_file_size(file_size)}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            _cleanup_dir(user_dir)
            ytup_sessions.pop(chat_id, None)
            return

        # Step 2: YouTube Upload
        yt_progress = {"uploaded": 0, "total": file_size, "done": False}

        def _prog_cb(uploaded, total):
            yt_progress["uploaded"] = uploaded or 0
            yt_progress["total"]    = total or file_size

        await callback_query.message.edit_text(
            f"📤 **Uploading to YouTube...**\n\n"
            f"📺 **Channel:** `{ch_name}`\n"
            f"🎬 `{title[:50]}`\n"
            f"📦 `{get_readable_file_size(file_size)}`\n"
            f"🔒 `{PRIVACY_LABELS[privacy]}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        yt_prog_task = asyncio.create_task(
            _yt_upload_progress_updater(callback_query.message, yt_progress)
        )

        try:
            yt_ok, yt_result = await loop.run_in_executor(
                None,
                lambda: _upload_file_to_youtube_sync(
                    creds, filepath, title, description,
                    tags, privacy, "22", _prog_cb,
                ),
            )
        finally:
            yt_progress["done"] = True
            try:
                await yt_prog_task
            except Exception:
                pass

        # Cleanup
        try:
            os.remove(filepath)
        except Exception:
            pass
        _cleanup_dir(user_dir)
        ytup_sessions.pop(chat_id, None)

        elapsed = time() - overall_start

        if yt_ok:
            video_id = yt_result
            yt_url   = f"https://youtu.be/{video_id}"

            await callback_query.message.edit_text(
                f"✅ **YouTube Upload সফল!**\n\n"
                f"📺 **Channel:** `{ch_name}`\n"
                f"🎬 **{title[:60]}**\n\n"
                f"🔗 **Link:** {yt_url}\n"
                f"🔒 **Privacy:** {PRIVACY_LABELS[privacy]}\n"
                f"📦 **Size:** `{get_readable_file_size(file_size)}`\n"
                f"⏱ **Time:** `{get_readable_time(int(elapsed))}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ YouTube-এ দেখুন", url=yt_url)],
                ]),
            )

            asyncio.create_task(_save_upload_log(
                user_id, _user_display(user_obj), "url", url,
                video_id, title, privacy, file_size, "success",
                "", ch_id, ch_name, elapsed,
            ))
            asyncio.create_task(_notify_log_group(
                client, user_obj, "url", url, title,
                video_id, ch_name, privacy, file_size, "success", elapsed,
            ))
        else:
            await callback_query.message.edit_text(
                f"❌ **YouTube Upload Failed!**\n\n{yt_result}",
                parse_mode=ParseMode.MARKDOWN,
            )
            asyncio.create_task(_save_upload_log(
                user_id, _user_display(user_obj), "url", url,
                "", title, privacy, file_size, "failed",
                yt_result, ch_id, ch_name, elapsed,
            ))
            asyncio.create_task(_notify_log_group(
                client, user_obj, "url", url, title,
                "", ch_name, privacy, file_size, "failed", elapsed, yt_result,
            ))

    # ═════════════════════════════════════════════════════════════════════
    # CORE: Telegram Mode Download + Upload
    # ═════════════════════════════════════════════════════════════════════

    async def _execute_telegram_upload(
        client,
        callback_query: CallbackQuery,
        session:        dict,
        privacy:        str,
    ):
        """
        Telegram ভিডিও download করে user-এর YouTube channel-এ আপলোড করে।
        """
        chat_id   = callback_query.message.chat.id
        user_id   = session["user_id"]
        file_id   = session["file_id"]
        file_size = session.get("file_size", 0)
        title     = session.get("title", "Untitled")
        duration  = session.get("duration", 0)
        user_obj  = session.get("user_obj", callback_query.from_user)

        # ── Credentials load ──────────────────────────────────────────────
        creds = await _load_user_token(user_id)
        if not creds:
            await callback_query.message.edit_text(
                "❌ **YouTube token invalid!** আবার /ytconnect করুন।",
                parse_mode=ParseMode.MARKDOWN,
            )
            ytup_sessions.pop(chat_id, None)
            return

        ch_info  = await _get_user_channel_info(user_id)
        ch_name  = (ch_info or {}).get("channel_name", "Unknown")
        ch_id    = (ch_info or {}).get("channel_id", "")

        overall_start = time()

        # Step 1: Telegram থেকে Download
        await callback_query.message.edit_text(
            f"📥 **Telegram থেকে Downloading...**\n\n"
            f"📺 **Channel:** `{ch_name}`\n"
            f"🎬 `{title[:50]}`\n"
            f"📦 `{get_readable_file_size(file_size)}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        user_dir  = os.path.join(DOWNLOAD_DIR, f"tgup_{user_id}")
        os.makedirs(user_dir, exist_ok=True)
        filepath  = os.path.join(user_dir, f"{file_id[:20]}.mp4")

        try:
            # Pyrogram দিয়ে file download করো
            await client.download_media(
                file_id,
                file_name=filepath,
            )
        except Exception as e:
            await callback_query.message.edit_text(
                f"❌ **Telegram Download Failed!**\n`{str(e)[:150]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            _cleanup_dir(user_dir)
            ytup_sessions.pop(chat_id, None)
            return

        if not os.path.exists(filepath):
            await callback_query.message.edit_text(
                "❌ **File download হয়নি!**",
                parse_mode=ParseMode.MARKDOWN,
            )
            _cleanup_dir(user_dir)
            ytup_sessions.pop(chat_id, None)
            return

        actual_size = os.path.getsize(filepath)

        # Step 2: YouTube Upload
        yt_progress = {"uploaded": 0, "total": actual_size, "done": False}

        def _prog_cb(uploaded, total):
            yt_progress["uploaded"] = uploaded or 0
            yt_progress["total"]    = total or actual_size

        await callback_query.message.edit_text(
            f"📤 **Uploading to YouTube...**\n\n"
            f"📺 **Channel:** `{ch_name}`\n"
            f"🎬 `{title[:50]}`\n"
            f"📦 `{get_readable_file_size(actual_size)}`\n"
            f"🔒 `{PRIVACY_LABELS[privacy]}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        loop         = asyncio.get_event_loop()
        yt_prog_task = asyncio.create_task(
            _yt_upload_progress_updater(callback_query.message, yt_progress)
        )

        try:
            yt_ok, yt_result = await loop.run_in_executor(
                None,
                lambda: _upload_file_to_youtube_sync(
                    creds, filepath, title, "",
                    [], privacy, "22", _prog_cb,
                ),
            )
        finally:
            yt_progress["done"] = True
            try:
                await yt_prog_task
            except Exception:
                pass

        # Cleanup
        try:
            os.remove(filepath)
        except Exception:
            pass
        _cleanup_dir(user_dir)
        ytup_sessions.pop(chat_id, None)

        elapsed = time() - overall_start

        if yt_ok:
            video_id = yt_result
            yt_url   = f"https://youtu.be/{video_id}"

            await callback_query.message.edit_text(
                f"✅ **YouTube Upload সফল!**\n\n"
                f"📺 **Channel:** `{ch_name}`\n"
                f"🎬 **{title[:60]}**\n\n"
                f"🔗 **Link:** {yt_url}\n"
                f"🔒 **Privacy:** {PRIVACY_LABELS[privacy]}\n"
                f"📦 **Size:** `{get_readable_file_size(actual_size)}`\n"
                f"⏱ **Time:** `{get_readable_time(int(elapsed))}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ YouTube-এ দেখুন", url=yt_url)],
                ]),
            )

            asyncio.create_task(_save_upload_log(
                user_id, _user_display(user_obj), "telegram", file_id,
                video_id, title, privacy, actual_size, "success",
                "", ch_id, ch_name, elapsed,
            ))
            asyncio.create_task(_notify_log_group(
                client, user_obj, "telegram", file_id, title,
                video_id, ch_name, privacy, actual_size, "success", elapsed,
            ))
        else:
            await callback_query.message.edit_text(
                f"❌ **YouTube Upload Failed!**\n\n{yt_result}",
                parse_mode=ParseMode.MARKDOWN,
            )
            asyncio.create_task(_save_upload_log(
                user_id, _user_display(user_obj), "telegram", file_id,
                "", title, privacy, actual_size, "failed",
                yt_result, ch_id, ch_name, elapsed,
            ))

    # ═════════════════════════════════════════════════════════════════════
    # CALLBACKS
    # ═════════════════════════════════════════════════════════════════════

    @app.on_callback_query(filters.regex(r"^ytup_(pub|prv|unl)_"))
    async def ytup_privacy_callback(client, callback_query: CallbackQuery):
        """Privacy selection callback — উভয় mode-এর জন্য।"""
        data    = callback_query.data
        chat_id = callback_query.message.chat.id
        user_id = callback_query.from_user.id

        session = ytup_sessions.get(chat_id)
        if not session or session["user_id"] != user_id:
            await callback_query.answer("❌ Session expired!", show_alert=True)
            return

        # ── Privacy extract ────────────────────────────────────────────────
        # Pattern: ytup_{pub|prv|unl}_{chat_id}
        parts   = data.split("_")
        key     = parts[1] if len(parts) > 1 else "pub"
        privacy = PRIVACY_FROM_CB.get(key, "public")

        await callback_query.answer(f"✅ {PRIVACY_LABELS[privacy]} selected!")

        mode = session.get("mode", "url")
        if mode == "url":
            await _execute_url_upload(client, callback_query, session, privacy)
        else:
            await _execute_telegram_upload(client, callback_query, session, privacy)

    @app.on_callback_query(filters.regex(r"^ytup_confirm_"))
    async def ytup_confirm_callback(client, callback_query: CallbackQuery):
        """Privacy flag-সহ command-এর সরাসরি confirm callback।"""
        chat_id = callback_query.message.chat.id
        user_id = callback_query.from_user.id

        session = ytup_sessions.get(chat_id)
        if not session or session["user_id"] != user_id:
            await callback_query.answer("❌ Session expired!", show_alert=True)
            return

        privacy = session.get("privacy", "public")
        await callback_query.answer("⏳ শুরু হচ্ছে...")

        mode = session.get("mode", "url")
        if mode == "url":
            await _execute_url_upload(client, callback_query, session, privacy)
        else:
            await _execute_telegram_upload(client, callback_query, session, privacy)

    @app.on_callback_query(filters.regex(r"^ytup_cancel_"))
    async def ytup_cancel_callback(client, callback_query: CallbackQuery):
        """Upload cancel করে।"""
        chat_id = callback_query.message.chat.id
        user_id = callback_query.from_user.id

        session = ytup_sessions.get(chat_id)
        if session and session["user_id"] != user_id:
            await callback_query.answer("❌ এটা তোমার session না!", show_alert=True)
            return

        ytup_sessions.pop(chat_id, None)
        await callback_query.message.edit_text(
            "❌ **Cancelled.**",
            parse_mode=ParseMode.MARKDOWN,
        )
        await callback_query.answer()

    # ═════════════════════════════════════════════════════════════════════
    # HANDLER REGISTRATION
    # ═════════════════════════════════════════════════════════════════════

    cmd_filter = filters.private | filters.group

    app.add_handler(MessageHandler(
        ytconnect_command,
        filters.command("ytconnect", COMMAND_PREFIX) & cmd_filter,
    ), group=2)

    app.add_handler(MessageHandler(
        ytcode_command,
        filters.command("ytcode", COMMAND_PREFIX) & cmd_filter,
    ), group=2)

    app.add_handler(MessageHandler(
        ytdisconnect_command,
        filters.command("ytdisconnect", COMMAND_PREFIX) & cmd_filter,
    ), group=2)

    app.add_handler(MessageHandler(
        ytme_command,
        filters.command("ytme", COMMAND_PREFIX) & cmd_filter,
    ), group=2)

    app.add_handler(MessageHandler(
        ytupload_command,
        filters.command("ytupload", COMMAND_PREFIX) & cmd_filter,
    ), group=2)

    app.add_handler(MessageHandler(
        ytsend_command,
        filters.command("ytsend", COMMAND_PREFIX) & cmd_filter,
    ), group=2)

    LOGGER.info("[ytupload] Multi-user YouTube upload handler registered ✅")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UTILITY FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _cleanup_dir(dirpath: str):
    """Directory empty হলে delete করো।"""
    try:
        if os.path.isdir(dirpath) and not os.listdir(dirpath):
            os.rmdir(dirpath)
    except Exception:
        pass


def _user_display(user) -> str:
    """User-এর display name তৈরি করে।"""
    fname = getattr(user, "first_name", "") or ""
    lname = getattr(user, "last_name",  "") or ""
    name  = f"{fname} {lname}".strip() or "Unknown"
    uname = getattr(user, "username", None)
    return f"{name} (@{uname})" if uname else name


def _fetch_channel_info_sync(creds: "Credentials") -> dict:
    """Channel info synchronously fetch করে (executor-এ ব্যবহারের জন্য)।"""
    try:
        youtube  = build("youtube", "v3", credentials=creds)
        response = youtube.channels().list(part="snippet", mine=True).execute()
        items    = response.get("items", [])
        if not items:
            return {"id": "", "title": "Unknown Channel"}
        item = items[0]
        return {
            "id":    item.get("id", ""),
            "title": item["snippet"].get("title", "Unknown"),
        }
    except Exception as e:
        LOGGER.warning(f"[ytupload] Channel info fetch error: {e}")
        return {"id": "", "title": "Unknown Channel"}
