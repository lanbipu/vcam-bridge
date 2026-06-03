from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

from vcam_bridge.cli import render, runtime
from vcam_bridge.cli.commands import meta as meta_cmd
from vcam_bridge.config import load_config
from vcam_bridge.domain.errors import ConfigError, VcamError
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vcam", description="UE FBX camera -> Disguise ACC injector")
    _add_global(parser)
    gp = argparse.ArgumentParser(add_help=False)
    _add_global(gp, suppress=True)
    sub = parser.add_subparsers(dest="command")

    p_conv = sub.add_parser("convert", parents=[gp])
    p_conv.add_argument("--fbx", required=True)
    p_conv.add_argument("--target-uid", required=True)
    p_conv.add_argument("--vc-uid", default=None)
    p_conv.add_argument("--pivot-distance", default=None)
    p_conv.add_argument("--chunk-size", type=int, default=None)
    p_conv.add_argument("--verify", action="store_true", default=False)

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

    return parser


def _normalize_fmt(fmt: str) -> str:
    return "ndjson" if fmt == "stream-json" else fmt


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
        from vcam_bridge.designer.transport import RequestsTransport
        from vcam_bridge.cli.commands import targets as targets_cmd
        return targets_cmd.list_targets(RequestsTransport(), host=args.director)

    if args.command == "vc" and getattr(args, "subcommand", None) == "list":
        if not args.director:
            raise ConfigError("--director HOST:PORT is required")
        from vcam_bridge.designer.transport import RequestsTransport
        from vcam_bridge.cli.commands import vc as vc_cmd
        return vc_cmd.list_vcams(RequestsTransport(), host=args.director)

    if args.command == "probe":
        if not args.director:
            raise ConfigError("--director HOST:PORT is required")
        from vcam_bridge.designer.transport import RequestsTransport
        from vcam_bridge.cli.commands import probe as probe_cmd
        return probe_cmd.run_probe(RequestsTransport(), host=args.director,
                                   probe_layer_uid=args.probe_layer_uid)

    if args.command == "convert":
        cfg = load_config(args.config)
        const = None
        if args.pivot_distance and args.pivot_distance != "focus":
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

        if args.dry_run:
            return convert_cmd.convert_dry_run(args.fbx, config=cfg, layer_uid=args.target_uid,
                                               pivot_distance_const=const)

        # Live injection path
        if not args.director:
            raise ConfigError("--director HOST:PORT is required for live injection")
        if not args.vc_uid:
            raise ConfigError("--vc-uid is required for live injection")
        from vcam_bridge.designer.transport import RequestsTransport
        return convert_cmd.convert_live(
            RequestsTransport(),
            host=args.director,
            fbx=args.fbx,
            config=cfg,
            layer_uid=args.target_uid,
            vc_uid=args.vc_uid,
            pivot_distance_const=const,
            chunk_size=args.chunk_size,
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
