# Re-export shim — real module lives in amplifier_tui.core.constants
from amplifier_tui.core.constants import *  # noqa: F401,F403

# import * skips underscore names — re-export them explicitly
from amplifier_tui.core.constants import (  # noqa: F401
    _DANGEROUS_PATTERNS,
    _MAX_LABEL_LEN,
    _MAX_RUN_OUTPUT_LINES,
    _RUN_TIMEOUT,
)
