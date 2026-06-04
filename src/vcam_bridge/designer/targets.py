from __future__ import annotations

import re

from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.domain.errors import ConfigError, NotFoundError

# 真正的 AnimateCameraControl 层 module 名（精确）。Disguise 的 moduleType() 返回 _blipValue(...)
# 对象，str() 形如 "<_blipValue(AnimateCamera) instance at 0x..>"；子串匹配 "AnimateCamera" 会
# 误抓 Preset 的 "AnimateCamera2"，故必须提取括号内 module 名精确比对。
_ACC_MODULE = "AnimateCamera"
_MODULE_RE = re.compile(r"_blipValue\((\w+)\)")

# 枚举 track 全部 layer 的 (name, uid, moduleType 字符串)；过滤放 Python 端做——避免在脆弱的
# Py2.7 /execute 脚本里写正则（C++ 异常会穿透 try/except）。
_LAYER_ENUM_SCRIPT = '''
import json
local_state = state.localOrDirectorState()
out = []
for track in [local_state.track]:
    for layer in track.layers:
        out.append([layer.name, "0x%x" % layer.uid, str(layer.moduleType())])
return json.dumps(out)
'''

_VC_ENUM_SCRIPT = '''
import json
out = []
for cam in state.stage.cameras:
    if getattr(cam, "isVirtual", False) or "Virtual" in str(type(cam).__name__):
        out.append([cam.name, "0x%x" % cam.uid])
return json.dumps(out)
'''


def _module_name(module_type_str: str) -> str:
    m = _MODULE_RE.search(module_type_str)
    return m.group(1) if m else module_type_str


def list_tracks(client: DesignerClient) -> list[dict]:
    resp = client._t.get_json(client.host, "/api/session/transport/tracks", client._timeout_s)
    return [{"uid": t["uid"], "name": t["name"]} for t in resp.get("result", [])]


def list_acc_layers(client: DesignerClient) -> list[dict]:
    rows = client.execute(_LAYER_ENUM_SCRIPT).return_value or []
    return [{"name": n, "uid": u} for n, u, mt in rows if _module_name(mt) == _ACC_MODULE]


def list_vcs(client: DesignerClient) -> list[dict]:
    rows = client.execute(_VC_ENUM_SCRIPT).return_value or []
    return [{"name": n, "uid": u} for n, u in rows]


def resolve_layer_uid(layers: list[dict], selector: str) -> str:
    """把 selector（layer name 或 '0x..' uid）解析成 uid。layers 为已过滤的真 ACC 层 [{name, uid}]。
    uid 直给则校验存在（大小写不敏感）；name 精确匹配：0 匹配 → NotFoundError，
    多匹配 → ConfigError（歧义，提示改用 --target-uid）。每次调用现场解析，不缓存。"""
    s = selector.strip()
    if s.lower().startswith("0x"):
        for layer in layers:
            if layer["uid"].lower() == s.lower():
                return layer["uid"]
        raise NotFoundError(f"no ACC layer with uid {s}",
                            details={"available_uids": [l["uid"] for l in layers]})
    matches = [layer for layer in layers if layer["name"] == s]
    if len(matches) == 1:
        return matches[0]["uid"]
    if not matches:
        raise NotFoundError(f"no ACC layer named {s!r}",
                            details={"available_names": [l["name"] for l in layers]})
    raise ConfigError(
        f"ambiguous ACC layer name {s!r}: {len(matches)} matches; pass --target-uid instead",
        details={"matches": [{"name": l["name"], "uid": l["uid"]} for l in matches]})
