# Copyright @juktijol
# Channel t.me/juktijol
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

# ══════════════════════════════════════════════════
# MAIN REPLY KEYBOARD — Always visible at the bottom
# Order: Batch, Login, Logout first — then the rest
# ══════════════════════════════════════════════════

def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("📦 Batch Download"), KeyboardButton("🔑 Login")],
            [KeyboardButton("🚪 Logout"),         KeyboardButton("❓ Help")],
            [KeyboardButton("👑 Plans & Buy"),    KeyboardButton("🧾 My Profile")],
            [KeyboardButton("🖼 Set Thumbnail"),  KeyboardButton("👀 View Thumbnail")],
            [KeyboardButton("♻️ Remove Thumbnail"), KeyboardButton("⚙️ Settings")],
            [KeyboardButton("💫 Transfer"),       KeyboardButton("🎁 Referral")],
            [KeyboardButton("🏡 Home")],
        ],
        resize_keyboard=True,
    )


BUTTON_COMMAND_MAP: dict[str, str] = {
    "❓ Help":                "help",
    "🏡 Home":                "start",
    "📦 Batch Download":      "autobatch",
    "👑 Plans & Buy":         "plans",
    "🧾 My Profile":          "profile_info",
    "🖼 Set Thumbnail":       "setthumb",
    "👀 View Thumbnail":      "getthumb",
    "♻️ Remove Thumbnail":    "rmthumb",
    "🔑 Login":               "login",
    "🚪 Logout":              "logout",
    "⚙️ Settings":            "settings",
    "💫 Transfer":            "transfer",
    "🎁 Referral":            "referral",
}


def get_start_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Batch Download", callback_data="menu_autobatch"),
        ],
        [
            InlineKeyboardButton("🔑 Login",  callback_data="menu_login"),
            InlineKeyboardButton("🚪 Logout", callback_data="action_logout"),
        ],
        [
            InlineKeyboardButton("👑 Plans & Buy", callback_data="menu_plans"),
            InlineKeyboardButton("🧾 My Profile",  callback_data="menu_profile"),
        ],
        [
            InlineKeyboardButton("🖼 Thumbnail", callback_data="menu_thumb"),
            InlineKeyboardButton("⚙️ Settings",  callback_data="menu_settings"),
        ],
        [
            InlineKeyboardButton("💫 Transfer", callback_data="menu_transfer"),
            InlineKeyboardButton("🎁 Referral", callback_data="menu_referral"),
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
        ],
    ])


def get_thumb_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖼 Set Thumbnail",     callback_data="guide_setthumb"),
            InlineKeyboardButton("👀 View Thumbnail",    callback_data="action_getthumb"),
        ],
        [
            InlineKeyboardButton("♻️ Remove Thumbnail", callback_data="action_rmthumb"),
        ],
        [InlineKeyboardButton("🏡 Home", callback_data="menu_home")],
    ])


def get_login_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 Login",  callback_data="action_login"),
            InlineKeyboardButton("🚪 Logout", callback_data="action_logout"),
        ],
        [InlineKeyboardButton("🏡 Home", callback_data="menu_home")],
    ])


def back_to_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏡 Home", callback_data="menu_home")],
    ])


def get_download_menu() -> InlineKeyboardMarkup:
    return get_start_inline()

def back_to_download() -> InlineKeyboardMarkup:
    return back_to_home()
