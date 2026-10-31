# Historical frontend captures and current fixture inputs

The production frontend is `../src`. Installation and operation are described in
the [current usage manual](https://github.com/zys743551828-art/tender-docs/blob/dev/使用说明.md).

The duplicated source trees in candidates 04–11 have been retired. Their remaining
capture manifests, screenshots and configuration preserve historical context.
Reproducing a historical harness requires the
[complete original candidate tree](https://github.com/zys743551828-art/tender-app/tree/35b9e3c6f84a43ac79a2f21b4a3616ae378f61d8/workbench/apps/web/qa-previews)
in a separate checkout. These captures are not current deployment entry points.

The separate `frozen-inputs/` directory is different: its eleven `.ts` modules are
current typecheck/test/build inputs. They remain tracked and are explicitly copied
by `deploy/Dockerfile.web-build`. Keep them, along with their supporting files.
Regeneratable `tsconfig.tsbuildinfo` caches are not tracked.
