"""One transaction per command; native authority owns exposure ordering and receipts."""

from psycopg import Error
from psycopg.types.json import Jsonb

from packages.domain.runtime import DomainError


class NativeProtocols:
    def __init__(self, connections):
        self.connections = connections

    def _call(self, sql, parameters):
        with self.connections() as c:
            if not c.execute(
                "SELECT to_regprocedure('model_admission.read_protocol(uuid,uuid)') IS NOT NULL AS ready"
            ).fetchone()["ready"]:
                raise DomainError("ADMISSION_NOT_CONFIGURED", "业务门槛冻结尚未配置", 503)
            try:
                return c.execute(sql, parameters).fetchone()["receipt"]
            except Error as error:
                if error.sqlstate in {"42501", "22023", "55000"}:
                    code = error.diag.message_primary or ""
                    if code.startswith("admission_"):
                        status = {"42501": 403, "22023": 422, "55000": 409}[error.sqlstate]
                        raise DomainError(
                            code.upper(), "业务门槛冻结被权威校验拒绝", status
                        ) from None
                raise

    def freeze(self, cohort_id, actor_id, document, key, reason):
        return self._call(
            "SELECT model_admission.freeze_protocol(%s,%s,%s,%s,%s) AS receipt",
            (cohort_id, actor_id, Jsonb(document), key, reason),
        )

    def read(self, cohort_id, actor_id):
        return self._call(
            "SELECT model_admission.read_protocol(%s,%s) AS receipt", (cohort_id, actor_id)
        )
