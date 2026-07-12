# Copyright @juktijol
# Channel t.me/juktijol

"""
Server Cache / Junk File Cleaner
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Owner/Admin-only command to clear stale downloaded files and
temporary junk from the bot's working directories.

Commands:
  /clean   — Remove leftover files in DOWNLOAD_DIR (and any extra
              temp dirs configured) and report how much space
              and how many files were freed.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import shutil
import tempfile

from pyrogram import filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from pyrogram.handlers import MessageHandler

from config import COMMAND_PREFIX, DEVELOPER_USER_ID
from utils.logging_setup import LOGGER
from utils.helper import get_readable_file_size

try:
    # Reuse the same download directory the rest of the bot uses,
    # so /clean actually targets where junk accumulates.
    from plugins.ytdl import DOWNLOAD_DIR
except Exception:
    DOWNLOAD_DIR = "downloads"

# Extra folders to sweep besides DOWNLOAD_DIR. tempfile.gettempdir()
# catches stray files any library may have dropped in system temp.
EXTRA_CLEAN_DIRS = [
    DOWNLOAD_DIR,
]

# Owner IDs allowed to run /clean. Supports either a single int or a
# list/tuple of ints in config, so this plugin doesn't break either way.
if isinstance(DEVELOPER_USER_ID, (list, tuple, set)):
    OWNER_IDS = set(DEVELOPER_USER_ID)
else:
    OWNER_IDS = {DEVELOPER_USER_ID}


def _clean_directory(path: str) -> tuple:
    """
    Recursively removes every file and empty subfolder inside `path`,
    but keeps `path` itself intact (so the bot can keep using it).
    Returns (files_removed, bytes_freed, errors).
    """
    files_removed = 0
    bytes_freed   = 0
    errors        = 0

    if not path or not os.path.isdir(path):
        return files_removed, bytes_freed, errors

    # Walk bottom-up so empty directories can be removed after
    # their files are gone.
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            file_path = os.path.join(root, name)
            try:
                size = os.path.getsize(file_path)
                os.remove(file_path)
                files_removed += 1
                bytes_freed   += size
            except Exception as e:
                errors += 1
                LOGGER.warning(f"[cleaner] Could not delete file {file_path}: {e}")

        for name in dirs:
            dir_path = os.path.join(root, name)
            try:
                # Only removes if empty; non-empty dirs are left alone
                # in case something is still writing to them.
                os.rmdir(dir_path)
            except OSError:
                pass
            except Exception as e:
                errors += 1
                LOGGER.warning(f"[cleaner] Could not delete folder {dir_path}: {e}")

    return files_removed, bytes_freed, errors


def setup_cleaner_handler(app):

    async def clean_command(client, message: Message):
        user_id = message.from_user.id if message.from_user else None

        if user_id not in OWNER_IDS:
            await message.reply_text(
                "❌ **Access Denied!**\n\nOnly the bot owner/admin can use this command.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        status_msg = await message.reply_text(
            "🧹 Cleaning server cache...",
            parse_mode=ParseMode.MARKDOWN,
        )

        total_files  = 0
        total_bytes  = 0
        total_errors = 0

        # Sweep configured directories (e.g. downloads/).
        for directory in EXTRA_CLEAN_DIRS:
            try:
                files, size, errs = _clean_directory(directory)
                total_files  += files
                total_bytes  += size
                total_errors += errs
            except Exception as e:
                total_errors += 1
                LOGGER.error(f"[cleaner] Error cleaning {directory}: {e}")

        # Also sweep any bot-created temp files in the system temp dir,
        # limited to ones this bot is likely to have made, so we don't
        # touch unrelated system temp files.
        try:
            tmp_dir = tempfile.gettempdir()
            for entry in os.listdir(tmp_dir):
                if entry.startswith(("ytup_", "tgup_", "tmp_bot_")):
                    entry_path = os.path.join(tmp_dir, entry)
                    try:
                        if os.path.isfile(entry_path):
                            size = os.path.getsize(entry_path)
                            os.remove(entry_path)
                            total_files += 1
                            total_bytes += size
                        elif os.path.isdir(entry_path):
                            # shutil.rmtree used here for whole leftover
                            # session folders (e.g. ytup_<id>, tgup_<id>).
                            size = sum(
                                os.path.getsize(os.path.join(r, f))
                                for r, _, fs in os.walk(entry_path)
                                for f in fs
                            )
                            shutil.rmtree(entry_path, ignore_errors=True)
                            total_files += 1
                            total_bytes += size
                    except Exception as e:
                        total_errors += 1
                        LOGGER.warning(f"[cleaner] Could not delete temp entry {entry_path}: {e}")
        except Exception as e:
            total_errors += 1
            LOGGER.error(f"[cleaner] Error scanning temp dir: {e}")

        result_text = (
            "✅ **Server cleaned successfully!**\n\n"
            f"🗑 **Files removed:** `{total_files}`\n"
            f"💾 **Space freed:** `{get_readable_file_size(total_bytes)}`\n"
        )
        if total_errors:
            result_text += f"⚠️ **Skipped (in use/locked):** `{total_errors}`\n"

        try:
            await status_msg.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            LOGGER.error(f"[cleaner] Could not edit status message: {e}")

        LOGGER.info(
            f"[cleaner] /clean run by {user_id}: "
            f"{total_files} files, {get_readable_file_size(total_bytes)} freed, "
            f"{total_errors} errors"
        )

    app.add_handler(
        MessageHandler(
            clean_command,
            filters.command(["clean", "clear"], COMMAND_PREFIX) & (filters.private | filters.group),
        ),
        group=2,
    )

    LOGGER.info("[cleaner] Handler registered ✅")
