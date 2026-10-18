"""固定转换入口：限制资源及文件可见范围后 exec LibreOffice。"""

import os
import resource
import sys
from pathlib import Path

from landlock import restrict

job = Path(sys.argv[1]).resolve()
if job.parent != Path("/work") or not job.name.startswith("word-") or job.is_symlink():
    raise ValueError("invalid_job_directory")
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
resource.setrlimit(resource.RLIMIT_FSIZE, (52428800, 52428800))
resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
environment = {
    "HOME": str(job),
    "TMPDIR": str(job),
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "SAL_USE_VCLPLUGIN": "svp",
    "OMP_NUM_THREADS": "1",
    "OSL_SOCKET_PATH": str(job),
}
argv = [
    "/usr/lib/libreoffice/program/soffice.bin",
    f"-env:UserInstallation={(job / 'profile').as_uri()}",
    "--headless",
    "--nologo",
    "--nodefault",
    "--norestore",
    "--convert-to",
    "pdf:writer_pdf_Export",
    "--outdir",
    str(job / "out"),
    str(job / "source.docx"),
]
restrict(job)
os.execve(argv[0], argv, environment)
