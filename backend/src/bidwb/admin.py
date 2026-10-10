"""运维命令：``bidwb-admin <子命令>``。口令只从文件或标准输入读取，不接受命令行明文参数（避免进入 shell 历史与进程列表）。

研究产出的登记（打分模型、锚点包）与评分配对集导出也在这里：它们由人决定何时生效，不走 API。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from bidwb import db
from bidwb.config import get_settings
from bidwb.errors import Conflict, DomainError
from bidwb.logs import configure_logging
from bidwb.messaging import ensure_topics
from bidwb.runtime import Container
from bidwb.services import anchor_packs, auth, model_registry, score_pairs, scoring_models
from bidwb.storage import S3ObjectStore

ContainerFactory = Callable[[], Container]


def _read_password(args: argparse.Namespace) -> str:
    if args.password_file:
        return Path(args.password_file).read_text(encoding="utf-8").strip()
    if sys.stdin.isatty():
        import getpass  # noqa: PLC0415  只在交互场景需要

        return getpass.getpass("口令：")
    return sys.stdin.readline().strip()


def _create_member(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = db.make_engine(settings.database_url.get_secret_value(), pool_size=1, application_name="bidwb-admin")
    try:
        with db.transaction(engine) as conn:
            member_id = auth.create_local_member(
                conn,
                login=args.login,
                display_name=args.display_name,
                password=_read_password(args),
                request_id="cli",
            )
    except Conflict as exc:
        if args.if_not_exists and exc.code == "login_taken":
            print(f"成员 {args.login} 已存在，跳过")
            return 0
        print(f"失败：{exc.message}", file=sys.stderr)
        return 1
    except DomainError as exc:
        print(f"失败：{exc.message}", file=sys.stderr)
        return 1
    print(f"已创建成员 {member_id}（{args.login}）")
    return 0


def _ensure_topics(args: argparse.Namespace) -> int:
    created = ensure_topics(get_settings(), replication_factor=args.replication_factor)
    print("新建主题：" + (", ".join(created) if created else "无（均已存在）"))
    return 0


def _default_container() -> Container:
    settings = get_settings()
    engine = db.make_engine(settings.database_url.get_secret_value(), pool_size=1, application_name="bidwb-admin")
    return Container(settings, engine, S3ObjectStore(settings))


_container: ContainerFactory = _default_container


def _register(args: argparse.Namespace, build: Callable[[], model_registry.Registration]) -> int:
    ctr = _container()
    try:
        registration = build()
        with db.transaction(ctr.engine) as conn:
            done = model_registry.register(conn, ctr.store, registration, environment=args.environment, reviewer_login=args.reviewer)
    except DomainError as exc:
        print(f"失败：{exc.message}", file=sys.stderr)
        return 1
    finally:
        ctr.close()
    if done.unchanged:
        print(f"{registration.identity[:12]} 已是 {args.environment} 环境的生效发布（{done.release_id}），未做改动")
    else:
        previous = f"，取代 {done.previous_release_id}" if done.previous_release_id else ""
        print(
            f"已登记并发布 {registration.identity[:12]} → {args.environment}：发布 {done.release_id}，路由第 {done.revision} 版{previous}"
        )
    return 0


def _register_scoring_model(args: argparse.Namespace) -> int:
    return _register(
        args,
        lambda: scoring_models.registration(Path(args.bundle).read_bytes(), Path(args.report).read_bytes(), args.environment),
    )


def _register_anchor_pack(args: argparse.Namespace) -> int:
    return _register(
        args, lambda: anchor_packs.registration(Path(args.pack).read_bytes(), Path(args.report).read_bytes() if args.report else None)
    )


def _unroute(target: str) -> Callable[[argparse.Namespace], int]:
    def run(args: argparse.Namespace) -> int:
        ctr = _container()
        try:
            with db.transaction(ctr.engine) as conn:
                release = model_registry.unroute(conn, target=target, environment=args.environment, actor_login=args.reviewer)
        except DomainError as exc:
            print(f"失败：{exc.message}", file=sys.stderr)
            return 1
        finally:
            ctr.close()
        print(f"已撤下 {target} 在 {args.environment} 环境的发布 {release}")
        return 0

    return run


def _list(target: str) -> Callable[[argparse.Namespace], int]:
    def run(_args: argparse.Namespace) -> int:
        ctr = _container()
        try:
            with ctr.engine.connect() as conn:
                rows = [r for r in model_registry.routes(conn) if r["target"] == target]
                history = db.all_(
                    conn,
                    """SELECT r.id, r.environment, r.released_at, r.scope, b.components_json FROM releases r JOIN model_bundles b ON b.id=r.bundle_id
                       WHERE b.target=:t ORDER BY r.released_at DESC, r.id DESC LIMIT 20""",
                    {"t": target},
                )
        finally:
            ctr.close()
        print("生效的发布：" + ("无" if not rows else ""))
        for r in rows:
            identity = r["components_json"].get("model_id") or r["components_json"].get("pack_id") or ""
            print(
                f"  {r['environment']:<8} {identity[:12]}  发布 {r['release_id']}（路由第 {r['revision']} 版，{r['released_at']:%Y-%m-%d %H:%M}）{r['release_scope']}"
            )
        print("最近的发布记录：" + ("无" if not history else ""))
        for h in history:
            identity = h["components_json"].get("model_id") or h["components_json"].get("pack_id") or ""
            print(f"  {h['released_at']:%Y-%m-%d %H:%M} {h['environment']:<8} {identity[:12]}  {h['id']}  {h['scope']}")
        return 0

    return run


def _export_score_pairs(args: argparse.Namespace) -> int:
    ctr = _container()
    try:
        with ctr.engine.connect() as conn:
            counts = score_pairs.export(conn, ctr.store, Path(args.out))
    finally:
        ctr.close()
    print(
        f"已导出 {counts['samples']} 份样本（重复正文 {counts['duplicates']} 份，格式 B 标为失败 {counts['predictions_failed']} 份）到 {args.out}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bidwb-admin", description="施组工作台运维命令")
    sub = parser.add_subparsers(dest="command", required=True)
    member = sub.add_parser("create-member", help="创建登录账号")
    member.add_argument("--login", required=True)
    member.add_argument("--display-name", required=True)
    member.add_argument("--password-file", help="口令文件；缺省时从标准输入读取")
    member.add_argument("--if-not-exists", action="store_true", help="登录名已存在时视为成功（幂等）")
    member.set_defaults(func=_create_member)
    topics = sub.add_parser("ensure-topics", help="幂等创建 Kafka 业务主题与死信主题")
    topics.add_argument("--replication-factor", type=int, default=1)
    topics.set_defaults(func=_ensure_topics)

    environments = ("business", "shadow")
    model = sub.add_parser("register-scoring-model", help="登记打分模型（scoring-model/1）并路由到指定环境")
    model.add_argument("bundle", help="模型 JSON")
    model.add_argument("--report", required=True, help="研究侧的评估报告 JSON")
    model.add_argument("--reviewer", required=True, help="审核人登录名")
    model.add_argument("--environment", required=True, choices=environments)
    model.set_defaults(func=_register_scoring_model)
    pack = sub.add_parser("register-anchor-pack", help="登记比较锚点包（anchor-pack/1）并路由到指定环境")
    pack.add_argument("pack", help="锚点包 JSON")
    pack.add_argument("--report", help="锚点包的说明或评估报告 JSON；缺省时以锚点包摘要登记")
    pack.add_argument("--reviewer", required=True, help="审核人登录名")
    pack.add_argument("--environment", required=True, choices=environments)
    pack.set_defaults(func=_register_anchor_pack)
    for name, target, what in (
        ("scoring-model", model_registry.TARGET_SCORING, "打分模型"),
        ("anchor-pack", model_registry.TARGET_ANCHORS, "锚点包"),
    ):
        unroute = sub.add_parser(f"unroute-{name}", help=f"撤下{what}在指定环境的路由")
        unroute.add_argument("--environment", required=True, choices=environments)
        unroute.add_argument("--reviewer", help="操作人登录名（记入审计）")
        unroute.set_defaults(func=_unroute(target))
        listing = sub.add_parser(f"list-{name}s", help=f"列出{what}的生效发布与最近的发布记录")
        listing.set_defaults(func=_list(target))
    export = sub.add_parser("export-score-pairs", help="导出评分配对集（格式 A）与各提交的系统预测（格式 B）")
    export.add_argument("--out", required=True, help="输出目录")
    export.set_defaults(func=_export_score_pairs)
    return parser


def main(argv: list[str] | None = None, container: ContainerFactory | None = None) -> int:
    """``container`` 只供测试注入（真实数据库＋内存对象存储）；缺省按配置连接数据库与对象存储。"""
    global _container  # noqa: PLW0603  命令函数共用同一个装配入口
    configure_logging("WARNING", json_output=False)
    args = build_parser().parse_args(argv)
    _container = container or _default_container
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
