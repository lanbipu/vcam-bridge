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

# 全部 stage 相机的原始数据；派生/过滤放 Python 端（避免 Py2.7 脚本里 C++ 异常穿透）。
# d3 Camera 无 .name（实测 AttributeError）；只读安全属性 uid/path/description/类型名。
_CAMERA_ENUM_SCRIPT = '''
import json
out = []
for cam in state.stage.cameras:
    out.append(["0x%x" % cam.uid, str(cam.path), str(getattr(cam, "description", "")), str(type(cam).__name__)])
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


def _camera_name(path_str: str, description: str) -> str:
    base = path_str.rsplit("/", 1)[-1]
    if base.endswith(".apx"):
        base = base[:-4]
    return base or description


def list_cameras(client: DesignerClient) -> list[dict]:
    """枚举 stage 全部相机（live + virtual），名取 path 末段去 .apx（d3 Camera 无 .name）。"""
    rows = client.execute(_CAMERA_ENUM_SCRIPT).return_value or []
    return [{"name": _camera_name(p, d), "uid": u,
             "type": "virtual" if "Virtual" in t else "live"} for u, p, d, t in rows]


def resolve_camera_uid(cameras: list[dict], selector: str) -> str:
    """把 selector（相机名或 '0x..' uid）解析成 uid。镜像 resolve_layer_uid 的消歧语义。"""
    s = selector.strip()
    if s.lower().startswith("0x"):
        for cam in cameras:
            if cam["uid"].lower() == s.lower():
                return cam["uid"]
        raise NotFoundError(f"no camera with uid {s}",
                            details={"available_uids": [c["uid"] for c in cameras]})
    matches = [cam for cam in cameras if cam["name"] == s]
    if len(matches) == 1:
        return matches[0]["uid"]
    if not matches:
        raise NotFoundError(f"no camera named {s!r}",
                            details={"available": [{"name": c["name"], "type": c["type"]} for c in cameras]})
    raise ConfigError(
        f"ambiguous camera name {s!r}: {len(matches)} matches; pass --vc-uid instead",
        details={"matches": [{"name": c["name"], "uid": c["uid"]} for c in matches]})


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
