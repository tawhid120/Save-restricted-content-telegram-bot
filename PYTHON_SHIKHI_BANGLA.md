# 🐍 পাইথন শেখার নোট — একদম শুরু থেকে (বাংলায়)

> **এই নোট কাদের জন্য?**
> যারা আগে কখনো কোডিং বা পাইথন দেখেনি। একদম শূন্য থেকে শিখবে।
> এখানে ইংরেজি শব্দগুলোর বাংলা মানে + কী কাজ করে — সব একদম সহজ ভাষায় লেখা হয়েছে।
> ছোট বাচ্চাও যাতে বুঝতে পারে, এমন ভাষায় লেখা হয়েছে।
>
> এই নোটের প্রজেক্টটি হলো একটি **Telegram Bot** (টেলিগ্রাম রোবট)। যা টেলিগ্রাম থেকে ছবি/ভিডিও/ফাইল ডাউনলোড করে দেয়।

---

## 📖 সূচিপত্র

**অংশ ১ — কম্পিউটার ও প্রোগ্রামিং বোঝো (মাটির নিচ থেকে)**
- কম্পিউটার কী? প্রোগ্রাম কী?
- পাইথন কী? কেন শিখবো?

**অংশ ২ — পাইথনের মৌলিক শব্দ ও নিয়ম**
- `print` কী? (স্ক্রিনে লেখা দেখানো)
- `import` কী? (অন্যের তৈরি সরঞ্জাম ব্যবহার)
- ভেরিয়েবল (Variable) — নাম দিয়ে রাখা
- `def` — নিজের তৈরি কাজ
- `if` / `else` — শর্ত (যদি... তাহলে...)
- `for` / `while` — বারবার কাজ
- লিস্ট (List) ও ডিকশনারি (Dict) — তালিকা
- `try` / `except` — ভুল হলে কী করবে
- `async` / `await` — একসাথে অনেক কাজ
- `f"..."` — লেখার ভিতরে সংখ্যা বসানো

**অংশ ৩ — এই প্রজেক্টটা আসলে কী?**
- Telegram Bot মানে কী?
- বটটা কীভাবে কাজ করে (ছবি দিয়ে বোঝানো)

**অংশ ৪ — ফোল্ডার ও ফাইলের ছবি (স্ট্রাকচার)**

**অংশ ৫ — প্রতিটা ফাইল বিস্তারিত ব্যাখ্যা**
- `main.py` — বট চালু করার মূল দরজা
- `app.py` — বটের "ফোন" (কানেকশন)
- `bot.py` — ইউজার সেজে লগইন
- `web.py` — বটকে ঘুম থেকে জাগ্রত রাখা
- `core/` — ডাটাবেস ও /start
- `utils/` — সাহায্যকারী টুল
- `plugins/` — সব ফিচার
- `auth/` — বড়দের (অ্যাডমিন) কমান্ড
- `misc/` — বাটন ও কিবোর্ড
- `db/` — ইউজার ডাটা সেভ
- কনফিগ ফাইল: `requirements.txt`, `sample.env`, `Dockerfile`, `start.sh`

**অংশ ৬ — অ্যাডভান্সড বিষয় (একটু বড়দের জন্য)**

**অংশ ৭ — তোমার প্র্যাকটিস (নিজে চর্চা)**
---

# 🟢 অংশ ১ — কম্পিউটার ও প্রোগ্রামিং বোঝো

## কম্পিউটার কী?
কম্পিউটার হলো একটা বাক্স, যা খুব দ্রুত গণনা করতে পারে। তুমি যদি বলো "১+১ কত?", সে সেকেন্ডের ভাগের মধ্যে "২" বলে দেয়। কিন্তু কম্পিউটার নিজে থেকে কিছু বুঝে না — তোমাকে ঠিকঠাক নির্দেশ দিতে হয়।

## প্রোগ্রাম কী?
প্রোগ্রাম মানে **নির্দেশের একটা তালিকা**। ঠিক যেমন রান্নার রেসিপি:
- চুলায় আঁচ দাও
- প্যানে তেল দাও
- ডিম ভাজো

কম্পিউটারকেও এমনি করে ধাপে ধাপে নির্দেশ দিতে হয়। সেই নির্দেশের ভাষাকে বলে **প্রোগ্রামিং ল্যাঙ্গুয়েজ** (Programming Language)। পাইথন এমনই একটা ভাষা।

## পাইথন কী?
পাইথন (Python) হলো একটা প্রোগ্রামিং ভাষা যা মানুষের পড়তে সহজ। ইংরেজির মতো লেখা যায়। উদাহরণ:
```python
print("হ্যালো দুনিয়া")
```
এটি স্ক্রিনে লিখবে: **হ্যালো দুনিয়া**
পাইথন দিয়ে গেম, ওয়েবসাইট, বট, ডাটা এনালাইসিস — সব করা যায়।

---

# 🟢 অংশ ২ — পাইথনের মৌলিক শব্দ ও নিয়ম

নিচে প্রতিটা শব্দের বাংলা মানে + উদাহরণ দেওয়া হলো।

## ১. `print` — স্ক্রিনে লেখা দেখানো
- **মানে:** "ছাপাও" বা "দেখাও"।
- **কাজ:** যা লেখা থাকবে, স্ক্রিনে দেখাবে।
```python
print("আমি পাইথন শিখছি")
```
→ স্ক্রিনে লেখা আসবে: আমি পাইথন শিখছি

## ২. `import` — অন্যের তৈরি সরঞ্জাম ব্যবহার
- **মানে:** "আনো" বা "নাও"।
- **কাজ:** পাইথনে অনেকে আগেই অনেক সরঞ্জাম বানিয়ে রেখেছে। `import` দিয়ে সেই সরঞ্জাম আমাদের প্রোগ্রামে আনি।
```python
import os          # "os" নামের সরঞ্জাম আনো (ফাইল/ফোল্ডার নিয়ে কাজ করে)
from time import sleep   # "time" থেকে শুধু "sleep" টুকু আনো (ঘুম পাড়ায়)
```
- `import os` মানে: পুরো `os` সরঞ্জামটা আনো।
- `from time import sleep` মানে: `time` নামের বাক্স থেকে শুধু `sleep` (ঘুম) নামের টুকরোটা আনো।

## ৩. ভেরিয়েবল (Variable) — নাম দিয়ে রাখা
- **মানে:** "পরিবর্তনশীল" বা যার নামে জিনিস রাখা যায়।
- **কাজ:** কোনো সংখ্যা বা লেখা মনে রাখতে একটা নাম দেই।
```python
name = "সুমন"      # name নামে "সুমন" রাখলাম
age = 20            # age নামে 20 রাখলাম
print(name)         # → সুমন
```
- `=` চিহ্নটা এখানে "সমান" না, এটা "বামে ডানের জিনিসটা রাখো" মানে।

## ৪. `def` — নিজের তৈরি কাজ
- **মানে:** "define" = সংজ্ঞা দাও / তৈরি করো।
- **কাজ:** একটা কাজের নাম দিয়ে একটা গোছা কোড বানাই। পরে শুধু নাম ডাকলেই কাজটা হয়।
```python
def greet():                    # greet নামে একটা কাজ বানালাম
    print("হ্যালো!")           # এর ভিতরে কী করবে

greet()                        # এখন ডাকলাম → হ্যালো! ছাপাবে
```
- `()` এই বন্ধনীর ভিতরে আমরা "ইনপুট" দেই (কাজটা যা দরকার)।

## ৫. `if` / `else` — শর্ত (যদি... তাহলে...)
- **মানে:** "যদি" / "নাহলে"।
- **কাজ:** কোনো শর্ত পূরণ হলে এক কাজ, না হলে অন্য কাজ।
```python
age = 20
if age >= 18:
    print("তুমি বড়")        # যদি 18 বা বেশি হয়
else:
    print("তুমি ছোট")        # নাহলে
```

## ৬. `for` / `while` — বারবার কাজ
- **মানে:** "জন্য" / "যতক্ষণ"।
- **কাজ:** একই কাজ বারবার করা।
```python
for i in range(3):     # i = 0, 1, 2 — তিনবার ঘুরবে
    print("হ্যালো")      # ৩ বার হ্যালো ছাপাবে
```

## ৭. লিস্ট (List) ও ডিকশনারি (Dict)
### লিস্ট (List) — সাজানো তালিকা
```python
fruits = ["আপেল", "কলা", "আম"]   # তিনটা ফলের তালিকা
print(fruits[0])                   # → আপেল (০ নম্বরে আছে)
```
- লিস্ট `[ ]` বন্ধনী দিয়ে লেখা হয়। গুনতি ০ থেকে শুরু।

### ডিকশনারি (Dict) — নাম-মান জুটি
```python
user = {"name": "সুমন", "age": 20}
print(user["name"])    # → সুমন
```
- `{ }` বন্ধনী দিয়ে লেখা হয়। `"name": "সুমন"` মানে নাম হচ্ছে সুমন।

## ৮. `try` / `except` — ভুল হলে কী করবে
- **মানে:** "চেষ্টা করো" / "ছাড়া নাও" (ভুল ধরো)।
- **কাজ:** কোনো কাজে ভুল হলে প্রোগ্রাম বন্ধ না করে, ভুলটা ধরে অন্য কাজ করে।
```python
try:
    print(ভাঙা_জিনিস)     # এটা ভুল, কারণ ভাঙা_জিনিস নাই
except:
    print("ভুল হয়েছে!")    # ভুল ধরে এটা ছাপাবে, প্রোগ্রাম বন্ধ হবে না
```

## ৯. `async` / `await` — একসাথে অনেক কাজ
- **মানে:** "async" = অ্যাসিঙ্ক্রোনাস = একসাথে / অপেক্ষা না করে। "await" = অপেক্ষা করো।
- **কাজ:** সাধারণত কম্পিউটার একটা কাজ শেষ না করা পর্যন্ত পরের কাজ করে না। কিন্তু বটের অনেক ইউজার একসাথে আসে। তাই `async` দিয়ে একাধিক কাজ একসাথে চালায়।
```python
async def download():        # async = এটা একসাথে চলতে পারে
    await wait_for_file()    # await = এইটা শেষ না হওয়া পর্যন্ত এখানে দাঁড়াও
```
- এটা একটু বড়দের বিষয়, মোটামুটি বুঝলেই হবে: **অনেকে একসাথে বট ব্যবহার করতে পারে** এজন্য এটা লাগে।

## ১০. `f"..."` — লেখার ভিতরে সংখ্যা বসানো
- **মানে:** "format" = গুছানো।
- **কাজ:** লেখার ভিতরে সরাসরি ভেরিয়েবল বসানো যায়।
```python
name = "সুমন"
print(f"হ্যালো {name}!")    # → হ্যালো সুমন!
```
- `f"..."` এর ভিতরে `{name}` লিখলে সেখানে ভেরিয়েবলের মান বসে।

---

# 🟢 অংশ ৩ — এই প্রজেক্টটা আসলে কী?

## Telegram Bot মানে কী?
টেলিগ্রাম (Telegram) হলো একটা মেসেজিং অ্যাপ (যেমন হোয়াটসঅ্যাপ)। **Bot** মানে রোবট — একটা অ্যাকাউন্ট যা মানুষ না, কম্পিউটার চালায়।

এই বটটি করে কী:
1. তুমি বটকে একটা লিংক পাঠাও (যেমন `t.me/channel/123`)
2. বট সেই লিংকের ছবি/ভিডিও ডাউনলোড করে
3. তোমাকে ফেরত পাঠিয়ে দেয়

## বটটা কীভাবে কাজ করে (ছবি দিয়ে):

```
  তুমি (ইউজার)
     │  (লিংক পাঠালে)
     ▼
  Telegram অ্যাপ
     │
     ▼
  বটের প্রোগ্রাম (main.py)
     │
     ├──→ চেক করে: ইউজার চ্যানেলে জয়েন করেছে? (force_sub)
     ├──→ ডাটাবেসে নাম সেভ করে (database)
     ├──→ লিংকটা বুঝে ফাইল ডাউনলোড করে (plugins)
     │
     ▼
  তোমাকে ফাইল পাঠিয়ে দেয় ✅
```

---

# 🟢 অংশ ৪ — ফোল্ডার ও ফাইলের ছবি (স্ট্রাকচার)

প্রজেক্ট ফোল্ডারটা এমন দেখতে:

```
Save-restricted-content-telegram-bot/   ← মূল ফোল্ডার
│
├── main.py              ← বট চালু করার মূল ফাইল (দরজা)
├── app.py               ← বটের "ফোন" (টেলিগ্রামের সাথে কানেক্ট)
├── bot.py               ← ইউজার সেজে লগইন করার ফোন
├── web.py               ← বটকে ঘুম থেকে জাগিয়ে রাখে
├── requirements.txt     ← যে সরঞ্জামগুলো লাগবে তার তালিকা
├── sample.env          ← সিক্রেট তথ্যের নমুনা (পাসওয়ার্ডের মতো)
├── Dockerfile          ← বটকে বাক্সে প্যাক করার নিয়ম
├── docker-compose.yml  ← Docker চালানোর কনফিগ
├── start.sh            ← বট শুরু করার স্ক্রিপ্ট (নির্দেশ তালিকা)
├── update.sh           ← আপডেট নেওয়ার স্ক্রিপ্ট
├── Procfile            ← Heroku-তে চালানোর নির্দেশ
├── app.json            ← Heroku ডিপ্লয় কনফিগ
├── runtime.txt         ← পাইথন কোন ভার্সন লাগবে
│
├── auth/               ← বড়দের (অ্যাডমিন) কমান্ড
├── core/               ← ডাটাবেস ও /start কমান্ড
├── db/                 ← ইউজার ডাটা সেভ করার হেল্পার
├── misc/               ← বাটন ও কিবোর্ড
├── plugins/            ← সব ফিচার (যুটিউব, লিংক ডাউনলোড ইত্যাদি)
├── utils/              ← সাহায্যকারী টুল (লগ, হেল্পার)
└── cookies/            ← ইউটিউব কুকিজ ফাইল
```

**ফোল্ডার মানে কী?** — একসাথে রাখা ফাইলের বাক্স। যেমন তোমার আলমারিতে জামার বাক্স, বইয়ের বাক্স আলাদা।

**`__init__.py` কী?** — প্রতিটা ফোল্ডারে এই ফাইলটা থাকে। এটা পাইথনকে বলে: "এই ফোল্ডারটা একটা প্যাকেজ (package), এর ভিতরের ফাইলগুলো অন্য জায়গা থেকে ডাকা যাবে।"

---

# 🟢 অংশ ৫ — প্রতিটা ফাইল বিস্তারিত ব্যাখ্যা

নিচে প্রতিটা ফাইল কীভাবে কাজ করে, লাইনে লাইনে বোঝানো হলো।

---

## 📄 `main.py` — বট চালু করার মূল দরজা

এটি সবার আগে চলে। যেমন বাড়ির মূল দরজা দিয়ে ঢোকা।
```python
import sys
import asyncio
```
- `import sys` → "sys" সরঞ্জাম আনো (সিস্টেম নিয়ে কাজ)।
- `import asyncio` → "asyncio" সরঞ্জাম আনো (একসাথে অনেক কাজ করার যন্ত্র)।
```python
try:
    import uvloop
    uvloop.install()
    print("✅ uvloop installed — event loop boosted!")
except ImportError:
    print("⚠️ uvloop not available, using default asyncio loop")
```
- `try:` → চেষ্টা করো uvloop আনতে।
- `uvloop` → asyncio-এর একটা দ্রুত সংস্করণ (গাড়ির টার্বোর মতো)।
- `uvloop.install()` → এটা চালু করো।
- `except ImportError:` → যদি uvloop না থাকে (যেমন Windows-এ), তাহলে ভুল দেখিয়ে সাধারণটা ব্যবহার করো।
- মানে: **যদি দ্রুত ইঞ্জিন পাও তবে লাগাও, নাহলে সাধারণটা চলবে।**

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
- এখানে অন্য ফোল্ডার থেকে বিভিন্ন "setup" ফাংশন আনা হয়েছে।
- `setup_..._handler` মানে: "এই কাজটা যদি ঘটে, তবে এই ফাংশনটা চালাও" — এটাকে বলে **Handler** (হ্যান্ডলার = হাত দিয়ে ধরা/সামলানো)।

```python
asyncio.get_event_loop().run_until_complete(init_db())
```
- `asyncio.get_event_loop()` → কাজ চালানোর চাকা (ইভেন্ট লুপ) নাও।
- `run_until_complete(init_db())` → ডাটাবেস রেডি না হওয়া পর্যন্ত অপেক্ষা করো।
- মানে: বট চালুর আগে ডাটাবেস ঠিক করো।

```python
setup_force_sub_handler(app)     # ১. আগে চেক: ইউজার চ্যানেলে আছে?
setup_plugins_handlers(app)      # ২. সব ফিচার (যুটিউব, লিংক ডাউনলোড)
setup_auth_handlers(app)         # ৩. অ্যাডমিন কমান্ড
setup_start_handler(app)         # ৪. /start কমান্ড
setup_button_router(app)         # ৫. নিচের বাটনগুলো (সবশেষে)
```
- **অর্ডার গুরুত্বপূর্ণ:** আগে চেক করতে হবে ইউজার চ্যানেলে জয়েন করেছে কি না। না করলে বাকি কাজ হবে না।

```python
@app.on_callback_query()
async def handle_callback(client, callback_query):
    await handle_callback_query(client, callback_query)

LOGGER.info("Bot Successfully Started! 💥")
app.run()
```
- `@app.on_callback_query()` → যদি ইউজার ইনলাইন বাটনে চাপ দেয়, তবে এই ফাংশন চলবে।
- `LOGGER.info(...)` → লগ ফাইলে লেখো "বট চালু হয়েছে"।
- `app.run()` → বটটা চালু করো (এটাই মূল চাকা ঘোরা শুরু করে)।

---

## 📄 `app.py` — বটের "ফোন" (টেলিগ্রামের সাথে কানেক্ট)

```python
from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN
```
- `pyrogram` → টেলিগ্রামের সাথে কথা বলার একটা সরঞ্জাম (লাইব্রেরি)।
- `Client` → "ক্লায়েন্ট" = ক্লায়েন্ট = যে ফোন দিয়ে টেলিগ্রামে ঢোকে।
- `config` → আমাদের সিক্রেট তথ্যের ফাইল (API_ID, ইত্যাদি)।

```python
app = Client(
    "SmartTools",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=1000,
    max_concurrent_transmissions=5,
)
```
- `Client(...)` → একটা ক্লায়েন্ট তৈরি করো।
- `"SmartTools"` → এই ক্লায়েন্টের নাম (সেশন ফাইল হিসেবে ব্যবহার হয়)।
- `api_id`, `api_hash` → টেলিগ্রাম দেয় (my.telegram.org থেকে)। এটা বটের "পরিচয়পত্র"।
- `bot_token` → @BotFather দেয়। বটের "চাবি"।
- `workers=1000` → একসাথে ১০০০ কাজ হ্যান্ডেল করতে পারবে।
- `max_concurrent_transmissions=5` → একসাথে ৫টা ফাইল আপলোড করতে পারবে।

মানে: **এই ফাইলটা বটকে টেলিগ্রামের সাথে যুক্ত করে দেয় — ঠিক যেমন ফোন দিয়ে নেটওয়ার্কে ঢোকা।**

---

## 📄 `bot.py` — ইউজার সেজে লগইন করার ফোন

```python
from telethon import TelegramClient
import config
from helpers.logger import LOGGER

SmartYTUtil = None
```
- `telethon` → আরেকটা টেলিগ্রাম লাইব্রেরি (এটা ইউজার অ্যাকাউন্টের মতো কাজ করে)।
- `SmartYTUtil = None` → আপাতত ফাঁকা রাখলাম (পরে ভরবো)।

```python
async def init_client():
    global SmartYTUtil
    SmartYTUtil = TelegramClient(
        session='smartytutil',
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        connection_retries=None,
        retry_delay=1,
    )
    return SmartYTUtil
```
- `async def` → একসাথে চলতে পারে এমন ফাংশন।
- `global SmartYTUtil` → "বাইরের ওই ভেরিয়েবলটাই বদলাবো" এমন বলে।
- `TelegramClient(...)` → ইউজারের ফোন তৈরি।
- `connection_retries=None` → কানেক্ট না হলে বারবার চেষ্টা করতে থাকো (শেষ নাই)।
- `retry_delay=1` → ১ সেকেন্ড পর পর চেষ্টা।

**কেন দুইটা ক্লায়েন্ট?** (app.py আর bot.py)
- `app.py` = বট (রোবট)। বট একা প্রাইভেট চ্যানেলের ফাইল পায় না।
- `bot.py` = ইউজারের অ্যাকাউন্ট। ইউজার লগইন করলে, তার অ্যাকাউন্ট দিয়ে প্রাইভেট ফাইল আনা যায়।

```python
async def start_bot():
    global SmartYTUtil
    if SmartYTUtil is None:
        await init_client()
    await SmartYTUtil.start(bot_token=config.BOT_TOKEN)
    return SmartYTUtil

def get_client():
    global SmartYTUtil
    if SmartYTUtil is None:
        raise RuntimeError("Client not initialized")
    return SmartYTUtil
```
- `if SmartYTUtil is None:` → যদি ফাঁকা থাকে, তবে তৈরি করো।
- `await SmartYTUtil.start(...)` → এখন চালু করো।
- `get_client()` → অন্য ফাইল এই ক্লায়েন্ট চাইলে দেয়। যদি না থাকে, তবে `raise RuntimeError` → ভুল বার্তা দেয়।

---

## 📄 `web.py` — বটকে ঘুম থেকে জাগ্রত রাখা

কিছু ফ্রি হোস্টিং (যেমন Render) বটকে ঘুম পাড়িয়ে দেয় যদি কাজ না করে। তাই একটা ওয়েব সার্ভার + নিজেই নিজেকে পিং (ping) করে জাগিয়ে রাখে।

```python
import os
import time
import threading
from flask import Flask, jsonify
```
- `os` → অপারেটিং সিস্টেম নিয়ে কাজ (এনভায়রনমেন্ট ভেরিয়েবল পড়া)।
- `time` → সময় নিয়ে কাজ।
- `threading` → একসাথে একাধিক কাজ (যেমন ২টা লোক একসাথে কাজ করা)।
- `flask` → ছোট ওয়েব সার্ভার বানানোর সরঞ্জাম।

```python
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 8000))
_start_time = time.time()
```
- `Flask(__name__)` → একটা ওয়েব সার্ভার তৈরি।
- `os.environ.get("PORT", 8000)` → এনভায়রনমেন্টে PORT নামের সেটিং আছে কি? থাকলে ওটা নাও, নাহলে ৮০০০ ব্যবহার করো।
- `_start_time` → বট কখন চালু হয়েছে মনে রাখো।

```python
@app.route('/')
def home():
    uptime = int(time.time() - _start_time)
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"Restricted Content DL Bot is Running Successfully! 🚀\n"
        f"Uptime: {hours}h {minutes}m {seconds}s"
    )
```
- `@app.route('/')` → যদি কেউ ওয়েবসাইটের মূল পাতায় আসে (`/`), তবে `home()` চলবে।
- `uptime` → কতক্ষণ চলছে হিসাব করে।
- `divmod(...)` → ভাগ করে ভাগফল ও ভাগশেষ দেয় (যেমন ৩৭০০ সেকেন্ড = ১ ঘন্টা ১ মিনিট ৪০ সেকেন্ড)।
- `return ...` → ওয়েব পাতায় ওই লেখা দেখাবে।

```python
@app.route('/health')
def health():
    return jsonify({"status": "ok", "uptime": ...}), 200
```
- `/health` → "আমি বেঁচে আছি কি?" চেক করার পাতা। `jsonify` → ডাটা ফরম্যাটে পাঠায়। `200` → "ঠিক আছে" মানে।

```python
def _keep_alive():
    import urllib.request
    url = f"http://0.0.0.0:{PORT}/health"
    while True:
        time.sleep(300)
        try:
            urllib.request.urlopen(url, timeout=10)
        except Exception:
            pass
```
- `_keep_alive()` → "জাগিয়ে রাখো"।
- `while True:` → সবসময় চলতে থাকো (কখনো থামো না)।
- `time.sleep(300)` → ৩০০ সেকেন্ড (৫ মিনিট) ঘুমাও।
- `urllib.request.urlopen(url)` → নিজের `/health` পাতাটা নিজেই ওপেন করো (যাতে হোস্টিং ভাবে বট জাগ্রত)।
- `except Exception: pass` → ভুল হলে কিছু করো না, চলতে থাকো।

```python
if __name__ == "__main__":
    t = threading.Thread(target=run, daemon=True)
    t.start()
    ka = threading.Thread(target=_keep_alive, daemon=True)
    ka.start()
    os.system("bash start.sh")
```
- `if __name__ == "__main__":` → যদি এই ফাইলটা সরাসরি চালানো হয় (অন্য কেউ ইম্পোর্ট না করে), তবে এই ব্লক চলবে।
- `threading.Thread(...)` → আলাদা "কর্মী" তৈরি (একজন ওয়েব সার্ভার চালাবে, আরেকজন জাগিয়ে রাখবে)।
- `daemon=True` → মূল প্রোগ্রাম বন্ধ হলে এরাও বন্ধ হবে।
- `os.system("bash start.sh")` → বট চালু করার স্ক্রিপ্ট রান করো।

---

## 📂 `core/` — ডাটাবেস ও /start কমান্ড

### `core/database.py` — ডাটাবেস (তথ্যের বিশাল ভাণ্ডার)

```python
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from utils import LOGGER
from config import MONGO_URL
```
- `datetime` → তারিখ ও সময় নিয়ে কাজ।
- `motor` → MongoDB (ডাটাবেস) এর সাথে কথা বলার অ্যাসিঙ্ক্রোনাস সরঞ্জাম।
- `pymongo` → MongoDB-এর সাধারণ সরঞ্জাম।
- `MONGO_URL` → ডাটাবেসের ঠিকানা (যেমন বাড়ির ঠিকানা)।

**ডাটাবেস কী?** — তথ্য রাখার জায়গা। যেমন স্কুলের হাজিরা খাতা। এখানে ইউজারদের নাম, প্রিমিয়াম স্ট্যাটাস ইত্যাদি রাখে।

```python
_main_client = AsyncIOMotorClient(
    MONGO_URL,
    connectTimeoutMS=10000,
    socketTimeoutMS=10000,
)
_main_db = _main_client["ItsSmartTool"]
```
- `AsyncIOMotorClient(...)` → ডাটাবেসের সাথে কানেক্ট করার "ফোন"।
- `connectTimeoutMS=10000` → ১০ সেকেন্ডের বেশি লাগলে ছেড়ে দাও।
- `_main_db = _main_client["ItsSmartTool"]` → "ItsSmartTool" নামের ডাটাবেসটা ব্যবহার করো।

```python
prem_plan1    = _main_db["prem_plan1"]
prem_plan2    = _main_db["prem_plan2"]
prem_plan3    = _main_db["prem_plan3"]
user_sessions = _main_db["user_sessions"]
premium_users = _main_db["premium_users"]
downloads_collection = _main_db["downloads"]
total_users   = _main_db["total_users"]
referrals     = _main_db["referrals"]
```
- এগুলো **Collection** (কালেকশন = টেবিলের মতো)। যেমন হাজিরা খাতার আলাদা পাতা — এক পাতায় ছাত্র, আরেকটায় শিক্ষক।

```python
async def _create_ttl_index(collection, field="expiry_date"):
    await collection.create_index(
        [(field, ASCENDING)],
        expireAfterSeconds=0,
        name=f"{field}_ttl",
        sparse=True,
    )
```
- `async def` → একসাথে চলতে পারে এমন ফাংশন।
- `_create_ttl_index` → "TTL ইনডেক্স তৈরি"।
- **TTL** = Time To Live = বাঁচার সময়। মানে: প্রিমিয়াম প্ল্যানের মেয়াদ শেষ হলে ডাটাবেস নিজেই ডিলিট করে দেবে। যেমন দুধের এক্সপায়ারি ডেট।
- `expireAfterSeconds=0` → মেয়াদ শেষ হলেই মুছে দাও।
- `sparse=True` → যাদের এই ফিল্ড আছে শুধু তাদেরই ইনডেক্স করো।

```python
async def _cleanup_premium_duplicates():
    now = datetime.utcnow()
    for name, col in plan_map:
        result = await col.delete_many({"expiry_date": {"$lte": now}})
```
- `_cleanup_premium_duplicates` → "প্রিমিয়ামের ডুপ্লিকেট (নকল কপি) পরিষ্কার করো"।
- `datetime.utcnow()` → এই মুহূর্তের সময়।
- `delete_many({"expiry_date": {"$lte": now}})` → যাদের মেয়াদ এখনকার চেয়ে কম/সমান, তাদের সব ডিলিট করো।
- `$lte` → "less than or equal" = কম বা সমান।

```python
async def init_db():
    for col in (prem_plan1, prem_plan2, prem_plan3, premium_users):
        await _create_ttl_index(col, "expiry_date")
    await _create_supporting_indexes()
    await _cleanup_premium_duplicates()
    return True
```
- `init_db()` → "ডাটাবেস ইনিশিয়ালাইজ (প্রস্তুত) করো"।
- এটি বট শুরুর আগে ইনডেক্স বানায় ও পুরানো ডাটা পরিষ্কার করে।

### `core/start.py` — /start কমান্ড

```python
def setup_start_handler(app):
    @app.on_message(filters.command("start"))
    async def start(client, message):
```
- `setup_start_handler(app)` → বটে /start কমান্ড যোগ করো।
- `@app.on_message(filters.command("start"))` → যদি ইউজার `/start` লেখে, তবে `start()` ফাংশন চলবে।
- `filters.command("start")` → শুধু "start" কমান্ড ফিল্টার করো।

```python
        user = message.from_user
        user_fullname = f"{user.first_name} {user.last_name or ''}".strip()
```
- `message.from_user` → যে মেসেজ পাঠিয়েছে (ইউজার)।
- `user.first_name` → ইউজারের নাম।
- `or ''` → যদি শেষ নাম না থাকে, তবে ফাঁকা রাখো (ভুল না দেখায়)।
- `.strip()` → আগে-পিছে ফাঁকা জায়গা কেটে দাও।

```python
        try:
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
```
- `total_users.update_one(...)` → "total_users" কালেকশনে একটা ডকুমেন্ট (তথ্য) আপডেট করো।
- `{"user_id": user.id}` → যার আইডি এটা, তাকে খুঁজে বের করো।
- `"$set": {...}` → এই তথ্যগুলো সেট (রাখো) করো।
- `upsert=True` → যদি না থাকে, তবে নতুন সেভ করো; থাকলে আপডেট করো।

```python
        if len(message.command) > 1:
            referrer_id = int(message.command[1])
            success = await process_referral(client, user.id, referrer_id)
```
- `message.command` → কমান্ড ভাঙা অংশ। যেমন `/start 12345` → `["start", "12345"]`।
- `len(...) > 1` → যদি ১-এর বেশি অংশ থাকে (মানে রেফারেল আইডি আছে)।
- `int(...)` → স্ট্রিংকে সংখ্যায় বদলাও।
- `process_referral(...)` → রেফারেল (কেউ কাউকে ডাকলে বোনাস) প্রসেস করো।

---

## 📂 `utils/` — সাহায্যকারী টুল

### `utils/logging_setup.py` — লগ (রেকর্ড) রাখা

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
- `logging` → প্রোগ্রাম কী কী করছে তা রেকর্ড (লগ) করার সরঞ্জাম।
- `RotatingFileHandler` → ফাইল ভর্তি হলে নতুন ফাইলে যাওয়া (ঘুরে ঘুরে)।
- `maxBytes=50000000` → ৫ কোটি বাইট (৫০ MB) হলে নতুন ফাইল।
- `backupCount=10` → পুরানো ১০টা ফাইল রাখবে।
- `StreamHandler()` → কনসোলেও দেখাবে।
- `LOGGER = logging.getLogger(__name__)` → লগ লেখার জন্য একটা "কলম" তৈরি।

ব্যবহার: `LOGGER.info("বট চালু")` → লগ ফাইলে লেখে।

### `utils/helper.py` — সাধারণ সাহায্যকারী ফাংশন

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
- `SIZE_UNITS` → সাইজের নামের তালিকা (বাইট, কিলোবাইট...)।
- `get_readable_file_size(...)` → ফাইলের সাইজ বুঝতে সহজ ভাষায় দেয়।
- `if size_in_bytes is None` → যদি কিছু না থাকে।
- `for unit in SIZE_UNITS:` → প্রতিটা ইউনিট ধরে ঘুরে।
- `size_in_bytes /= 1024` → ১০২৪ দিয়ে ভাগ দাও (কিলোবাইটে রূপান্তর)।
- `f"{size_in_bytes:.2f} {unit}"` → দশমিক ২ ঘরসহ সংখ্যা + ইউনিট লেখো (যেমন "২.৫০ MB")।

মানে: **বাইট সংখ্যাকে "MB" বা "GB" এ বদলে দেয় যাতে মানুষ বুঝতে পারে।**

### `utils/force_sub.py` — ফোর্স সাবস্ক্রাইব (চ্যানেলে জয়েন বাধ্যতামূলক)

```python
import time
import asyncio
from pyrogram import Client, filters
```
- `filters` → ফিল্টার = ছাঁকনি। কোন মেসেজটা দরকার শুধু সেটা বাছাই করে।

```python
CACHE_TTL = 300
API_TIMEOUT = 5.0
_sub_cache: dict[int, tuple[bool, float]] = {}
```
- `CACHE_TTL = 300` → ক্যাশে ৩০০ সেকেন্ড (৫ মিনিট) থাকবে।
- **Cache** (ক্যাশে) = মনে রাখা। বারবার টেলিগ্রামকে জিজ্ঞাসা না করে, একবার জেনে মনে রাখে।
- `_sub_cache` → সাবস্ক্রাইব স্ট্যাটাস মনে রাখার ডিকশনারি।

```python
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
- `_cache_get(user_id)` → ক্যাশে থেকে ইউজারের স্ট্যাটাস নাও।
- `entry = _sub_cache.get(user_id)` → ডিকশনারি থেকে খোঁজো।
- `is_sub, ts = entry` → টাপল থেকে আলাদা করো (যোগ্য আছে কি + কখন চেক করেছে)।
- `time.monotonic()` → সিস্টেম টাইমার (সময় মাপার ঘড়ি)।
- `.pop(user_id, None)` → ক্যাশে থেকে মুছে দাও।

```python
async def check_force_sub(client, user_id, refresh=False):
    if not API_CHANNEL:
        return True
    if user_id == DEVELOPER_USER_ID:
        return True
    if not refresh:
        cached = _cache_get(user_id)
        if cached is not None:
            return cached

    try:
        member = await asyncio.wait_for(
            client.get_chat_member(API_CHANNEL, user_id),
            timeout=API_TIMEOUT,
        )
        is_sub = member.status not in (ChatMemberStatus.BANNED, ChatMemberStatus.LEFT)
        _cache_set(user_id, is_sub)
        return is_sub
```
- `check_force_sub(...)` → চেক করো ইউজার চ্যানেলে আছে কি না।
- `if not API_CHANNEL: return True` → ফোর্স-সাব বন্ধ থাকলে সবাইকে allow।
- `if user_id == DEVELOPER_USER_ID: return True` → বটের মালিক সবসময় allow।
- `asyncio.wait_for(..., timeout=5.0)` → ৫ সেকেন্ডের বেশি লাগলে টাইমআউট।
- `member.status not in (...)` → স্ট্যাটাস যদি "ব্যানড" বা "লেফট" না হয়, তবে সাবস্ক্রাইব করা।

```python
    except UserNotParticipant:
        _cache_set(user_id, False)
        return False
    except FloodWait as e:
        await asyncio.sleep(min(e.value, 5))
        return True
```
- `except UserNotParticipant:` → যদি ইউজার পার্টিসিপেন্ট না হয় (মানে জয়েন করেনি)।
- `except FloodWait:` → যদি টেলিগ্রাম "অনেক রিকোয়েস্ট পাঠিয়েছো, অপেক্ষা করো" বলে।
- `asyncio.sleep(min(e.value, 5))` → সর্বোচ্চ ৫ সেকেন্ড ঘুমাও।

```python
def setup_force_sub_handler(app):
    if not API_CHANNEL:
        LOGGER.info("Force Subscribe disabled")
        return

    @app.on_message(filters.private & ~filters.service, group=-1)
    async def _msg_interceptor(client, message):
        if not message.from_user:
            return
        user_id = message.from_user.id
        is_sub = await check_force_sub(client, user_id)
        if not is_sub:
            await message.reply_text(NOT_SUBSCRIBED_TEXT, reply_markup=_not_sub_keyboard())
            message.stop_propagation()
```
- `setup_force_sub_handler(app)` → ফোর্স-সাব হ্যান্ডলার যোগ করো।
- `filters.private & ~filters.service` → শুধু প্রাইভেট মেসেজ, সার্ভিস মেসেজ বাদ দিয়ে।
- `group=-1` → এটা আগে চলবে (অন্য হ্যান্ডলারের আগে)।
- `_msg_interceptor` → মেসেজ ধরার লোক।
- `if not is_sub:` → যদি সাবস্ক্রাইব না করা থাকে।
- `message.reply_text(...)` → রিপ্লাই দাও "আগে জয়েন করো"।
- `message.stop_propagation()` → এই মেসেজ আর অন্য কোথাও যাবে না (আটকে দাও)।

---

## 📂 `plugins/` — সব ফিচার (যুটিউব, লিংক ডাউনলোড)

এখানে অনেক ফাইল: `yt.py` (যুটিউব), `autolink.py` (টেলিগ্রাম লিংক), `settings.py` (সেটিংস), `plan.py` (প্রিমিয়াম), ইত্যাদি।

### `plugins/__init__.py` — সব ফিচার রেজিস্টার করা

```python
from .plan import setup_plan_handler
from .info import setup_info_handler
from .thumb import setup_thumb_handler
from .login import setup_login_handler
...
def setup_plugins_handlers(app):
    setup_plan_handler(app)
    setup_info_handler(app)
    setup_thumb_handler(app)
    ...
```
- `from .plan import setup_plan_handler` → এই ফোল্ডারের `plan.py` থেকে ফাংশন আনো।
- `setup_plugins_handlers(app)` → সব ফিচার বটে যোগ করো।

### `plugins/yt.py` — যুটিউব ডাউনলোডার (উদাহরণ)

```python
pending_downloads: dict = {}
SPLIT_PROMPT_TEXT = (
    "**Bro File Size Exceeds 2 GB Limit❌**\n"
    "Do You Want Spilted Downloader⬇️?"
)
```
- `pending_downloads: dict = {}` → চলমান ডাউনলোডগুলো মনে রাখার ডিকশনারি।
- `SPLIT_PROMPT_TEXT` → ফাইল ২ GB-এর বেশি হলে ভাগ করার (split) প্রশ্ন।

```python
@Client.on_message(filters.command(["yt", "video", "mp4", "dl"], prefixes=["/", "!", "."]))
async def yt_video_command(client, message):
    query = message.text.split(None, 1)[1].strip() if len(...) > 1 else ""
```
- `@Client.on_message(...)` → ডেকোরেটর = উপরে লেখা নিয়ম। যদি `yt`/`video`/`mp4`/`dl` কমান্ড আসে, তবে এই ফাংশন চলবে।
- `prefixes=["/", "!", "."]` → কমান্ড আগে `/`, `!`, বা `.` যেকোনোটা থাকতে পারে।
- `message.text.split(None, 1)` → মেসেজকে স্পেস দিয়ে ২ ভাগ করো (কমান্ড + সার্চ কোয়েরি)।
- `[1]` → দ্বিতীয় অংশটা নাও (সার্চ কোয়েরি)।
- `.strip()` → আগে-পিছে ফাঁকা জায়গা কেটে দাও।

```python
async def handle_yt_command(client, message, query):
    status = await message.reply_text("🔍 Searching YouTube...")
    video_url = youtube_parser(query)
    if not video_url:
        video_url = await search_youtube_url(query)
```
- `await message.reply_text(...)` → "খুঁজছি..." রিপ্লাই দাও (এবং ওই মেসেজটা `status` এ রাখো)।
- `youtube_parser(query)` → কোয়েরি থেকে যুটিউব লিংক বের করো।
- `if not video_url:` → লিংক না পেলে, সার্চ করো।

```python
token = generate_token(message.from_user.id)
pending_downloads[token] = {
    "url": video_url,
    "user_id": message.from_user.id,
    "chat_id": chat_id,
    "msg_id": status.id,
}
```
- `generate_token(...)` → ইউনিক (অনন্য) আইডি বানাও।
- `pending_downloads[token] = {...}` → এই ডাউনলোডের তথ্য টোকেন দিয়ে মনে রাখো।

```python
@Client.on_callback_query(filters.regex(r"^YV\|"))
async def yt_video_cb(client, callback_query):
    raw = callback_query.data
    parts = raw.split("|")
    token = parts[1]
    quality_key = parts[2]
```
- `@Client.on_callback_query(...)` → যদি ইউজার ইনলাইন বাটনে চাপ দেয়।
- `filters.regex(r"^YV\|")` → ডাটা "YV|" দিয়ে শুরু হলে মিলবে।
- `callback_query.data` → বাটনে লেখা ডাটা (যেমন "YV|abc123|720p")।
- `raw.split("|")` → পাইপ দিয়ে ভাঙো → `["YV", "abc123", "720p"]`।

```python
asyncio.create_task(do_video_download(client, token, quality_key))
```
- `asyncio.create_task(...)` → ব্যাকগ্রাউন্ডে (পেছনে) ডাউনলোড শুরু করো, অপেক্ষা না করে।

```python
async def do_video_download(client, token, quality_key):
    data = pending_downloads.get(token)
    if not data:
        return
    url = data["url"]
    ...
    file_path = find_downloaded_file(temp_dir, [".mp4", ".mkv", ".webm"])
    if not file_path:
        return
    await client.send_video(chat_id, video=file_path, caption=caption, ...)
```
- `data = pending_downloads.get(token)` → টোকেন দিয়ে ডাউনলোডের তথ্য নাও।
- `find_downloaded_file(...)` → ডাউনলোড হওয়া ফাইলটা খুঁজে বের করো।
- `client.send_video(...)` → ইউজারকে ভিডিও পাঠিয়ে দাও।

**সহজ কথায় yt.py:** ইউজার `/yt গানের নাম` লেখে → বট যুটিউব থেকে ডাউনলোড করে → ভিডিও পাঠিয়ে দেয়।

### `plugins/autolink.py` — টেলিগ্রাম লিংক অটো ডিটেক্ট

```python
TELEGRAM_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:c/)?([a-zA-Z0-9_]+|\d+)/(\d+)(?:/\d+)?"
)
```
- `re.compile(...)` → রেজেক্স (regex) = প্যাটার্ন ম্যাচ করার নিয়ম।
- এটি টেলিগ্রাম লিংকের আকৃতি চিনে (যেমন `t.me/channel/123`)।
- `re` → রেগুলার এক্সপ্রেশন মডিউল।

```python
COOLDOWN_SECONDS = 300
async def check_and_set_cooldown(user_id):
    record = await daily_limit.find_one({"user_id": user_id})
    if record:
        last_dl = record.get("last_download")
        elapsed = (now - last_dl).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            return int(COOLDOWN_SECONDS - elapsed)
```
- `COOLDOWN_SECONDS = 300` → ফ্রি ইউজার ৫ মিনিট অপেক্ষা করবে (কুলডাউন)।
- `daily_limit.find_one(...)` → ডাটাবেস থেকে ইউজারের রেকর্ড খোঁজো।
- `elapsed` → কত সেকেন্ড আগে ডাউনলোড করেছে হিসাব।
- `if elapsed < COOLDOWN_SECONDS:` → যদি ৫ মিনিট না পার হয়ে থাকে, তবে অপেক্ষা করতে বলো।

---

## 📂 `auth/` — বড়দের (অ্যাডমিন) কমান্ড
```python
from .logs.logs import setup_logs_handler
from .restart.restart import setup_restart_handler
from .speedtest.speedtest import setup_speed_handler
...
def setup_auth_handlers(app):
    setup_sudo_handler(app)
    setup_restart_handler(app)
    setup_speed_handler(app)
    ...
```
- `auth/` মানে authorization = অনুমোদন। এখানে শুধু বটের মালিক/অ্যাডমিন চালাতে পারবে এমন কমান্ড।
- `setup_restart_handler` → বট রিস্টার্ট করার কমান্ড।
- `setup_speed_handler` → সার্ভার স্পিড টেস্ট।
- `setup_logs_handler` → লগ দেখা।

ভিতরের ফাইল: `admin/`, `restart/`, `speedtest/`, `sudo/`, `set/`, `migrate/`, `fix/`, `logs/` — প্রতিটা আলাদা কমান্ডের ফোল্ডার।

---

## 📂 `misc/` — বাটন ও কিবোর্ড

### `misc/keyboards.py` — বাটন তৈরি

```python
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

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
- `InlineKeyboardMarkup` → মেসেজের সাথে থাকা বাটন (ক্লিক করলে ডাটা পাঠায়)।
- `ReplyKeyboardMarkup` → চ্যাটের নিচে সবসময় থাকা বাটন।
- `KeyboardButton("📦 Batch Download")` → "Batch Download" লেখা বাটন।
- `resize_keyboard=True` → বাটনগুলো ছোট করে দেখাও।

```python
BUTTON_COMMAND_MAP = {
    "❓ Help": "help",
    "🏡 Home": "start",
    "📦 Batch Download": "autobatch",
    ...
}
```
- এটি বাটনের লেখা → কমান্ড ম্যাপ করে (যোগ করে)। যেমন "📦 Batch Download" বাটন চাপলে `autobatch` কমান্ড চলবে।

### `misc/button_router.py` — বাটনে চাপ দিলে কী হবে

```python
def setup_button_router(app):
    _button_labels = set(BUTTON_COMMAND_MAP.keys())

    @app.on_message(
        filters.text & (filters.private | filters.group),
        group=99,
    )
    async def button_router(client, message):
        label = message.text.strip()
        command = BUTTON_COMMAND_MAP.get(label)
        if not command:
            return
        if command == "autobatch":
            await handle_batch_start(client, message)
```
- `setup_button_router(app)` → বাটন রাউটার যোগ করো।
- `_button_labels = set(...)` → সব বাটনের নাম একসাথে রাখো।
- `group=99` → এটা সবশেষে চেক করবে (যাতে আসল কমান্ড আগে প্রাধান্য পায়)।
- `button_router(...)` → ইউজার নিচের বাটনে চাপ দিলে এটা চলবে।
- `command = BUTTON_COMMAND_MAP.get(label)` → বাটনের নাম → কমান্ড বদলাও।
- `if command == "autobatch":` → যদি ব্যাচ ডাউনলোড হয়, তবে সেই ফাংশন চালাও।

### `misc/callback.py` — ইনলাইন বাটনের কাজ

ইউজার ইনলাইন বাটনে চাপ দিলে `handle_callback_query` চলে। এটি বাটনের `callback_data` দেখে বুঝে কী করতে হবে (যেমন সেটিংস ওপেন করা, প্ল্যান কেনা)।

---

## 📂 `db/` — ইউজার ডাটা সেভ

### `db/users.py`

```python
from datetime import datetime, timezone
from utils import LOGGER
from core.database import total_users

async def upsert_user(user) -> dict:
    now = datetime.now(timezone.utc)
    full_name = " ".join(
        part for part in (user.first_name or "", user.last_name or "") if part
    ).strip() or "Unknown"

    doc = {
        "user_id": user.id,
        "username": user.username or None,
        "first_name": user.first_name or "",
        "is_premium": bool(getattr(user, "is_premium", False)),
        "last_active": now,
    }

    await total_users.update_one(
        {"user_id": user.id},
        {"$set": doc},
        upsert=True,
    )
    return doc
```
- `upsert_user(user)` → ইউজারের তথ্য ডাটাবেসে সেভ/আপডেট করো।
- `datetime.now(timezone.utc)` → বর্তমান UTC সময়।
- `" ".join(...)` → নামের অংশগুলো জোড়া দাও।
- `bool(getattr(user, "is_premium", False))` → ইউজার প্রিমিয়াম কি না চেক করো (না থাকলে False)।
- `doc = {...}` → ডাটাবেসে রাখার তথ্যের ডিকশনারি।
- `return doc` → যা লেখা হয়েছে তা ফেরত দাও।

---

## 📂 `cookies/` — যুটিউব কুকিজ

```
cookies/ytcookies.txt
```
- কুকিজ (cookies) = ওয়েবসাইটে লগইন তথ্য মনে রাখার ফাইল। যুটিউব ডাউনলোড করতে কখনো লাগে।

---

# 🟡 অংশ ৬ — অ্যাডভান্সড বিষয় (একটু বড়দের জন্য)

এগুলো একটু কঠিন, ধীরে ধীরে বুঝবে।

## ১. Decorator (`@app.on_message`)
ফাংশনের উপরে লেখা `@...` কে বলে ডেকোরেটর। এটা ফাংশনের আচরণ বদলে দেয়। এখানে এটা বলে: "এই কমান্ড এলে এই ফাংশন চালাও"।

## ২. Async/Await + Event Loop
`asyncio` = ইভেন্ট লুপ (চাকা)। `async def` ফাংশনগুলো একসাথে চলতে পারে, তাই হাজার হাজার ইউজার হ্যান্ডেল করা যায়।

## ৩. uvloop
আমাদের asyncio-এর দ্রুত সংস্করণ (C দিয়ে বানানো)। গাড়ির টার্বোর মতো।

## ৪. Motor (Async MongoDB)
ডাটাবেসে `await` দিয়ে কথা বলে। সিনক্রোনাস না, অ্যাসিঙ্ক্রোনাস।

## ৫. Threading
`web.py`-এ একাধিক কাজ একসাথে (ওয়েব সার্ভার + কিপ-অ্যালাইভ + বট)।

## ৬. Executor (`run_in_executor`)
ভারী কাজ (যেমন ffmpeg ভিডিও কাটা) মেইন লুপ ব্লক না করে আলাদা থ্রেডে চালায়।

## ৭. Cache (TTL)
বারবার API কল এড়াতে মেমোরিতে ডাটা মনে রাখে (force_sub.py)।

## ৮. Regex (`filters.regex`)
প্যাটার্ন ম্যাচিং — কলব্যাক ডাটা পার্স করতে।

## ৯. Package Structure (`__init__.py`)
কোডকে ছোট ছোট প্যাকেজে ভাগ করে রি-ইউজ করা।

## ১০. Environment Variables
পাসওয়ার্ড/টোকেন কোডের ভিতরে না লিখে এনভায়রনমেন্ট ভেরিয়েবলে রাখা সিকিউর পদ্ধতি।

## ১১. Dict-based State
`pending_downloads[token]` → ইউজারের চলমান ডাউনলোড ট্র্যাক করতে।

## ১২. Circular Import এড়ানো
```python
# ফাংশনের ভিতরে import করলে circular import এড়ানো যায়
from plugins.referral import process_referral
```
সাধারণত ফাইলের ওপরে import করি, কিন্তু কখনো কখনো ফাংশনের ভিতরে import করতে হয় যাতে দুই ফাইল একে অপরকে ঘুরে ঘুরে না ডাকে।

---

# 🟡 অংশ ৭ — তোমার প্র্যাকটিস (নিজে চর্চা)

নিচের গুলো নিজে করে দেখো:

**ধাপ ১:** পাইথন ইনস্টল করো (python.org থেকে)।
```bash
python3 --version   # চেক করো পাইথন আছে কি
```

**ধাপ ২:** প্রথম প্রোগ্রাম লেখো (`hello.py`):
```python
print("হ্যালো পাইথন!")
```

**ধাপ ৩:** ভেরিয়েবল চর্চা:
```python
name = "সুমন"
age = 20
print(f"আমার নাম {name}, বয়স {age}")
```

**ধাপ ৪:** `if` চর্চা:
```python
if age >= 18:
    print("বড়")
else:
    print("ছোট")
```

**ধাপ ৫:** `for` লুপ চর্চা:
```python
for i in range(3):
    print("হ্যালো", i)
```

**ধাপ ৬:** ডিকশনারি চর্চা:
```python
user = {"name": "সুমন", "age": 20}
print(user["name"])
```

**ধাপ ৭:** এই প্রজেক্টটা গভীরভাবে পড়ো — `main.py` দিয়ে শুরু করো, ধীরে ধীরে বাকি ফাইল।

---

## 📝 শেষ কথা

এই প্রজেক্টটা বড় মনে হতে পারে, কিন্তু এর মূল লজিক খুব সিম্পল:

> **মেসেজ আসে → হ্যান্ডলার চেক করে → কাজ করে → রিপ্লাই দেয়।**

একটা একটা ফাইল পড়তে থাকো। বুঝতে না পারলে ওই ফাইলটা আবার পড়ো। ধীরে ধীরে সব বুঝে যাবে। 🚀

**মনে রাখো:** প্রোগ্রামিং শেখা = সাঁতার শেখার মতো। জলে নামলে না, ততক্ষণ না শেখা যায়। তুমি এখন জলে নেমে গেছো! 💪

---

*এই নোটটি তৈরি করেছে: তোমার পাইথন শেখার সাথী* 🙏
