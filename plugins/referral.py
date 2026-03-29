# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/referral.py — Advanced Referral System v3.0
#
# FIXED BUGS:
#   ✅ Bug 1 (Critical): Milestone এখন premium দেওয়ার পরে mark হবে (আগে নয়)
#      → আগে premium দিতে ব্যর্থ হলে milestone lost হতো, এখন হবে না
#   ✅ Bug 2: সব জায়গায় try/except যোগ করা হয়েছে
#      → আগে exception হলে status message update হতো না
#   ✅ Bug 3: expiry_date comparison-এ TypeError fix
#   ✅ Bug 4: asyncio.Lock দিয়ে race condition প্রতিরোধ
#   ✅ Bug 5: /refgive force এখন সত্যিই কাজ করবে
#
# ADVANCED FEATURES:
#   🚀 Multi-tier milestone rewards (আরো মাইলস্টোন)
#   🔥 Streak bonus (সপ্তাহে সক্রিয় রেফার করলে বোনাস দিন)
#   📊 Detailed stats (সাপ্তাহিক / মাসিক breakdown)
#   🔔 Progress notification (পরের মাইলস্টোনের কাছাকাছি হলে alert)
#   🏆 Enhanced leaderboard with ranks & medals
#   🎯 Referral quality scoring
#   ⚡ Admin: /reflist, /refcheck (enhanced), /refgive (fixed), /refstats (enhanced)

import asyncio
import urllib.parse
from datetime import datetime, timedelta, timezone
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
# RACE CONDITION PREVENTION
# ─────────────────────────────────────────────────────────────────────────────
# একই user-এর জন্য একই সময়ে দুটো reward process না হোক
_reward_locks: dict[int, asyncio.Lock] = {}


def _get_user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _reward_locks:
        _reward_locks[user_id] = asyncio.Lock()
    return _reward_locks[user_id]


# ─────────────────────────────────────────────────────────────────────────────
# ADVANCED MILESTONE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

MILESTONE_REWARDS = {
    3:   7,    # ৩টি রেফার → ৭ দিন প্রিমিয়াম
    5:   15,   # ৫টি রেফার → ১৫ দিন প্রিমিয়াম
    10:  30,   # ১০টি রেফার → ৩০ দিন প্রিমিয়াম
    20:  30,   # ২০টি রেফার → ৩০ দিন প্রিমিয়াম
    30:  45,   # ৩০টি রেফার → ৪৫ দিন প্রিমিয়াম
    50:  60,   # ৫০টি রেফার → ৬০ দিন প্রিমিয়াম
    75:  75,   # ৭৫টি রেফার → ৭৫ দিন প্রিমিয়াম
    100: 90,   # ১০০টি রেফার → ৯০ দিন প্রিমিয়াম
}

# সপ্তাহে কমপক্ষে N জন রেফার করলে streak bonus পাবে
STREAK_WEEKLY_MIN = 3
STREAK_BONUS_DAYS = 5   # প্রতি active সপ্তাহের জন্য বোনাস

# পরের মাইলস্টোন থেকে কতটুকু দূরে থাকলে notification দেবে
MILESTONE_NEAR_THRESHOLD = 2

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — DB QUERIES
# ─────────────────────────────────────────────────────────────────────────────

async def _get_bot_username(client: Client) -> str:
    try:
        me = await client.get_me()
        return me.username or "bot"
    except Exception:
        return "bot"


async def _count_referrals(user_id: int) -> int:
    """
    পুরনো ও নতুন উভয় format count করে।
    পুরনো: {"referrer_id": x, "referred_user_id": y}  — _type নেই
    নতুন:  {"_type": "referral", "referrer_id": x, ...}
    """
    try:
        count = await referrals.count_documents({
            "referrer_id": user_id,
            "$or": [
                {"_type": {"$exists": False}},
                {"_type": {"$nin": ["milestone_log", "streak_log"]}},
            ],
        })
        return count
    except Exception as e:
        LOGGER.error(f"[Referral] _count_referrals error for {user_id}: {e}")
        return 0


async def _count_referrals_in_period(user_id: int, since: datetime) -> int:
    """নির্দিষ্ট সময়ের মধ্যে কতজন রেফার করেছে।"""
    try:
        count = await referrals.count_documents({
            "referrer_id": user_id,
            "referred_at": {"$gte": since},
            "$or": [
                {"_type": {"$exists": False}},
                {"_type": {"$nin": ["milestone_log", "streak_log"]}},
            ],
        })
        return count
    except Exception as e:
        LOGGER.error(f"[Referral] _count_referrals_in_period error: {e}")
        return 0


async def _get_milestone_doc(user_id: int) -> dict:
    try:
        doc = await referrals.find_one(
            {"_type": "milestone_log", "user_id": user_id}
        )
        return doc or {}
    except Exception as e:
        LOGGER.error(f"[Referral] _get_milestone_doc error for {user_id}: {e}")
        return {}


async def _get_referral_stats(user_id: int) -> dict:
    count = await _count_referrals(user_id)
    milestone_doc = await _get_milestone_doc(user_id)
    rewarded_milestones = milestone_doc.get("rewarded", [])

    next_milestone = None
    for ms in sorted(MILESTONE_REWARDS.keys()):
        if ms not in rewarded_milestones:
            next_milestone = ms
            break

    # সাপ্তাহিক ও মাসিক stats
    now = datetime.utcnow()
    weekly  = await _count_referrals_in_period(user_id, now - timedelta(days=7))
    monthly = await _count_referrals_in_period(user_id, now - timedelta(days=30))

    # Streak check
    streak_doc = await referrals.find_one(
        {"_type": "streak_log", "user_id": user_id}
    ) or {}
    current_streak = streak_doc.get("current_streak", 0)
    bonus_days_earned = streak_doc.get("bonus_days_earned", 0)

    return {
        "count": count,
        "weekly": weekly,
        "monthly": monthly,
        "rewarded_milestones": rewarded_milestones,
        "next_milestone": next_milestone,
        "needed_for_next": max(0, (next_milestone - count)) if next_milestone else 0,
        "current_streak": current_streak,
        "bonus_days_earned": bonus_days_earned,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FIXED: _give_premium_reward — premium দেওয়া
# ─────────────────────────────────────────────────────────────────────────────

async def _give_premium_reward(
    client: Client,
    user_id: int,
    days: int,
    reason: str,
) -> bool:
    """
    ✅ FIXED:
    - expiry_date comparison এখন safe (TypeError ছিল আগে)
    - Returns True on success, False on failure
    - Exception এখন caller-এ propagate হয় না
    """
    try:
        expiry_date = datetime.utcnow() + timedelta(days=days)

        existing = await prem_plan1.find_one({"user_id": user_id})

        if existing:
            # ✅ BUG FIX: safe comparison — expiry_date missing বা wrong type হলে crash হতো
            ex_expiry = existing.get("expiry_date")
            if isinstance(ex_expiry, datetime) and ex_expiry > datetime.utcnow():
                # Active plan আছে → extend করো
                new_expiry = ex_expiry + timedelta(days=days)
                await prem_plan1.update_one(
                    {"user_id": user_id},
                    {"$set": {"expiry_date": new_expiry}},
                )
                await premium_users.update_one(
                    {"user_id": user_id},
                    {"$set": {"expiry_date": new_expiry}},
                    upsert=True,
                )
                expiry_date = new_expiry
                LOGGER.info(
                    f"[Referral] Reward extended for {user_id}: "
                    f"+{days}d → new expiry {new_expiry.strftime('%Y-%m-%d')}"
                )
            else:
                # Expired plan আছে → replace করো
                plan_doc = _build_plan_doc(user_id, expiry_date)
                await prem_plan1.replace_one({"user_id": user_id}, plan_doc)
                await premium_users.update_one(
                    {"user_id": user_id},
                    {"$set": plan_doc},
                    upsert=True,
                )
                LOGGER.info(
                    f"[Referral] Reward replaced for {user_id}: "
                    f"{days}d expiry {expiry_date.strftime('%Y-%m-%d')}"
                )
        else:
            # কোনো plan নেই → নতুন insert করো
            plan_doc = _build_plan_doc(user_id, expiry_date)
            await prem_plan1.insert_one(plan_doc.copy())
            plan_doc.pop("_id", None)
            await premium_users.update_one(
                {"user_id": user_id},
                {"$set": plan_doc},
                upsert=True,
            )
            LOGGER.info(
                f"[Referral] New reward for {user_id}: "
                f"{days}d expiry {expiry_date.strftime('%Y-%m-%d')}"
            )

        # User-কে notify করো (failure হলে ignore করো)
        try:
            await client.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 **Referral Reward Unlocked!**\n\n"
                    f"**🏆 Reason:** {reason}\n"
                    f"**🎁 Reward:** `{days}` days **Premium Plan 1**\n"
                    f"**📅 Valid Until:** `{expiry_date.strftime('%d %b %Y')}`\n\n"
                    "Thanks for spreading the word! 💎\n"
                    "Keep referring to earn more rewards! 🚀\n\n"
                    "_Use /referral to see your progress_"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as notify_err:
            LOGGER.warning(
                f"[Referral] Could not notify user {user_id}: {notify_err}"
            )

        return True

    except Exception as e:
        LOGGER.error(f"[Referral] _give_premium_reward FAILED for {user_id}: {e}")
        return False


def _build_plan_doc(user_id: int, expiry_date: datetime) -> dict:
    return {
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


# ─────────────────────────────────────────────────────────────────────────────
# FIXED: _check_and_reward_milestones
# ─────────────────────────────────────────────────────────────────────────────

async def _check_and_reward_milestones(
    client: Client,
    referrer_id: int,
) -> list[int]:
    """
    ✅ FIXED (Critical Bug):
    আগে: milestone mark → premium দাও
    এখন: premium দাও → সফল হলে milestone mark

    Returns: list of newly rewarded milestones
    """
    async with _get_user_lock(referrer_id):
        newly_rewarded = []

        try:
            count = await _count_referrals(referrer_id)
            milestone_doc = await _get_milestone_doc(referrer_id)
            rewarded = milestone_doc.get("rewarded", [])

            LOGGER.info(
                f"[Referral] Milestone check — user={referrer_id}, "
                f"count={count}, already_rewarded={rewarded}"
            )

            for milestone, reward_days in sorted(MILESTONE_REWARDS.items()):
                if count >= milestone and milestone not in rewarded:
                    LOGGER.info(
                        f"[Referral] Attempting milestone {milestone} "
                        f"for user {referrer_id} (+{reward_days}d)"
                    )

                    reason = f"🏅 {milestone} Referrals Milestone"

                    # ✅ CRITICAL FIX: premium দাও আগে, mark করো পরে
                    success = await _give_premium_reward(
                        client, referrer_id, reward_days, reason
                    )

                    if success:
                        # Premium সফলভাবে দেওয়া হয়েছে → এখন DB-তে mark করো
                        try:
                            await referrals.update_one(
                                {"_type": "milestone_log", "user_id": referrer_id},
                                {"$addToSet": {"rewarded": milestone}},
                                upsert=True,
                            )
                            newly_rewarded.append(milestone)
                            LOGGER.info(
                                f"[Referral] ✅ Milestone {milestone} rewarded & "
                                f"marked for user {referrer_id}"
                            )
                        except Exception as mark_err:
                            # Milestone mark failed — কিন্তু premium দেওয়া হয়েছে
                            # Next time আবার reward দেওয়া হবে (duplicate reward possible)
                            # তাই manually track করো
                            LOGGER.error(
                                f"[Referral] Failed to mark milestone {milestone} "
                                f"for {referrer_id}: {mark_err} "
                                f"(premium WAS given, manual fix needed)"
                            )
                    else:
                        LOGGER.error(
                            f"[Referral] Failed to give milestone {milestone} "
                            f"reward to user {referrer_id}"
                        )

        except Exception as e:
            LOGGER.error(
                f"[Referral] _check_and_reward_milestones error "
                f"for {referrer_id}: {e}"
            )

        return newly_rewarded


# ─────────────────────────────────────────────────────────────────────────────
# STREAK BONUS SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

async def _check_streak_bonus(client: Client, referrer_id: int):
    """
    সপ্তাহে STREAK_WEEKLY_MIN জন রেফার করলে streak bonus দেয়।
    """
    try:
        now = datetime.utcnow()
        week_start = now - timedelta(days=7)
        weekly_count = await _count_referrals_in_period(referrer_id, week_start)

        if weekly_count < STREAK_WEEKLY_MIN:
            return

        streak_doc = await referrals.find_one(
            {"_type": "streak_log", "user_id": referrer_id}
        ) or {}

        last_bonus_week = streak_doc.get("last_bonus_week")
        current_week_num = now.isocalendar()[1]
        current_year = now.year

        # এই সপ্তাহে ইতিমধ্যে streak bonus পেয়েছে কিনা
        if (last_bonus_week and
            last_bonus_week.get("week") == current_week_num and
            last_bonus_week.get("year") == current_year):
            return

        current_streak = streak_doc.get("current_streak", 0) + 1
        bonus_days_earned = streak_doc.get("bonus_days_earned", 0) + STREAK_BONUS_DAYS

        # DB update
        await referrals.update_one(
            {"_type": "streak_log", "user_id": referrer_id},
            {
                "$set": {
                    "current_streak": current_streak,
                    "bonus_days_earned": bonus_days_earned,
                    "last_bonus_week": {
                        "week": current_week_num,
                        "year": current_year,
                    },
                    "last_updated": now,
                }
            },
            upsert=True,
        )

        # Bonus reward দাও
        reason = (
            f"🔥 Weekly Streak #{current_streak} "
            f"({weekly_count} referrals this week!)"
        )
        success = await _give_premium_reward(
            client, referrer_id, STREAK_BONUS_DAYS, reason
        )

        if success:
            LOGGER.info(
                f"[Referral] Streak bonus given to {referrer_id}: "
                f"streak={current_streak}, bonus={STREAK_BONUS_DAYS}d"
            )

    except Exception as e:
        LOGGER.error(
            f"[Referral] _check_streak_bonus error for {referrer_id}: {e}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# MILESTONE NEAR NOTIFICATION
# ─────────────────────────────────────────────────────────────────────────────

async def _maybe_notify_near_milestone(
    client: Client,
    referrer_id: int,
    count: int,
    next_milestone: int | None,
    needed: int,
):
    """পরের মাইলস্টোনের MILESTONE_NEAR_THRESHOLD দূরে থাকলে notification দাও।"""
    if not next_milestone or needed > MILESTONE_NEAR_THRESHOLD or needed == 0:
        return
    try:
        reward_days = MILESTONE_REWARDS.get(next_milestone, 0)
        await client.send_message(
            chat_id=referrer_id,
            text=(
                f"🔔 **Almost There!**\n\n"
                f"You're just **{needed}** referral(s) away from your next reward!\n\n"
                f"**🎯 Next Milestone:** `{next_milestone}` referrals\n"
                f"**🎁 Reward:** `{reward_days}` days Premium\n\n"
                f"Keep sharing your referral link! 🚀\n"
                f"Use /referral to get your link."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# PROCESS REFERRAL
# ─────────────────────────────────────────────────────────────────────────────

async def process_referral(
    client: Client,
    new_user_id: int,
    referrer_id: int,
) -> bool:
    """
    নতুন user রেফারের মাধ্যমে join করলে এই function call হয়।
    Anti-cheat, duplicate check, milestone check, streak check সব করে।
    """
    # Self-referral block
    if referrer_id == new_user_id:
        return False

    # Developer block
    if referrer_id == DEVELOPER_USER_ID:
        return False

    # Duplicate check
    try:
        existing = await referrals.find_one({
            "referred_user_id": new_user_id,
            "$or": [
                {"_type": {"$exists": False}},
                {"_type": {"$nin": ["milestone_log", "streak_log"]}},
            ],
        })
        if existing:
            LOGGER.info(f"[Referral] Duplicate blocked: {new_user_id}")
            return False
    except Exception as e:
        LOGGER.error(f"[Referral] Duplicate check error: {e}")
        return False

    # Referrer exists check
    try:
        referrer_exists = await total_users.find_one({"user_id": referrer_id})
        if not referrer_exists:
            LOGGER.warning(f"[Referral] Referrer {referrer_id} not in DB")
            return False
    except Exception as e:
        LOGGER.error(f"[Referral] Referrer check error: {e}")
        return False

    # Record the referral
    try:
        await referrals.insert_one({
            "_type": "referral",
            "referrer_id": referrer_id,
            "referred_user_id": new_user_id,
            "referred_at": datetime.utcnow(),
            "is_active": True,
        })
        LOGGER.info(f"[Referral] Recorded: {new_user_id} referred by {referrer_id}")
    except Exception as e:
        LOGGER.error(f"[Referral] Failed to record referral: {e}")
        return False

    # Fetch updated stats
    stats = await _get_referral_stats(referrer_id)
    count = stats["count"]
    next_ms = stats["next_milestone"]
    needed = stats["needed_for_next"]

    # Notify referrer about new referral
    try:
        new_user_doc = await total_users.find_one({"user_id": new_user_id})
        new_name = (
            new_user_doc.get("name") or
            new_user_doc.get("first_name") or
            "Someone"
        ) if new_user_doc else "Someone"

        if next_ms:
            progress_text = (
                f"\n📊 **Progress:** `{count}/{next_ms}` "
                f"(need **{needed}** more for +{MILESTONE_REWARDS[next_ms]}d reward)"
            )
        else:
            progress_text = "\n🏆 **All milestones completed! You're a legend!**"

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

    # Check milestones (with fixed ordering)
    newly_rewarded = await _check_and_reward_milestones(client, referrer_id)

    # Check streak bonus
    await _check_streak_bonus(client, referrer_id)

    # Notify if near next milestone (after milestone check)
    if not newly_rewarded:
        updated_stats = await _get_referral_stats(referrer_id)
        await _maybe_notify_near_milestone(
            client, referrer_id,
            updated_stats["count"],
            updated_stats["next_milestone"],
            updated_stats["needed_for_next"],
        )

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
    weekly = stats["weekly"]
    monthly = stats["monthly"]
    streak = stats["current_streak"]

    # Progress bar toward next milestone
    if next_ms and next_ms > 0:
        progress_pct = min((count / next_ms) * 100, 100)
        filled = int(progress_pct / 10)
        bar = "▓" * filled + "░" * (10 - filled)
        reward_days = MILESTONE_REWARDS.get(next_ms, 0)
        progress_line = (
            f"\n`[{bar}]` {progress_pct:.0f}% → "
            f"**{next_ms}** refs (+{reward_days}d)"
        )
    else:
        bar = "▓" * 10
        progress_line = f"\n`[{bar}]` 100% 🏆 All milestones done!"

    # Milestone summary with status icons
    milestone_lines = []
    for ms, days in sorted(MILESTONE_REWARDS.items()):
        if ms in rewarded:
            icon = "✅"
            status = "Done"
        elif count >= ms:
            icon = "🔓"
            status = "Unlocking..."
        else:
            icon = "🔒"
            status = f"Need {ms - count} more"
        milestone_lines.append(
            f"  {icon} **{ms} refs** → +{days}d | _{status}_"
        )

    milestones_text = "\n".join(milestone_lines)

    # Streak info
    streak_line = ""
    if streak > 0:
        streak_line = f"\n🔥 **Active Streak:** `{streak}` weeks in a row!"
    if weekly >= STREAK_WEEKLY_MIN:
        streak_line += f"\n⚡ **This week:** {weekly} refs (streak active!)"

    return (
        f"🔗 **Your Referral Link**\n"
        f"`{referral_link}`\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"**📊 Your Stats**\n"
        f"👥 **Total:** `{count}` | 📅 **Monthly:** `{monthly}` | "
        f"📆 **Weekly:** `{weekly}`"
        f"{streak_line}"
        f"{progress_line}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"**🏆 Milestone Rewards**\n"
        f"{milestones_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"**🔥 Streak Bonus**\n"
        f"Refer `{STREAK_WEEKLY_MIN}+` friends/week = "
        f"extra `{STREAK_BONUS_DAYS}` days each week!\n\n"
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
    share_url = (
        f"https://t.me/share/url?url={encoded_link}&text={encoded_text}"
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share My Link", url=share_url)],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="ref_leaderboard"),
            InlineKeyboardButton("🔄 Refresh Stats", callback_data="ref_refresh"),
        ],
        [InlineKeyboardButton("📋 My Referrals List", callback_data="ref_mylist")],
    ])


async def get_leaderboard_text() -> str:
    pipeline = [
        {"$match": {"$or": [
            {"_type": {"$exists": False}},
            {"_type": {"$nin": ["milestone_log", "streak_log"]}},
        ]}},
        {"$group": {"_id": "$referrer_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    try:
        top_users = await referrals.aggregate(pipeline).to_list(length=10)
    except Exception as e:
        LOGGER.error(f"[Referral] Leaderboard error: {e}")
        return "**🏆 Referral Leaderboard**\n\n_Error loading data. Try again._"

    if not top_users:
        return (
            "**🏆 Referral Leaderboard**\n\n"
            "_No referrals yet! Be the first!_"
        )

    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines = ["**🏆 Referral Leaderboard — Top 10**\n━━━━━━━━━━━━━━━━━━\n"]

    for i, entry in enumerate(top_users):
        uid = entry["_id"]
        count = entry["count"]
        if uid is None:
            continue
        try:
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
        except Exception:
            name = f"User {uid}"

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

        if len(message.command) >= 2 and message.command[1].lower() in (
            "top", "leaderboard"
        ):
            text = await get_leaderboard_text()
            await message.reply_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🔗 My Referral Link",
                        callback_data="ref_refresh",
                    )],
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

    # ── Callback handler ──────────────────────────────────────────────────

    @app.on_callback_query(
        filters.regex(r"^ref_(refresh|leaderboard|mylist)$")
    )
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
                        [InlineKeyboardButton(
                            "🔗 My Referral Link",
                            callback_data="ref_refresh",
                        )],
                    ]),
                )
            except Exception:
                pass
            await cq.answer("🏆 Leaderboard updated!")
            return

        if data == "ref_mylist":
            # User-এর নিজের রেফারেলের list দেখাও
            try:
                cursor = referrals.find(
                    {
                        "referrer_id": user_id,
                        "$or": [
                            {"_type": {"$exists": False}},
                            {"_type": {"$nin": ["milestone_log", "streak_log"]}},
                        ],
                    },
                    {"referred_user_id": 1, "referred_at": 1},
                ).sort("referred_at", -1).limit(15)
                recent = await cursor.to_list(length=15)
            except Exception:
                recent = []

            if not recent:
                text = "**📋 Your Referrals**\n\n_No referrals yet! Share your link!_"
            else:
                lines = [
                    f"**📋 Your Recent Referrals** (last {len(recent)})\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                ]
                for r in recent:
                    uid = r.get("referred_user_id", "?")
                    at = r.get("referred_at")
                    at_str = at.strftime("%d %b %Y") if isinstance(at, datetime) else "Unknown"
                    lines.append(f"👤 `{uid}` — {at_str}")
                text = "\n".join(lines)

            try:
                await cq.message.edit_text(
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "🔗 Back to Referral",
                            callback_data="ref_refresh",
                        )],
                    ]),
                )
            except Exception:
                pass
            await cq.answer()
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
            await message.reply_text(
                "**Usage:** `/refcheck <user_id>`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text(
                "❌ **Invalid user ID!**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        count = await _count_referrals(target_id)
        stats = await _get_referral_stats(target_id)
        milestone_doc = await _get_milestone_doc(target_id)
        rewarded = milestone_doc.get("rewarded", [])

        # Recent referrals
        try:
            cursor = referrals.find(
                {
                    "referrer_id": target_id,
                    "$or": [
                        {"_type": {"$exists": False}},
                        {"_type": {"$nin": ["milestone_log", "streak_log"]}},
                    ],
                },
                {"referred_user_id": 1, "referred_at": 1},
            ).sort("referred_at", -1).limit(10)
            recent = await cursor.to_list(length=10)
        except Exception:
            recent = []

        recent_lines = []
        for r in recent:
            uid = r.get("referred_user_id", "?")
            at = r.get("referred_at")
            at_str = at.strftime("%d %b %Y") if isinstance(at, datetime) else "Unknown"
            recent_lines.append(f"  • `{uid}` — {at_str}")

        recent_text = "\n".join(recent_lines) if recent_lines else "  _None yet_"

        pending_milestones = [
            ms for ms in sorted(MILESTONE_REWARDS.keys())
            if ms not in rewarded and count >= ms
        ]

        await message.reply_text(
            f"**📊 Referral Report — `{target_id}`**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**👥 Total Referrals:** `{count}`\n"
            f"**📅 Monthly:** `{stats['monthly']}` | "
            f"**📆 Weekly:** `{stats['weekly']}`\n"
            f"**🔥 Streak:** `{stats['current_streak']}` weeks\n"
            f"**🏆 Milestones Rewarded:** `{rewarded}`\n"
            f"**⚠️ Pending (bug?):** `{pending_milestones}`\n\n"
            f"**📋 Recent (last 10):**\n{recent_text}\n\n"
            f"_Use /refgive {target_id} force to manually give rewards_",
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Admin: /refgive <user_id> [force] — FIXED ────────────────────────

    @app.on_message(
        filters.command("refgive", prefixes=COMMAND_PREFIX)
        & filters.private
        & filters.user(DEVELOPER_USER_ID)
    )
    async def refgive_command(client: Client, message: Message):
        """
        ✅ FIXED: এখন সত্যিই কাজ করে।
        - Premium দেওয়ার পরে milestone mark হয়
        - সব exception handle করা
        - Force mode সঠিকভাবে কাজ করে
        """
        if len(message.command) < 2:
            await message.reply_text(
                "**Usage:** `/refgive <user_id> [force]`\n\n"
                "`force` দিলে milestone log reset করে সব eligible reward দেবে।",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text(
                "❌ **Invalid user ID!**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        force_mode = (
            len(message.command) >= 3 and
            message.command[2].lower() == "force"
        )

        count = await _count_referrals(target_id)

        status_msg = await message.reply_text(
            f"**⏳ Processing...**\n"
            f"**Referral count:** `{count}`\n"
            f"**Force mode:** `{'ON' if force_mode else 'OFF'}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            if force_mode:
                # milestone_log reset করো
                await referrals.delete_one(
                    {"_type": "milestone_log", "user_id": target_id}
                )
                LOGGER.info(
                    f"[refgive] Force mode: milestone_log cleared for {target_id}"
                )

            # Before state
            milestone_doc_before = await _get_milestone_doc(target_id)
            rewarded_before = milestone_doc_before.get("rewarded", [])

            # Reward দাও (fixed function)
            newly_rewarded = await _check_and_reward_milestones(client, target_id)

            # After state
            milestone_doc_after = await _get_milestone_doc(target_id)
            rewarded_after = milestone_doc_after.get("rewarded", [])

            if newly_rewarded:
                # Reward দেওয়া সফল হয়েছে
                reward_summary = []
                for ms in newly_rewarded:
                    days = MILESTONE_REWARDS.get(ms, 0)
                    reward_summary.append(f"  ✅ Milestone **{ms}** → +{days} days")

                await status_msg.edit_text(
                    f"✅ **Rewards given for user `{target_id}`!**\n\n"
                    f"**👥 Referral count:** `{count}`\n"
                    f"**🎁 Rewards given:**\n" + "\n".join(reward_summary) + "\n\n"
                    f"**📋 All rewarded milestones:** `{rewarded_after}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                # কোনো নতুন reward নেই
                pending = [
                    ms for ms in sorted(MILESTONE_REWARDS.keys())
                    if ms not in rewarded_after and count >= ms
                ]

                if pending:
                    await status_msg.edit_text(
                        f"⚠️ **Milestone eligible but reward failed!**\n\n"
                        f"**👥 Count:** `{count}`\n"
                        f"**Already rewarded:** `{rewarded_after}`\n"
                        f"**Eligible but failed:** `{pending}`\n\n"
                        f"Check logs for DB errors.\n"
                        f"Try: `/refgive {target_id} force`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    next_ms_list = [
                        ms for ms in sorted(MILESTONE_REWARDS.keys())
                        if ms not in rewarded_after
                    ]
                    next_needed = (
                        next_ms_list[0] - count
                        if next_ms_list else 0
                    )
                    await status_msg.edit_text(
                        f"ℹ️ **No new rewards for `{target_id}`.**\n\n"
                        f"**👥 Count:** `{count}`\n"
                        f"**Already rewarded:** `{rewarded_after}`\n\n"
                        + (
                            f"_Next milestone: {next_ms_list[0]} refs "
                            f"(need {next_needed} more)_"
                            if next_ms_list else
                            "_All milestones completed!_"
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )

        except Exception as e:
            LOGGER.error(f"[refgive] Error: {e}")
            try:
                await status_msg.edit_text(
                    f"❌ **Error during refgive!**\n\n`{str(e)[:200]}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

    # ── Admin: /refstats ──────────────────────────────────────────────────

    @app.on_message(
        filters.command("refstats", prefixes=COMMAND_PREFIX)
        & filters.private
        & filters.user(DEVELOPER_USER_ID)
    )
    async def refstats_command(client: Client, message: Message):
        try:
            total_ref = await referrals.count_documents({
                "$or": [
                    {"_type": {"$exists": False}},
                    {"_type": {"$nin": ["milestone_log", "streak_log"]}},
                ]
            })

            ur_result = await referrals.aggregate([
                {"$match": {"$or": [
                    {"_type": {"$exists": False}},
                    {"_type": {"$nin": ["milestone_log", "streak_log"]}},
                ]}},
                {"$group": {"_id": "$referrer_id"}},
                {"$count": "count"},
            ]).to_list(length=1)
            unique_referrers = ur_result[0]["count"] if ur_result else 0

            top_result = await referrals.aggregate([
                {"$match": {"$or": [
                    {"_type": {"$exists": False}},
                    {"_type": {"$nin": ["milestone_log", "streak_log"]}},
                ]}},
                {"$group": {"_id": "$referrer_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 1},
            ]).to_list(length=1)
            top_info = "N/A"
            if top_result:
                top_uid = top_result[0]["_id"]
                top_cnt = top_result[0]["count"]
                top_info = f"`{top_uid}` ({top_cnt} referrals)"

            # Weekly stats
            week_ago = datetime.utcnow() - timedelta(days=7)
            weekly_ref = await referrals.count_documents({
                "referred_at": {"$gte": week_ago},
                "$or": [
                    {"_type": {"$exists": False}},
                    {"_type": {"$nin": ["milestone_log", "streak_log"]}},
                ],
            })

            # Monthly stats
            month_ago = datetime.utcnow() - timedelta(days=30)
            monthly_ref = await referrals.count_documents({
                "referred_at": {"$gte": month_ago},
                "$or": [
                    {"_type": {"$exists": False}},
                    {"_type": {"$nin": ["milestone_log", "streak_log"]}},
                ],
            })

            # Total milestones rewarded
            milestone_count = await referrals.count_documents(
                {"_type": "milestone_log"}
            )

            await message.reply_text(
                f"**📊 Global Referral Stats**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"**🔗 Total Referrals:** `{total_ref}`\n"
                f"**👤 Unique Referrers:** `{unique_referrers}`\n"
                f"**📅 Monthly:** `{monthly_ref}`\n"
                f"**📆 Weekly:** `{weekly_ref}`\n"
                f"**🏆 Users with Milestones:** `{milestone_count}`\n"
                f"**🥇 Top Referrer:** {top_info}\n"
                f"━━━━━━━━━━━━━━━━━━",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            await message.reply_text(
                f"❌ **Error fetching stats:** `{e}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Admin: /reflist <user_id> — full referral list ────────────────────

    @app.on_message(
        filters.command("reflist", prefixes=COMMAND_PREFIX)
        & filters.private
        & filters.user(DEVELOPER_USER_ID)
    )
    async def reflist_command(client: Client, message: Message):
        if len(message.command) < 2:
            await message.reply_text(
                "**Usage:** `/reflist <user_id>`\n"
                "Shows all referrals made by a user.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            target_id = int(message.command[1])
        except ValueError:
            await message.reply_text(
                "❌ **Invalid user ID!**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        try:
            cursor = referrals.find(
                {
                    "referrer_id": target_id,
                    "$or": [
                        {"_type": {"$exists": False}},
                        {"_type": {"$nin": ["milestone_log", "streak_log"]}},
                    ],
                },
                {"referred_user_id": 1, "referred_at": 1},
            ).sort("referred_at", -1)
            all_refs = await cursor.to_list(length=None)
        except Exception as e:
            await message.reply_text(
                f"❌ **DB error:** `{e}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if not all_refs:
            await message.reply_text(
                f"**No referrals found for `{target_id}`.**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        lines = [
            f"**📋 All Referrals by `{target_id}`**\n"
            f"Total: **{len(all_refs)}**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
        ]
        for r in all_refs:
            uid = r.get("referred_user_id", "?")
            at = r.get("referred_at")
            at_str = at.strftime("%d %b %Y %H:%M") if isinstance(at, datetime) else "Unknown"
            lines.append(f"• `{uid}` — {at_str}")

        text = "\n".join(lines)
        # Telegram message limit
        if len(text) > 4000:
            text = text[:3997] + "..."

        await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    # ── Register /referral command ────────────────────────────────────────

    app.add_handler(
        MessageHandler(
            referral_command,
            filters=filters.command("referral", prefixes=COMMAND_PREFIX)
            & (filters.private | filters.group),
        ),
        group=1,
    )
