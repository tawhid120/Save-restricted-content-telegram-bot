# 📘 RestrictedContentDL — পাইথন প্রজেক্ট নোট (বাংলায়)

> এই নোটটি তৈরি করা হয়েছে পাইথন শেখার জন্য। প্রজেক্টটি একটি **Telegram Bot** — যা টেলিগ্রামের পাবলিক/প্রাইভেট চ্যানেল থেকে রেস্ট্রিক্টেড (restricted) কনটেন্ট ডাউনলোড করে এবং YouTube/অন্য সাইট থেকেও ভিডিও ডাউনলোড করে।
>
> লেখক: @juktijol | ভিত্তি: Pyrofork (Pyrogram fork) + Motor (async MongoDB)

---

## 📑 সূচিপত্র

1. [প্রজেক্টটা কী এবং কীভাবে চলে](#১-প্রজেক্টটা-কী-এবং-কীভাবে-চলে)
2. [পাইথন বেসিক রিভিশন (যা এখানে ব্যবহার হয়েছে)](#২-পাইথন-বেসিক-রিভিশন)
3. [ফোল্ডার ও ফাইল স্ট্রাকচার](#৩-ফোল্ডার-ও-ফাইল-স্ট্রাকচার)
4. [মেইন এন্ট্রি পয়েন্ট — main.py](#৪-মেইন-এন্ট্রি-পয়েন্ট--mainpy)
5. [app.py — বট ক্লায়েন্ট তৈরি](#৫-apppy--বট-ক্লায়েন্ট-তৈরি)
6. [config ও environment variables](#৬-config-ও-environment-variables)
7. [bot.py — Telethon ক্লায়েন্ট (ইউজার লগইন)](#৭-botpy--telethon-ক্লায়েন্ট)
8. [Database — core/database.py ও db/users.py](#৮-database--coredatabasepy-ও-dbuserspy)
9. [utils — লগিং, হেল্পার, ফোর্স-সাব](#৯-utils--লগিং-হেল্পার-ফোর্স-সাব)
10. [plugins — ফিচারগুলো](#১০-plugins--ফিচারগুলো)
11. [auth — অ্যাডমিন কমান্ড](#১১-auth--অ্যাডমিন-কমান্ড)
12. [misc — কিবোর্ড ও বাটন রাউটার](#১২-misc--কিবোর্ড-ও-বাটন-রাউটার)
13. [core/start.py — /start কমান্ড](#১৩-corestartpy--start-কমান্ড)
14. [web.py — Flask keep-alive সার্ভার](#১৪-webpy--flask-keep-alive-সার্ভার)
15. [ডিপ্লয়মেন্ট — Docker, Heroku, start.sh](#১৫-ডিপ্লয়মেন্ট)
16. [পাইথন কনসেপ্ট — অ্যাডভান্সড](#১৬-পাইথন-কনসেপ্ট--অ্যাডভান্সড)
17. [তোমার প্র্যাকটিসের জন্য](#১৭-তোমার-প্র্যাকটিসের-জন্য)

---

## ১. প্রজেক্টটা কী এবং কীভাবে চলে

এটি একটি **Telegram Bot**। ইউজার টেলিগ্রামে বটকে একটা লিংক পাঠায় (যেমন `t.me/channel/123`), বট সেই লিংকের ফাইল/মেসেজ ডাউনলোড করে ইউজারের কাছে পাঠিয়ে দেয়।

**চলার ধাপ (flow):**
```
User → Telegram → Bot (main.py) → Pyrofork Client → Telegram API
                                          ↓
                                   Handler (plugins/)
                                          ↓
                                   Database (MongoDB)
                                          ↓
                                   Reply to User
```

**দুইটা লাইব্রেরি ব্যবহার হয়েছে:**
- **Pyrofork** (`pyrogram` এর একটা fork) → বট হিসেবে চলে, মেসেজ পড়ে/পাঠায়।
- **Telethon** (`bot.py`) → ইউজার অ্যাকাউন্ট হিসেবে লগইন করে (প্রাইভেট কনটেন্ট আনার জন্য)।

---

## ২. পাইথন বেসিক রিভিশন

যারা এই কোডটা পড়ে শিখবে, তাদের জন্য কয়েকটা বেসিক বিষয়:

### `import` কী?
```python
import os              # বিল্ট-ইন মডিউল (ফাইল/এনভায়রনমেন্ট নিয়ে কাজ)
from pyrogram import Client   # pyrogram প্যাকেজ থেকে Client ক্লাস আনা
```
`from X import Y` মানে X মডিউল থেকে শুধু Y টা আনো।

### `async` / `await` কী?
এটি **asynchronous programming**। বট অনেক ইউজারের রিকোয়েস্ট একসাথে হ্যান্ডেল করে, তাই এটা দরকার।
```python
async def my_func():        # ফাংশনটা "awaitable"
    await some_task()       # ওই টাস্ক শেষ না হওয়া পর্যন্ত অপেক্ষা করবে
```
`async` = অ্যাসিঙ্ক্রোনাস ফাংশন। `await` = ওই ফাংশনের শেষ হওয়ার জন্য অপেক্ষা।

### `dict` (ডিকশনারি)
```python
user = {"name": "Sumon", "age": 20}   # key: value
user["name"]    # → "Sumon"
user.get("age") # → 20  (get() সেফ মেথড)
```

### `f-string`
```python
name = "Sumon"
print(f"Hello {name}!")   # → Hello Sumon!
```

### `try / except` (Error handling)
```python
try:
    risky_thing()
except Exception as e:
    print(f"Error: {e}")   # এরর হলে প্রোগ্রাম ক্র্যাশ না করে এখানে আসবে
```

---

## ৩. ফোল্ডার ও ফাইল স্ট্রাকচার

```
Save-restricted-content-telegram-bot/
│
├── main.py              ← বট চালু করার মেইন ফাইল (এন্ট্রি পয়েন্ট)
├── main.py(polling)     ← polling মোডের বিকল্প (একই কোড)
├── app.py               ← Pyrofork বট ক্লায়েন্ট তৈরি
├── bot.py               ← Telethon ইউজার ক্লায়েন্ট
├── web.py               ← Flask keep-alive সার্ভার
├── requirements.txt     ← যে প্যাকেজগুলো লাগবে
├── sample.env          ← সব কনফিগ ভেরিয়েবলের নমুনা
├── Dockerfile          ← Docker ইমেজ বানানোর নিয়ম
├── docker-compose.yml  ← Docker চালানোর কনফিগ
├── start.sh            ← বট শুরু করার স্ক্রিপ্ট
├── update.sh           ← গিট থেকে আপডেট নেওয়ার স্ক্রিপ্ট
├── Procfile            ← Heroku worker
├── app.json            ← Heroku deploy কনফিগ
├── runtime.txt         ← Python ভার্সন
│
├── auth/               ← অ্যাডমিন/ওনার কমান্ড (sudo, restart, speedtest...)
├── core/               ← ডাটাবেস + /start হ্যান্ডলার
├── db/                 ← ইউজার ডাটাবেস হেল্পার
├── misc/               ← কিবোর্ড বাটন + কলব্যাক রাউটার
├── plugins/            ← সব ফিচার (yt.py, autolink.py, settings.py...)
├── utils/              ← কমন হেল্পার (logger, helper, force_sub)
└── cookies/            ← YouTube cookies ফাইল
```

প্রতিটা ফোল্ডারে `__init__.py` থাকে → এটি পাইথনকে বুঝায় যে এটি একটি **package** (মডিউল হিসেবে ইম্পোর্ট করা যাবে)।

---

## ৪. মেইন এন্ট্রি পয়েন্ট — main.py

এটি বট চালু করার প্রথম ফাইল।

```python
import asyncio
try:
    import uvloop
    uvloop.install()   # asyncio event loop 2-4x দ্রুত করে (Linux-এ)
except ImportError:
    pass
```

**uvloop** — এটি asyncio-এর একটা দ্রুত ভার্সন। `try/except` দিয়ে চেক করা হয়েছে যদি না থাকে তবুও এরর না দেখায়।

```python
from utils import LOGGER
from utils.force_sub import setup_force_sub_handler
from auth import setup_auth_handlers
from plugins import setup_plugins_handlers
from core import setup_start_handler, init_db
from misc import handle_callback_query
from misc.button_router import setup_button_router
from app import app
```

এখানে প্রতিটা ফোল্ডার থেকে `setup_*` ফাংশন ইম্পোর্ট করা হয়েছে। এদেরকে **handler registration** বলে — মানে "এই কমান্ড এলে এই ফাংশন চালাও"।

```python
asyncio.get_event_loop().run_until_complete(init_db())
```
বট শুরুর আগে ডাটাবেস রেডি করো (ইনডেক্স তৈরি, পুরানো ডাটা পরিষ্কার)।

```python
setup_force_sub_handler(app)    # ১. ফোর্স-সাব চেক (সবার আগে)
setup_plugins_handlers(app)     # ২. সব ফিচার
setup_auth_handlers(app)        # ৩. অ্যাডমিন কমান্ড
setup_start_handler(app)        # ৪. /start
setup_button_router(app)        # ৫. রিপ্লাই কিবোর্ড বাটন (সবশেষে)
```

**গুরুত্বপূর্ণ:** হ্যান্ডলার রেজিস্টার করার অর্ডার ম্যাটার করে। ফোর্স-সাব আগে চেক করতে হবে যাতে ইউজার চ্যানেলে জয়েন না করলে বাকি কাজ না হয়।

```python
@app.on_callback_query()
async def handle_callback(client, callback_query):
    await handle_callback_query(client, callback_query)

LOGGER.info("Bot Successfully Started! 💥")
app.run()    # ← বট চালু (এটাই মেইন লুপ)
```

---

## ৫. app.py — বট ক্লায়েন্ট তৈরি

```python
from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN

app = Client(
    "SmartTools",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=1000,                 # একসাথে ১০০০ টাস্ক হ্যান্ডেল করতে পারবে
    max_concurrent_transmissions=5, # একসাথে ৫টা ফাইল আপলোড
)
```

`Client` হলো Pyrofork-এর মেইন ক্লাস। এটি টেলিগ্রাম API-এর সাথে কানেক্ট করে।
- `api_id`, `api_hash` → my.telegram.org থেকে নিতে হয়।
- `bot_token` → @BotFather থেকে নিতে হয়।
- `"SmartTools"` → সেশন ফাইলের নাম (যাতে বারবার লগইন না করতে হয়)।

---

## ৬. config ও environment variables

রিপোতে `config.py` ফাইলটা নেই (এটি `.gitignore` করা আছে, ব্যক্তিগত তথ্য বলে)। কিন্তু `sample.env` থেকে বোঝা যায় এতে কী কী থাকে:

```env
API_ID=YOUR_API_ID
API_HASH=YOUR_API_HASH
BOT_TOKEN=YOUR_BOT_TOKEN
DEVELOPER_USER_ID=YOUR_USER_ID
LOG_GROUP_ID=YOUR_LOG_GROUP_ID
MONGO_URL=YOUR_MONGO_URL
FORCE_SUB_CHANNEL=juktijol
COMMAND_PREFIX=!|.|#|,|/
```

`config.py` সাধারণত এভাবে থাকে:
```python
import os
from dotenv import load_dotenv
load_dotenv()   # .env ফাইল থেকে ভেরিয়েবল লোড করে

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
```

**Environment variable** মানে সিস্টেম-লেভেল ভেরিয়েবল। পাসওয়ার্ড/টোকেন কোডের ভিতরে হার্ডকোড না করে এনভায়রনমেন্ট ভেরিয়েবলে রাখা **বেস্ট প্র্যাকটিস** (সিকিউরিটি)।

`COMMAND_PREFIX=!|.|#|,|/` → কমান্ডের আগে এই সিম্বলগুলো যেকোনোটা থাকতে পারবে (`/start`, `!start`, `.start` সবই কাজ করবে)।

---

## ৭. bot.py — Telethon ক্লায়েন্ট

```python
from telethon import TelegramClient
import config

SmartYTUtil = None

async def init_client():
    global SmartYTUtil
    SmartYTUtil = TelegramClient(
        session='smartytutil',
        api_id=config.API_ID,
        api_hash=config.API_HASH,
    )
    return SmartYTUtil
```

**কেন দুইটা ক্লায়েন্ট?**
- `app.py` (Pyrofork) → বট হিসেবে চলে।
- `bot.py` (Telethon) → ইউজার অ্যাকাউন্ট হিসেবে লগইন করে, যাতে প্রাইভেট চ্যানেলের কনটেন্ট আনা যায় (বট একা প্রাইভেট কনটেন্ট পায় না)।

`global` কীওয়ার্ড → ফাংশনের বাইরের ভেরিয়েবলকে মডিফাই করার জন্য।

```python
async def start_bot():
    global SmartYTUtil
    if SmartYTUtil is None:
        await init_client()
    await SmartYTUtil.start(bot_token=config.BOT_TOKEN)
    return SmartYTUtil
```

---

## ৮. Database — core/database.py ও db/users.py

এই প্রজেক্টে **MongoDB** (NoSQL ডাটাবেস) ব্যবহার হয়েছে। পাইথন থেকে MongoDB-এর সাথে কানেক্ট করতে **Motor** (async ভার্সন) ব্যবহার হয়।

### core/database.py
```python
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL

_main_client = AsyncIOMotorClient(MONGO_URL, connectTimeoutMS=10000)
_main_db = _main_client["ItsSmartTool"]

# Collection গুলো (টেবিলের মতো):
prem_plan1    = _main_db["prem_plan1"]
prem_plan2    = _main_db["prem_plan2"]
prem_plan3    = _main_db["prem_plan3"]
user_sessions = _main_db["user_sessions"]
premium_users = _main_db["premium_users"]
downloads_collection = _main_db["downloads"]
total_users   = _main_db["total_users"]
referrals     = _main_db["referrals"]
```

**SQL vs NoSQL:**
- SQL → টেবিল, রো, কলাম।
- NoSQL (MongoDB) → **Collection** (টেবিল) + **Document** (JSON মতো `{}`)।

### TTL Index (অটো-এক্সপায়ার)
```python
async def _create_ttl_index(collection, field="expiry_date"):
    await collection.create_index(
        [(field, ASCENDING)],
        expireAfterSeconds=0,   # এই ফিল্ডের সময় শেষ → ডকুমেন্ট অটো ডিলিট
        name=f"{field}_ttl",
        sparse=True,
    )
```
**TTL** = Time To Live। প্রিমিয়াম প্ল্যানের মেয়াদ শেষ হলে ডাটাবেস নিজেই ডিলিট করে দেয়।

### Startup Cleanup
```python
async def _cleanup_premium_duplicates():
    now = datetime.utcnow()
    # ১. মেয়াদ শেষ এন্ট্রি মুছে দাও
    for name, col in plan_map:
        await col.delete_many({"expiry_date": {"$lte": now}})
    # ২. ডুপ্লিকেট ইউজার ঠিক করো
    # ৩. premium_users রিবিল্ড করো
```
বট শুরুর সময় পুরানো/ডুপ্লিকেট ডাটা পরিষ্কার করে।

### db/users.py — upsert
```python
async def upsert_user(user) -> dict:
    doc = {
        "user_id": user.id,
        "username": user.username or None,
        "first_name": user.first_name or "",
        ...
    }
    await total_users.update_one(
        {"user_id": user.id},
        {"$set": doc},
        upsert=True,    # না থাকলে insert, থাকলে update
    )
    return doc
```
**upsert** = update + insert। ইউজার না থাকলে নতুন সেভ, থাকলে আপডেট।

---

## ৯. utils — লগিং, হেল্পার, ফোর্স-সাব

### utils/logging_setup.py
```python
import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler("botlog.txt", maxBytes=50000000, backupCount=10),
        logging.StreamHandler()
    ]
)
LOGGER = logging.getLogger(__name__)
```
**Logging** মানে বটের কাজগুলো লগ ফাইলে/কনসোলে রেকর্ড করা। `RotatingFileHandler` → ফাইল ৫০MB হলে নতুন ফাইলে যায় (পুরানো ১০টা রাখে)।

### utils/helper.py (উদাহরণঃ ফাইল সাইজ ফরম্যাট)
```python
SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]

def get_readable_file_size(size_in_bytes):
    if size_in_bytes is None or size_in_bytes < 0:
        return "0B"
    for unit in SIZE_UNITS:
        if size_in_bytes < 1024:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024
    return "File too large"
```
এটি বাইটকে `MB`/`GB`-এ কনভার্ট করে। লুপ চালিয়ে ১০২৪ দিয়ে ভাগ দেয় যতক্ষণ না ছোট হয়।

### utils/force_sub.py — ফোর্স সাবস্ক্রাইব সিস্টেম

ইউজারকে একটা চ্যানেলে জয়েন করতে বাধ্য করে।

**In-memory TTL Cache:**
```python
_sub_cache: dict[int, tuple[bool, float]] = {}

def _cache_get(user_id):
    entry = _sub_cache.get(user_id)
    if entry is None:
        return None
    is_sub, ts = entry
    ttl = CACHE_TTL if is_sub else NOT_JOINED_CACHE_TTL
    if time.monotonic() - ts < ttl:
        return is_sub
    _sub_cache.pop(user_id, None)
    return None
```
**Cache** মানে বারবার API কল না করে মেমোরিতে রাখা। `time.monotonic()` → সিস্টেম টাইম (রানটাইম মাপার জন্য)।

**Core check:**
```python
async def check_force_sub(client, user_id, refresh=False):
    if not API_CHANNEL:
        return True          # ফোর্স-সাব বন্ধ থাকলে সবাইকে allow
    if user_id == DEVELOPER_USER_ID:
        return True          # ওনার সবসময় allow
    if not refresh:
        cached = _cache_get(user_id)
        if cached is not None:
            return cached    # ক্যাশ থেকে রিটার্ন (দ্রুত)

    try:
        member = await asyncio.wait_for(
            client.get_chat_member(API_CHANNEL, user_id),
            timeout=API_TIMEOUT,
        )
        is_sub = member.status not in (ChatMemberStatus.BANNED, ChatMemberStatus.LEFT)
        _cache_set(user_id, is_sub)
        return is_sub
    except UserNotParticipant:
        return False
    except FloodWait as e:
        await asyncio.sleep(min(e.value, 5))
        return True   # ফ্লাড ওয়েট-এর সময় allow করে (ভালো UX)
```
`asyncio.wait_for(..., timeout=5.0)` → ৫ সেকেন্ডের বেশি লাগলে টাইমআউট।

**Handler interceptor (group=-1):**
```python
@app.on_message(filters.private & ~filters.service, group=-1)
async def _msg_interceptor(client, message):
    is_sub = await check_force_sub(client, user_id)
    if not is_sub:
        await message.reply_text(NOT_SUBSCRIBED_TEXT, reply_markup=_not_sub_keyboard())
        message.stop_propagation()   # অন্য হ্যান্ডলারে যাবে না
```
`stop_propagation()` → এই মেসেজ আর অন্য কোনো হ্যান্ডলারে যাবে না।

---

## ১০. plugins — ফিচারগুলো

`plugins/` ফোল্ডারে প্রতিটা ফিচার আলাদা ফাইলে:
- `yt.py` → YouTube ডাউনলোড
- `autolink.py` → টেলিগ্রাম লিংক অটো-ডিটেক্ট
- `settings.py` → সেটিংস প্যানেল
- `plan.py` → প্রিমিয়াম প্ল্যান
- `login.py` → ইউজার লগইন
- `referral.py` → রেফারেল সিস্টেম
- আরও অনেক (aria2dl, qbtdl, fbdl, gdl...)।

### plugins/__init__.py — সব হ্যান্ডলার রেজিস্টার
```python
from .plan import setup_plan_handler
from .info import setup_info_handler
...
def setup_plugins_handlers(app):
    setup_plan_handler(app)
    setup_info_handler(app)
    setup_thumb_handler(app)
    ...
```

### উদাহরণ: plugins/yt.py (YouTube ডাউনলোড)

**Command filter:**
```python
@Client.on_message(filters.command(["yt", "video", "mp4", "dl"], prefixes=["/", "!", "."]))
async def yt_video_command(client, message):
    query = message.text.split(None, 1)[1].strip() if ... else ""
    await handle_yt_command(client, message, query)
```
`@Client.on_message(...)` → **decorator**। এটি ফাংশনের উপরে লেখা হয়, মানে "এই কমান্ড এলে এই ফাংশন চালাও"।

`message.text.split(None, 1)` → মেসেজকে স্পেস দিয়ে ২ ভাগ করে (কমান্ড + আর্গুমেন্ট)।

**State dict (pending downloads):**
```python
pending_downloads: dict = {}
...
pending_downloads[token] = {
    "url": video_url,
    "user_id": message.from_user.id,
    "chat_id": chat_id,
    "msg_id": status.id,
}
```
প্রতিটা ডাউনলোডের জন্য একটা `token` (ইউনিক আইডি) দেওয়া হয়, যাতে ইউজার বাটনে ক্লিক করলে বোঝা যায় কোন ডাউনলোডের কথা বলছে।

**Callback handler:**
```python
@Client.on_callback_query(filters.regex(r"^YV\|"))
async def yt_video_cb(client, callback_query):
    raw = callback_query.data
    parts = raw.split("|")    # "YV|token|quality" → ["YV", "token", "quality"]
    token = parts[1]
    quality_key = parts[2]
    data = pending_downloads.get(token)
    if not data:
        await callback_query.answer("❌ Session expired.")
        return
    asyncio.create_task(do_video_download(client, token, quality_key))
```
`callback_query.data` → ইনলাইন বাটনে ক্লিক করলে যে ডাটা আসে (স্ট্রিং)।
`asyncio.create_task(...)` → ব্যাকগ্রাউন্ডে টাস্ক চালু করে (অপেক্ষা না করে)।

**FFmpeg দিয়ে ফাইল স্প্লিট (২GB+ হলে):**
```python
loop = asyncio.get_running_loop()
parts = await loop.run_in_executor(executor, split_file_ffmpeg, file_path, split_dir, segment_dur, ext)
```
**Executor** → ভারী CPU কাজ (যেমন ffmpeg) asyncio লুপ ব্লক না করে আলাদা থ্রেডে চালায়।

---

## ১১. auth — অ্যাডমিন কমান্ড

`auth/` ফোল্ডারে ওনার/অ্যাডমিনের কমান্ড:
- `sudo.py` → সুডো কমান্ড
- `restart.py` → বট রিস্টার্ট
- `speedtest.py` → সার্ভার স্পিড টেস্ট
- `logs.py` → লগ দেখা
- `set.py` → বটফাদার কমান্ড লিস্ট
- `migrate.py` → ডাটাবেস মাইগ্রেট
- `admin.py` → অ্যাডমিন প্যানেল

`auth/__init__.py`:
```python
def setup_auth_handlers(app):
    setup_sudo_handler(app)
    setup_restart_handler(app)
    setup_speed_handler(app)
    ...
```

---

## ১২. misc — কিবোর্ড ও বাটন রাউটার

### misc/keyboards.py
```python
def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("📦 Batch Download"), KeyboardButton("🔑 Login")],
            [KeyboardButton("🚪 Logout"), KeyboardButton("❓ Help")],
            ...
        ],
        resize_keyboard=True,
    )
```
`ReplyKeyboardMarkup` → চ্যাটের নিচে সবসময় দেখা যায় এমন বাটন।
`InlineKeyboardMarkup` → মেসেজের সাথে থাকা বাটন (কলব্যাক ডাটা পাঠায়)।

`BUTTON_COMMAND_MAP` → বাটনের লেবেল → কমান্ড ম্যাপ:
```python
BUTTON_COMMAND_MAP = {
    "❓ Help": "help",
    "🏡 Home": "start",
    "📦 Batch Download": "autobatch",
    ...
}
```

### misc/button_router.py — ক্যাচ-অল রাউটার
```python
@app.on_message(
    filters.text & (filters.private | filters.group)
    & filters.create(lambda _, __, msg: msg.text.strip() in _button_labels),
    group=99,   # সবশেষে চেক করবে
)
async def button_router(client, message):
    label = message.text.strip()
    command = BUTTON_COMMAND_MAP.get(label)
    if command == "autobatch":
        await handle_batch_start(client, message)
    elif command == "settings":
        ...
```
ইউজার যদি নিচের কিবোর্ড থেকে "📦 Batch Download" বাটনে চাপ দেয়, এই রাউটার সেটাকে `autobatch` কমান্ডে কনভার্ট করে।

---

## ১৩. core/start.py — /start কমান্ড

```python
def setup_start_handler(app):
    @app.on_message(filters.command("start"))
    async def start(client, message):
        user = message.from_user
        # MongoDB-তে ইউজার সেভ
        await total_users.update_one(
            {"user_id": user.id},
            {"$set": {
                "user_id": user.id,
                "first_name": user.first_name or "",
                "name": user_fullname,
                "last_active": datetime.utcnow(),
            }},
            upsert=True,
        )

        # রেফারেল চেক: /start 12345 (কেউ রেফার করলে)
        if len(message.command) > 1:
            referrer_id = int(message.command[1])
            success = await process_referral(client, user.id, referrer_id)

        await message.reply_text(start_message, reply_markup=get_start_inline())
```
`/start 12345` → `message.command = ["start", "12345"]`। রেফারেল আইডি হিসেবে কাজ করে।

---

## ১৪. web.py — Flask keep-alive সার্ভার

Render/Heroku-এর মতো ফ্রি হোস্টিং সার্ভিস বটকে ঘুম পাড়িয়ে দেয়। তাই একটা ওয়েব সার্ভার + self-ping দিয়ে জাগ্রত রাখা হয়।

```python
from flask import Flask, jsonify
import threading

app = Flask(__name__)
PORT = int(os.environ.get("PORT", 8000))

@app.route('/')
def home():
    return "Restricted Content DL Bot is Running Successfully! 🚀"

@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

def _keep_alive():
    import urllib.request
    while True:
        time.sleep(300)   # প্রতি ৫ মিনিটে
        urllib.request.urlopen(f"http://0.0.0.0:{PORT}/health")

if __name__ == "__main__":
    t = threading.Thread(target=run, daemon=True)
    t.start()
    ka = threading.Thread(target=_keep_alive, daemon=True)
    ka.start()
    os.system("bash start.sh")   # বট চালু
```
**threading** → একসাথে একাধিক কাজ (ওয়েব সার্ভার + কিপ-অ্যালাইভ + বট)।
`__name__ == "__main__"` → ফাইলটা সরাসরি চালালে (না যে ইম্পোর্ট করলে) এই ব্লক চলে।

---

## ১৫. ডিপ্লয়মেন্ট

### requirements.txt
সব প্যাকেজের লিস্ট:
```
pyrofork, tgcrypto-pyrofork, uvloop, aiofiles, pillow,
yt-dlp, flask, motor, pymongo, telegraph, ...
```
`pip install -r requirements.txt` → সব ইনস্টল হয়।

### Dockerfile
```dockerfile
FROM python:3.10-slim-bookworm
RUN apt-get update && apt-get install -y ffmpeg nodejs ...
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python3", "web.py"]
```
Docker → বটকে "কন্টেইনার"-এ প্যাক করে যেকোনো সার্ভারে চালানো যায়।

### start.sh
```bash
#!/bin/bash
# bgutil POT সার্ভার চালু (YouTube এর জন্য)
node "$SERVER_JS" --port "$BGUTIL_POT_PORT" &
# বট চালু
python3 main.py
```

### update.sh
গিট থেকে আপডেট নেয়, config.py ব্যাকআপ রাখে, বট রিস্টার্ট করে।

---

## ১৬. পাইথন কনসেপ্ট — অ্যাডভান্সড

এই প্রজেক্টে যে অ্যাডভান্সড কনসেপ্টগুলো আছে:

### ১. Decorator (`@app.on_message`)
ফাংশনের আচরণ পরিবর্তন করে। এখানে হ্যান্ডলার রেজিস্টার করে।

### ২. Async/Await + Event Loop
`asyncio` → নন-ব্লকিং I/O। বট হাজার হাজার ইউজার হ্যান্ডেল করতে পারে।

### ৩. uvloop
asyncio-এর দ্রুত ইমপ্লিমেন্টেশন (C দিয়ে লেখা)।

### ৪. Motor (Async MongoDB)
সিনক্রোনাস না, অ্যাসিঙ্ক্রোনাস ডাটাবেস অপারেশন।

### ৫. Threading
`web.py`-এ একাধিক কাজ একসাথে চালাতে।

### ৬. Executor (`run_in_executor`)
ভারী CPU কাজ (ffmpeg) মেইন লুপ ব্লক না করে আলাদা থ্রেডে।

### ৭. Cache (TTL)
বারবার API কল এড়াতে মেমোরিতে ডাটা রাখা।

### ৮. Regex (`filters.regex`)
প্যাটার্ন ম্যাচিং — কলব্যাক ডাটা পার্স করতে।

### ৯. Package Structure (`__init__.py`)
কোডকে মডিউলার ও রি-ইউজেবল করতে।

### ১০. Environment Variables
সিকিউর কনফিগ ম্যানেজমেন্ট।

### ১১. Dict-based State
`pending_downloads[token]` → ইউজার সেশন ট্র্যাক করতে।

### ১২. Circular Import এড়ানো
```python
# main.py-তে ফাংশনের ভিতরে import করা হয়েছে
from plugins.referral import process_referral
```
ফাংশনের ভিতরে ইম্পোর্ট করলে circular import এড়ানো যায়।

---

## ১৭. তোমার প্র্যাকটিসের জন্য

১. **ছোট বট বানাও:** `pyrogram` দিয়ে একটা `/start` রিপ্লাই করা বট।
2. **Dict নিয়ে খেলো:** `user = {"name": "X", "age": 20}` → এডিট/অ্যাক্সেস করো।
3. **Async শিখো:** `async def` + `await` দিয়ে ২টা কাজ একসাথে করার চেষ্টা করো।
4. **Logging:** `logging` মডিউল দিয়ে তোমার প্রোগ্রামের লগ রাখো।
5. **MongoDB:** স্থানীয় MongoDB ইনস্টল করে `motor` দিয়ে একটা ডকুমেন্ট সেভ/রিড করো।
6. **Flask:** ছোট ওয়েব সার্ভার বানাও যা `/` এ "Hello" দেখায়।

---

> **মনে রাখো:** এই প্রজেক্টটা বড়, কিন্তু এর মূল লজিক খুব সিম্পল:
> **মেসেজ আসে → হ্যান্ডলার চেক করে → কাজ করে → রিপ্লাই দেয়।**
> ধীরে ধীরে একটা একটা ফাইল পড়লে তুমি পুরোটা বুঝে যাবে। 🚀
