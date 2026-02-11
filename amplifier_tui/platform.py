# Re-export shim — real module lives in amplifier_tui.core.platform_info
# (renamed to platform_info to avoid shadowing the stdlib platform module)
from amplifier_tui.core.platform_info import *  # noqa: F401,F403
