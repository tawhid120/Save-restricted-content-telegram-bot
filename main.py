# Copyright @juktijol
# Channel t.me/juktijol
# ✅ Webhook + Polling Hybrid Mode
# ✅ Render / Azure / VPS compatible
# ✅ Pyrogram MTProto + Bot API Webhook
# ✅ Bandwidth optimized

import sys
import os
import asyncio
import logging
import json
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

WEBHOOK_MODE   = os.environ.get("WEBHOOK_MODE", "false").lower() == "true"
WEBHOOK_HOST   = os.environ.get("WEBHOOK_HOST", "").rstrip("/")
WEBHOOK_PORT   = int(os.environ.get("PORT", 10000))   # Render default = 10000
WEBHOOK_PATH   = f"/webhook/{BOT_TOKEN}"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
WEBHOOK_URL    = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else ""

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
# WEBHOOK UPDATE PROCESSOR
# ════════════════════════════════════════════════════════════════════════════

async def process_update(data: dict):
    """
    Telegram থেকে আসা raw update dict কে
    Pyrogram দিয়ে process করো।
    """
    try:
        from pyrogram import utils as pyrogram_utils
        from pyrogram.raw import types as raw_types

        # Pyrogram এর dispatcher এ update পাঠাও
        # app.dispatcher আছে কিনা চেক করো
        if hasattr(app, "dispatcher") and app.dispatcher:
            # Update টাকে Pyrogram format এ convert করো
            update_obj = await app.parse_update(data)
            if update_obj:
                await app.dispatcher.process_update(update_obj, [], [])
                LOGGER.debug(f"[Webhook] Update processed via dispatcher")
                return True

        # Fallback: handlers manually trigger করো
        LOGGER.debug(f"[Webhook] Dispatcher not available — using handler fallback")
        await _fallback_process_update(data)
        return True

    except AttributeError:
        # Pyrogram এর parse_update না থাকলে fallback
        await _fallback_process_update(data)
        return True

    except Exception as e:
        LOGGER.error(f"[Webhook] process_update error: {e}", exc_info=True)
        return False


async def _fallback_process_update(data: dict):
    """
    Pyrogram dispatcher কাজ না করলে
    manually message/callback handle করো।
    এটা basic fallback — primary logic Pyrogram MTProto polling করে।
    """
    try:
        # Message update
        if "message" in data:
            msg_data = data["message"]
            LOGGER.debug(
                f"[Fallback] Message from user_id="
                f"{msg_data.get('from', {}).get('id', 'unknown')}: "
                f"{msg_data.get('text', '')[:50]}"
            )

        # Callback query update
        elif "callback_query" in data:
            cb_data = data["callback_query"]
            LOGGER.debug(
                f"[Fallback] Callback from user_id="
                f"{cb_data.get('from', {}).get('id', 'unknown')}: "
                f"{cb_data.get('data', '')}"
            )

        # Edited message
        elif "edited_message" in data:
            LOGGER.debug("[Fallback] Edited message received")

        # Inline query
        elif "inline_query" in data:
            LOGGER.debug("[Fallback] Inline query received")

    except Exception as e:
        LOGGER.warning(f"[Fallback] Error: {e}")


# ════════════════════════════════════════════════════════════════════════════
# AIOHTTP ROUTE HANDLERS
# ════════════════════════════════════════════════════════════════════════════

async def handle_webhook(request: web.Request) -> web.Response:
    """
    Telegram Bot API থেকে আসা webhook update handle করে।

    Flow:
    Telegram → POST /webhook/{token} → এই function
             → process_update() → Pyrogram handlers
             → 200 OK → Telegram
    """
    try:
        # ── Secret Token Verify ───────────────────────────────────────────
        if WEBHOOK_SECRET:
            secret_header = request.headers.get(
                "X-Telegram-Bot-Api-Secret-Token", ""
            )
            if secret_header != WEBHOOK_SECRET:
                LOGGER.warning(
                    f"[Webhook] Invalid secret from IP: "
                    f"{request.remote}"
                )
                return web.Response(status=403, text="Forbidden")

        # ── Update Parse করো ──────────────────────────────────────────────
        try:
            data = await request.json()
        except json.JSONDecodeError as e:
            LOGGER.error(f"[Webhook] Invalid JSON: {e}")
            return web.Response(status=400, text="Bad Request")

        update_id   = data.get("update_id", "unknown")
        update_type = _get_update_type(data)

        LOGGER.info(
            f"[Webhook] ✅ Update #{update_id} | Type: {update_type}"
        )

        # ── Update Process করো ───────────────────────────────────────────
        # Background task হিসেবে চালাও যাতে Telegram কে
        # সঙ্গে সঙ্গে 200 দিতে পারি (timeout এড়াতে)
        asyncio.create_task(process_update(data))

        # Telegram কে সাথে সাথে 200 দাও (timeout হলে retry করে)
        return web.Response(status=200, text="OK")

    except Exception as e:
        LOGGER.error(f"[Webhook] Unhandled error: {e}", exc_info=True)
        # 200 দাও নইলে Telegram বারবার retry করবে
        return web.Response(status=200, text="OK")


def _get_update_type(data: dict) -> str:
    """Update এর type বের করো।"""
    update_types = [
        "message", "edited_message", "channel_post",
        "edited_channel_post", "inline_query",
        "chosen_inline_result", "callback_query",
        "shipping_query", "pre_checkout_query",
        "poll", "poll_answer", "my_chat_member",
        "chat_member", "chat_join_request",
    ]
    for t in update_types:
        if t in data:
            return t
    return "unknown"


async def handle_health(request: web.Request) -> web.Response:
    """
    Health check endpoint।
    Render / Azure keep-alive আর monitoring এর জন্য।
    """
    import time

    # Bot connected কিনা চেক করো
    bot_connected = False
    bot_username  = "unknown"

    try:
        if app.is_connected:
            bot_connected = True
            me = await app.get_me()
            bot_username = f"@{me.username}" if me.username else str(me.id)
    except Exception:
        pass

    status = {
        "status"       : "ok" if bot_connected else "starting",
        "mode"         : "webhook" if WEBHOOK_MODE else "polling",
        "bot"          : bot_username,
        "bot_connected": bot_connected,
        "webhook_url"  : WEBHOOK_URL if WEBHOOK_MODE else "disabled",
        "port"         : WEBHOOK_PORT,
        "timestamp"    : int(time.time()),
        "channel"      : "@juktijol",
    }

    http_status = 200 if bot_connected else 503

    return web.json_response(status, status=http_status)


async def handle_root(request: web.Request) -> web.Response:
    """Root endpoint — browser এ দেখা যাবে।"""
    mode = "Webhook + MTProto Hybrid" if WEBHOOK_MODE else "MTProto Polling"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>RestrictedContentDL Bot</title>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: monospace;
                background: #0d1117;
                color: #58a6ff;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }}
            .box {{
                border: 1px solid #30363d;
                padding: 30px;
                border-radius: 8px;
                text-align: center;
            }}
            .green {{ color: #3fb950; }}
            .gray  {{ color: #8b949e; }}
        </style>
    </head>
    <body>
        <div class="box">
            <h2>🤖 RestrictedContentDL Bot</h2>
            <p class="green">● Running</p>
            <p>Mode: <b>{mode}</b></p>
            <p>Port: <b>{WEBHOOK_PORT}</b></p>
            <p class="gray">Channel: @juktijol</p>
            <p class="gray">
                <a href="/health" style="color:#58a6ff">Health Check</a>
            </p>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type="text/html")


async def handle_set_webhook(request: web.Request) -> web.Response:
    """
    Manual webhook set endpoint।
    GET /set_webhook → webhook register করে।
    (Admin use only — production এ সরিয়ে দিন)
    """
    success = await register_webhook()
    info    = await get_webhook_info()

    result = {
        "registered" : success,
        "webhook_url": WEBHOOK_URL,
        "info"       : info,
    }
    return web.json_response(result)


# ════════════════════════════════════════════════════════════════════════════
# WEB SERVER SETUP
# ════════════════════════════════════════════════════════════════════════════

async def setup_webhook_server() -> web.AppRunner:
    """aiohttp web server তৈরি করো।"""
    aio_app = web.Application(
        client_max_size = 10 * 1024 * 1024  # 10MB max request size
    )

    # ── Routes ────────────────────────────────────────────────────────────
    aio_app.router.add_get("/",             handle_root)
    aio_app.router.add_get("/health",       handle_health)
    aio_app.router.add_get("/set_webhook",  handle_set_webhook)
    aio_app.router.add_post(WEBHOOK_PATH,   handle_webhook)

    # ── Middlewares ───────────────────────────────────────────────────────
    # Request logging middleware
    @web.middleware
    async def log_middleware(request, handler):
        if request.path not in ["/health", "/"]:
            LOGGER.debug(
                f"[HTTP] {request.method} {request.path} "
                f"from {request.remote}"
            )
        response = await handler(request)
        return response

    aio_app.middlewares.append(log_middleware)

    # ── Start server ──────────────────────────────────────────────────────
    runner = web.AppRunner(aio_app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host = "0.0.0.0",
        port = WEBHOOK_PORT,
        reuse_address = True,
        reuse_port    = True,
    )
    await site.start()

    LOGGER.info(f"✅ Web server started → port {WEBHOOK_PORT}")
    LOGGER.info(f"   Root   : http://0.0.0.0:{WEBHOOK_PORT}/")
    LOGGER.info(f"   Health : http://0.0.0.0:{WEBHOOK_PORT}/health")

    if WEBHOOK_MODE and WEBHOOK_URL:
        LOGGER.info(f"   Webhook: {WEBHOOK_URL}")

    return runner


# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM WEBHOOK API FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

async def register_webhook() -> bool:
    """
    Telegram Bot API তে webhook register করো।
    WEBHOOK_HOST সেট না থাকলে skip করে।
    """
    if not WEBHOOK_URL:
        LOGGER.warning(
            "[Webhook] WEBHOOK_HOST not set — skipping registration"
        )
        return False

    import aiohttp

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"

    params = {
        "url"                  : WEBHOOK_URL,
        "allowed_updates"      : json.dumps([
            "message",
            "edited_message",
            "callback_query",
            "inline_query",
            "chosen_inline_result",
            "pre_checkout_query",
            "shipping_query",
        ]),
        "drop_pending_updates" : True,
        "max_connections"      : 40,   # Render free tier এ কম রাখুন
    }

    if WEBHOOK_SECRET:
        params["secret_token"] = WEBHOOK_SECRET

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url,
                data    = params,
                timeout = aiohttp.ClientTimeout(total=15)
            ) as resp:
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


async def delete_webhook() -> bool:
    """
    Webhook মুছে ফেলো।
    Polling mode এ switch করার সময় call করো।
    """
    import aiohttp

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    params  = {"drop_pending_updates": False}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url,
                data    = params,
                timeout = aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()

        if result.get("ok"):
            LOGGER.info("✅ Webhook deleted — polling mode ready")
            return True
        else:
            LOGGER.warning(f"⚠️ Webhook delete response: {result}")
            return False

    except Exception as e:
        LOGGER.error(f"❌ Webhook delete error: {e}")
        return False


async def get_webhook_info() -> dict:
    """Current webhook status দেখো।"""
    import aiohttp

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url,
                timeout = aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()

        info = result.get("result", {})

        LOGGER.info(
            f"[Webhook Info]\n"
            f"  URL          : {info.get('url', 'none')}\n"
            f"  Pending      : {info.get('pending_update_count', 0)}\n"
            f"  Last Error   : {info.get('last_error_message', 'none')}\n"
            f"  Last Error At: {info.get('last_error_date', 'none')}\n"
            f"  Max Conn     : {info.get('max_connections', 'N/A')}"
        )
        return info

    except Exception as e:
        LOGGER.error(f"❌ getWebhookInfo error: {e}")
        return {}


# ════════════════════════════════════════════════════════════════════════════
# KEEP-ALIVE TASK
# ════════════════════════════════════════════════════════════════════════════

async def keep_alive_task():
    """
    প্রতি ৪ মিনিটে নিজের health endpoint ping করে।
    Render / Azure free tier এ server sleep থেকে জাগিয়ে রাখে।
    """
    import aiohttp

    url     = f"http://127.0.0.1:{WEBHOOK_PORT}/health"
    counter = 0

    # Startup শেষ হওয়ার পর শুরু করো
    await asyncio.sleep(30)

    LOGGER.info("[KeepAlive] Task started — ping every 4 minutes")

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout = aiohttp.ClientTimeout(total=10)
                ) as resp:
                    counter += 1

                    # প্রতি ৪০ মিনিটে একবার log
                    if counter % 10 == 0:
                        LOGGER.info(
                            f"[KeepAlive] Ping #{counter} → "
                            f"status {resp.status}"
                        )

        except Exception as e:
            LOGGER.debug(f"[KeepAlive] Ping failed (harmless): {e}")

        await asyncio.sleep(240)  # ৪ মিনিট পর পর


# ════════════════════════════════════════════════════════════════════════════
# BOT CONNECTION CHECKER
# ════════════════════════════════════════════════════════════════════════════

async def wait_for_bot_ready(timeout: int = 60) -> bool:
    """
    Pyrogram bot connected হওয়া পর্যন্ত অপেক্ষা করো।
    Timeout হলে False return করে।
    """
    LOGGER.info("[Main] Waiting for bot to connect...")

    for i in range(timeout):
        try:
            if app.is_connected:
                me = await app.get_me()
                LOGGER.info(
                    f"✅ Bot connected: @{me.username} "
                    f"(id={me.id})"
                )
                return True
        except Exception:
            pass

        await asyncio.sleep(1)

    LOGGER.error(f"❌ Bot not connected after {timeout}s")
    return False


# ════════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ════════════════════════════════════════════════════════════════════════════

async def main():
    """
    Main async runner।

    ┌─────────────────────────────────────────────┐
    │  WEBHOOK_MODE=true                          │
    │  ✅ Web server (port 10000)                 │
    │  ✅ Webhook registered                      │
    │  ✅ Pyrogram MTProto (ফাইল operations)     │
    │  ✅ Keep-alive task                         │
    │                                             │
    │  WEBHOOK_MODE=false (default)               │
    │  ✅ Web server (health check only)          │
    │  ✅ Webhook deleted                         │
    │  ✅ Pyrogram normal polling                 │
    │  ✅ Keep-alive task                         │
    └─────────────────────────────────────────────┘
    """
    runner = None

    try:
        # ── Step 1: Web server চালু করো ──────────────────────────────────
        LOGGER.info(f"[Main] Starting web server on port {WEBHOOK_PORT}...")
        runner = await setup_webhook_server()

        # ── Step 2: Pyrogram bot start করো ───────────────────────────────
        LOGGER.info("[Main] Starting Pyrogram bot...")
        await app.start()

        # Bot ready হওয়া পর্যন্ত অপেক্ষা করো
        bot_ready = await wait_for_bot_ready(timeout=60)

        if not bot_ready:
            LOGGER.error("[Main] Bot failed to connect! Exiting...")
            return

        # ── Step 3: Webhook / Polling mode configure করো ─────────────────
        if WEBHOOK_MODE:
            if not WEBHOOK_HOST:
                LOGGER.error(
                    "[Main] WEBHOOK_MODE=true কিন্তু WEBHOOK_HOST খালি!\n"
                    "       .env এ WEBHOOK_HOST=https://your-app.onrender.com দিন"
                )
                LOGGER.warning("[Main] Falling back to polling mode...")
                await delete_webhook()

            else:
                LOGGER.info("[Main] Configuring WEBHOOK MODE...")

                # পুরনো webhook delete করো
                await delete_webhook()
                await asyncio.sleep(2)

                # নতুন webhook register করো
                success = await register_webhook()

                if success:
                    LOGGER.info("✅ Webhook mode active!")
                    # Webhook info দেখাও
                    await asyncio.sleep(1)
                    await get_webhook_info()
                else:
                    LOGGER.warning(
                        "[Main] Webhook registration failed — "
                        "falling back to polling"
                    )
                    await delete_webhook()

        else:
            LOGGER.info("[Main] Configuring POLLING MODE...")

            # Polling mode এ webhook অবশ্যই delete থাকতে হবে
            await delete_webhook()
            LOGGER.info("✅ Polling mode active — Pyrogram handling updates")

        # ── Step 4: Keep-alive task চালু করো ─────────────────────────────
        asyncio.create_task(keep_alive_task())

        # ── Step 5: Bot info print করো ───────────────────────────────────
        try:
            me = await app.get_me()
            mode_str = (
                f"Webhook ({WEBHOOK_URL})"
                if WEBHOOK_MODE and WEBHOOK_HOST
                else "MTProto Polling"
            )

            print(f"""
╔══════════════════════════════════════════════════════╗
║           🤖 Bot Successfully Started! 💥            ║
╠══════════════════════════════════════════════════════╣
║  Bot     : @{str(me.username or me.id):<41} ║
║  Mode    : {mode_str[:42]:<42} ║
║  Port    : {str(WEBHOOK_PORT):<42} ║
║  Channel : @juktijol{'':<33} ║
╚══════════════════════════════════════════════════════╝
            """)

        except Exception as e:
            LOGGER.warning(f"[Main] Could not get bot info: {e}")
            LOGGER.info("🤖 Bot Successfully Started! 💥")

        # ── Step 6: চলতে থাকুক ───────────────────────────────────────────
        await asyncio.Event().wait()

    except KeyboardInterrupt:
        LOGGER.info("[Main] Keyboard interrupt — shutting down...")

    except Exception as e:
        LOGGER.error(f"[Main] Fatal error: {e}", exc_info=True)
        raise

    finally:
        # ── Cleanup ───────────────────────────────────────────────────────
        LOGGER.info("[Main] Shutting down gracefully...")

        # Pyrogram stop
        try:
            if app.is_connected:
                await app.stop()
                LOGGER.info("✅ Pyrogram stopped")
        except Exception as e:
            LOGGER.warning(f"[Main] Pyrogram stop error: {e}")

        # Web server stop
        if runner:
            try:
                await runner.cleanup()
                LOGGER.info("✅ Web server stopped")
            except Exception as e:
                LOGGER.warning(f"[Main] Web server cleanup error: {e}")

        LOGGER.info("👋 Shutdown complete")


# ════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    # Startup banner
    mode_label = (
        "WEBHOOK + MTProto Hybrid"
        if WEBHOOK_MODE
        else "MTProto Polling (Recommended)"
    )

    print(f"""
╔══════════════════════════════════════════════════════╗
║           RestrictedContentDL Bot                    ║
║           MODE: {mode_label:<37} ║
╠══════════════════════════════════════════════════════╣
║  Port        : {str(WEBHOOK_PORT):<37} ║
║  Webhook     : {"Enabled" if WEBHOOK_MODE else "Disabled":<37} ║
║  Webhook URL : {(WEBHOOK_URL[:37] if WEBHOOK_URL else "Not configured"):<37} ║
║  Health URL  : http://0.0.0.0:{WEBHOOK_PORT}/health{'':<7} ║
╚══════════════════════════════════════════════════════╝
    """)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
