from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

from vcam_bridge.cli import render, runtime
from vcam_bridge.cli.commands import meta as meta_cmd
from vcam_bridge.config import load_config
from vcam_bridge.domain.errors import ConfigError, ConflictError, VcamError
from vcam_bridge.envelope import EXIT_OK, EXIT_RUNTIME, EXIT_USAGE, error_envelope, success_envelope


def _add_global(parser: argparse.ArgumentParser, *, suppress: bool = False) -> None:
    def d(v: Any) -> Any:
        return argparse.SUPPRESS if suppress else v
    parser.add_argument("--output", "-o", choices=["text", "json", "ndjson", "stream-json"], default=d(None))
    parser.add_argument("--director", default=d(None))
    parser.add_argument("--config", default=d(None))
    parser.add_argument("--dry-run", action="store_true", default=d(False))
    parser.add_argument("--yes", "-y", action="store_true", default=d(False))
    parser.add_argument("--no-input", action="store_true", default=d(False))
    parser.add_argument("--no-color", action="store_true", default=d(False))
    parser.add_argument("--curl", action="store_true", default=d(False),
                        help="改用 curl 子进程而非 requests（macOS/Surge 下 requests 被网络策略拦死时用）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vcam", description="UE FBX camera -> Disguise ACC injector")
    _add_global(parser)
    gp = argparse.ArgumentParser(add_help=False)
    _add_global(gp, suppress=True)
    sub = parser.add_subparsers(dest="command")

    p_conv = sub.add_parser("convert", parents=[gp])
    p_conv.add_argument("--fbx", required=True)
    p_conv.add_argument("--target-uid", default=None)
    p_conv.add_argument("--target-name", default=None,
                        help="目标 ACC 层名（替代 --target-uid；经 --director 现场解析成 uid，须精确层名）")
    p_conv.add_argument("--vc-uid", default=None)
    p_conv.add_argument("--camera-name", default=None,
                        help="目标相机名（替代 --vc-uid；经 --director 现场解析成 uid，含 live/virtual）")
    p_conv.add_argument("--pivot-distance", default=None)
    p_conv.add_argument("--chunk-size", type=int, default=None)
    p_conv.add_argument("--overwrite", action="store_true", default=False,
                        help="注入前清掉目标层动画字段的旧键（换不同长度/起点的 take 时避免残帧；同 take 重跑天然幂等，无需此项）")
    p_conv.add_argument("--verify", action="store_true", default=False)
    p_conv.add_argument("--trim-hold", action="store_true", default=False,
                        help="自动去除首尾静止 hold 帧（每端保留 1 帧锚点）")
    p_conv.add_argument("--start-frame", type=int, default=None,
                        help="手动裁剪：起始帧 idx（含，0-based）")
    p_conv.add_argument("--end-frame", type=int, default=None,
                        help="手动裁剪：结束帧 idx（含，0-based）")
    p_conv.add_argument("--tol-pos", type=float, default=0.001)
    p_conv.add_argument("--tol-rot", type=float, default=0.05)
    p_conv.add_argument("--tol-zoom", type=float, default=0.05)

    sub.add_parser("manifest", parents=[gp])
    sub.add_parser("version", parents=[gp])
    sub.add_parser("schema", parents=[gp])

    # targets subcommand with nested "list"
    p_targets = sub.add_parser("targets", parents=[gp])
    p_targets.add_subparsers(dest="subcommand").add_parser("list", parents=[gp])

    # vc subcommand with nested "list"
    p_vc = sub.add_parser("vc", parents=[gp])
    p_vc.add_subparsers(dest="subcommand").add_parser("list", parents=[gp])

    # probe subcommand
    p_probe = sub.add_parser("probe", parents=[gp])
    p_probe.add_argument("--probe-layer-uid", required=True)

    # config subcommand with nested init/show/validate
    p_config = sub.add_parser("config", parents=[gp])
    config_sub = p_config.add_subparsers(dest="subcommand")
    p_cfg_init = config_sub.add_parser("init", parents=[gp])
    p_cfg_init.add_argument("--path", default="vcam.yaml",
                            help="输出配置文件路径（默认 vcam.yaml）")
    config_sub.add_parser("show", parents=[gp])
    p_cfg_val = config_sub.add_parser("validate", parents=[gp])
    p_cfg_val.add_argument("--path", required=True, help="待验证配置文件路径")

    return parser


def _normalize_fmt(fmt: str) -> str:
    return "ndjson" if fmt == "stream-json" else fmt


def _make_transport(args: argparse.Namespace):
    """全部命令共用：--curl → CurlTransport（绕过 macOS/Surge 的 requests 拦截），否则 RequestsTransport。"""
    if getattr(args, "curl", False):
        from vcam_bridge.designer.transport import CurlTransport
        return CurlTransport()
    from vcam_bridge.designer.transport import RequestsTransport
    return RequestsTransport()


def _dispatch(args: argparse.Namespace) -> tuple[str, Any]:
    if args.command == "manifest":
        return meta_cmd.manifest()
    if args.command == "version":
        return meta_cmd.version()
    if args.command == "schema":
        return meta_cmd.schema()

    if args.command == "targets" and getattr(args, "subcommand", None) == "list":
        if not args.director:
            raise ConfigError("--director HOST:PORT is required")
        from vcam_bridge.cli.commands import targets as targets_cmd
        return targets_cmd.list_targets(_make_transport(args), host=args.director)

    if args.command == "vc" and getattr(args, "subcommand", None) == "list":
        if not args.director:
            raise ConfigError("--director HOST:PORT is required")
        from vcam_bridge.cli.commands import vc as vc_cmd
        return vc_cmd.list_vcams(_make_transport(args), host=args.director)

    if args.command == "probe":
        if not args.director:
            raise ConfigError("--director HOST:PORT is required")
        from vcam_bridge.cli.commands import probe as probe_cmd
        return probe_cmd.run_probe(_make_transport(args), host=args.director,
                                   probe_layer_uid=args.probe_layer_uid)

    if args.command == "config":
        from vcam_bridge.cli.commands import config_cmd
        sc = getattr(args, "subcommand", None)
        if sc == "init":
            return config_cmd.config_init(args.path, dry_run=args.dry_run)
        if sc == "show":
            return config_cmd.config_show(args.config)
        if sc == "validate":
            return config_cmd.config_validate(args.path)
        raise ConfigError("config subcommand required: init | show | validate")

    if args.command == "convert":
        cfg = load_config(args.config)
        const = None
        if args.pivot_distance == "focus":
            const = "focus"
        elif args.pivot_distance:
            if not args.pivot_distance.startswith("const="):
                raise ConfigError("--pivot-distance must be 'focus' or 'const=<meters>'",
                                  details={"value": args.pivot_distance})
            raw = args.pivot_distance.split("=", 1)[1]
            try:
                const = float(raw)
            except ValueError as exc:
                raise ConfigError("--pivot-distance const value must be a number, got %r" % raw,
                                  details={"value": args.pivot_distance}) from exc

        from vcam_bridge.cli.commands import convert as convert_cmd

        # uid 直给与 name 现场解析互斥（同一目标同时给两者=冲突，避免静默丢弃 name）。
        from vcam_bridge.designer.client import DesignerClient
        from vcam_bridge.designer.targets import (list_acc_layers, resolve_layer_uid,
                                                  list_cameras, resolve_camera_uid)
        if args.target_uid and args.target_name:
            raise ConfigError("--target-uid and --target-name are mutually exclusive")
        if args.vc_uid and args.camera_name:
            raise ConfigError("--vc-uid and --camera-name are mutually exclusive")

        # 共享一个 director client，懒建一次（layer 解析 dry-run 也要；camera 解析仅 live 要）。
        _shared = {"transport": None, "client": None}

        def _resolve_client():
            if _shared["client"] is None:
                if not args.director:
                    raise ConfigError("--target-name/--camera-name require --director to resolve names")
                _shared["transport"] = _make_transport(args)
                _shared["client"] = DesignerClient(_shared["transport"], args.director)
                _shared["client"].resolve_routing()
            return _shared["client"]

        layer_uid = args.target_uid
        if not layer_uid:
            if not args.target_name:
                raise ConfigError("one of --target-uid / --target-name is required")
            layer_uid = resolve_layer_uid(list_acc_layers(_resolve_client()), args.target_name)

        trim_kw = {"trim_hold_flag": args.trim_hold,
                   "start_frame": args.start_frame, "end_frame": args.end_frame}

        if args.dry_run:
            return convert_cmd.convert_dry_run(args.fbx, config=cfg, layer_uid=layer_uid,
                                               overwrite=args.overwrite, pivot_distance_const=const,
                                               **trim_kw)

        # Live injection path — camera 解析推迟到这里（dry-run 不消费 vc_uid，不该被 --camera-name 逼连 director）。
        if not args.yes:
            raise ConflictError(
                "live 'convert' writes to a production ACC layer; preview with --dry-run, then add --yes to confirm",
                details={"hint": "run --dry-run first, then re-run with --yes"})
        if not args.director:
            raise ConfigError("--director HOST:PORT is required for live injection")
        vc_uid = args.vc_uid
        if not vc_uid and args.camera_name:
            vc_uid = resolve_camera_uid(list_cameras(_resolve_client()), args.camera_name)
        if not vc_uid:
            raise ConfigError("--vc-uid or --camera-name is required for live injection")
        transport = _shared["transport"] or _make_transport(args)   # 复用 name 解析时已建的 transport
        return convert_cmd.convert_live(
            transport,
            client=_shared["client"],   # name 解析路径已路由的 client（None=直给 uid，convert_live 自建）
            host=args.director,
            fbx=args.fbx,
            config=cfg,
            layer_uid=layer_uid,
            vc_uid=vc_uid,
            pivot_distance_const=const,
            chunk_size=args.chunk_size,
            overwrite=args.overwrite,
            verify=args.verify,
            tol_pos=args.tol_pos,
            tol_rot=args.tol_rot,
            tol_zoom=args.tol_zoom,
            **trim_kw,
        )

    raise VcamError("no command given")


def _op_id(args: argparse.Namespace) -> str:
    m = {
        "manifest": "meta.manifest",
        "version": "meta.version",
        "schema": "meta.schema",
        "convert": "convert",
        "probe": "probe",
        "targets": "targets.list",
        "vc": "vc.list",
        "config": "config.%s" % (getattr(args, "subcommand", None) or "show"),
    }
    return m.get(args.command, "INTERNAL")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ai_agent = os.environ.get("AI_AGENT") == "1"
    request_id = runtime.new_request_id()
    timestamp = runtime.utc_now_iso()
    started = time.monotonic()

    def _elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    fmt = _normalize_fmt(runtime.resolve_output(args.output, ai_agent_env=ai_agent,
                                                is_tty=sys.stdout.isatty()))
    op_id = _op_id(args)
    try:
        op, data = _dispatch(args)
        env = success_envelope(op, data, request_id=request_id,
                               duration_ms=_elapsed(),
                               timestamp=timestamp)
        sys.stdout.write(render.render_success(env, fmt) + "\n")
        return EXIT_OK
    except VcamError as exc:
        env = error_envelope(op_id, code=exc.code, exit_code=exc.exit_code,
                             message=exc.message, retryable=exc.retryable, details=exc.details,
                             request_id=request_id,
                             duration_ms=_elapsed(),
                             timestamp=timestamp)
        sys.stdout.write(render.render_error(env, fmt) + "\n")
        return exc.exit_code
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # never crash with a raw traceback; emit a structured envelope
        env = error_envelope(op_id, code="INTERNAL", exit_code=EXIT_RUNTIME, message=str(exc),
                             retryable=False, details={"type": type(exc).__name__},
                             request_id=request_id, duration_ms=_elapsed(), timestamp=timestamp)
        sys.stdout.write(render.render_error(env, fmt) + "\n")
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
