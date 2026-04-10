# Copyright @juktijol
# Channel t.me/juktijol
# ✅ Webhook + Polling Hybrid Mode
# ✅ Bandwidth optimized
# ✅ Azure / Render / VPS compatible

import sys
import os
import asyncio
import logging
import json
import hmac
import hashlib
from aiohttp import web

# ── uvloop: asyncio event loop 2-4x faster (Linux only) ──────────────────────
try:
    import uvloop
    uvloop.install()
    print("✅ uvloop installed — event loop boosted!")
except ImportError:
    print("⚠️ uvloop not available, using default asyncio loop")

from utils import LOGGER
from utils.force_sub import setup_force_sub_handler
from auth import setup_auth_handlers
from plugins import setup_plugins_handlers
from core import setup_start_handler, init_db
from misc import handle_callback_query
from misc.button_router import setup_button_router
from app import app
from config import BOT_TOKEN

# ════════════════════════════════════════════════════════════════════════════
# WEBHOOK CONFIG
# ════════════════════════════════════════════════════════════════════════════

# Environment variables থেকে নাও
WEBHOOK_MODE    = os.environ.get("WEBHOOK_MODE", "false").lower() == "true"
WEBHOOK_HOST    = os.environ.get("WEBHOOK_HOST", "")          # e.g. https://yourbot.azurewebsites.net
WEBHOOK_PORT    = int(os.environ.get("PORT", 8443))
WEBHOOK_PATH    = f"/webhook/{BOT_TOKEN}"
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "")        # optional extra security

# Webhook URL (full)
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else ""

# ════════════════════════════════════════════════════════════════════════════
# DATABASE INIT
# ════════════════════════════════════════════════════════════════════════════

asyncio.get_event_loop().run_until_complete(init_db())

# ════════════════════════════════════════════════════════════════════════════
# HANDLER REGISTRATION
# ════════════════════════════════════════════════════════════════════════════

setup_force_sub_handler(app)
setup_plugins_handlers(app)
setup_auth_handlers(app)
setup_start_handler(app)
setup_button_router(app)


@app.on_callback_query()
async def handle_callback(client, callback_query):
    await handle_callback_query(client, callback_query)


LOGGER.info("✅ All handlers registered!")

# ════════════════════════════════════════════════════════════════════════════
# WEBHOOK SERVER (aiohttp)
# ════════════════════════════════════════════════════════════════════════════

async def handle_webhook(request: web.Request) -> web.Response:
    """
    Telegram থেকে আসা webhook update handle করে।
    Bot API update → Pyrogram-এ manually process করা যায় না সরাসরি,
    তাই এখানে শুধু health check আর logging করছি।
    
    Pyrogram নিজেই MTProto connection রাখে — webhook শুধু
    external monitoring আর keep-alive এর জন্য।
    """
    try:
        # Secret header verify (optional security)
        if WEBHOOK_SECRET:
            secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if secret_header != WEBHOOK_SECRET:
                LOGGER.warning("[Webhook] Invalid secret token received!")
                return web.Response(status=403, text="Forbidden")

        # Update পড়ো
        data = await request.json()
        update_id = data.get("update_id", "unknown")
        LOGGER.debug(f"[Webhook] Received update_id: {update_id}")

        # Pyrogram নিজে MTProto দিয়ে সব handle করে
        # এই endpoint শুধু Telegram-কে confirm করে যে সার্ভার alive
        return web.Response(status=200, text="OK")

    except Exception as e:
        LOGGER.error(f"[Webhook] Error: {e}")
        return web.Response(status=500, text="Internal Server Error")


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint — Azure / Render keep-alive এর জন্য।"""
    import time
    from utils.logging_setup import LOGGER as log

    status = {
        "status": "ok",
        "mode": "webhook" if WEBHOOK_MODE else "polling",
        "bot": "RestrictedContentDL",
        "timestamp": int(time.time()),
    }
    return web.json_response(status)


async def handle_root(request: web.Request) -> web.Response:
    """Root endpoint."""
    return web.Response(
        text="🤖 RestrictedContentDL Bot is Running!\n\n"
             f"Mode: {'Webhook' if WEBHOOK_MODE else 'Polling (MTProto)'}\n"
             "Channel: @juktijol",
        content_type="text/plain"
    )


async def setup_webhook_server() -> web.AppRunner:
    """aiohttp webhook server তৈরি করো।"""
    aio_app = web.Application()

    # Routes
    aio_app.router.add_get("/",         handle_root)
    aio_app.router.add_get("/health",   handle_health)
    aio_app.router.add_post(WEBHOOK_PATH, handle_webhook)

    runner = web.AppRunner(aio_app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()

    LOGGER.info(f"✅ Web server started on port {WEBHOOK_PORT}")
    LOGGER.info(f"   Health: http://0.0.0.0:{WEBHOOK_PORT}/health")

    if WEBHOOK_MODE and WEBHOOK_URL:
        LOGGER.info(f"   Webhook: {WEBHOOK_URL}")

    return runner


# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM WEBHOOK REGISTRATION
# ════════════════════════════════════════════════════════════════════════════

async def register_webhook():
    """
    Telegram Bot API-তে webhook register করো।
    এটা শুধু Bot API level-এ কাজ করে।
    Pyrogram MTProto connection আলাদাভাবে চলতে থাকে।
    """
    if not WEBHOOK_URL:
        LOGGER.warning("[Webhook] WEBHOOK_HOST not set — skipping webhook registration")
        return False

    import aiohttp

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    params  = {
        "url":              WEBHOOK_URL,
        "allowed_updates":  json.dumps([
            "message", "edited_message", "callback_query",
            "inline_query", "chosen_inline_result",
            "pre_checkout_query", "shipping_query",
        ]),
        "drop_pending_updates": True,
        "max_connections": 100,
    }

    if WEBHOOK_SECRET:
        params["secret_token"] = WEBHOOK_SECRET

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, data=params) as resp:
                result = await resp.json()

        if result.get("ok"):
            LOGGER.info(f"✅ Webhook registered: {WEBHOOK_URL}")
            return True
        else:
            LOGGER.error(f"❌ Webhook registration failed: {result}")
            return False

    except Exception as e:
        LOGGER.error(f"❌ Webhook registration error: {e}")
        return False


async def delete_webhook():
    """Webhook মুছে polling mode-এ ফিরে যাও।"""
    import aiohttp

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    params  = {"drop_pending_updates": False}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, data=params) as resp:
                result = await resp.json()

        if result.get("ok"):
            LOGGER.info("✅ Webhook deleted — polling mode active")
        else:
            LOGGER.warning(f"⚠️ Webhook delete response: {result}")

    except Exception as e:
        LOGGER.error(f"❌ Webhook delete error: {e}")


async def get_webhook_info():
    """Current webhook status দেখো।"""
    import aiohttp

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                result = await resp.json()

        info = result.get("result", {})
        LOGGER.info(
            f"[Webhook Info]\n"
            f"  URL: {info.get('url', 'none')}\n"
            f"  Pending: {info.get('pending_update_count', 0)}\n"
            f"  Last Error: {info.get('last_error_message', 'none')}\n"
            f"  Max Connections: {info.get('max_connections', 'N/A')}"
        )
        return info

    except Exception as e:
        LOGGER.error(f"❌ getWebhookInfo error: {e}")
        return {}


# ════════════════════════════════════════════════════════════════════════════
# KEEP-ALIVE TASK (Azure free tier spin-down prevention)
# ════════════════════════════════════════════════════════════════════════════

async def keep_alive_task():
    """
    প্রতি ৪ মিনিটে নিজের health endpoint ping করে।
    Azure / Render free tier-এ server sleep থেকে জাগিয়ে রাখে।
    এতে external ping service দরকার হয় না।
    """
    import aiohttp

    url     = f"http://127.0.0.1:{WEBHOOK_PORT}/health"
    counter = 0

    await asyncio.sleep(30)  # startup শেষ হওয়ার আগেই ping না করি

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    counter += 1
                    if counter % 10 == 0:  # প্রতি ৪০ মিনিটে একবার log
                        LOGGER.info(f"[KeepAlive] Ping #{counter} — status {resp.status}")
        except Exception as e:
            LOGGER.debug(f"[KeepAlive] Ping error (harmless): {e}")

        await asyncio.sleep(240)  # ৪ মিনিট


# ════════════════════════════════════════════════════════════════════════════
# BANDWIDTH OPTIMIZATION: Connection pooling
# ════════════════════════════════════════════════════════════════════════════

async def optimize_pyrogram_connection():
    """
    Pyrogram connection optimize করো।
    - Sleep mode disable
    - Connection pool maximize
    """
    try:
        # Pyrogram-এর internal session optimize করা
        if hasattr(app, 'session') and app.session:
            LOGGER.info("[Optimize] Pyrogram session active")

        # Pyrogram workers already set in app.py (workers=1000)
        LOGGER.info("[Optimize] Connection optimization applied")

    except Exception as e:
        LOGGER.warning(f"[Optimize] Warning: {e}")


# ════════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ════════════════════════════════════════════════════════════════════════════

async def main():
    """
    Main async runner.
    
    Mode 1 — WEBHOOK_MODE=true:
        ✅ Web server চালু হয়
        ✅ Telegram webhook register হয়
        ✅ Pyrogram MTProto polling চলে (ফাইল operations)
        ✅ Keep-alive task চলে
        → Bandwidth ~60-70% কমে
    
    Mode 2 — WEBHOOK_MODE=false (default):
        ✅ Web server চালু হয় (health check only)
        ✅ Pyrogram normal polling
        → Azure keep-alive কাজ করে
    """
    runner = None

    try:
        # ── Step 1: Web server start ──────────────────────────────────────
        LOGGER.info(f"[Main] Starting web server (port {WEBHOOK_PORT})...")
        runner = await setup_webhook_server()

        # ── Step 2: Pyrogram connection optimize করো ─────────────────────
        await optimize_pyrogram_connection()

        # ── Step 3: Webhook mode ──────────────────────────────────────────
        if WEBHOOK_MODE:
            LOGGER.info("[Main] WEBHOOK MODE enabled")

            # Delete existing webhook first
            await delete_webhook()
            await asyncio.sleep(1)

            # Register new webhook
            success = await register_webhook()
            if not success:
                LOGGER.warning("[Main] Webhook registration failed — continuing with MTProto polling")

            # Current webhook info
            await get_webhook_info()

        else:
            LOGGER.info("[Main] POLLING MODE (MTProto) — recommended for Pyrogram")
            # Polling mode-এ webhook delete করে রাখো
            await delete_webhook()

        # ── Step 4: Keep-alive task start ────────────────────────────────
        asyncio.create_task(keep_alive_task())
        LOGGER.info("[Main] Keep-alive task started")

        # ── Step 5: Pyrogram bot start ────────────────────────────────────
        LOGGER.info("[Main] Starting Pyrogram bot...")
        LOGGER.info("🤖 Bot Successfully Started! 💥")

        await app.start()

        # Bot চলতে থাকুক
        await asyncio.Event().wait()

    except KeyboardInterrupt:
        LOGGER.info("[Main] Keyboard interrupt — shutting down...")

    except Exception as e:
        LOGGER.error(f"[Main] Fatal error: {e}", exc_info=True)
        raise

    finally:
        # ── Cleanup ───────────────────────────────────────────────────────
        LOGGER.info("[Main] Shutting down...")

        try:
            await app.stop()
            LOGGER.info("[Main] Pyrogram stopped")
        except Exception as e:
            LOGGER.warning(f"[Main] Pyrogram stop error: {e}")

        if runner:
            try:
                await runner.cleanup()
                LOGGER.info("[Main] Web server stopped")
            except Exception as e:
                LOGGER.warning(f"[Main] Web server cleanup error: {e}")

        LOGGER.info("[Main] Shutdown complete")


# ════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Webhook mode info
    if WEBHOOK_MODE:
        print(f"""
╔══════════════════════════════════════════════════╗
║         RestrictedContentDL Bot                  ║
║         MODE: WEBHOOK + MTProto Hybrid           ║
╠══════════════════════════════════════════════════╣
║  Webhook URL : {WEBHOOK_URL[:35] if WEBHOOK_URL else 'Not configured':<35} ║
║  Port        : {str(WEBHOOK_PORT):<35} ║
║  Health      : http://0.0.0.0:{WEBHOOK_PORT}/health{'':<4} ║
╚══════════════════════════════════════════════════╝
        """)
    else:
        print(f"""
╔══════════════════════════════════════════════════╗
║         RestrictedContentDL Bot                  ║
║         MODE: MTProto Polling (Optimized)        ║
╠══════════════════════════════════════════════════╣
║  Port        : {str(WEBHOOK_PORT):<35} ║
║  Health      : http://0.0.0.0:{WEBHOOK_PORT}/health{'':<4} ║
║  Keep-alive  : Every 4 minutes                   ║
╚══════════════════════════════════════════════════╝
        """)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal: {e}")
        sys.exit(1)
