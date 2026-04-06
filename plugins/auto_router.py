# Copyright @juktijol
# Channel t.me/juktijol
#
# plugins/auto_router.py — Fully Automatic Link Router (No Command Required)
#
# URL paste করলেই অটোমেটিক সঠিক downloader-এ পাঠাবে
# কোনো confirm button বা command দরকার নেই
#
# ═══════════════════════════════════════════════════════════════════
# ROUTING TABLE:
# ───────────────────────────────────────────────────────────────────
# t.me / telegram.me লিংক  → autolink.py   (কোনো conflict নেই)
# drive.google.com          → gdl.py        (অটো)
# mediafire, gofile, etc.   → directdl.py   (অটো)
# youtube, vimeo, 1000+ sites → ytdl.py    (অটো)
# magnet: / .torrent        → aria2dl.py    (অটো)
# Direct HTTP file URL      → urldl.py      (অটো)
# ═══════════════════════════════════════════════════════════════════

import re
import asyncio
import sys
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode, ChatType

from config import COMMAND_PREFIX
from utils import LOGGER
from utils.force_sub import check_force_sub

# ─────────────────────────────────────────────────────────────────
# PATTERN DEFINITIONS
# ─────────────────────────────────────────────────────────────────

# Telegram লিংক — autolink.py handle করবে
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

# HLS / m3u8 stream
HLS_PATTERN = re.compile(r"\.m3u8(\?.*)?$", re.IGNORECASE)

# Generic URL pattern
GENERIC_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"{}|\\^`\[\]]+",
    re.IGNORECASE,
)

# yt-dlp সাপোর্টেড সাইটের domain list
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

# directdl.py সাপোর্টেড সাইটগুলো
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
    for yd in YTDLP_DOMAINS:
        if domain == yd or domain.endswith(f".{yd}"):
            return True
    return False


def _is_directdl_site(url: str) -> bool:
    domain = _get_domain(url)
    for dd in DIRECTDL_DOMAINS:
        if domain == dd or domain.endswith(f".{dd}") or dd in domain:
            return True
    return False


def _is_hls_stream(url: str) -> bool:
    return bool(HLS_PATTERN.search(url.split("?")[0]))


def _is_direct_http_file(url: str) -> bool:
    """সরাসরি HTTP ফাইল লিংক"""
    if not url.startswith(("http://", "https://")):
        return False
    domain = _get_domain(url)
    if "t.me" in domain or "telegram.me" in domain:
        return False
    if _is_gdrive_link(url):
        return False
    return True


def detect_route(url: str) -> str:
    """
    URL দেখে সঠিক route নির্ধারণ।

    Returns:
        "telegram"  → autolink.py
        "gdrive"    → gdl.py
        "aria2"     → aria2dl.py
        "ytdlp"     → ytdl.py
        "directdl"  → directdl.py
        "urldl"     → urldl.py
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

    # 4. HLS stream
    if _is_hls_stream(url):
        return "ytdlp"

    # 5. Known yt-dlp সাইট
    if _is_ytdlp_site(url):
        return "ytdlp"

    # 6. Known directdl সাইট
    if _is_directdl_site(url):
        return "directdl"

    # 7. Generic HTTP ফাইল
    if _is_direct_http_file(url):
        return "urldl"

    return "unknown"


# ─────────────────────────────────────────────────────────────────
# ROUTE LABELS (logging ও status message এর জন্য)
# ─────────────────────────────────────────────────────────────────

ROUTE_INFO = {
    "telegram": {
        "icon": "📨",
        "label": "Telegram Link",
        "hint": "autolink দিয়ে handle হবে",
    },
    "gdrive": {
        "icon": "☁️",
        "label": "Google Drive",
        "hint": "Google Drive থেকে download করছে...",
    },
    "aria2": {
        "icon": "🌊",
        "label": "Torrent / Magnet",
        "hint": "Aria2c দিয়ে download করছে...",
    },
    "ytdlp": {
        "icon": "🎬",
        "label": "Video Site (yt-dlp)",
        "hint": "yt-dlp দিয়ে download করছে...",
    },
    "directdl": {
        "icon": "📦",
        "label": "File Hosting Site",
        "hint": "Direct link generate করছে...",
    },
    "urldl": {
        "icon": "🔗",
        "label": "Direct URL",
        "hint": "HTTP download করছে...",
    },
}


# ─────────────────────────────────────────────────────────────────
# ROUTE EXECUTOR — সঠিক handler-এ সরাসরি forward করে
# ─────────────────────────────────────────────────────────────────

async def _execute_route(client: Client, message: Message, url: str, route: str):
    """নির্ধারিত route অনুযায়ী সরাসরি download শুরু করে।"""
    user_id = message.from_user.id if message.from_user else message.chat.id
    info = ROUTE_INFO.get(route, {})

    LOGGER.info(
        f"[AutoRouter] route={route} url={url[:60]} user={user_id}"
    )

    # ── Google Drive ──────────────────────────────────────────────
    if route == "gdrive":
        try:
            from plugins.gdl import _process_gdl
            await _process_gdl(client, message, url)
        except ImportError:
            await message.reply_text(
                "❌ **Google Drive downloader লোড হয়নি!**",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Torrent / Magnet ──────────────────────────────────────────
    elif route == "aria2":
        try:
            import shutil
            if not shutil.which("aria2c"):
                await message.reply_text(
                    "❌ **aria2c ইনস্টল নেই!**\n"
                    "`sudo apt install aria2`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            from plugins.aria2dl import (
                _run_download,
                _cancel_events,
                _is_premium,
            )

            status_msg = await message.reply_text(
                f"🌊 **Torrent/Magnet download শুরু হচ্ছে...**\n\n"
                f"`{url[:80]}`",
                parse_mode=ParseMode.MARKDOWN,
            )

            cancel_event = asyncio.Event()
            _cancel_events[status_msg.id] = cancel_event
            is_prem = await _is_premium(user_id)

            asyncio.create_task(
                _run_download(
                    client, message, url, None,
                    status_msg, is_prem, cancel_event,
                )
            )

        except ImportError:
            await message.reply_text(
                "❌ **Aria2 downloader লোড হয়নি!**",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── yt-dlp ───────────────────────────────────────────────────
    elif route == "ytdlp":
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
                await message.reply_text(
                    rate_msg,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            await _handle_single_video_initiate_public(
                client, message, url_clean, user_id, is_prem, referer
            )

        except (ImportError, AttributeError):
            # Fallback: manual command hint
            await message.reply_text(
                f"🎬 **yt-dlp downloader লোড হয়নি।**\n\n"
                f"Manual: `/ytdl {url[:60]}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Direct Download Sites ─────────────────────────────────────
    elif route == "directdl":
        try:
            from plugins.directdl import _process_ddl

            status_msg = await message.reply_text(
                f"📦 **Direct link generate করছে...**\n\n"
                f"`{url[:80]}`",
                parse_mode=ParseMode.MARKDOWN,
            )

            asyncio.create_task(
                _process_ddl(client, message, url, status_msg)
            )

        except ImportError:
            await message.reply_text(
                "❌ **DirectDL downloader লোড হয়নি!**",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Generic HTTP URL ──────────────────────────────────────────
    elif route == "urldl":
        try:
            from plugins.urldl import _process_url_download

            await _process_url_download(client, message, url)

        except ImportError:
            await message.reply_text(
                "❌ **URL downloader লোড হয়নি!**",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Unknown ───────────────────────────────────────────────────
    else:
        LOGGER.warning(f"[AutoRouter] Unknown route for URL: {url[:80]}")


# ─────────────────────────────────────────────────────────────────
# MAIN AUTO-DETECT HANDLER
# URL paste করলেই অটো কাজ করবে — কোনো command লাগবে না
# group=3 — autolink (group=1) ও urldl (group=2) এর পরে
# ─────────────────────────────────────────────────────────────────

async def _auto_detect_handler(client: Client, message: Message):
    """
    যেকোনো URL paste করলে অটোমেটিক সঠিক downloader-এ পাঠাবে।
    কোনো command বা confirm button ছাড়াই কাজ করবে।
    """
    if not message.text:
        return

    # Command message skip
    if message.text.strip().startswith(tuple(COMMAND_PREFIX)):
        return

    # Telegram লিংক → autolink.py-তে ছেড়ে দাও
    if TELEGRAM_LINK_PATTERN.search(message.text):
        return

    # pbatch session চেক — batch চলাকালীন interfere করবে না
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
        # Magnet লিংক আলাদাভাবে চেক
        text = message.text.strip()
        if not MAGNET_PATTERN.match(text):
            return
        url = text
    else:
        url = match.group(0).strip().rstrip(".,;!?)")

    # Route নির্ধারণ
    route = detect_route(url)

    # Skip করার route
    if route in ("telegram", "unknown"):
        return

    # urldl → urldl.py নিজেই group=2 তে handle করে, skip
    # তবে যদি urldl.py না থাকে তাহলে এখানে handle করব
    if route == "urldl":
        _urldl = sys.modules.get("plugins.urldl")
        if _urldl:
            return  # urldl.py ই handle করবে

    user_id = message.from_user.id if message.from_user else 0

    # Force sub check (শুধু private chat-এ)
    if message.chat.type == ChatType.PRIVATE and message.from_user:
        if not await check_force_sub(client, user_id):
            return

    info = ROUTE_INFO.get(route, {})
    LOGGER.info(
        f"[AutoRouter] Auto-detected route={route} "
        f"url={url[:60]} user={user_id}"
    )

    # সরাসরি execute — কোনো confirm ছাড়া
    await _execute_route(client, message, url, route)


# ─────────────────────────────────────────────────────────────────
# /route COMMAND — লিংক বিশ্লেষণ করে দেখাবে
# ─────────────────────────────────────────────────────────────────

async def _route_command_handler(client: Client, message: Message):
    """/route <URL> — কোন downloader ব্যবহার হবে দেখাবে"""
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
    info = ROUTE_INFO.get(
        route,
        {"icon": "❓", "label": "Unknown", "hint": "অজানা"},
    )

    await message.reply_text(
        f"**🗺 Link Analysis**\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 **URL:** `{url[:80]}`\n\n"
        f"{info['icon']} **Route:** `{info['label']}`\n"
        f"ℹ️ **Info:** {info['hint']}",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


# ─────────────────────────────────────────────────────────────────
# /plugininfo COMMAND — সব কমান্ডের তালিকা
# ─────────────────────────────────────────────────────────────────

PLUGIN_COMMAND_INFO = """
**📋 সব Plugin Commands**
━━━━━━━━━━━━━━━━━━━━━━━━

**📨 Telegram Content:**
• লিংক সরাসরি paste করুন — অটো download হবে

**🎬 Video Downloader (yt-dlp):**
• লিংক paste করুন — অটো download হবে
• `/ytdl <URL>` — Manual command

**☁️ Google Drive:**
• লিংক paste করুন — অটো download হবে
• `/gdl <URL>` — Manual command

**📦 File Hosting Sites:**
• লিংক paste করুন — অটো download হবে
• `/ddl <URL>` — Manual command

**🌊 Torrent / Magnet:**
• Magnet/torrent link paste করুন — অটো download হবে
• `/dl <magnet>` — Manual command

**🔗 Direct URL:**
• HTTP লিংক paste করুন — অটো download হবে
• `/urldl <URL>` — Manual command

**📺 YouTube Upload:**
• `/ytconnect` — YouTube channel connect
• `/ytupload <URL>` — Video upload to YouTube

**🗺 Router Tools:**
• `/route <URL>` — কোন downloader হবে দেখাবে

> 💡 **সব ধরনের লিংক সরাসরি paste করলেই অটো কাজ করবে!**
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
      group=1  → autolink.py (Telegram লিংক)
      group=2  → urldl.py (generic HTTP auto-detect)
      group=3  → এই ফাইলের auto-detect (gdrive, ytdlp, directdl, aria2)
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

    # /plugininfo command
    app.add_handler(
        MessageHandler(
            _plugininfo_command_handler,
            filters=filters.command(
                ["plugininfo", "commands", "allcmds"],
                prefixes=COMMAND_PREFIX,
            )
            & (filters.private | filters.group),
        ),
        group=1,
    )

    # ── মূল অটো-ডিটেক্ট হ্যান্ডলার ────────────────────────────
    # URL paste করলেই কাজ করবে — কোনো command লাগবে না
    app.add_handler(
        MessageHandler(
            _auto_detect_handler,
            filters=filters.text & (filters.private | filters.group),
        ),
        group=3,
    )

    LOGGER.info(
        "[AutoRouter] ✅ Registered:\n"
        "  • /route command\n"
        "  • /plugininfo command\n"
        "  • Auto URL detection (group=3) — কোনো command ছাড়াই কাজ করবে"
    )
