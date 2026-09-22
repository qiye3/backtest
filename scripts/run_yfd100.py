"""兼容旧命令，仅运行 yfd100 指数增强策略。"""

from __future__ import annotations

import sys

from run_strategy_backtests import main

if __name__ == "__main__":
    if "--suite" not in sys.argv:
        sys.argv.extend(["--suite", "yfd100"])
    main()
