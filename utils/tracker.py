# Copyright @juktijol
# Channel t.me/juktijol
#
# utils/tracker.py
# ─────────────────
# ইউজার ট্র্যাকিং মডিউল।
# প্রতিটা ডাউনলোডের সময় admin-কে notify করে এবং
# ডাউনলোড করা ফাইল LOG_GROUP_ID-তে পাঠায়।
#
# ✅ FIXED: Private channel name → bot member না হলে graceful fallback
# ✅ FIXED: t.me/c/.../topic/msg → thread/topic link regex সংশোধন
# ✅ FIXED: Public link regex → "c" username ধরে না ফেলার সুরক্ষা
# ✅ FIXED: log_file_to_group video → width/height/duration যোগ

import os
import re
from datetime import datetime, timezone, timedelta
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait,
    ChatWriteForbidden,
    ChannelInvalid,
    ChannelPrivate,
    PeerIdInvalid,
    BadRequest,
)
import asyncio

from .logging_setup import LOGGER
from .helper import get_video_thumbnail, get_video_resolution

# ── IST timezone (UTC+5:30) ────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> str:
    return datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")


def _link_type(url: str) -> str:
    """Public নাকি Private লিংক?"""
    if "/c/" in url or "t.me/c/" in url:
        return "🔒 Private"
    return "✅ Public"


def _extract_ids_from_url(url: str) -> tuple[str | None, int | None]:
    """
    URL থেকে (channel_identifier, msg_id) বের করো।

    Supported formats:
      Public : t.me/username/123
      Public : t.me/username/topic/123   (topic/thread)
      Private: t.me/c/1234567890/123
      Private: t.me/c/1234567890/6/527   (topic/thread)

    Returns:
        (channel_id_or_username, msg_id)
        Private → channel_id is numeric string e.g. "1234567890"
        Public  → channel_id is "@username"
        None, None on failure
    """
    # ── Private link ──────────────────────────────────────────────────────
    # t.me/c/CHANNEL_ID/MSG_ID
    # t.me/c/CHANNEL_ID/TOPIC_ID/MSG_ID
    pvt = re.search(
        r"t\.me/c/(\d+)/(?:\d+/)?(\d+)",
        url
    )
    if pvt:
        return pvt.group(1), int(pvt.group(2))

    # ── Public link ───────────────────────────────────────────────────────
    # t.me/USERNAME/MSG_ID
    # t.me/USERNAME/TOPIC_ID/MSG_ID
    # ✅ [^c] নয়, বরং username "c" হলেও চলবে কিন্তু
    #    pvt আগে check হয়েছে তাই t.me/c/... এখানে আসবে না
    pub = re.search(
        r"t\.me/([a-zA-Z][a-zA-Z0-9_]{3,})/(?:\d+/)?(\d+)",
        url
    )
    if pub:
        return f"@{pub.group(1)}", int(pub.group(2))

    return None, None


async def _resolve_channel_name(bot: Client, url: str) -> str:
    """
    URL থেকে চ্যানেল/গ্রুপের নাম বের করার চেষ্টা।

    ✅ FIXED: Private channel-এ bot member না থাকলে
       CHANNEL_INVALID error আসে।
       এখন সেটা gracefully handle করে fallback দেয়।

    ✅ FIXED: t.me/c/.../topic/msg format এখন সঠিকভাবে parse হয়।

    Priority:
      1. bot.get_chat() দিয়ে চেষ্টা করো
      2. Fail করলে URL থেকে readable name বানাও
      3. শেষ fallback: URL নিজেই return করো
    """
    channel_id, _ = _extract_ids_from_url(url)

    if not channel_id:
        LOGGER.warning(f"[Tracker] Could not parse channel from URL: {url}")
        return url

    # ── Private channel ───────────────────────────────────────────────────
    if channel_id.lstrip("-").isdigit() or (
        channel_id.startswith("-100")
    ):
        # Numeric ID → private channel
        raw_id = channel_id  # e.g. "1234567890"
        try:
            from pyrogram.utils import get_channel_id
            cid = get_channel_id(int(raw_id))
        except Exception:
            cid = int(raw_id)

        try:
            chat  = await bot.get_chat(cid)
            title = getattr(chat, "title", None) or str(raw_id)
            LOGGER.info(f"[Tracker] Resolved private channel: {title}")
            return f"{title} (Private)"

        except (ChannelInvalid, ChannelPrivate, PeerIdInvalid, BadRequest) as e:
            # ✅ Bot এই private channel-এর member নয়
            # এটা expected — error log নয়, info log করো
            LOGGER.info(
                f"[Tracker] Bot not in private channel {raw_id} "
                f"({type(e).__name__}) — using ID as name"
            )
            # Readable fallback: channel ID দিয়ে বানাও
            return f"Private Channel ({raw_id})"

        except Exception as e:
            LOGGER.warning(
                f"[Tracker] Unexpected error resolving private channel "
                f"{raw_id}: {e}"
            )
            return f"Private Channel ({raw_id})"

    # ── Public channel ────────────────────────────────────────────────────
    else:
        # channel_id is "@username"
        try:
            chat  = await bot.get_chat(channel_id)
            title = getattr(chat, "title", None) or channel_id
            LOGGER.info(f"[Tracker] Resolved public channel: {title}")
            return f"{title} ({channel_id})"

        except (ChannelInvalid, ChannelPrivate, PeerIdInvalid, BadRequest) as e:
            LOGGER.info(
                f"[Tracker] Could not resolve public channel {channel_id}: "
                f"{type(e).__name__}"
            )
            # username থেকে readable fallback
            clean = channel_id.lstrip("@")
            return f"@{clean}"

        except Exception as e:
            LOGGER.warning(
                f"[Tracker] Unexpected error resolving public channel "
                f"{channel_id}: {e}"
            )
            return channel_id


# ══════════════════════════════════════════════════════════════════════════
# notify_admin_link
# ══════════════════════════════════════════════════════════════════════════

async def notify_admin_link(
    bot: Client,
    user,
    url: str,
    admin_id: int,
    channel_name: str | None = None,
):
    """
    Admin-কে ডাউনলোড রিকোয়েস্ট সম্পর্কে জানায়।

    channel_name পাস করলে resolve করার চেষ্টা করবে না।
    না করলে URL থেকে নিজেই resolve করবে।
    """
    if not admin_id:
        return

    full_name = (
        f"{user.first_name or ''} {user.last_name or ''}".strip()
        or "Unknown"
    )
    username = f"@{user.username}" if user.username else "N/A"
    ltype    = _link_type(url)

    # channel_name না দেওয়া হলে নিজেই বের করো
    if channel_name is None:
        channel_name = await _resolve_channel_name(bot, url)

    text = (
        "📌 **New Download Request**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Name:** `{full_name}`\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"📛 **Username:** {username}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔗 **Link:** `{url}`\n"
        f"📺 **Channel/Group:** `{channel_name}`\n"
        f"🏷 **Type:** {ltype}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🕐 **Time:** `{_now_ist()}`"
    )

    try:
        await bot.send_message(
            chat_id=admin_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 2)
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as ex:
            LOGGER.error(f"[Tracker] Admin notify failed after FloodWait: {ex}")
    except Exception as e:
        LOGGER.error(f"[Tracker] Admin notify failed: {e}")


# ══════════════════════════════════════════════════════════════════════════
# log_file_to_group
# ══════════════════════════════════════════════════════════════════════════

async def log_file_to_group(
    bot: Client,
    log_group_id: int,
    user,
    url: str,
    file_path: str | None = None,
    file_id: str | None = None,
    media_type: str = "document",
    caption_original: str = "",
    channel_name: str | None = None,
    thumbnail_path: str | None = None,
    # ✅ video metadata — squish সমস্যা সমাধানের জন্য
    width: int = 0,
    height: int = 0,
    duration: int = 0,
):
    """
    ডাউনলোড করা ফাইলটি LOG_GROUP_ID-তে পাঠায় সব তথ্য সহ।

    file_path (disk) অথবা file_id (Telegram) যেকোনো একটা দিলেই হবে।

    ✅ FIXED: channel_name → private channel-এ bot না থাকলে
              graceful fallback (CHANNEL_INVALID এড়ানো)
    ✅ FIXED: video log → width/height/duration সহ পাঠানো হচ্ছে
    """
    if not log_group_id:
        return

    full_name = (
        f"{user.first_name or ''} {user.last_name or ''}".strip()
        or "Unknown"
    )
    username = f"@{user.username}" if user.username else "N/A"
    ltype    = _link_type(url)

    # channel_name resolve
    if channel_name is None:
        channel_name = await _resolve_channel_name(bot, url)

    # User footer (reply message)
    user_footer = (
        "📥 **Downloaded File Log**\n"
        f"👤 **User:** `{full_name}`\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"📛 **Username:** {username}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔗 **Link:** `{url}`\n"
        f"📺 **Source:** `{channel_name}`\n"
        f"🏷 **Type:** {ltype}\n"
        f"🕐 **Time:** `{_now_ist()}`"
    )

    # Original caption — 1000 char limit
    orig = (caption_original or "").strip()
    if len(orig) > 1000:
        orig = orig[:997] + "..."

    sent_msg = None

    try:
        # ── file_id দিয়ে পাঠানো (re-upload without downloading) ──────────
        if file_id:
            if media_type == "photo":
                sent_msg = await bot.send_photo(
                    chat_id=log_group_id,
                    photo=file_id,
                    caption=orig,
                )
            elif media_type == "video":
                sent_msg = await bot.send_video(
                    chat_id=log_group_id,
                    video=file_id,
                    caption=orig,
                    # ✅ metadata পাস হলে ব্যবহার করো
                    width=width if width > 0 else None,
                    height=height if height > 0 else None,
                    duration=duration if duration > 0 else None,
                    supports_streaming=True,
                )
            elif media_type == "audio":
                sent_msg = await bot.send_audio(
                    chat_id=log_group_id,
                    audio=file_id,
                    caption=orig,
                )
            else:
                sent_msg = await bot.send_document(
                    chat_id=log_group_id,
                    document=file_id,
                    caption=orig,
                )

        # ── file_path (disk) থেকে upload ─────────────────────────────────
        elif file_path and os.path.exists(file_path):

            if media_type == "video":
                # ── Thumbnail ─────────────────────────────────────────────
                log_thumb      = None
                auto_log_thumb = None

                if thumbnail_path and os.path.exists(thumbnail_path):
                    log_thumb = thumbnail_path
                else:
                    auto_log_thumb = await get_video_thumbnail(file_path, 0)
                    if auto_log_thumb and os.path.exists(auto_log_thumb):
                        log_thumb = auto_log_thumb

                # ── Resolution ────────────────────────────────────────────
                # ✅ FIXED: ffprobe দিয়ে actual resolution নাও
                # caller থেকে পাস হলে সেটা ব্যবহার করো (সবচেয়ে accurate)
                # না হলে ffprobe দিয়ে detect করো
                if width > 0 and height > 0:
                    final_width  = width
                    final_height = height
                    LOGGER.info(
                        f"[Tracker] Using passed resolution: "
                        f"{final_width}x{final_height}"
                    )
                else:
                    final_width, final_height = await get_video_resolution(
                        file_path
                    )
                    LOGGER.info(
                        f"[Tracker] ffprobe resolution: "
                        f"{final_width}x{final_height}"
                    )

                # ── Duration ──────────────────────────────────────────────
                if duration > 0:
                    final_duration = duration
                else:
                    from .helper import get_media_info
                    final_duration, _, _ = await get_media_info(file_path)
                    final_duration = final_duration or 0

                try:
                    sent_msg = await bot.send_video(
                        chat_id=log_group_id,
                        video=file_path,
                        thumb=log_thumb,
                        caption=orig,
                        width=final_width,
                        height=final_height,
                        duration=final_duration,
                        supports_streaming=True,
                    )
                finally:
                    # auto-generated thumbnail cleanup
                    if auto_log_thumb and os.path.exists(auto_log_thumb):
                        try:
                            os.remove(auto_log_thumb)
                        except Exception:
                            pass

            elif media_type == "photo":
                sent_msg = await bot.send_photo(
                    chat_id=log_group_id,
                    photo=file_path,
                    caption=orig,
                )

            elif media_type == "audio":
                sent_msg = await bot.send_audio(
                    chat_id=log_group_id,
                    audio=file_path,
                    caption=orig,
                )

            else:
                sent_msg = await bot.send_document(
                    chat_id=log_group_id,
                    document=file_path,
                    caption=orig,
                )

        # ── ফাইল নেই — plain text log ─────────────────────────────────────
        else:
            sent_msg = await bot.send_message(
                chat_id=log_group_id,
                text=orig or "(No content)",
            )

        # ── User info reply ───────────────────────────────────────────────
        if sent_msg:
            try:
                await bot.send_message(
                    chat_id=log_group_id,
                    text=user_footer,
                    reply_to_message_id=sent_msg.id,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                LOGGER.warning(
                    f"[Tracker] Could not send user info reply: {e}"
                )

    except ChatWriteForbidden:
        LOGGER.error(
            "[Tracker] Bot is not admin in the log group or cannot write!"
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 2)
        LOGGER.warning(f"[Tracker] FloodWait {e.value}s for log group")
    except Exception as e:
        LOGGER.error(f"[Tracker] Log group upload failed: {e}")
