# Copyright @juktijol
# Channel t.me/juktijol
#
# utils/tracker.py
# ─────────────────
# ইউজার ট্র্যাকিং মডিউল।
# প্রতিটা ডাউনলোডের সময় admin-কে notify করে এবং
# ডাউনলোড করা ফাইল LOG_GROUP_ID-তে পাঠায়।

import os
from datetime import datetime, timezone, timedelta
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, ChatWriteForbidden
import asyncio

from .logging_setup import LOGGER
from .helper import get_video_thumbnail

# ── IST timezone (UTC+5:30) ────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> str:
    return datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")


def _link_type(url: str) -> str:
    """Public নাকি Private লিংক?"""
    if "/c/" in url or "t.me/c/" in url:
        return "🔒 Private"
    return "✅ Public"


async def _resolve_channel_name(bot: Client, url: str) -> str:
    """
    URL থেকে চ্যানেল/গ্রুপের নাম বের করার চেষ্টা।
    না পারলে URL-ই ফেরত দেয়।
    """
    try:
        import re
        # public: t.me/channelname/123
        pub = re.search(r"t\.me/([a-zA-Z0-9_]+)/\d+", url)
        # private: t.me/c/1234567890/123
        pvt = re.search(r"t\.me/c/(\d+)/\d+", url)

        if pvt:
            from pyrogram.utils import get_channel_id
            cid = get_channel_id(int(pvt.group(1)))
            chat = await bot.get_chat(cid)
            title = getattr(chat, "title", None) or str(cid)
            return f"{title} (Private Channel)"
        elif pub:
            username = pub.group(1)
            chat = await bot.get_chat(f"@{username}")
            title = getattr(chat, "title", None) or username
            return f"{title} (@{username})"
    except Exception as e:
        LOGGER.warning(f"[Tracker] Could not resolve channel name: {e}")

    return url  # fallback


async def notify_admin_link(
    bot: Client,
    user,               # pyrogram User object
    url: str,
    admin_id: int,
    channel_name: str | None = None,
):
    """
    Admin-কে ডাউনলোড রিকোয়েস্ট সম্পর্কে জানায়।
    """
    if not admin_id:
        return

    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
    username  = f"@{user.username}" if user.username else "N/A"
    ltype     = _link_type(url)

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
            await bot.send_message(chat_id=admin_id, text=text, parse_mode=ParseMode.MARKDOWN)
        except Exception as ex:
            LOGGER.error(f"[Tracker] Admin notify failed: {ex}")
    except Exception as e:
        LOGGER.error(f"[Tracker] Admin notify failed: {e}")


async def log_file_to_group(
    bot: Client,
    log_group_id: int,
    user,               # pyrogram User object
    url: str,
    file_path: str | None = None,
    file_id: str | None = None,
    media_type: str = "document",
    caption_original: str = "",
    channel_name: str | None = None,
    thumbnail_path: str | None = None,
):
    """
    ডাউনলোড করা ফাইলটি LOG_GROUP_ID-তে পাঠায় সব তথ্য সহ।
    file_path (disk) অথবা file_id (Telegram) যেকোনো একটা দিলেই হবে।
    """
    if not log_group_id:
        return

    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
    username  = f"@{user.username}" if user.username else "N/A"
    ltype     = _link_type(url)

    if channel_name is None:
        channel_name = await _resolve_channel_name(bot, url)

    # User info to be sent as a separate reply
    user_footer = (
        "📥 **Downloaded File Log**\n"
        f"👤 **User:** `{full_name}`\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"📛 **Username:** {username}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔗 **Link:** `{url}`\n"
        f"📺 **Source:** `{channel_name}`\n"
        f"🏷 **Type:** {ltype}\n"
        f"🕐 **Time:** `{_now_ist()}`"
    )

    # Original caption only, truncated to 1000 chars to stay within Telegram limits
    orig = (caption_original or "").strip()
    if len(orig) > 1000:
        orig = orig[:997] + "..."

    sent_msg = None

    try:
        if file_id:
            # ফাইল আইডি দিয়ে পাঠানো (re-upload without downloading)
            sender = {
                "photo":    bot.send_photo,
                "video":    bot.send_video,
                "audio":    bot.send_audio,
                "document": bot.send_document,
            }.get(media_type, bot.send_document)

            kwargs = {
                "chat_id": log_group_id,
                "caption": orig,
            }
            # media type অনুযায়ী সঠিক parameter
            if media_type == "photo":
                kwargs["photo"] = file_id
            elif media_type == "video":
                kwargs["video"] = file_id
            elif media_type == "audio":
                kwargs["audio"] = file_id
            else:
                kwargs["document"] = file_id

            sent_msg = await sender(**kwargs)

        elif file_path and os.path.exists(file_path):
            # Disk থেকে upload
            if media_type == "video":
                # Resolve thumbnail: caller-provided > auto-generate
                log_thumb = None
                auto_log_thumb = None
                if thumbnail_path and os.path.exists(thumbnail_path):
                    log_thumb = thumbnail_path
                else:
                    auto_log_thumb = await get_video_thumbnail(file_path, 0)
                    if auto_log_thumb and os.path.exists(auto_log_thumb):
                        log_thumb = auto_log_thumb
                try:
                    sent_msg = await bot.send_video(
                        chat_id=log_group_id,
                        video=file_path,
                        thumb=log_thumb,
                        caption=orig,
                        supports_streaming=True,
                    )
                finally:
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
        else:
            # ফাইল নেই — original text/caption as a plain text log
            sent_msg = await bot.send_message(
                chat_id=log_group_id,
                text=orig or "(No content)",
            )

        # Reply with user info on the sent message
        if sent_msg:
            try:
                await bot.send_message(
                    chat_id=log_group_id,
                    text=user_footer,
                    reply_to_message_id=sent_msg.id,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                LOGGER.warning(f"[Tracker] Could not send user info reply: {e}")

    except ChatWriteForbidden:
        LOGGER.error("[Tracker] Bot is not admin in the log group or cannot write!")
    except FloodWait as e:
        await asyncio.sleep(e.value + 2)
        LOGGER.warning(f"[Tracker] FloodWait {e.value}s for log group")
    except Exception as e:
        LOGGER.error(f"[Tracker] Log group upload failed: {e}")
