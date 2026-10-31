# Isolated local Word execution

The official Gotenberg image remains the conversion engine. No custom Word
image is built. `word-conversion-execution/2` serves an explicitly installed
local Desktop full/2 instance, or a separately owned disposable test Worker,
without a Docker socket or Docker credentials inside the Worker.

The topology has a trusted host controller and separate API, Worker, database,
object-store and conversion containers. Admission, document assembly, font/PDF
qualification and the RICH convergence loop execute in the Worker. The host
only performs fixed Docker conversion and returns raw font/isolation facts;
it remains a host process, without a business qualification verdict. The original
`fusion-full-local/1` role/profile allowlists are unchanged. The explicitly
versioned Desktop full/2 overlay installs the renderer profiles and supervises
the two host executors; full/1 is not silently upgraded.

## Desktop full/2 installation

From `workbench/`, select a new `.local/full-desktop/<name>` directory, unused
loopback port and the exact application/server image references produced by
[the build recipe](build-artifacts.md):

```sh
python -B -m deploy.fusion_desktop prepare --word --directory .local/full-desktop/local2 --name full_local2 --origin http://127.0.0.1:5189 --python-image <repository@sha256:digest> --web-image nginx:1.30.5-alpine@sha256:8f84ed99befc3891b8f329c5c202785278a2cfb7c25107d57fb2a134a3117433
python -B -m deploy.fusion_desktop up --directory .local/full-desktop/local2 --ask-admin-password
python -B -m deploy.fusion_desktop status --directory .local/full-desktop/local2
python -B -m deploy.fusion_desktop verify --directory .local/full-desktop/local2
python -B -m deploy.fusion_desktop stop --directory .local/full-desktop/local2
```

The prompt supplies the initial `admin` password through bounded stdin to the
Linux bootstrap. It is not an argument, environment variable or public host
file. On subsequent starts, omit the prompt or supply the same password;
bootstrap refuses to reset an existing account or replace existing credentials.
The ordinary no-prompt path still creates a random validation-only bootstrap
password and is intended for automated isolated checks, not a human login guide.

The installation freezes the existing external/PAGE/RICH profiles against the
selected source and official image. Only the API, document/export Workers and
Word controller receive their component-specific Word configuration. The
underlying database and role contracts remain the existing full/1 contracts.
The component processes check private renderer files; `status` separately checks
the two exact Docker peer IDs, deployment labels, launcher/interpreter process
creation identities and ready records. HTTP API readiness alone does not prove
Word executor availability. Unavailable Word status exits with code 2.

`stop` preserves data volumes. It stops producers, lets the two consumers drain
under the existing bounded budgets, closes the executors and then stops the
remaining services. A normal stop followed by `up` may start a new executor
generation for the same two container IDs. A recreated peer is never rebound
implicitly: use the explicit `restart-word` action after checking the reason.
That action validates the saved installation, starts its services, confirms old
executor cleanup, archives its metadata and binds the current exact peer IDs.
It does not repair source/profile drift or initialize an unrelated database.

Optional DeepSeek configuration is declared at preparation with `--model` as
well as `--word`. Supply an explicitly selected existing private three-key JSON
file with `up --model-profile <file>`. Its keys are `DEEPSEEK_API_KEY`,
`DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL`; the existing provider, purpose, budget and
qualification checks remain in force. These API identifiers are configuration,
not deployment dependency locks. No model request is part of preparation,
startup or this synthetic verification. Do not add model settings to the public
request or reuse bootstrap to rotate existing credentials.

## Runtime materials

See [application build materials](build-artifacts.md) for the matching locked
frontend build and official Nginx reference used by the local deployment path.

From `workbench/`, build the application dependency image:

```sh
docker build --platform linux/amd64 -f deploy/Dockerfile.runtime -t tender-workbench-runtime:py3.12.16 .
```

The Dockerfile pins Python3.12.16 and the Dockerfile frontend by manifest digest,
uses the existing full dependency lock and an exact setuptools build lock, and
installs from the builder's wheelhouse. Its build context excludes application
source and private configuration. Mount the selected source checkout read-only;
record that Git revision separately from the dependency image identity. The
runtime does not contain LibreOffice, a compiler, browser or Docker client.

API/Worker containers run as `65532:65532`, with read-only root filesystems,
dropped capabilities and private `/tmp` tmpfs. The API also needs a separate
`/workspace/.local` tmpfs (16 MiB, uid/gid65532, mode0700) for its generated upload
journal. Keep this separate from read-only source mounts. Do not grant write
access to the checkout or mount a Docker socket to address generated state.

## Explicit disposable test execution

The Worker uses freshly generated versioned external/PAGE/RICH profiles and
`WORD_RENDER_EXECUTION_DIRECTORY=/tmp/word-execution`. This environment variable
is accepted only on Linux and at that exact tmpfs path. The transport has one
fixed conversion operation accepting DOCX bytes and validated requested font
names. Snapshots, materials, manifests and RICH iterations stay in the Worker.
Callers cannot submit a command, image name, arbitrary URL or host path.

The test operator starts the host executor using an explicitly selected full Worker
container ID and its exact `tender.test.run` UUID label:

```sh
python -B deploy/word_execution_host.py --container-id <64-hex-id> --run-id <32-hex-run-id> --report-dir <new-private-directory> --stop-file <operator-stop-file>
```

The test peer must also carry `tender.test.disposable=true`, run as `65532:65532`,
have a read-only root filesystem and private `/tmp` tmpfs, and have no Docker
socket mount. The executor inspects this exact container rather than discovering
other services. It clears business/model/proxy environment before importing
rendering code, uses a private Docker configuration directory and exposes no
listener. Database and model credentials are unnecessary for the host executor.
The normal installation uses the separate `--deployment-binding` mode; it
requires instance, deployment, plan, Compose project/service and complete peer
identity rather than adopting disposable test labels.

The controller returns the PDF, raw `fc-match` family/character-set facts,
fixed image identity, source digest, isolation and confirmed cleanup. The Worker
matches those facts to its request and applies the existing font, content,
layout and source qualification checks. A missing fact, wrong identity or
unconfirmed cleanup cannot become complete. HTTP or transport success alone
does not qualify a document. Metadata receipts exclude document bodies; the
Worker tmpfs holds source/response bytes only for execution.

The previous high-level `word-render-execution/1` wire format is not accepted
by this version. Its historical evidence remains unchanged. Source identity
also changes when the adapter changes: use `deploy/word_prebuilt.py profile`
separately with `--lane external`, `--lane page` and `--lane rich`, each with
new private `--profile` and `--receipt` destinations. Generate these for the
installed source rather than reusing earlier qualification profiles.

## Failure, cancellation and cleanup

Requests and responses use private no-follow regular files, bounded sizes and
atomic publication, and response identity is bound to the original request.
Each conversion wait is bounded at 120 seconds. The business dispatchers also
enforce total budgets of 120 seconds for external/PAGE and 240 seconds for
RICH, including successful completion of local qualification. A depleted
budget cannot publish another request. The single local executor runs one
conversion at a time.

Cancellation or timeout revokes the client's wait. It does not promise to
interrupt LibreOffice immediately: an in-flight render retains the original
bounded timeout, runs its existing cleanup, and its late response is discarded.
Cancelled request files remain in the Worker's disposable tmpfs until that
container exits. Do not treat this transport as a persistent queue. A cleanup
failure prevents a qualified success response.

External Word active-content policy failures remain blocked before rendering.
The materials card explains the dynamic-field/macro/external-link restriction,
retains the original and offers a corresponding PDF; the exact public error code
remains in the expandable details. This explanation does not permit those fields
or promote a failed/partial conversion to an adopted or qualified result.

Stop the host executor with its operator stop file, wait for its cleanup summary,
then close only the test run's recorded resources through `DockerTestRun`.
Keep reports needed for acceptance. Do not prune unrelated containers, images,
volumes, networks or bind-mounted user files.

This local test topology does not establish real document acceptance, paid-model
qualification, Kafka delivery, the original frozen Word03 byte baseline or a
production deployment. Final execution evidence belongs in tender-docs alongside
the actual tested revision and the remaining deployment boundaries.
