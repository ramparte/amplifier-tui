# Re-export shim — real module lives in amplifier_tui.core.features.context_profiler
from amplifier_tui.core.features.context_profiler import *  # noqa: F401,F403
from amplifier_tui.core.features.context_profiler import (  # noqa: F401
    _classify_role,
    _fmt_tokens,
    _make_sparkline,
)
