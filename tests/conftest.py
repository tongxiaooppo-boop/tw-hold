"""讓 `import factors` / `import screener` / `import reference` 在測試裡可用，
不需要安裝套件。repo 根目錄放進 sys.path，對一次就好。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
