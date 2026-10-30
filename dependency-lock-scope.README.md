# Linux dependency lock scope

These locks target **CPython 3.11, Linux amd64, glibc**. They contain one
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

The locks are consumed by the two Dockerfiles; no pyproject, original dependency
declaration or CI file was changed by this task. Fresh Linux/Python 3.11
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

Reproducibility evidence is retained under
`../evidence-local-20261030/dependency-locks/` in the isolated workspace:
`environment.json`, per-group `.in`, `*-report.json`, resolve/install/check
logs, `status.json`, `backend-wheel-build.log`, `python-exact-tag.json`, and the
exact-resource Docker cleanup receipts. The official
Python image is retained for this dependency-verification purpose. No Word
image was built, no global packages were installed, and no old Docker resources
were removed.
