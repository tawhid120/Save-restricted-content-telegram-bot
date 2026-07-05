# Copyright @juktijol
# Channel t.me/juktijol
#
# core/start.py — UPDATED: Uses new process_referral() from plugins/referral.py

from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from utils import LOGGER

from misc.keyboards import get_main_reply_keyboard, get_start_inline
from core.database import total_users, referrals


def setup_start_handler(app: Client):

    @app.on_message(filters.command("start"))
    async def start(client: Client, message: Message):
        user = message.from_user
        user_fullname = (
            f"{user.first_name} "
            f"{user.last_name or ''}".strip()
        )

        # ── MongoDB-তে ইউজার সেভ/আপডেট করো ─────────────────────────────────
        try:
            await total_users.update_one(
                {"user_id": user.id},
                {
                    "$set": {
                        "user_id":    user.id,
                        "first_name": user.first_name or "",
                        "last_name":  user.last_name or "",
                        "name":       user_fullname,
                        "username":   user.username or "",
                        "last_active": datetime.utcnow(),
                    }
                },
                upsert=True,
            )
            LOGGER.info(f"User saved/updated in DB: {user.id} ({user_fullname})")
        except Exception as e:
            LOGGER.error(f"Failed to save user {user.id} to DB: {e}")

        # ── Referral tracking: /start <referrer_id> ───────────────────────
        if len(message.command) > 1:
            referrer_arg = message.command[1]
            try:
                referrer_id = int(referrer_arg)
                # Import here to avoid circular imports
                from plugins.referral import process_referral
                # process_referral handles anti-cheat + reward automatically
                success = await process_referral(client, user.id, referrer_id)
                if success:
                    LOGGER.info(f"Referral processed: {user.id} referred by {referrer_id}")
            except (ValueError, TypeError):
                pass  # Not a referral deep link
            except Exception as e:
                LOGGER.error(f"Referral tracking error for {user.id}: {e}")

        start_message = f"""✨ **Welcome, {user_fullname}!** ✨
⚡ **The Ultimate Restricted Content Downloader**

━━━━━━━━━━━━━━━━━━━━━━━━
❏ **NEW UPDATE FEATURES:**
✓ **Instant Bypass:** Send any link to download instantly.
✓ **Batch Mode:** Save multiple restricted files at once.
✓ **Private Source:** Access and download from private chats.

❏ **BENEFITS:**
✓ **Premium:** Remove 5-min cooldown & unlock bulk download!
━━━━━━━━━━━━━━━━━━━━━━━━

👇 **Just paste your Telegram link below to start:**
"""

        await message.reply_text(
            start_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_start_inline(),
            disable_web_page_preview=True,
        )

        await client.send_message(
            chat_id=message.chat.id,
            text="⌨️ __Use the buttons below for quick access to all features:__",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_reply_keyboard(),
        )

        LOGGER.info(f"Start command triggered by {user.id}")
