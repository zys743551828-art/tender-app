# Linux dependency lock scope

The legacy backend/MLflow locks below target **CPython 3.11, Linux amd64, glibc**. They contain one
SHA256-verified wheel per resolved package. They are not cross-platform locks.
Resolution was performed on 2026-10-30 using Python 3.11.18 in the official
`python:3.11.18-slim-bookworm` Linux amd64 manifest (exact official tag verified):
`sha256:061c190f3d5815b341a18dfe8a45771f8ba68c15a607ea56997fde3009ac4eec`.
Package metadata came from `https://pypi.org/simple`; wheel archives came from
`https://files.pythonhosted.org/`.

| Lock | Scope and selection |
| --- | --- |
| `backend/requirements-runtime.lock.txt` | `[project].dependencies` plus `parsing` and `retrieval`, matching the existing Dockerfile's wheel extras. Includes `uvicorn[standard]` and `psycopg[binary,pool]`. Existing feedback versions constrain the base packages; the four exact optional dependency versions remain unchanged. Complete closure: 74 packages. |
| `backend/requirements-build.lock.txt` | `[build-system].requires` and its complete dependency closure, resolved independently. |
| `deploy/mlflow/requirements.lock.txt` | `mlflow[db]==3.17.0` from the existing Dockerfile and `boto3==1.43.114` from the existing backend feedback version. Its remaining closure is resolved independently. |

`backend/Dockerfile` now installs the 6-package build lock into a separate
build virtual environment, builds the application wheel with `--no-index
--no-deps --no-build-isolation`, and installs the 74-package runtime lock with
`--require-hashes`. It then installs only that locally built project wheel with
`--no-index --no-deps`; `parsing` and `retrieval` dependencies are already in the
runtime lock. Build tools are not copied into the runtime image. There is no
uncontrolled pip upgrade or isolated build-tool download.

`deploy/mlflow/Dockerfile` installs the 96-package lock with `--require-hashes`
and runs `pip check`. Its existing `MLFLOW_VERSION` argument must match the
installed locked version; changing the argument alone cannot change or bypass
the lock. Regenerate and verify the lock when upgrading MLflow.

Both Dockerfiles and the current Compose defaults use
`python:3.11.18-slim-bookworm@sha256:061c190f3d5815b341a18dfe8a45771f8ba68c15a607ea56997fde3009ac4eec`.
This is an **amd64 platform manifest**, not a multiarchitecture index. No arm64
support is claimed by these locks. `PYTHON_IMAGE` remains overridable by callers,
including through Compose; callers who override it are responsible for image,
Python and platform compatibility and repeating validation. The compatibility
`PIP_INDEX_URL` build argument is retained but does not override the lock's
explicit index URL. A mirror change requires an intentional lock source edit
and verification against the same hashes.

The runtime lock does not include the backend `dev` extra. The existing
feedback file describes Python 3.12 feedback checks and
is not itself the new Python 3.11 deployment lock. The MLflow lock is a
candidate dependency environment; successful installation is not a database
migration test or a live tracking-server acceptance test.

The original optional pins are preserved: `onnxruntime==1.31.0`,
`tokenizers==0.23.3`, `rapidocr==3.10.0`, and `pdfplumber==0.11.9`.
ONNX Runtime 1.31.0 declares Python >=3.11 and provides the tested cp311 Linux
amd64 wheel. Installing Python packages does not invoke or freeze external
model APIs or model artifacts.

Install into a fresh Linux/Python 3.11 virtual environment with:

```sh
python -m pip --isolated install --require-hashes -r backend/requirements-runtime.lock.txt
python -m pip check
```

Use the build or MLflow path in the same command for those separate
environments. Install build tools in the build environment and disable
uncontrolled PEP 517 build isolation when consuming that lock, for example
`python -m pip wheel --no-index --no-deps --no-build-isolation ./backend` after installing
the build lock. The local project source/wheel is not a PyPI dependency entry
and is not included in these files.

The locks are consumed by the two Dockerfiles; their adoption did not change
pyproject or original dependency declarations. Fresh Linux/Python 3.11
environments passed hashed installation and `pip check` for all three locks.
Production adoption still requires application/integration acceptance; this
task does not claim a complete image build or live MLflow/database validation.
An additional disposable official-image run installed the 6-package build lock
with hashes, passed `pip check`, and successfully built `bidwb-0.1.0` from a
read-only source mount using `--no-index --no-deps --no-build-isolation`.
These Dockerfiles add no apt/system-package installation: base OS contents are
fixed by the default image digest. The Docker/BuildKit environment and Dockerfile
frontend remain external build tooling; these dependency locks do not promise
byte-identical image rebuilds or govern external model API versions.

Workbench CI separately requests exact Python **3.12.16** and Node **24.22.2**
patches through the existing setup actions; action commit SHAs are unchanged.
Availability was rechecked on 2026-10-30 against the official
[Python Actions manifest](https://github.com/actions/python-versions/releases/tag/3.12.16-40260402378)
(Ubuntu 24.04 x64 archive available) and
[Node.js release index](https://nodejs.org/dist/index.json) (v24.22.2,
2026-10-27, Linux x64 available). This fixes toolchain selection, not the hosted
runner or OS-package closure. Compatibility with these exact patches remains
subject to the next CI run; no new toolchain execution is claimed here. These
CI versions are separate from the legacy backend/MLflow Python 3.11 locks.

## Workbench full runtime dependency image

The current workbench is a separate **CPython 3.12, Linux amd64, glibc**
application. Its `workbench/requirements.lock.txt` contains 58 exact package
versions; `workbench/deploy/fusion_full_requirements.txt` consumes that lock and
adds `pillow==12.3.0`. The legacy Python3.11 application locks above are not its
dependency input.

`workbench/deploy/Dockerfile.runtime` uses the official
`python:3.12.16-slim-bookworm` amd64 platform manifest
`sha256:623674a14ef93d052bb9b0de4dbf5f28eb578a35263838941cc8aa43213c1487`
in both stages. The official config declares `PYTHON_VERSION=3.12.16`; the
Dockerfile frontend is also pinned to the previously verified
`docker/dockerfile:1.7` amd64 manifest
`sha256:b5f3b260a9678e1d83d2fce86eeddf79420b79147eaba2a25986f47133d73720`.
No other platform is supported by this recipe.

The builder installs the standard exact-version build lock
`workbench/deploy/requirements-build.lock.txt` (`setuptools==84.0.0`) and uses
`pip wheel --no-deps --no-build-isolation` on the existing full requirement
entry. The final stage installs the same requirement entry from that stage's
wheelhouse using `--no-index --no-deps --no-compile`, then runs `pip check`.
There is no pip upgrade, automatic build-dependency selection, extra apt/GCC
installation, or newly embedded Word engine, Office, OCR, Java or browser.

The source-build boundary is explicit: PyPI publishes no Linux/universal wheel
for `crcmod==1.7`, and `oss2==2.19.1` is also sdist-only. Existing local Python3.12
image metadata records both as pure `py3-none-any` wheels generated by
setuptools84.0.0; that exact setuptools release provides a Python>=3.10 wheel
on official PyPI. The local build completed both pure-Python wheels without
a compiler. Missing tools/backends must fail visibly rather than silently expand installation.
The existing runtime pins are unchanged, and no per-file hash registry is added.

Build from `tender-app-dev/workbench` (not `backend` or the repository root):

```sh
docker build --platform linux/amd64 -f deploy/Dockerfile.runtime -t tender-workbench-runtime:local .
```

This recipe is a dependency image. The existing full Compose keeps
`packages`, `apps/api`, `apps/worker` and `deploy` mounted read-only at
`/workspace`; the image does not copy application source or private profiles.
Deployment therefore still requires the corresponding approved source checkout
and its recorded Git commit. An image digest alone does not identify mounted
source. The runtime defaults to numeric UID/GID65532, `/workspace`, no bytecode
writes and `HOME=/tmp`; the existing Compose enforces a read-only root filesystem
and `/tmp` tmpfs, with its fresh-init bootstrap exception unchanged. An eventual
source-copy release image must remove those source overrides to run the copied
source; that is a separate deployment change.

The local Linux amd64 build completed on 2026-10-31 (+08), including all 59
dependencies and `pip check`. A separate network-disabled, read-only UID65532
container verified Python3.12.16, the full dependency identity and the absence
of setuptools/wheel in the final image. The API's generated upload journal
also wrote a mode0600 file in its separate mode0700 `/workspace/.local` tmpfs
with application source mounted read-only. This does not prove the original
full deployment or its Word installation. Exact versions and image/frontend manifest pins constrain
inputs; they do not promise bitwise-identical image rebuilds or freeze external
model API versions.

The tested local Docker store reports the repository reference
`tender-workbench-runtime@sha256:126140f957f2988cea63a404c84debc7787fe7a800cb53b084fbd8624968ee5e`.
This is an observed local RepoDigest, not a published registry release. A new
machine must build the recipe and inspect its own resulting repository digest;
do not substitute a build-export config digest for a repository reference.

Reproducibility evidence is retained under
`../evidence-local-20261030/dependency-locks/` in the isolated workspace:
`environment.json`, per-group `.in`, `*-report.json`, resolve/install/check
logs, `status.json`, `backend-wheel-build.log`, `python-exact-tag.json`, and the
exact-resource Docker cleanup receipts. The official
Python image is retained for this dependency-verification purpose. No Word
image was built, no global packages were installed, and no old Docker resources
were removed.
