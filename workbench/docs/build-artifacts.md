# Reproducible local application build materials

Run these commands from `workbench/` on a Docker Linux/amd64 engine. They build
application dependencies and static files; Word conversion uses the separate
official Gotenberg image and does not require a custom conversion image.

## Python runtime

```sh
docker build --platform linux/amd64 -f deploy/Dockerfile.runtime -t tender-workbench-runtime:py3.12.16 .
docker image inspect tender-workbench-runtime:py3.12.16
```

The source checkout is mounted read-only at runtime; record its Git revision
alongside the resulting image reference. See [Word execution](word-execution.md)
for the independently bounded local test transport and its remaining full
deployment integration boundary.

## Frontend static files

Choose a new, empty output directory. Do not overwrite another running
environment's mounted files. For example, when `apps/web/dist` does not exist:

```sh
docker build --platform linux/amd64 -f deploy/Dockerfile.web-build --output type=local,dest=apps/web/dist apps/web
```

The recipe pins Node24.22.2 and the BuildKit frontend by manifest digest, runs
`npm ci` against the committed lock, then the existing `npm run build` including
TypeScript checks. Its context excludes private environment files and local
dependencies. Eleven tracked synthetic fixture modules in
`qa-previews/frozen-inputs/*.ts` are needed by the existing typecheck; they are
build inputs, not disposable preview output. PDF.js resources are regenerated
from the locked package. The final scratch stage exports static files only.

An official prebuilt server for the existing full Nginx configurations is:

```sh
docker pull nginx:1.30.5-alpine@sha256:8f84ed99befc3891b8f329c5c202785278a2cfb7c25107d57fb2a134a3117433
```

Use this repository digest as the explicit web image reference when configuring
the existing full deployment. Its controller still requires a supported POSIX
environment and its own private configuration, initialization and validation;
building files alone does not start that deployment. The mounted main config
selects port8080, `/tmp` writable paths and only the mounted server config.
Keep its UID65532, read-only filesystem, dropped capabilities and no-new-privileges
settings. `/nginx-health` proxies API readiness, so an absent API does not count
as a healthy deployment. Full deployment and Word transport integration are
separate from this build recipe; see tender-docs for the actual tested topology.

These fixed Linux/amd64 inputs and ecosystem lock files make versions explicit.
They do not promise byte-identical output across arbitrary platforms, external
model responses, different source revisions or application data.

PDF original-page preview pairs PDF.js6.4.299's official `legacy/build/pdf.mjs`
with its matching legacy Worker. The ordinary modern build requires native
JavaScript APIs such as `Uint8Array.toHex` that Chromium134 does not provide.
The compatibility implementation comes from the same locked vendor package;
keep both entry points together rather than adding an application polyfill or
silently raising the supported browser baseline.

The Desktop `verify` command uses a fixed two-page synthetic PDF fixture,
generated once with the existing locked ReportLab5.0.1 check tool. It does not
require ReportLab in the application image. The verification still uploads
and downloads real bytes through Nginx, Kafka and the ordinary Worker; the
fixture is test material and gives no business or model qualification.
