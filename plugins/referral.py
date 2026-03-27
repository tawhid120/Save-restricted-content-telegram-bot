# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/referral.py — POWERFUL Referral System v2.1
# FIXED: Compatible with old referral documents (no _type field)

from datetime import datetime, timedelta, timezone
import urllib.parse
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from pyrogram.enums import ParseMode
from pyrogram.handlers import MessageHandler

from config import COMMAND_PREFIX, DEVELOPER_USER_ID
from utils import LOGGER
from core.database import referrals, prem_plan1, premium_users, total_users

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

MILESTONE_REWARDS = {
    5:  30,
    10: 30,
    20: 30,
    50: 60,
}

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _get_bot_username(client: Client) -> str:
    me = await client.get_me()
    return me.username or "bot"


async def _count_referrals(user_id: int) -> int:
    """
    পুরনো ও নতুন উভয় ধরনের document count করে।
    পুরনো: {"referrer_id": x, "referred_user_id": y}  (no _type)
    নতুন:  {"_type": "referral", "referrer_id": x, ...}
    """
    # সব document যেখানে referrer_id মিলে এবং _type "milestone_log" না
    count = await referrals.count_documents({
        "referrer_id": user_id,
        "_type": {"$ne": "milestone_log"},
    })
    return count


async def _get_referral_stats(user_id: int) -> dict:
    count = await _count_referrals(user_id)

    milestone_doc = await referrals.find_one(
        {"_type": "milestone_log", "user_id": user_id}
    )
    rewarded_milestones = milestone_doc.get("rewarded", []) if milestone_doc else []

    next_milestone = None
    for ms in sorted(MILESTONE_REWARDS.keys()):
        if ms not in rewarded_milestones:
            next_milestone = ms
            break

    return {
        "count": count,
        "rewarded_milestones": rewarded_milestones,
        "next_milestone": next_milestone,
        "needed_for_next": max(0, (next_milestone - count)) if next_milestone else 0,
    }


async def _give_premium_reward(client: Client, user_id: int, days: int, reason: str):
    expiry_date = datetime.utcnow() + timedelta(days=days)

    existing = await prem_plan1.find_one({"user_id": user_id})
    if existing and existing.get("expiry_date", datetime.utcnow()) > datetime.utcnow():
        new_expiry = existing["expiry_date"] + timedelta(days=days)
        await prem_plan1.update_one(
            {"user_id": user_id},
            {"$set": {"expiry_date": new_expiry}}
        )
        expiry_date = new_expiry
    else:
        plan_doc = {
            "user_id": user_id,
            "plan": "plan1",
            "plan_name": "Plan Premium 1 (Referral Reward)",
            "accounts": 1,
            "max_downloads": 1000,
            "private_support": True,
            "inbox_support": False,
            "expiry_date": expiry_date,
            "activated_at": datetime.utcnow(),
            "source": "referral",
        }
        await prem_plan1.insert_one(plan_doc.copy())
        plan_doc.pop("_id", None)
        await premium_users.update_one(
            {"user_id": user_id},
            {"$set": plan_doc},
            upsert=True,
        )

    try:
        await client.send_message(
            chat_id=user_id,
            text=(
                f"🎉 **Referral Reward Unlocked!**\n\n"
                f"**🏆 Reason:** {reason}\n"
                f"**🎁 Reward:** `{days}` days **Premium Plan 1**\n"
                f"**📅 Valid Until:** `{expiry_date.strftime('%d %b %Y')}`\n\n"
                "Thanks for spreading the word! 💎\n"
                "Keep referring to earn more rewards! 🚀"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        LOGGER.warning(f"[Referral] Could not notify user {user_id}: {e}")

    LOGGER.info(f"[Referral] Reward given: {user_id} → {days} days ({reason})")


async def _check_and_reward_milestones(client: Client, referrer_id: int):
    """Milestone পূরণ হলে reward দেয়।"""
    stats = await _get_referral_stats(referrer_id)
    count = stats["count"]
    rewarded = stats["rewarded_milestones"]

    for milestone, reward_days in sorted(MILESTONE_REWARDS.items()):
        if count >= milestone and milestone not in rewarded:
            await referrals.update_one(
                {"_type": "milestone_log", "user_id": referrer_id},
                {"$addToSet": {"rewarded": milestone}},
                upsert=True,
            )
            reason = f"🏅 {milestone} Referrals Milestone"
            await _give_premium_reward(client, referrer_id, reward_days, reason)


# ─────────────────────────────────────────────────────────────────────────────
# PROCESS REFERRAL
# ─────────────────────────────────────────────────────────────────────────────

async def process_referral(client: Client, new_user_id: int, referrer_id: int):
    if referrer_id == new_user_id:
        return False

    if referrer_id == DEVELOPER_USER_ID:
        return False

    # Duplicate check — পুরনো ও নতুন উভয় format চেক
    existing = await referrals.find_one({
        "referred_user_id": new_user_id,
        "_type": {"$ne": "milestone_log"},
    })
    if existing:
        LOGGER.info(f"[Referral] Duplicate blocked: {new_user_id}")
        return False

    referrer_exists = await total_users.find_one({"user_id": referrer_id})
    if not referrer_exists:
        LOGGER.warning(f"[Referral] Referrer {referrer_id} not in DB")
        return False

    await referrals.insert_one({
        "_type": "referral",
        "referrer_id": referrer_id,
        "referred_user_id": new_user_id,
        "referred_at": datetime.utcnow(),
        "is_active": True,
    })

    LOGGER.info(f"[Referral] Recorded: {new_user_id} referred by {referrer_id}")

    stats = await _get_referral_stats(referrer_id)
    count = stats["count"]
    next_ms = stats["next_milestone"]
    needed = stats["needed_for_next"]

    try:
        new_user_doc = await total_users.find_one({"user_id": new_user_id})
        new_name = (
            new_user_doc.get("name") or
            new_user_doc.get("first_name") or
            "Someone"
        ) if new_user_doc else "Someone"

        progress_text = (
            f"\n📊 **Progress:** `{count}/{next_ms}` (need **{needed}** more for reward)"
            if next_ms
            else "\n🏆 **You've completed all milestones! You're a legend!**"
        )

        await client.send_message(
            chat_id=referrer_id,
            text=(
                f"🔔 **New Referral!**\n\n"
                f"**👤 {new_name}** joined via your link!\n"
                f"**📊 Total Referrals:** `{count}`"
                f"{progress_text}\n\n"
                "Keep sharing to earn more rewards! 🎁"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        LOGGER.warning(f"[Referral] Could not notify referrer {referrer_id}: {e}")

    await _check_and_reward_milestones(client, referrer_id)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# UI BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

async def get_referral_text(client: Client, user_id: int) -> str:
    bot_username = await _get_bot_username(client)
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    stats = await _get_referral_stats(user_id)

    count = stats["count"]
    next_ms = stats["next_milestone"]
    needed = stats["needed_for_next"]
    rewarded = stats["rewarded_milestones"]

    # Progress bar
    if next_ms and next_ms > 0:
        progress_pct = min((count / next_ms) * 100, 100)
        filled = int(progress_pct / 10)
        bar = "▓" * filled + "░" * (10 - filled)
        progress_line = f"\n`[{bar}]` {progress_pct:.0f}% → **{next_ms}** referrals"
    else:
        bar = "▓" * 10
        progress_line = f"\n`[{bar}]` 100% 🏆 All milestones completed!"

    # Milestone summary — ✅ rewarded, 🔓 reached but not rewarded, 🔒 not yet
    milestone_lines = []
    for ms, days in sorted(MILESTONE_REWARDS.items()):
        if ms in rewarded:
            icon = "✅"
        elif count >= ms:
            icon = "🔓"  # পূরণ হয়েছে কিন্তু reward এখনো দেওয়া হয়নি
        else:
            icon = "🔒"
        milestone_lines.append(f"  {icon} **{ms} referrals** → +{days} days Premium")

    milestones_text = "\n".join(milestone_lines)

    return (
        f"🔗 **Your Referral Link**\n"
        f"`{referral_link}`\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"**📊 Your Stats**\n"
        f"👥 **Total Referrals:** `{count}`"
        f"{progress_line}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"**🏆 Milestone Rewards**\n"
        f"{milestones_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"**💡 How It Works**\n"
        f"1️⃣ Share your link with friends\n"
        f"2️⃣ They start the bot via your link\n"
        f"3️⃣ You earn rewards automatically! 🎁\n\n"
        f"_Tap the button below to share your link!_"
    )


def _referral_keyboard(user_id: int, bot_username: str) -> InlineKeyboardMarkup:
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    share_text = (
        f"🚀 Download restricted Telegram content easily!\n"
        f"Join via my link: {referral_link}"
    )
    encoded_text = urllib.parse.quote(share_text)
    encoded_link = urllib.parse.quote(referral_link)
    share_url = f"https://t.me/share/url?url={encoded_link}&text={encoded_text}"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share My Link", url=share_url)],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="ref_leaderboard")],
        [InlineKeyboardButton("🔄 Refresh Stats", callback_data="ref_refresh")],
    ])


async def get_leaderboard_text() -> str:
    pipeline = [
        {"$match": {"_type": {"$ne": "milestone_log"}}},
        {"$group": {"_id": "$referrer_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    cursor = referrals.aggregate(pipeline)
    top_users = await cursor.to_list(length=10)

    if not top_users:
        return "**🏆 Referral Leaderboard**\n\n_No referrals yet! Be the first!_"

    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines = ["**🏆 Referral Leaderboard — Top 10**\n━━━━━━━━━━━━━━━━━━\n"]

    for i, entry in enumerate(top_users):
        uid = entry["_id"]
        count = entry["count"]
        if uid is None:
            continue
        user_doc = await total_users.find_one({"user_id": uid})
        name = "Unknown"
        if user_doc:
            name = (
                user_doc.get("name") or
                user_doc.get("first_name") or
                f"User {uid}"
            )
            if len(name) > 20:
                name = name[:17] + "..."
        lines.append(f"{medals[i]} **{name}** — `{count}` referrals")

    lines.append("\n━━━━━━━━━━━━━━━━━━")
    lines.append("_Share your link to climb the leaderboard!_")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_referral_handler(app: Client):

    async def referral_command(client: Client, message: Message):
        user_id = message.from_user.id

        if len(message.command) >= 2 and message.command[1].lower() in ("top", "leaderboard"):
            text = await get_leaderboard_text()
            await message.reply_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 My Referral Link", callback_data="ref_refresh")],
                ]),
            )
            return

        bot_username = await _get_bot_username(client)
        text = await get_referral_text(client, user_id)
        keyboard = _referral_keyboard(user_id, bot_username)

        await message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        LOGGER.info(f"[/referral] from user {user_id}")

    @app.on_callback_query(filters.regex(r"^ref_(refresh|leaderboard)$"))
    async def ref_callback(client: Client, cq: CallbackQuery):
        user_id = cq.from_user.id
        data = cq.data

        if data == "ref_leaderboard":
            text = await get_leaderboard_text()
            try:
                await cq.message.edit_text(
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 My Referral Link", callback_data="ref_refresh")],
                    ]),
                )
            except Exception:
                pass
            await cq.answer("🏆 Leaderboard updated!")
            return

        if data == "ref_refresh":
            bot_username = await _get_bot_username(client)
            text = await get_referral_text(client, user_id)
            keyboard = _referral_keyboard(user_id, bot_username)
            try:
                await cq.message.edit_text(
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
            await cq.answer("✅ Stats refreshed!")

    # ── Admin: /refcheck <user_id> ────────────────────────────────────────

    @app.on_message(
        filters.command("refcheck", prefixes=COMMAND_PREFIX)
        & filters.private
        & filters.user(DEVELOPER_USER_ID)
    )
    async def refcheck_command(client: Client, message: Message):
        if len(message.command) < 2:
            await message.reply_text("**Usage:** `/refcheck <user_id>`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ **Invalid user ID!**", parse_mode=ParseMode.MARKDOWN)
            return

        stats = await _get_referral_stats(target_id)
        count = stats["count"]
        rewarded = stats["rewarded_milestones"]

        cursor = referrals.find(
            {"referrer_id": target_id, "_type": {"$ne": "milestone_log"}},
            {"referred_user_id": 1, "referred_at": 1}
        ).sort("referred_at", -1).limit(10)
        recent = await cursor.to_list(length=10)

        recent_lines = []
        for r in recent:
            uid = r.get("referred_user_id", "?")
            at = r.get("referred_at")
            at_str = at.strftime("%d %b %Y") if at else "Unknown"
            recent_lines.append(f"  • `{uid}` — {at_str}")

        recent_text = "\n".join(recent_lines) if recent_lines else "  _None yet_"

        await message.reply_text(
            f"**📊 Referral Report — `{target_id}`**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**👥 Total Referrals:** `{count}`\n"
            f"**🏆 Milestones Rewarded:** `{rewarded}`\n\n"
            f"**📋 Recent (last 10):**\n{recent_text}",
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Admin: /refgive <user_id> — manually trigger milestone check ──────

    @app.on_message(
        filters.command("refgive", prefixes=COMMAND_PREFIX)
        & filters.private
        & filters.user(DEVELOPER_USER_ID)
    )
    async def refgive_command(client: Client, message: Message):
        """Manually trigger milestone reward for a user (e.g. for existing referrals)."""
        if len(message.command) < 2:
            await message.reply_text(
                "**Usage:** `/refgive <user_id>`\n\n"
                "Manually check & give milestone rewards for a user.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ **Invalid user ID!**", parse_mode=ParseMode.MARKDOWN)
            return

        stats_before = await _get_referral_stats(target_id)
        await _check_and_reward_milestones(client, target_id)
        stats_after = await _get_referral_stats(target_id)

        new_rewards = [
            ms for ms in stats_after["rewarded_milestones"]
            if ms not in stats_before["rewarded_milestones"]
        ]

        if new_rewards:
            await message.reply_text(
                f"✅ **Rewards given for user `{target_id}`!**\n"
                f"**Milestones unlocked:** `{new_rewards}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await message.reply_text(
                f"ℹ️ No new rewards for `{target_id}`.\n"
                f"Count: `{stats_after['count']}` | Already rewarded: `{stats_after['rewarded_milestones']}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Admin: /refstats ──────────────────────────────────────────────────

    @app.on_message(
        filters.command("refstats", prefixes=COMMAND_PREFIX)
        & filters.private
        & filters.user(DEVELOPER_USER_ID)
    )
    async def refstats_command(client: Client, message: Message):
        total_ref = await referrals.count_documents({"_type": {"$ne": "milestone_log"}})

        ur_result = await referrals.aggregate([
            {"$match": {"_type": {"$ne": "milestone_log"}}},
            {"$group": {"_id": "$referrer_id"}},
            {"$count": "count"},
        ]).to_list(length=1)
        unique_referrers = ur_result[0]["count"] if ur_result else 0

        top_result = await referrals.aggregate([
            {"$match": {"_type": {"$ne": "milestone_log"}}},
            {"$group": {"_id": "$referrer_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 1},
        ]).to_list(length=1)
        top_info = "N/A"
        if top_result:
            top_uid = top_result[0]["_id"]
            top_cnt = top_result[0]["count"]
            top_info = f"`{top_uid}` ({top_cnt} referrals)"

        await message.reply_text(
            f"**📊 Global Referral Stats**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**🔗 Total Referrals:** `{total_ref}`\n"
            f"**👤 Unique Referrers:** `{unique_referrers}`\n"
            f"**🏆 Top Referrer:** {top_info}\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.MARKDOWN,
        )

    app.add_handler(
        MessageHandler(
            referral_command,
            filters=filters.command("referral", prefixes=COMMAND_PREFIX)
            & (filters.private | filters.group),
        ),
        group=1,
    )
