"""构建时固定转换方法、系统库与字体身份；不包含任何业务凭据。"""

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent
paths = [
    *root.glob("*.py"),
    *Path("/usr/share/fonts").rglob("*.ttf"),
    *Path("/usr/share/fonts").rglob("*.ttc"),
]
files = {
    str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)
}
profile = {
    "contract": "word-renderer-1",
    "python": platform.python_version(),
    "architecture": platform.machine(),
    "pdfium": importlib.metadata.version("pypdfium2"),
    "landlock_min_abi": 6,
    "packages": subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Package}=${Version}\n"], text=True
    ),
    "files": files,
    "options": {
        "timeout_seconds": 45,
        "max_pdf_bytes": 52428800,
        "network": "none",
        "macro_security": 3,
    },
}
profile["fingerprint"] = hashlib.sha256(
    json.dumps(profile, ensure_ascii=False, sort_keys=True).encode()
).hexdigest()
(root / "renderer-manifest.json").write_text(
    json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
