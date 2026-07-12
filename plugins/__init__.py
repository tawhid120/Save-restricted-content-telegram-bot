# Copyright @juktijol
# Channel t.me/juktijol

from .plan import setup_plan_handler
from .info import setup_info_handler
from .thumb import setup_thumb_handler
from .login import setup_login_handler
from .pbatch import setup_pbatch_handler
from .ytupload import setup_ytupload_handler
from .refresh import setup_refresh_handler
from .settings import setup_settings_handler
from .autolink import setup_autolink_handler
from .cleaner import setup_cleaner_handler
from .referral import setup_referral_handler
  # ← bug fix: handle → handler


def setup_plugins_handlers(app):
    setup_plan_handler(app)
    setup_info_handler(app)
    setup_thumb_handler(app)
    setup_login_handler(app)
    setup_pbatch_handler(app)
    setup_ytupload_handler(app)
    setup_refresh_handler(app)
    setup_settings_handler(app)
    setup_autolink_handler(app)   # group=1 — Telegram লিংক handle করে
    setup_cleaner_handler(app)
    setup_referral_handler(app)
    
