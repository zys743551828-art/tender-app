# Isolated local Word execution

The official Gotenberg image remains the conversion engine. No custom Word
image is built. Native API/Worker execution can still use the existing local
Docker adapter. The optional `word-render-execution/1` transport lets an
explicitly owned **local test Worker** run without a Docker socket or Docker
credentials inside that container.

The topology has a trusted host executor and separate API, Worker, database,
object-store and conversion containers. The executor remains a host process;
this is not an all-container installation or a production service. The original
`fusion-full-local/1` role/profile allowlists are unchanged and do not install
this transport automatically.

## Runtime materials

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

## Explicit test execution

The Worker uses the existing versioned external/PAGE/RICH profiles and
`WORD_RENDER_EXECUTION_DIRECTORY=/tmp/word-execution`. This environment variable
is accepted only on Linux and at that exact tmpfs path. Only these three
existing rendering operations are supported; callers cannot submit a command,
image name, arbitrary URL or host path.

The operator starts the host executor using an explicitly selected full Worker
container ID and its exact `tender.test.run` UUID label:

```sh
python -B deploy/word_execution_host.py --container-id <64-hex-id> --run-id <32-hex-run-id> --report-dir <new-private-directory> --stop-file <operator-stop-file>
```

The peer must also carry `tender.test.disposable=true`, run as `65532:65532`,
have a read-only root filesystem and private `/tmp` tmpfs, and have no Docker
socket mount. The executor inspects this exact container rather than discovering
other services. It clears business/model/proxy environment before importing
rendering code, uses a private Docker configuration directory and exposes no
listener. Database and model credentials are unnecessary for the host executor.

The transport preserves the original source, frozen snapshot, producer manifest,
materials, profiles, returned PDF/DOCX and RICH iteration bytes. Existing
content/layout/source qualification checks run unchanged. HTTP or transport
success cannot promote an unqualified document. Metadata receipts exclude
document bodies; the Worker tmpfs holds source/response bytes only for execution.

## Failure, cancellation and cleanup

Requests and responses use private no-follow regular files, bounded sizes and
atomic publication, and response identity is bound to the original request.
External/PAGE waits are bounded at 120 seconds; RICH waits at 240 seconds.
The single local executor runs one conversion at a time.

Cancellation or timeout revokes the client's wait. It does not promise to
interrupt LibreOffice immediately: an in-flight render retains the original
bounded timeout, runs its existing cleanup, and its late response is discarded.
Cancelled request files remain in the Worker's disposable tmpfs until that
container exits. Do not treat this transport as a persistent queue. A cleanup
failure prevents a qualified success response.

Stop the host executor with its operator stop file, wait for its cleanup summary,
then close only the test run's recorded resources through `DockerTestRun`.
Keep reports needed for acceptance. Do not prune unrelated containers, images,
volumes, networks or bind-mounted user files.

This local test topology does not establish real document acceptance, paid-model
qualification, Kafka delivery, the original frozen Word03 byte baseline or a
production deployment. Final execution evidence belongs in tender-docs alongside
the actual tested revision and the remaining deployment boundaries.
