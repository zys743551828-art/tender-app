"""运行配置。

所有配置来自环境变量（前缀 ``BIDWB_``）。凭据类配置支持 ``<NAME>_FILE`` 形式，从挂载的 secret 文件读取，
这样容器环境变量里不会出现明文，``docker inspect`` 也看不到。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]

LEASE_SECONDS_MIN = 30
LEASE_SECONDS_MAX = 900


class Settings(BaseSettings):
    """应用配置；生产环境对不安全的组合直接拒绝启动。"""

    model_config = SettingsConfigDict(env_prefix="BIDWB_", extra="ignore", env_file=None, env_ignore_empty=True)

    environment: Environment = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    public_base_url: str = "http://localhost:8080"

    # —— 数据库：API 与 worker 使用不同角色，权限见 contracts/schema.sql ——
    database_url: SecretStr = SecretStr("postgresql+psycopg://app_api@localhost:5432/bidwb")
    worker_database_url: SecretStr | None = None
    runtime_database_url: SecretStr | None = None  # LangGraph 检查点库（AI/实验 worker）
    db_pool_size: Annotated[int, Field(ge=1, le=50)] = 10
    db_pool_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 10.0

    # —— 会话与认证 ——
    session_ttl_hours: Annotated[int, Field(ge=1, le=24 * 30)] = 12
    session_cookie_name: str = "__Host-sid"
    cookie_secure: bool = True
    login_rate_limit_per_minute: Annotated[int, Field(ge=1)] = 10
    # 允许其 X-Forwarded-* 头被信任的代理地址（逗号分隔，或 *）。API 只经反向代理访问时设为 *。
    forwarded_allow_ips: str = "127.0.0.1"
    # 资料入库后自动解析、提取规则并评审；关闭后只由人工触发各步骤（模型服务故障或需要控制成本时使用）
    auto_analysis: bool = True
    # API 监听地址：默认只听回环；容器镜像通过 BIDWB_API_HOST=0.0.0.0 监听容器内网卡，对外暴露范围由编排层决定。
    api_host: str = "127.0.0.1"
    api_port: Annotated[int, Field(ge=1, le=65535)] = 8000

    # —— 对象存储（阿里云 OSS 的 S3 兼容接口；开发与测试可用 MinIO/moto） ——
    storage_endpoint_url: str | None = None
    storage_public_endpoint_url: str | None = None
    storage_region: str = "cn-hangzhou"
    storage_bucket: str = "bidwb"
    storage_access_key_id: SecretStr = SecretStr("")
    storage_secret_access_key: SecretStr = SecretStr("")
    storage_addressing_style: Literal["virtual", "path"] = "virtual"
    storage_signature_version: Literal["s3", "s3v4"] = "s3v4"
    upload_part_bytes: Annotated[int, Field(ge=100 * 1024)] = 8 * 1024 * 1024
    upload_max_bytes: Annotated[int, Field(ge=1)] = 100 * 1024 * 1024
    upload_url_ttl_seconds: Annotated[int, Field(ge=60, le=3600)] = 900
    upload_session_ttl_seconds: Annotated[int, Field(ge=300, le=86400)] = 6 * 3600

    # —— 消息（Kafka） ——
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_client_id: str = "bidwb"
    kafka_security_protocol: Literal["PLAINTEXT", "SSL", "SASL_SSL", "SASL_PLAINTEXT"] = "PLAINTEXT"
    kafka_sasl_mechanism: str | None = None
    kafka_sasl_username: str | None = None
    kafka_sasl_password: SecretStr | None = None
    kafka_topic_prefix: str = ""

    # —— 任务协议 ——
    lease_seconds: Annotated[int, Field(ge=LEASE_SECONDS_MIN, le=LEASE_SECONDS_MAX)] = 300
    lease_renew_seconds: Annotated[int, Field(ge=5, le=LEASE_SECONDS_MAX)] = 100
    reaper_interval_seconds: Annotated[int, Field(ge=5)] = 30
    redispatch_after_seconds: Annotated[int, Field(ge=10)] = 120
    relay_batch_size: Annotated[int, Field(ge=1, le=1000)] = 100
    relay_poll_seconds: Annotated[float, Field(gt=0, le=30)] = 1.0

    # —— 检索与模型 ——
    retrieval_backend: Literal["keyword", "milvus", "pgvector"] = "keyword"
    embedding_model_dir: str | None = None
    milvus_uri: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: Annotated[float, Field(gt=0)] = 120.0

    # —— 评分预测 ——
    # 每条评分条款独立判断的次数：第 1 次温度 0，其余升温抽样，用于估计判断的稳定性（重复间的分差是打分模型的特征）
    prediction_repeats: Annotated[int, Field(ge=1, le=7)] = 3
    # 比较式锚定：每条主要评分条款与多少份已知官方成绩的历史正文逐一比较；0 表示不做
    prediction_anchors: Annotated[int, Field(ge=0, le=12)] = 6
    # 比较结果折算为分数时的尺度（百分制分差）：越大，单次“更好／更差”对估计的拉动越平缓
    prediction_anchor_tau: Annotated[float, Field(gt=0, le=50)] = 6.0

    # 本地识别结果先作待核验候选，不能直接进入业务评分。
    parse_enrichment_enabled: bool = False
    parse_enrichment_python: str | None = None
    parse_model_dir: str | None = None
    parse_enrichment_max_pages: Annotated[int, Field(ge=1, le=1000)] = 32
    parse_enrichment_page_seconds: Annotated[float, Field(ge=1, le=300)] = 45.0
    parse_enrichment_total_seconds: Annotated[float, Field(ge=1, le=3600)] = 180.0

    worker_id: str = "worker-local"

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _production_guards(self) -> Self:
        if self.lease_renew_seconds * 2 > self.lease_seconds:
            msg = "lease_renew_seconds 必须不超过 lease_seconds 的一半，否则一次续租失败就会丢租约"
            raise ValueError(msg)
        if self.environment == "production":
            problems: list[str] = []
            if not self.cookie_secure:
                problems.append("生产环境必须启用 cookie_secure")
            if not self.public_base_url.startswith("https://"):
                problems.append("生产环境 public_base_url 必须是 https")
            if not self.session_cookie_name.startswith("__Host-"):
                problems.append("生产环境会话 cookie 必须使用 __Host- 前缀")
            if problems:
                raise ValueError("；".join(problems))
        return self

    def worker_dsn(self) -> str:
        """worker/relay/reaper 的数据库连接串。

        生产环境必须单独配置受限角色（app_worker）；开发环境未配置时退回 API 连接串，方便本机试运行。
        只在这些进程启动时调用，因此 API 进程不需要配置它。
        """
        if self.worker_database_url is not None:
            return self.worker_database_url.get_secret_value()
        if self.environment == "production":
            msg = "生产环境必须配置独立的 worker_database_url（受限角色 app_worker）"
            raise ValueError(msg)
        return self.database_url.get_secret_value()


def _read_secret_files(environ: dict[str, str]) -> dict[str, str]:
    """把 ``BIDWB_X_FILE=/run/secrets/x`` 展开为 ``BIDWB_X=<文件内容>``。"""
    expanded: dict[str, str] = {}
    for key, value in environ.items():
        if key.startswith("BIDWB_") and key.endswith("_FILE") and value:
            target = key.removesuffix("_FILE")
            if environ.get(target):
                msg = f"{target} 与 {key} 不能同时设置"
                raise ValueError(msg)
            expanded[target] = Path(value).read_text(encoding="utf-8").strip()
    return expanded


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例；测试通过 ``get_settings.cache_clear()`` 重置。"""
    import os  # noqa: PLC0415  仅此处读取进程环境

    secrets = _read_secret_files(dict(os.environ))
    if secrets:
        os.environ.update(secrets)
    return Settings()
