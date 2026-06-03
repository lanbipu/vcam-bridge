import json
from pathlib import Path
from vcam_bridge.manifest import build_manifest


def test_skill_manifest_matches_live():
    p = Path(".claude/skills/vcam-bridge/reference/contract-manifest.json")
    synced = json.loads(p.read_text())
    live = build_manifest()
    assert {o["operation_id"] for o in synced["operations"]} == {o["operation_id"] for o in live["operations"]}
    assert synced["contract_version"] == live["contract_version"]
