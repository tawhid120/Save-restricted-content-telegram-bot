# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/auto_router.py — Unified Auto-Link & Command Router
#
# এই ফাইলটি সব ধরনের লিংক ও কমান্ড অটোমেটিক ডিটেক্ট করে
# সঠিক plugin-এ পাঠায়। Telegram লিংক সবসময় autolink.py-তে যাবে।
#
# ═══════════════════════════════════════════════════════════════════
# ROUTING TABLE:
# ───────────────────────────────────────────────────────────────────
# t.me / telegram.me লিংক  → autolink.py   (কোনো conflict নেই)
# drive.google.com          → gdl.py        (/gdl)
# mediafire, gofile, etc.   → directdl.py   (/ddl)
# youtube, vimeo, 1000+ sites → ytdl.py    (/ytdl)
# magnet: / .torrent        → aria2dl.py    (/dl)
# Direct HTTP file URL      → urldl.py      (auto)
# ═══════════════════════════════════════════════════════════════════

import re
import asyncio
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode, ChatType

from config import COMMAND_PREFIX
from utils import LOGGER
from utils.force_sub import check_force_sub

# ─────────────────────────────────────────────────────────────────
# PATTERN DEFINITIONS
# ─────────────────────────────────────────────────────────────────

# Telegram লিংক — এগুলো autolink.py handle করবে, এখানে ছোঁয়া হবে না
TELEGRAM_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:c/)?([a-zA-Z0-9_]+|\d+)/(\d+)(?:/\d+)?"
)

# Google Drive
GDRIVE_PATTERN = re.compile(
    r"https?://(?:drive|docs)\.google\.com/\S+",
    re.IGNORECASE,
)

# Magnet লিংক ও torrent URL
MAGNET_PATTERN = re.compile(r"^magnet:\?xt=", re.IGNORECASE)
TORRENT_PATTERN = re.compile(r"\.torrent(\?.*)?$", re.IGNORECASE)

# yt-dlp সাপোর্টেড সাইটের pattern (প্রধান সাইটগুলো)
YTDLP_DOMAINS = {
    "youtube.com", "youtu.be", "www.youtube.com",
    "m.youtube.com", "music.youtube.com",
    "vimeo.com", "dailymotion.com", "twitch.tv",
    "tiktok.com", "vm.tiktok.com",
    "instagram.com", "www.instagram.com",
    "twitter.com", "x.com", "t.co",
    "facebook.com", "fb.watch", "www.facebook.com",
    "soundcloud.com", "bandcamp.com",
    "reddit.com", "v.redd.it",
    "bilibili.com", "b23.tv",
    "nicovideo.jp", "nico.ms",
    "mixcloud.com", "vk.com",
    "rumble.com", "odysee.com",
    "ok.ru", "coub.com",
    "streamable.com", "streamvi.com",
    "ted.com", "bbc.co.uk", "bbc.com",
    "cnn.com", "nbc.com", "abc.net.au",
    "arte.tv", "zdf.de", "ard.de",
    "crunchyroll.com", "funimation.com",
    "pornhub.com", "xvideos.com", "xnxx.com",
    "imdb.com", "openload.co",
    "9gag.com", "liveleak.com",
    "izlesene.com", "vidio.com",
    "kakao.com", "vlive.tv",
    "naver.com", "daum.net",
}

# HLS / m3u8 stream
HLS_PATTERN = re.compile(r"\.m3u8(\?.*)?$", re.IGNORECASE)

# directdl.py সাপোর্টেড সাইটগুলো (utils/direct_links.py থেকে)
DIRECTDL_DOMAINS = {
    "mediafire.com", "gofile.io", "pixeldrain.com", "pixeldra.in",
    "1fichier.com", "streamtape.com", "wetransfer.com", "we.tl",
    "swisstransfer.com", "qiwi.gg", "mp4upload.com", "buzzheavier.com",
    "send.cm", "linkbox.to", "lbx.to", "krakenfiles.com",
    "solidfiles.com", "upload.ee", "tmpsend.com", "easyupload.io",
    "streamvid.net", "streamhub.ink", "streamhub.to",
    "u.pcloud.link", "berkasdrive.com", "akmfiles.com", "akmfls.xyz",
    "hxfile.co", "1drv.ms", "osdn.net",
    "yadi.sk", "disk.yandex.com", "disk.yandex.ru",
    "devuploads.com", "uploadhaven.com", "fuckingfast.co",
    "mediafile.cc", "lulacloud.com",
    "shrdsk.me", "transfer.it",
    "terabox.com", "nephobox.com", "4funbox.com", "teraboxapp.com",
    "1024tera.com", "freeterabox.com",
    "filelions.co", "filelions.site", "filelions.live",
    "streamwish.to", "embedwish.com",
    "dood.watch", "doodstream.com", "dood.to", "dood.so",
    "ds2play.com", "dood.cx",
    "racaty.net", "racaty.io",
}

# ─────────────────────────────────────────────────────────────────
# ROUTER LOGIC
# ─────────────────────────────────────────────────────────────────

def _get_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower().lstrip("www.")
    except Exception:
        return ""


def _is_telegram_link(text: str) -> bool:
    return bool(TELEGRAM_LINK_PATTERN.search(text))


def _is_gdrive_link(url: str) -> bool:
    domain = _get_domain(url)
    return "drive.google.com" in domain or "docs.google.com" in domain


def _is_magnet_or_torrent(url: str) -> bool:
    return bool(MAGNET_PATTERN.match(url)) or bool(TORRENT_PATTERN.search(url))


def _is_ytdlp_site(url: str) -> bool:
    domain = _get_domain(url)
    # subdomain check
    for yd in YTDLP_DOMAINS:
        if domain == yd or domain.endswith(f".{yd}"):
            return True
    return False


def _is_directdl_site(url: str) -> bool:
    domain = _get_domain(url)
    for dd in DIRECTDL_DOMAINS:
        if domain == yd or domain.endswith(f".{dd}") or dd in domain:
            return True
    return False


def _is_hls_stream(url: str) -> bool:
    return bool(HLS_PATTERN.search(url.split("?")[0]))


def _is_direct_http_file(url: str) -> bool:
    """সরাসরি HTTP ফাইল লিংক — কোনো বিশেষ সাইট নয়"""
    if not url.startswith(("http://", "https://")):
        return False
    domain = _get_domain(url)
    # Telegram, Google Drive, ytdlp, directdl — এসব ছাড়া বাকি HTTP লিংক
    if "t.me" in domain or "telegram.me" in domain:
        return False
    if _is_gdrive_link(url):
        return False
    return True


def detect_route(url: str) -> str:
    """
    URL দেখে সঠিক route নির্ধারণ করে।

    Returns:
        "telegram"  → autolink.py (Telegram লিংক)
        "gdrive"    → gdl.py
        "aria2"     → aria2dl.py (magnet/torrent)
        "ytdlp"     → ytdl.py
        "directdl"  → directdl.py
        "urldl"     → urldl.py (generic HTTP)
        "unknown"   → অজানা
    """
    url = url.strip()

    if not url:
        return "unknown"

    # 1. Telegram লিংক — সর্বোচ্চ priority
    if _is_telegram_link(url):
        return "telegram"

    # 2. Google Drive
    if _is_gdrive_link(url):
        return "gdrive"

    # 3. Magnet / Torrent
    if _is_magnet_or_torrent(url):
        return "aria2"

    # 4. HLS stream — yt-dlp দিয়ে চেষ্টা করা হবে
    if _is_hls_stream(url):
        return "ytdlp"

    # 5. Known yt-dlp সাইট
    if _is_ytdlp_site(url):
        return "ytdlp"

    # 6. Known directdl সাইট
    domain = _get_domain(url)
    for dd in DIRECTDL_DOMAINS:
        if dd in domain:
            return "directdl"

    # 7. Generic HTTP ফাইল লিংক
    if _is_direct_http_file(url):
        return "urldl"

    return "unknown"


# ─────────────────────────────────────────────────────────────────
# ROUTE LABELS (UI display)
# ─────────────────────────────────────────────────────────────────

ROUTE_INFO = {
    "telegram": {
        "icon": "📨",
        "label": "Telegram Link",
        "hint": "autolink detection এ handled হবে",
        "command": None,
    },
    "gdrive": {
        "icon": "☁️",
        "label": "Google Drive",
        "hint": "Google Drive থেকে download করবে",
        "command": "gdl",
    },
    "aria2": {
        "icon": "🌊",
        "label": "Torrent / Magnet",
        "hint": "Aria2c দিয়ে download করবে",
        "command": "dl",
    },
    "ytdlp": {
        "icon": "🎬",
        "label": "Video Site (yt-dlp)",
        "hint": "yt-dlp দিয়ে download করবে",
        "command": "ytdl",
    },
    "directdl": {
        "icon": "📦",
        "label": "File Hosting Site",
        "hint": "Direct link generator দিয়ে download করবে",
        "command": "ddl",
    },
    "urldl": {
        "icon": "🔗",
        "label": "Direct URL",
        "hint": "সরাসরি HTTP download করবে",
        "command": "urldl",
    },
}


# ─────────────────────────────────────────────────────────────────
# INLINE KEYBOARDS
# ─────────────────────────────────────────────────────────────────

def _route_confirm_keyboard(route: str, url_short: str) -> InlineKeyboardMarkup:
    info = ROUTE_INFO.get(route, {})
    icon = info.get("icon", "🔗")
    label = info.get("label", route)
    cmd = info.get("command")

    buttons = []
    if cmd:
        buttons.append([
            InlineKeyboardButton(
                f"{icon} Download ({label})",
                callback_data=f"autoroute_go_{route}",
            )
        ])
    buttons.append([
        InlineKeyboardButton("❌ Cancel", callback_data="autoroute_cancel"),
    ])
    return InlineKeyboardMarkup(buttons)


def _multi_route_keyboard(routes: list) -> InlineKeyboardMarkup:
    """একাধিক route option দেখানোর জন্য"""
    buttons = []
    for route in routes:
        info = ROUTE_INFO.get(route, {})
        icon = info.get("icon", "🔗")
        label = info.get("label", route)
        buttons.append([
            InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"autoroute_go_{route}",
            )
        ])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="autoroute_cancel")])
    return InlineKeyboardMarkup(buttons)


# ─────────────────────────────────────────────────────────────────
# SESSION STORE: pending route confirmations
# ─────────────────────────────────────────────────────────────────

_pending_routes: dict = {}  # chat_id → { url, route, user_id }


# ─────────────────────────────────────────────────────────────────
# ROUTE EXECUTOR — সঠিক handler-এ forward করে
# ─────────────────────────────────────────────────────────────────

async def _execute_route(client: Client, message: Message, url: str, route: str):
    """নির্ধারিত route অনুযায়ী download শুরু করে।"""
    user_id = message.from_user.id if message.from_user else message.chat.id

    LOGGER.info(f"[AutoRouter] Executing route={route} url={url[:60]} user={user_id}")

    if route == "telegram":
        # autolink.py নিজেই handle করে — এখানে কিছু করার নেই
        # তবু confirm করা হয়েছে, তাই user-কে জানাই
        await message.reply_text(
            "ℹ️ **Telegram লিংক ডিটেক্ট হয়েছে।**\n\n"
            "লিংকটি সরাসরি chat-এ paste করুন — বট অটোমেটিক download করবে।",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif route == "gdrive":
        # gdl.py → _process_gdl()
        try:
            from plugins.gdl import _process_gdl
            await _process_gdl(client, message, url)
        except ImportError:
            await message.reply_text(
                "❌ **Google Drive downloader লোড হয়নি!**\n"
                "Admin-কে জানান।",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif route == "aria2":
        # aria2dl.py → /dl command handler simulate
        try:
            import shutil
            if not shutil.which("aria2c"):
                await message.reply_text(
                    "❌ **aria2c ইনস্টল নেই!**\n"
                    "Admin: `sudo apt install aria2`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            # aria2dl handler-কে simulate করতে fake command text set
            message.text = f"/dl {url}"
            message.command = ["dl", url]
            from plugins.aria2dl import _run_download, _cancel_events
            import asyncio
            status_msg = await message.reply_text(
                "🔄 **Torrent/Magnet download শুরু হচ্ছে...**",
                parse_mode=ParseMode.MARKDOWN,
            )
            cancel_event = asyncio.Event()
            _cancel_events[status_msg.id] = cancel_event
            from plugins.aria2dl import _is_premium, _check_and_set_cooldown
            is_prem = await _is_premium(user_id)
            asyncio.create_task(
                _run_download(client, message, url, None, status_msg, is_prem, cancel_event)
            )
        except ImportError:
            await message.reply_text(
                "❌ **Aria2 downloader লোড হয়নি!**\n"
                "Admin-কে জানান।",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif route == "ytdlp":
        # ytdl.py → _handle_single_video_initiate()
        try:
            from plugins.ytdl import (
                _handle_single_video_initiate_public,
                is_premium_user,
                _check_rate_limit,
                parse_url_and_referer,
            )
            url_clean, referer = parse_url_and_referer(url)
            is_prem = await is_premium_user(user_id)
            allowed, rate_msg = await _check_rate_limit(user_id, is_prem)
            if not allowed:
                await message.reply_text(rate_msg, parse_mode=ParseMode.MARKDOWN)
                return
            await _handle_single_video_initiate_public(
                client, message, url_clean, user_id, is_prem, referer
            )
        except (ImportError, AttributeError):
            # fallback: /ytdl command simulate
            await message.reply_text(
                f"🎬 **yt-dlp দিয়ে download করতে:**\n\n"
                f"`/ytdl {url}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif route == "directdl":
        # directdl.py → _process_ddl()
        try:
            from plugins.directdl import _process_ddl
            status_msg = await message.reply_text(
                "🔄 **Processing...**",
                parse_mode=ParseMode.MARKDOWN,
            )
            asyncio.create_task(_process_ddl(client, message, url, status_msg))
        except ImportError:
            await message.reply_text(
                f"📦 **File hosting site ডিটেক্ট হয়েছে।**\n\n"
                f"Download করতে:\n`/ddl {url}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif route == "urldl":
        # urldl.py → auto detection already covers this
        # just provide a command hint
        await message.reply_text(
            f"🔗 **Direct URL ডিটেক্ট হয়েছে।**\n\n"
            f"Download করতে:\n`/urldl {url}`\n\n"
            f"অথবা URL টি সরাসরি paste করুন।",
            parse_mode=ParseMode.MARKDOWN,
        )

    else:
        await message.reply_text(
            f"❓ **এই লিংকের জন্য কোনো handler পাওয়া যায়নি।**\n\n"
            f"URL: `{url[:100]}`",
            parse_mode=ParseMode.MARKDOWN,
        )


# ─────────────────────────────────────────────────────────────────
# /route COMMAND — যেকোনো লিংক দিলে route বলে দেবে
# ─────────────────────────────────────────────────────────────────

async def _route_command_handler(client: Client, message: Message):
    """
    /route <URL>
    যেকোনো লিংক দিলে কোন downloader ব্যবহার করা হবে তা দেখাবে।
    """
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.reply_text(
            "**🗺 Link Router**\n\n"
            "**Usage:** `/route <URL>`\n\n"
            "যেকোনো লিংক দিলে বট বলে দেবে কোন downloader ব্যবহার হবে।\n\n"
            "**উদাহরণ:**\n"
            "`/route https://youtu.be/xxxxx`\n"
            "`/route https://drive.google.com/file/d/xxx`\n"
            "`/route https://mediafire.com/file/xxx`\n"
            "`/route magnet:?xt=urn:btih:xxx`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = parts[1].strip()
    route = detect_route(url)
    info = ROUTE_INFO.get(route, {"icon": "❓", "label": "Unknown", "hint": "N/A", "command": None})

    cmd_line = f"`/{info['command']} {url[:60]}`" if info.get("command") else "_(autolink ডিটেক্ট করবে)_"

    await message.reply_text(
        f"**🗺 Link Analysis**\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 **URL:** `{url[:80]}`\n\n"
        f"{info['icon']} **Route:** `{info['label']}`\n"
        f"ℹ️ **Info:** {info['hint']}\n\n"
        f"**▶️ Command:**\n{cmd_line}",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


# ─────────────────────────────────────────────────────────────────
# /autoroute COMMAND — লিংক দিলে অটো detect করে download শুরু করবে
# ─────────────────────────────────────────────────────────────────

async def _autoroute_command_handler(client: Client, message: Message):
    """
    /autoroute <URL>
    লিংক ডিটেক্ট করে সঠিক downloader-এ পাঠায়।
    Telegram লিংক autolink.py-তে থাকে।
    """
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.reply_text(
            "**🚀 Auto Router**\n\n"
            "**Usage:** `/autoroute <URL>`\n\n"
            "লিংক দিলে বট অটোমেটিক সঠিক downloader বেছে নেবে।\n\n"
            "**Supported:**\n"
            "• 📨 Telegram লিংক → autolink\n"
            "• ☁️ Google Drive → `/gdl`\n"
            "• 🌊 Magnet/Torrent → `/dl`\n"
            "• 🎬 YouTube/1000+ sites → `/ytdl`\n"
            "• 📦 MediaFire, GoFile, etc → `/ddl`\n"
            "• 🔗 Direct HTTP file → `/urldl`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = parts[1].strip()
    route = detect_route(url)
    info = ROUTE_INFO.get(route, {"icon": "❓", "label": "Unknown", "hint": "N/A", "command": None})

    # Telegram লিংক হলে user-কে guide করি কিন্তু autolink conflict করি না
    if route == "telegram":
        await message.reply_text(
            "📨 **Telegram লিংক ডিটেক্ট হয়েছে!**\n\n"
            "এই লিংকটি সরাসরি chat-এ paste করুন —\n"
            "বট অটোমেটিক download করবে। ✅",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Unknown route
    if route == "unknown" or not info.get("command"):
        await message.reply_text(
            f"❓ **এই লিংকের জন্য কোনো handler পাওয়া যায়নি।**\n\n"
            f"URL: `{url[:100]}`\n\n"
            f"সরাসরি paste করলে বট চেষ্টা করবে।",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Confirm screen
    url_short = url[:70] + ("..." if len(url) > 70 else "")
    user_id = message.from_user.id

    _pending_routes[message.chat.id] = {
        "url": url,
        "route": route,
        "user_id": user_id,
    }

    await message.reply_text(
        f"**🚀 Link Detected!**\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{info['icon']} **Type:** `{info['label']}`\n"
        f"ℹ️ **Action:** {info['hint']}\n\n"
        f"🔗 `{url_short}`\n\n"
        f"**Download শুরু করবেন?**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_route_confirm_keyboard(route, url_short),
        disable_web_page_preview=True,
    )


# ─────────────────────────────────────────────────────────────────
# CALLBACK: autoroute_go_ / autoroute_cancel
# ─────────────────────────────────────────────────────────────────

async def _autoroute_callback(client: Client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id

    if data == "autoroute_cancel":
        _pending_routes.pop(chat_id, None)
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        await callback_query.answer("❌ Cancelled.")
        return

    if data.startswith("autoroute_go_"):
        route = data[len("autoroute_go_"):]
        pending = _pending_routes.get(chat_id)

        if not pending or pending.get("user_id") != user_id:
            await callback_query.answer("❌ Session expired!", show_alert=True)
            return

        url = pending["url"]
        _pending_routes.pop(chat_id, None)

        try:
            await callback_query.message.delete()
        except Exception:
            pass

        await callback_query.answer(f"⏳ Starting {route}...")

        # message object তৈরি করা কঠিন, তাই reply পাঠাই
        new_msg = await client.send_message(
            chat_id=chat_id,
            text=f"⏳ **Processing...**",
            parse_mode=ParseMode.MARKDOWN,
        )
        # message.from_user set করা যাবে না, তাই sender simulate করি
        new_msg.from_user = callback_query.from_user
        await _execute_route(client, new_msg, url, route)


# ─────────────────────────────────────────────────────────────────
# TEXT-based auto detection (group=3 — pbatch ও autolink এর পরে)
# ─────────────────────────────────────────────────────────────────
# শুধুমাত্র non-Telegram, non-command URL-এর জন্য।
# Telegram লিংক autolink.py (group=1) আগেই handle করে।
# ─────────────────────────────────────────────────────────────────

GENERIC_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"{}|\\^`\[\]]+",
    re.IGNORECASE,
)


async def _auto_detect_handler(client: Client, message: Message):
    """
    group=3 — Telegram লিংক বাদ দিয়ে অন্য URL auto-detect করে।
    """
    if not message.text:
        return
    if message.text.strip().startswith(tuple(COMMAND_PREFIX)):
        return

    # Telegram লিংক থাকলে autolink.py-এর উপর ছেড়ে দাও (এখানে handle করি না)
    if TELEGRAM_LINK_PATTERN.search(message.text):
        return

    # pbatch session চেক
    import sys
    _pbatch = sys.modules.get("plugins.pbatch")
    if _pbatch:
        state = _pbatch.batch_data.get(message.chat.id)
        if state and state.get("user_id") == (
            message.from_user.id if message.from_user else -1
        ):
            return

    # URL খোঁজা
    match = GENERIC_URL_PATTERN.search(message.text)
    if not match:
        return

    url = match.group(0).strip().rstrip(".,;!?)")
    route = detect_route(url)

    # Telegram ও unknown route skip
    if route in ("telegram", "unknown", "urldl"):
        return  # urldl.py নিজেই group=2 তে handle করে

    # Google Drive, magnet, ytdlp, directdl — hint দিই
    info = ROUTE_INFO.get(route, {})
    cmd = info.get("command")
    if not cmd:
        return

    user_id = message.from_user.id if message.from_user else 0

    # Force sub check
    if message.chat.type == ChatType.PRIVATE and message.from_user:
        if not await check_force_sub(client, user_id):
            return

    url_short = url[:60] + ("..." if len(url) > 60 else "")

    _pending_routes[message.chat.id] = {
        "url": url,
        "route": route,
        "user_id": user_id,
    }

    await message.reply_text(
        f"{info.get('icon', '🔗')} **{info.get('label', route)} ডিটেক্ট হয়েছে!**\n\n"
        f"`{url_short}`\n\n"
        f"**{info.get('hint', '')}**\n\n"
        f"Download করবেন?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_route_confirm_keyboard(route, url_short),
        disable_web_page_preview=True,
    )


# ─────────────────────────────────────────────────────────────────
# HANDLER INFO COMMAND — সব plugin-এর কমান্ড তালিকা দেখাবে
# ─────────────────────────────────────────────────────────────────

PLUGIN_COMMAND_INFO = """
**📋 সব Plugin Commands**
━━━━━━━━━━━━━━━━━━━━━━━━

**📨 Telegram Content:**
• _(Telegram লিংক সরাসরি paste করুন)_
• `/batch` — Batch download (Premium)

**🎬 Video Downloader (yt-dlp):**
• `/ytdl <URL>` — YouTube, TikTok, Instagram, 1000+ সাইট
• `/ytdl <URL> referer:<site>` — Protected HLS/m3u8 stream

**☁️ Google Drive:**
• `/gdl <URL>` — Google Drive file/folder download
• `/gdl` — সরাসরি command দিয়ে URL ask করবে

**📦 File Hosting Sites:**
• `/ddl <URL>` — MediaFire, GoFile, Pixeldrain, 1Fichier, etc.
• _(40+ সাইট supported)_

**🌊 Torrent / Magnet:**
• `/dl <magnet>` — Magnet link download
• `/dl <torrent URL>` — Torrent file download
• `/mirror <same>` — Alias

**🔗 Direct URL:**
• `/urldl <URL>` — যেকোনো direct HTTP file download
• _(URL সরাসরি paste করলেও কাজ করে)_

**📺 YouTube Upload:**
• `/ytconnect` — YouTube channel connect
• `/ytupload <URL>` — Video upload to YouTube
• `/ytsend` — Telegram video → YouTube

**🗺 Router Tools:**
• `/route <URL>` — কোন downloader হবে দেখাবে
• `/autoroute <URL>` — অটো detect করে download করবে
"""


async def _plugininfo_command_handler(client: Client, message: Message):
    await message.reply_text(
        PLUGIN_COMMAND_INFO,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


# ─────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────

def setup_auto_router(app: Client):
    """
    Auto Router handlers register করে।

    Handler groups:
      group=1  → autolink.py (Telegram লিংক) — conflict নেই
      group=2  → urldl.py (generic URL auto-detect)
      group=3  → এই ফাইলের auto-detect (non-Telegram, non-urldl)
    """
    from pyrogram.handlers import MessageHandler, CallbackQueryHandler

    # /route command
    app.add_handler(
        MessageHandler(
            _route_command_handler,
            filters=filters.command("route", prefixes=COMMAND_PREFIX)
            & (filters.private | filters.group),
        ),
        group=1,
    )

    # /autoroute command
    app.add_handler(
        MessageHandler(
            _autoroute_command_handler,
            filters=filters.command("autoroute", prefixes=COMMAND_PREFIX)
            & (filters.private | filters.group),
        ),
        group=1,
    )

    # /plugininfo command
    app.add_handler(
        MessageHandler(
            _plugininfo_command_handler,
            filters=filters.command(["plugininfo", "commands", "allcmds"], prefixes=COMMAND_PREFIX)
            & (filters.private | filters.group),
        ),
        group=1,
    )

    # Callback: autoroute_go_ / autoroute_cancel
    app.add_handler(
        CallbackQueryHandler(
            _autoroute_callback,
            filters=filters.regex(r"^autoroute_(go_.+|cancel)$"),
        ),
        group=1,
    )

    # Auto URL detection (group=3 — Telegram লিংক বাদ দিয়ে)
    app.add_handler(
        MessageHandler(
            _auto_detect_handler,
            filters=filters.text & (filters.private | filters.group),
        ),
        group=3,
    )

    LOGGER.info(
        "[AutoRouter] Registered: /route, /autoroute, /plugininfo, "
        "auto URL detection (group=3) ✅"
    )
