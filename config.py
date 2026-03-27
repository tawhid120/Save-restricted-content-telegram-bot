# Copyright @juktijol
# Channel t.me/juktijol

import os
from dotenv import load_dotenv

load_dotenv()

def get_env_or_default(key, default=None, cast_func=str):
    value = os.getenv(key)
    if value is not None and value.strip():
        try:
            return cast_func(value)
        except (ValueError, TypeError) as e:
            print(f"Error casting {key} with value '{value}' to {cast_func.name}: {e}")
            return default
    return default

# --- সরাসরি আপনার তথ্যগুলো এখানে বসিয়ে দেওয়া হলো ---

# Telegram API Configuration
API_ID   = get_env_or_default("API_ID",   "20193909")
API_HASH = get_env_or_default("API_HASH", "82cd035fc1eb439bda68b2bfc75a57cb")
BOT_TOKEN = get_env_or_default("BOT_TOKEN", "8435187351:AAErEsyB_BZsIDBZiVboDUHWiZjW_ZKLffQ")

# Admin Configuration
DEVELOPER_USER_ID = get_env_or_default("DEVELOPER_USER_ID", 7214443852, int)

# Force Subscribe Configuration
# ইউজারকে অবশ্যই এই চ্যানেলে জয়েন থাকতে হবে বট ব্যবহার করার জন্য।
# এখানে চ্যানেলের ইউজারনেম দিতে হয় (যেমন: juktijol)
FORCE_SUB_CHANNEL = get_env_or_default("FORCE_SUB_CHANNEL", "juktijol")

# Tracking / Logging
LOG_GROUP_ID = get_env_or_default("LOG_GROUP_ID", -1003745195255, int)

# Database Configuration
MONGO_URL    = get_env_or_default("MONGO_URL", "mongodb+srv://bot_user:bot_user@cluster0tawhid.9vribpz.mongodb.net/?appName=Cluster0tawhid")
DATABASE_URL = get_env_or_default("DATABASE_URL", MONGO_URL)
DB_URL       = get_env_or_default("DB_URL", MONGO_URL)

# Command Prefixes
raw_prefixes  = get_env_or_default("COMMAND_PREFIX", "!|.|/")
COMMAND_PREFIX = [prefix.strip() for prefix in raw_prefixes.split("|") if prefix.strip()]


# Validate Required Variables
required_vars = {
    "API_ID":              API_ID,
    "API_HASH":            API_HASH,
    "BOT_TOKEN":           BOT_TOKEN,
    "DEVELOPER_USER_ID":   DEVELOPER_USER_ID,
    "MONGO_URL":           MONGO_URL,
}

for var_name, var_value in required_vars.items():
    if var_value is None or var_value == f"Your_{var_name}_Here" or (isinstance(var_value, str) and not var_value.strip()):
        raise ValueError(f"Required variable {var_name} is missing or invalid.")

print(f"Loaded COMMAND_PREFIX: {COMMAND_PREFIX}")
if FORCE_SUB_CHANNEL:
    print(f"📢 Force Subscribe enabled for: @{FORCE_SUB_CHANNEL}")

if LOG_GROUP_ID:
    print(f"✅ User tracking enabled — LOG_GROUP_ID: {LOG_GROUP_ID}")
else:
    print("⚠️  LOG_GROUP_ID not set — file logging to group disabled.")

if not COMMAND_PREFIX:
    raise ValueError("No command prefixes found.")
