from __future__ import annotations

import json
import re

_UID_RE = re.compile(r"^0x[0-9a-fA-F]+$")
_FIELD_RE = re.compile(r"^[A-Za-z0-9_.]+$")

# Fixed Python 2.7 body. Reads only `payload`; no dynamic values are interpolated
# into code. Field names / uids are DATA passed to findSequence / uid lookup.
# Must stay Py2.7-safe: no comprehensions, no walrus, no print().
INJECT_BODY = '''
local_state = state.localOrDirectorState()
track = local_state.track
target = None
for l in track.layers:
    if hex(l.uid) == payload["layer_uid"]:
        target = l
        break
if target is None:
    result = {"ok": False, "error": "layer not found"}
else:
    fieldmap = payload["fields"]
    seqs = {}
    missing = []
    for key in fieldmap:
        fs = target.findSequence(fieldmap[key])
        if fs is None:
            missing.append(fieldmap[key])
        else:
            fs.disableSequencing = False
            seqs[key] = fs
    if missing:
        result = {"ok": False, "error": "missing fields", "missing": missing}
    else:
        written = 0
        for kf in payload["keys"]:
            beat = kf["beat"]
            vals = kf["values"]
            for key in vals:
                seqs[key].sequence.setFloat(beat, vals[key])
                written = written + 1
        result = {"ok": True, "written": written}
'''


def validate_uid(uid: str) -> str:
    if not _UID_RE.match(uid):
        raise ValueError(f"invalid uid (must be 0x-hex): {uid!r}")
    return uid


def validate_field_name(name: str) -> str:
    if not _FIELD_RE.match(name):
        raise ValueError(f"invalid field name: {name!r}")
    return name


def build_inject_script(payload: dict) -> str:
    """Generate a Py2.7 injection script. All dynamic data enters ONLY via a single
    json.loads of a safely-escaped string literal; nothing is concatenated as code."""
    validate_uid(payload["layer_uid"])
    for key, decorated in payload["fields"].items():
        validate_field_name(decorated)
    json_str = json.dumps(payload)
    header = "import json\npayload = json.loads(" + repr(json_str) + ")\n"
    return header + INJECT_BODY + "\nreturn json.dumps(result)\n"
