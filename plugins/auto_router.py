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
# t.me / telegram.me লিংক  → autolink.py   (group=1 handle করে)
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
        except Exception as e:
            LOGGER.error(f"[AutoRouter] gdrive error: {e}")
            await message.reply_text(
                f"❌ **Google Drive error:** `{str(e)[:150]}`",
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
        except Exception as e:
            LOGGER.error(f"[AutoRouter] aria2 error: {e}")

    # ── yt-dlp ───────────────────────────────────────────────────
    elif route == "ytdlp":
        try:
            from plugins.ytdl import (
                get_single_video_info,
                build_quality_keyboard,
                ytdl_sessions,
                _check_rate_limit,
                is_premium_user,
                parse_url_and_referer,
                normalize_url,
                _is_warp_available,
                cleanup_expired_sessions,
            )
            from time import time as _time

            url_clean, referer = parse_url_and_referer(url)
            is_prem = await is_premium_user(user_id)
            allowed, rate_msg = await _check_rate_limit(user_id, is_prem)

            if not allowed:
                await message.reply_text(
                    rate_msg,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            warp_ok = _is_warp_available()
            status_msg = await message.reply_text(
                f"🔍 **Analyzing...**\n"
                f"_{'🟢 WARP active' if warp_ok else '🟡 Direct connection'}_",
                parse_mode=ParseMode.MARKDOWN,
            )

            loop = asyncio.get_event_loop()
            info, error_msg = await loop.run_in_executor(
                None,
                lambda: get_single_video_info(url_clean, referer),
            )

            if not info:
                await status_msg.edit_text(
                    f"❌ **Video info fetch করা যায়নি!**\n\n"
                    f"`{error_msg[:200] if error_msg else 'Unknown error'}`\n\n"
                    f"Manual try: `/ytdl {url_clean[:60]}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            title = (info.get("title", "Unknown") or "Unknown")[:60]
            duration = info.get("duration", 0) or 0
            uploader = info.get("uploader", "Unknown") or "Unknown"

            from utils.helper import get_readable_time
            duration_str = get_readable_time(int(duration)) if duration else "Unknown"

            cleanup_expired_sessions()
            ytdl_sessions[message.chat.id] = {
                "user_id":    user_id,
                "url":        url_clean,
                "info":       info,
                "message_id": message.id,
                "created_at": _time(),
                "user_obj":   message.from_user,
                "type":       "single",
                "referer":    referer,
            }

            await status_msg.edit_text(
                f"📹 **{title}**\n\n"
                f"👤 **Channel:** {uploader}\n"
                f"⏱ **Duration:** {duration_str}\n\n"
                f"👇 **Quality বেছে নিন:**",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_quality_keyboard(info, message.chat.id, is_playlist=False),
                disable_web_page_preview=True,
            )

        except (ImportError, AttributeError) as e:
            LOGGER.warning(f"[AutoRouter] ytdlp import error: {e}")
            await message.reply_text(
                f"🎬 **Manual command ব্যবহার করুন:**\n`/ytdl {url[:60]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            LOGGER.error(f"[AutoRouter] ytdlp error: {e}")
            await message.reply_text(
                f"❌ **Error:** `{str(e)[:150]}`\n\nManual: `/ytdl {url[:60]}`",
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
                "❌ **DirectDL downloader লোড হয়নি!**\n\n"
                f"Manual: `/ddl {url[:60]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            LOGGER.error(f"[AutoRouter] directdl error: {e}")
            await message.reply_text(
                f"❌ **Error:** `{str(e)[:150]}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Generic HTTP URL ──────────────────────────────────────────
    elif route == "urldl":
        try:
            from plugins.urldl import (
                _get_file_info,
                _process_url_download,
                _is_premium as _urldl_is_premium,
                _check_cooldown,
                MAX_FILE_SIZE,
                FREE_FILE_LIMIT,
                _active_downloads,
            )
            import uuid
            from utils.helper import get_readable_file_size

            is_prem = await _urldl_is_premium(user_id)

            # Cooldown check
            remaining = await _check_cooldown(user_id, is_prem)
            if remaining > 0:
                mins, secs = divmod(remaining, 60)
                await message.reply_text(
                    f"⏳ **{mins}m {secs}s** পরে আবার চেষ্টা করুন।\n\n"
                    f"💎 Upgrade করুন: /plans",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            if user_id in _active_downloads:
                await message.reply_text(
                    "⏳ **একটি download চলছে!** শেষ হওয়ার পর চেষ্টা করুন।",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            max_size = MAX_FILE_SIZE if is_prem else FREE_FILE_LIMIT

            # File info fetch
            file_size, filename = await _get_file_info(url)

            if file_size > 0 and file_size > max_size:
                await message.reply_text(
                    f"❌ **File too large!**\n\n"
                    f"📦 Size: `{get_readable_file_size(file_size)}`\n"
                    f"🚫 Limit: `{get_readable_file_size(max_size)}`\n\n"
                    + ("💎 Upgrade: /plans" if not is_prem else ""),
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            size_display = get_readable_file_size(file_size) if file_size > 0 else "Unknown"

            _active_downloads.add(user_id)

            status_msg = await message.reply_text(
                f"⬇️ **Download শুরু হচ্ছে...**\n\n"
                f"📄 `{filename}`\n"
                f"📦 `{size_display}`",
                parse_mode=ParseMode.MARKDOWN,
            )

            asyncio.create_task(
                _process_url_download(
                    client, message, url, filename, status_msg, is_prem
                )
            )

        except ImportError:
            # urldl না থাকলে aiohttp দিয়ে সরাসরি download করার চেষ্টা
            LOGGER.warning("[AutoRouter] urldl not available, trying fallback")
            await message.reply_text(
                f"🔗 **URL Downloader লোড হয়নি।**\n\n"
                f"Manual: `/urldl {url[:60]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            LOGGER.error(f"[AutoRouter] urldl error: {e}")
            await message.reply_text(
                f"❌ **Error:** `{str(e)[:150]}`",
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

    # Telegram লিংক → autolink.py-তে ছেড়ে দাও (group=1 handle করবে)
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

    # settings conversation চেক
    try:
        from plugins.settings import _conv
        if message.from_user and message.from_user.id in _conv:
            return
    except Exception:
        pass

    # login conversation চেক
    try:
        from plugins.login import session_data
        if message.chat.id in session_data:
            return
    except Exception:
        pass

    # gdl pending url চেক
    try:
        from plugins.gdl import _pending_url_requests
        user_id_check = message.from_user.id if message.from_user else -1
        if (message.chat.id, user_id_check) in _pending_url_requests:
            return
    except Exception:
        pass

    # URL খোঁজা
    url = None
    text = message.text.strip()

    # Magnet লিংক আলাদাভাবে চেক
    if MAGNET_PATTERN.match(text):
        url = text
    else:
        match = GENERIC_URL_PATTERN.search(text)
        if match:
            url = match.group(0).strip().rstrip(".,;!?)")

    if not url:
        return

    # Route নির্ধারণ
    route = detect_route(url)

    LOGGER.info(f"[AutoRouter] Detected: route={route} url={url[:60]}")

    # Telegram লিংক skip — autolink.py handle করবে
    if route == "telegram":
        return

    # Unknown skip
    if route == "unknown":
        return

    user_id = message.from_user.id if message.from_user else 0

    # Force sub check (শুধু private chat-এ)
    if message.chat.type == ChatType.PRIVATE and message.from_user:
        if not await check_force_sub(client, user_id):
            return

    # urldl route — এখন auto_router নিজেই handle করবে
    # (আগে group=2 এ urldl.py handle করত, কিন্তু সেখানে pending/rename UI ছিল)
    # auto_router সরাসরি download শুরু করবে কোনো UI ছাড়াই

    LOGGER.info(
        f"[AutoRouter] Executing route={route} "
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
      group=2  → urldl.py (generic HTTP auto-detect with UI)
      group=3  → এই ফাইলের auto-detect (gdrive, ytdlp, directdl, aria2, urldl)
    """
    from pyrogram.handlers import MessageHandler

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
    # group=3 তে রাখা হয়েছে যাতে:
    #   - autolink.py (group=1) আগে Telegram লিংক handle করে
    #   - urldl.py (group=2) আগে generic URL handle করে (UI সহ)
    #   - এই handler বাকি সব handle করে (gdrive, ytdlp, directdl, aria2)
    #   - BUT urldl route-ও এখানে handle হবে যদি urldl.py skip করে
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
        "  • Auto URL detection (group=3) — কোনো command ছাড়াই কাজ করবে\n"
        "  • Supports: gdrive, ytdlp, directdl, aria2, urldl"
    )
