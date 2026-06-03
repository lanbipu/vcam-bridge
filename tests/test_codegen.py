import ast
import json
import re
import pytest
from vcam_bridge.designer.codegen import (
    build_inject_script, validate_uid, validate_field_name, INJECT_BODY,
)


def _payload():
    return {
        "layer_uid": "0x1a2b",
        "fields": {"pivot.x": "camera_pivot.x", "fov": "fieldOfView"},
        "keys": [{"beat": 1.0, "values": {"pivot.x": 1.5, "fov": 60.0}}],
    }


def test_script_is_valid_python_and_embeds_payload_safely():
    # Note: the script contains a top-level `return` which is valid only inside
    # Designer's userScript() wrapper; bare ast.parse() accepts it at module level.
    script = build_inject_script(_payload())
    ast.parse(script)  # must be syntactically valid
    # the embedded payload must json-roundtrip exactly
    m = re.search(r"payload = json\.loads\((.*)\)\n", script)
    assert m
    embedded = ast.literal_eval(m.group(1))  # the python string literal
    assert json.loads(embedded) == _payload()


def test_script_valid_as_designer_function_body():
    import textwrap
    script = build_inject_script(_payload())
    wrapped = "def userScript():\n" + textwrap.indent(script, "    ")
    compile(wrapped, "<userScript>", "exec")   # valid as Designer wraps it in a function


def test_injection_attempt_cannot_break_out():
    evil = dict(_payload())
    evil["fields"] = {"a\"b\n'); import os; os.system('x') #": "x"}
    script = build_inject_script(evil)
    ast.parse(script)                       # still valid python, no code escape
    m = re.search(r"payload = json\.loads\((.*)\)\n", script)
    assert json.loads(ast.literal_eval(m.group(1))) == evil


def test_body_has_no_forbidden_py3_constructs():
    tree = ast.parse(INJECT_BODY)
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                                     ast.GeneratorExp, ast.NamedExpr))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "print"


def test_validate_uid():
    assert validate_uid("0x1a2b") == "0x1a2b"
    with pytest.raises(ValueError):
        validate_uid("0xZZ")
    with pytest.raises(ValueError):
        validate_uid("1a2b; drop")


def test_validate_field_name():
    assert validate_field_name("camera_pivot.x") == "camera_pivot.x"
    with pytest.raises(ValueError):
        validate_field_name('bad"name')
    with pytest.raises(ValueError):
        validate_field_name(".x")
    with pytest.raises(ValueError):
        validate_field_name("a..b")
    with pytest.raises(ValueError):
        validate_field_name("trailing.")
