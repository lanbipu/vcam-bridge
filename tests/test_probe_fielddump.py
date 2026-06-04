from vcam_bridge.designer.probe import _FIELD_DUMP


def test_field_dump_uses_layer_fields_not_sequences():
    # d3 Layer 无 .sequences（实测 AttributeError）；字段枚举必须用 .fields
    assert ".sequences" not in _FIELD_DUMP
    assert "target.fields" in _FIELD_DUMP
