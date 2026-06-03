from vcam_bridge.cli.main import build_parser
from vcam_bridge.manifest import build_manifest


def test_cli_subcommands_subset_of_manifest():
    parser = build_parser()
    sub_actions = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
    cli_cmds = set(sub_actions[0].choices.keys())
    manifest_ops = {op["operation_id"] for op in build_manifest()["operations"]}
    # each implemented CLI command maps to a manifest operation_id
    mapping = {"convert": "convert", "manifest": "meta.manifest",
               "version": "meta.version", "schema": "meta.schema"}
    for cmd in cli_cmds:
        assert mapping[cmd] in manifest_ops
