from vcam_bridge.manifest import build_manifest


def test_manifest_has_contract_version_and_ops():
    m = build_manifest()
    assert m["contract_version"] == "1.0"
    ids = {op["operation_id"] for op in m["operations"]}
    assert {"convert", "probe", "targets.list", "vc.list", "meta.manifest"} <= ids


def test_convert_declares_destructive_and_dry_run():
    m = build_manifest()
    convert = next(op for op in m["operations"] if op["operation_id"] == "convert")
    assert convert["side_effects"]["writes"] is True
    assert convert["side_effects"]["destructive"] is True
    assert convert["cli"]["supports_dry_run"] is True
    assert 11 in convert["exit_codes"]


def test_readonly_ops_not_destructive():
    m = build_manifest()
    for oid in ("targets.list", "vc.list", "meta.manifest"):
        op = next(o for o in m["operations"] if o["operation_id"] == oid)
        assert op["side_effects"]["writes"] is False
        assert op["side_effects"]["destructive"] is False
