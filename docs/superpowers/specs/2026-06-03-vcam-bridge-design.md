# 设计规格：`vcam-bridge` — UE Sequencer FBX 相机 → Disguise AnimateCameraControl keyframe 注入工具

> 状态：设计已确认（2026-06-03）；**v2 已吸收 Codex adversarial review 修订（见 §13）**，待进入 writing-plans。
> 本文是 `docs/PLAN_fbx-to-disguise-acc.md` 的**丰富版超集**：吸收知识库核实结果、修正项、CLI 契约（依据 `docs/CLI_DESIGN_SPEC.md` v3.0）与工程架构（对齐同生态项目 `tracksim`）。
> 工具不在 Disguise 内运行；它是外部 **Python 3.11+** 工具，通过 Disguise HTTP/Python API 远程写入 keyframe。repo `vcam-bridge`，CLI `vcam`。
>
> 标注约定：
> **[FACT✓]** 已由知识库/源码核实（附出处）；**[PROBE]** 运行时真机自查标定，禁止写死；**[INFER]** 工程推断，需 verify 环节验证。

---

## 0. 目标

把 Unreal Engine 5.7 Sequencer 里 K 好、经 **Sequencer「Export…」导出为 FBX** 的相机动画，1:1 复现到 Disguise Designer（R33+）的一个 **AnimateCameraControl（ACC）** layer 上；该 layer 驱动 xR **MR Set** 里的 **Virtual Camera（VC）**，用于现场 XR 拍摄中"超远距离、大画幅、带运动轨迹"的合成画面输出。

## 1. Scope / Non-goals

**In scope**
- 解析 FBX 相机逐帧 world transform + 水平 FOV + fps（经无头 Blender 提取；另含 CSV/JSON 中间格式前端）。
- UE world → Disguise stage space 的坐标/单位/旋转变换（Global，相似变换标定）。
- 自由相机 → ACC pivot-orbit 参数分解。
- 通过 API 枚举项目内 ACC layer，按 **uid** 选目标层；设 `Camera` target = 选定 VC、coordinate system = **Global**。
- **分块**批量写入 keyframe + 往返误差自检。
- 三态可调用接口：人类 CLI / CI / AI agent（CLI + Contract Manifest + Skill）。

**Non-goals（明确不做）**
- 不做 VC 的 rig 搭建（Parent camera、Live action position marker、MR Set target 绑定属现场手动 setup；本工具只产出运动轨迹）。
- 不做镜头畸变/色彩；不处理实拍重投影伪影（属分镜设计，见 §11）。
- 不在 Disguise 内常驻；一次性注入。
- v1 **不做 MCP / HTTP adapter**（contract-first 已保证后续低成本添加）。

---

## 2. 已核实的事实与约束（含出处与判定）

> 出处为项目知识库 `.claude/knowledge/<source>/...` 与 workspace 源码 `python-plugin/`、`tracksim`。判定来自 2026-06-03 的 KB 精读 + 4-agent 研究 workflow。

### 2.1 Disguise keyframe 注入契约 — [FACT✓]
来源：`disguise_python_api/09-add-both-strings-to-patch`、`10-set-the-brightness-value`、`04-add-a-layer-at-the`、`05-load-a-resource`。

| 项 | 结论 |
|---|---|
| 写帧 | `fseq = layer.findSequence("name")` → `fseq.disableSequencing = False` → `fseq.sequence.setFloat(track_beat, value)` |
| 关键帧时间 | **beat（Track time，非 Layer-local，非秒非帧）**；`fseq.sequence` 是 KeySequence |
| 回读 | `fseq.eval(beat, default)`；`keyseq.nKeys()/t(i)/key(i)` |
| 清理 | `keyseq.stripToFirstKey()`（幂等 overwrite 用） |
| 字段枚举 | `layer.sequences`（P2 dump 全部 FieldSequence decorated 名） |
| 建层/时间范围 | `track.addNewLayer(ModuleType, start_beats, length_beats, name)`；`layer.tStart/tEnd/tLength` 均 beats；`layer.moduleType()` |
| 时间换算 | `track.timeToBeat(sec)` / `beatToTime(beat)`（**关系沿 track 可变，非固定**，故不需 BPM）；`trackTime()`（秒）；`guisystem.player.tCurrent`（beats） |
| ⚠️ key 类型 | **`setFloat(beat, value)` 不带 key_type 参数** → 设 Linear 须用 `keyseq.insert(i, t, key_type)` 或写后改插值。**[PROBE P9]** |
| ⚠️ 持久化 | 资源改动模式 `markDirty(res)` → `res.saveOnDelete()`；keyframe 写入是否必须 markDirty **[PROBE]** |

### 2.2 execute 执行环境 — [FACT✓]
来源：`disguise_python_api/05`、`03`、`developer-disguise-one/01`。

- POST `/api/session/python/execute`，body `{"script": "...", "moduleName": 可选}`。
- 响应 `{"status":{code,message,details}, "d3Log", "pythonLog", "returnValue"}`；**`returnValue` 是字符串**（如 `"null"`）→ 回读脚本须 `return json.dumps(...)`，Py3 侧 `json.loads`。
- 错误：非零 `status.code`；**报错行号偏移 +10**（脚本被包进 `def userScript():`）→ 展示时减 10。
- ⚠️ **脚本跑在 Designer 主线程 → 执行期间 Designer 暂停渲染**；`pythonApiExecutionTimeout`（默认值 KB 未载）超时 → `KeyboardInterrupt` → `TimeoutError`。官方建议**拆分 / 链式多次 execute**。
- 嵌入解释器为 **Python 2.7 系**（移除模块文档链接指向 py2.7；禁 `threading`/`sys`）。**[FACT✓ 强支持，"2.7" 字样为文档链接推断]**
- solo/director：`GET /api/session/status/session` → `{isRunningSolo, director:{hostname}}`；非 solo 则 execute 打到 `director.hostname`。`state.localOrDirectorState().track` 是通用取 track 方式。
- DNS-SD：`_d3host._tcp`（恒）、`_d3director._tcp`（hosting 时）、`_d3plugin._tcp`；默认端口 80。
- 枚举：REST `GET /api/session/transport/tracks` 列 tracks(uid,name,length,crossfade)；**无 REST 端点枚举 track 内 layer** → 必须 /execute（`track.layers` + `moduleType`）。`guisystem.selectedlayers` **KB 查无** → best-effort probe，回退 `--target-uid`。Locator `uid` = hex，改名稳定。

### 2.3 AnimateCameraControl / Virtual Camera — [FACT✓]
来源：`help-disguise-one/88-common-layer-properties`、`264`（VC 工作流 L2867-2939）、`115`（改名记录）。

- ACC 字段：**Camera pivot (x,y,z)** stage-space **米**；**Camera rotation (x,y,z)** 度，**x=elevation/pitch、y=heading/yaw、z=roll**，绕 pivot（Euler 顺序与 handedness **KB 未载 → P5**）；**Distance from pivot** 米；**Field of view**（"view angle"）度；**Lock camera**（always / when-playing）。
- **ACC 可驱动 MR Set 的 VC，且是新工作流当前支持方法**（`264` L2910-2919）：加 ACC 层 → 设 camera 为 VC → 设 coordinate system 为 **Global/Relative** → keyframe；VC 下除标准属性外 **zoom scale 可 keyframe**。
- coordinate-system 开关**仅当 ACC 的 target 是 VC 时出现**（驱动普通 stage 相机时无）。**Global = 绝对 stage-space**；Relative 下位置字段叫 **Offset**（相对 parent）。1:1 复现用 **Global**。
- **FOV 是水平**：VC 字段标 **"Field of view (horizontal)"**（`264` L2975）→ UE 水平 FOV 大概率直写。**[PROBE P7 确认]**
- **zoom scale**：有 "Animate zoom scale" 开关在 **zoom-scale ↔ global-FOV** 间二选一 → 驱动 global FOV，zoom 置中性（≈1.0，**[PROBE]**）。
- `enableLegacyVirtualCameraWorkflow`（R33+ 默认 OFF）：开则恢复 ACC/ACP 上的旧"额外字段"——**字段集 legacy ON/OFF 不同** → P0 复核 flag、P2 真机取字段集，不写死。
- 内部 module：曾名 `AnimateCamera`（后改名 `AnimateCameraControl`），**Python 枚举名 KB 无** → `moduleType()` 真机取 **[P1]**。

### 2.4 UE FBX 导出约定 — 部分 [FACT✓] / 部分 [PROBE]
来源：`ue56-docs/778-coordinate-system-and`、`720-cameras`、`239-migrating-assets`（UE5.7 内容与 5.6 一致）。

| 项 | 判定 |
|---|---|
| UE 原生世界系：LH、Z-up、X-forward、Y-right、cm（1uu=1cm） | [FACT✓] |
| **UE 导出 FBX 是否重映射成 FBX 标准 Y-up/RH** | **KB 查无明文** → 由 Blender importer 消化 + extract 脚本轴常量 + P5/P6 标定吸收 |
| UE 相机 FOV 水平/垂直、focal↔FOV 关系 | KB 仅证实 perspective 有 vertical FOV；FBX 存储轴未载 → **读 `cam.data.angle_x`（Blender 归一的水平 FOV）+ P7** |
| FBX 内嵌帧率（FbxGlobalSettings TimeMode） | KB 未载 → Blender `scene.render.fps/fps_base` 读取；缺失则 `--fps` |
| 旋转 Euler 顺序、CineCameraActor vs Component transform | KB 未载 → Blender `matrix_world` 统一处理 + P5 |

**结论**：FBX 导出约定的不确定性**全部由"Blender 归一 + Umeyama 相似变换标定（P6）"吸收**，工具不臆造矩阵。

### 2.5 designer-plugin 包（连接层备选）— [FACT✓]
来源：`python-plugin/src/designer_plugin/*`（v1.2.1，Python 3.11+）。

- `D3Session(host, port=80)` / `D3AsyncSession`（context manager）；`@d3pythonscript`（一次性）/ `@d3function`（注册复用）→ `session.rpc()` 返回 returnValue、`session.execute()` 返回全响应；Designer 出错抛 `PluginException`（含 status/d3Log/pythonLog）。
- **Py3→Py2.7 AST 转换**：支持 f-string→`.format()`、去 type hint、async→sync；**不支持 walrus `:=`、列表/字典/集合推导式、`print()`**。
- **无 retry、无连接池**（每请求新建 aiohttp session）、**无批处理 API**。`D3PluginClient` 元类靠 `inspect.currentframe` 帧检查 → **打包成 CLI 后失效**。
- **判定**：v1 采用**直连 REST**（见 §6.1）；designer-plugin 仅作可选 `@d3pythonscript` 替代，**不用 D3PluginClient 元类**。

---

## 3. 架构（对齐 tracksim，contract-first 分层）

> 参照实现：`/Users/bip.lan/AIWorkspace/vp/calibration/tracksim`（branch `feat+fbx-playback`），已是 `CLI_DESIGN_SPEC.md` v3.0 的完整落地，且同域（读相机 FBX 轨迹）。直接克隆其分层与 `envelope.py`/`domain/errors.py`/`cli/main.py`/`manifest.py`/`infra/blender_*` 形态。

```
src/vcam_bridge/
├── domain/
│   ├── models.py        # pydantic: CameraTrack, StagePose, ACCKeyframe, Calibration, Config
│   └── errors.py        # VcamError 基类 + 子类→exit_code（照搬 tracksim 形态）
├── envelope.py          # SCHEMA_VERSION/CONTRACT_VERSION, EXIT_*, success/error_envelope
├── manifest.py          # 轻量 manifest：operation_id + summary
├── ingest/
│   ├── blender_fbx.py    # 无头 Blender 子进程端口（缓存 + killpg + 原子写，借 tracksim）
│   ├── blender_extract.py# bpy 内运行：matrix_world + angle_x + fps + focus → CameraTrack JSON
│   └── intermediate.py   # CSV/JSON fallback 前端（无 Blender / 单测夹具）
├── transform/
│   ├── register.py       # Umeyama 求 M_ue2dis（P6）+ fallback 基变换
│   ├── decompose.py      # 自由相机 → pivot-orbit
│   └── fov.py            # FOV 轴映射（水平直写 / H↔V）
├── designer/
│   ├── client.py         # 直连 REST /execute 端口 + solo/director 路由 + 错误解析 + retry
│   ├── probe.py          # P0–P9 标定
│   ├── targets.py        # track/layer/VC 枚举
│   └── inject.py         # 分块 Py2.7 注入 + P10 回读
├── cli/
│   ├── main.py           # argparse + 全局 flag + --output + AI_AGENT=1（照搬骨架）
│   ├── commands/         # 每 operation 一模块，返回 (operation_id, data)
│   ├── render.py         # 信封渲染 + ndjson 流写
│   └── runtime.py        # request_id / 时间戳 / 输出格式解析
└── config.py             # 分层配置：director / fbx / calibration / tolerances
.claude/skills/vcam-bridge/  # 一个主 Skill
tests/                       # 单元 + 集成 + golden（镜像模块结构）
pyproject.toml               # src 布局, [project.scripts] vcam=..., requires-python>=3.11
```

**职责分离**：FBX 解析、矩阵运算、相似变换求解全在外部 Py3（numpy）；注入脚本只含轻量 Py2.7 `setFloat` 循环。
**Ports（DI，spec §1.1）**：`FbxExtractor`、`DesignerClient`、`Clock`、`FileSystem` —— Core SDK 不直接 IO，便于无硬件单测。

---

## 4. 数据模型（pydantic）

- **`CameraTrack`**（ingest 统一输出，两前端共用）：`{schema:"vcam.track/1", fps:float, camera:str, frames:[{idx:int, t_sec:float, T:mat4_world, fov_h_deg:float, focus_m:float|None}]}`。`T` 为 Blender 归一后的 world transform。
- **`Calibration`**（持久化 `config.yaml`，每 stage 标定一次复用）：`module_type, field_map{pivot.x/y/z, rotation.x/y/z, distance, fov, camera_target, coord_system, zoom_scale?}, forward_axis, euler_order, handedness, fov_axis, linear_key_type, M_ue2dis(4×4), aspect=16:9, legacy_vc, zoom_scale_neutral`。
- **`Config`**：`director(host:port)`、`fbx{blender_path, timeout_s, cache_dir, default_camera}`、`calibration`、`tolerances{pos=0.001m, rot=0.05°, fov=0.05°}`、`inject{chunk_size}`。
- **`StagePose`** / **`ACCKeyframe`**：中间结果模型。

---

## 5. 分阶段规格

### 5.1 连接层（`designer/client.py`）
- **直连 REST `/api/session/python/execute`**；持久 `requests.Session` 复用连接 + 自实现 retry/backoff（designer-plugin 无 retry/池）。
- **solo/director 路由**：启动先 `GET /api/session/status/session`，非 solo 把 execute 打到 `director.hostname`。
- **响应解析**：`status.code`→分类 + exit code；`returnValue` 字符串 `json.loads`；错误行号 −10；`d3Log`/`pythonLog` 写日志。
- 连通性自检：网络 / CodeMeter / 版本，失败给明确指引。

### 5.2 FBX ingest（`ingest/`）
- **Blender 子进程**（默认）：`blender --background --factory-startup --python blender_extract.py -- --in <fbx> --out <track.json> [--camera N]`；`blender_extract.py` 内 `bpy.ops.import_scene.fbx` → 逐帧 `scene.frame_set` 取 `cam.matrix_world` + `cam.data.angle_x`（水平 FOV）+ `cam.data.dof.focus_distance`；fps = `scene.render.fps/fps_base`；帧范围取自相机 action（import 不更新 scene 帧范围，已知坑）。
- **缓存/健壮性**（借 tracksim）：内容寻址缓存（key 含 fbx sha + extract 脚本 sha + 版本 + schema + camera）；超时 killpg 杀进程组防孤儿 Blender；`os.replace` 原子写；日志截断 + 富 `FbxConversionError`。
- **轴常量**：UE→Disguise 轴映射做成 extract 脚本具名常量（`_POS_AXES/_SIGN`、`_ROT_AXES/_SIGN/_OFFSET`），由 **P5** 锁定；改常量→脚本 sha 变→缓存自动失效。
- **CSV/JSON fallback**（`intermediate.py`）：接受 UE 直出逐帧（loc+rot+FOV 或 4×4）。**先用它跑通全链路**再依赖 Blender；亦作单测夹具。
- 校验：含相机、含 animation、fps 可得（否则报错或 `--fps`）。

### 5.3 变换 / 分解 / FOV（`transform/`，纯单测）
- **`M_ue2dis` = Umeyama（含 scale）最小二乘**（P6），≥3 非共线对应 pose；fallback 解析基变换起步。吸收 UE FBX 导出约定的不确定性。
- **pivot-orbit 分解**：`f = R·forward_local`；`pivot = C + d·f`；`(elev,head,roll)=euler(R, order)`；`d` 取逐帧 focus 或常量（不影响 pose 精度）。
- **FOV**：先验水平直写；P7 确认；fallback `vFOV = 2·atan(tan(hFOV/2)/(16/9))`。

### 5.4 注入执行模型（`designer/inject.py`）— 核心修正

**(a) 代码生成信任边界（防注入，必须）**：注入脚本是一段**固定 Py2.7 模板**，所有动态数据（field_map decorated 名、layer/VC uid、逐帧 pivot/rot/dist/fov payload）**只经单一 JSON 字面量进入**——模板顶部 `payload = json.loads(<外部 json.dumps 的字符串>)`，脚本体只引用 `payload[...]`，**绝不把动态值拼进代码**。字段名/uid 作为**数据**传给 `layer.findSequence(name)` / uid 解析，**不作代码标识符**。注入前校验：uid 严格 hex、field 名来自 P2 live map 且匹配 `^[A-Za-z0-9_.]+$`，否则 fail-fast。新增含 quotes/newlines 的 codegen 安全单测。

**(b) Py2.7-safe codegen**：禁列表/字典/集合推导式（用 for）、禁 walrus、禁 `print()`；字符串用 `.format()`；回读脚本 `return json.dumps(...)`，Py3 侧 `json.loads`。

**(c) 分块 + 幂等重放**：N 帧切 chunk，每 chunk = 一次 execute，脚本体 Py2.7 循环写该 chunk。**每个 chunk 写前先清掉该 chunk beat-range 内各字段的既有 key**（remove-in-range / 段内 stripToFirstKey 语义），再写——使 chunk 写入对 `setFloat` 的 replace-at-beat / append 语义**都幂等可重放**（[PROBE P9] 确认 setFloat 语义）。

**(d) 超时不盲重试（修正 F2）**：遇 `TimeoutError`/中断**不直接减半重试**；先**回读该 chunk 实际 key 状态**（`fseq.eval` 覆盖该 chunk 全部 beat），与目标比对，只**续写缺失/不符**的帧；持续失败再缩小 chunk。`--chunk-size` 可配，自适应缩小为兜底。

**(e) key 类型**：按 P9 结果设 Linear（`insert` 或写后改插值）。

**(f) 幂等 overwrite**：`--overwrite` 注入前对整目标段 `stripToFirstKey()` / 清同段既有 keyframe（与 (c) 段内清理叠加，避免叠帧）。

**(g) dry-run**：生成 Py2.7 脚本 + `(frame,beat,pivot,rot,dist,fov)` CSV 写 `data.dry_run_plan`，不执行。

> 备注（推回 Codex 建议）：评审建议的 "staging layer + 原子 swap" 在当前 d3 API 下**无文档化的 keyframe 跨层原子交换机制**，不可行且过重；改用 (c) 段内清理 + (d) 回读续写 + §5.7 P10 全 beat 校验达成同等安全。

### 5.5 目标枚举与选择（`designer/targets.py`，按 uid）
1. REST `GET /api/session/transport/tracks` → tracks。
2. 每 track 经 /execute：`[(l.name, hex(l.uid)) for l in track.layers if l.moduleType()==ACC]`。
3. `vc.list`：枚举 stage 内 Virtual Camera（uid + name）。
4. 选层：`--target-uid` / `--select`（交互）/ best-effort 读 `guisystem.selectedlayers`（回退前两者）。
5. 注入前设 `Camera` target = 选定 VC（uid）、coordinate system = **Global**。

### 5.6 时间映射（注入脚本 Py2.7 内）
```
t_sec = start_offset_sec + frame_idx / fps
beat  = track.timeToBeat(t_sec)
```
`start_offset_sec` 默认 `trackTime()`，或 `--start-tc` TC 换秒。不引入 BPM。

### 5.7 验证闭环（P10）
**字段值校验覆盖全部已写 beat**（不仅抽样）：对每个写入的 (field, beat) 用 `fseq.eval(beat,default)` 比对注入值——这能发现 (d) 续写遗漏 / 段内污染；该校验廉价（纯 eval）。VC world pose 端到端比对可抽样（较贵，读 VC world pose 比对该帧目标 stage pose）。报告帧数、beat 范围、各字段 max/RMS、VC world pose 误差、FOV 轴、`M_ue2dis`；超阈值非零退出（`11 verify-tolerance-exceeded`）。

---

## 6. P0–P10 探测套件

> P0–P9 每 stage 标定一次写 `config.yaml`；P10 每次 convert 后运行。

### 6.0 探测安全（必须，修正 F1）
probe 会向真实 ACC/VC 写已知 pivot/rotation/FOV/keyframe（P5/P7/P9），故：
- **专用 scratch 层**：probe 在**独立临时 ACC 层**进行（`--probe-layer NAME`；默认自建临时层并结束后删除），**绝不命中 production 目标层**。
- **snapshot / restore**：P3/P5/P7/P9 写入前**快照所有将被改动的状态**（相关 FieldSequence 的 key、`Camera` target、coordinate system、FOV、zoom scale）；无论成败 `finally` **还原**。
- **破坏性闸门**：若 scratch/目标层**已有 keyframe**，默认拒绝运行，除非显式 `--yes --allow-destructive-probe`。
- 失败路径除写 config/报错外，**必须先完成 restore**（含删除自建 scratch 层）。

> P0–P10 均在"`Camera` 已设为目标 VC"的真实配置下进行（VC 与普通相机、legacy 与新工作流字段集可能不同）。

| Probe | 动作 | 判据 / 落地 |
|---|---|---|
| **P0** 连接+版本 | 读版本、`enableLegacyVirtualCameraWorkflow` | 版本≥R33；legacy=OFF（期望）；ON 则走 legacy 分支 |
| **P1** moduleType | `l.moduleType()`（probe ACC 层） | 写 `module_type`（KB 无内部名，必须真机取） |
| **P2** 字段枚举 | `[s for s in l.sequences]` | 建 `field_map`，逐项 `findSequence is not None` 断言；缺失 fail-fast |
| **P3** target+坐标系 | 设 `Camera`=VC(uid)、coord=Global，回读 | 确认字段名与设值方式，锁 Global |
| **P4** VC pose 可读 | 读 VC world pos/rot | 可读→自动验证；否则降级可视人工 |
| **P5** convention-lock | 写 ≥6 已知(pivot,rot,dist)→回读 VC pose；在 {forward±轴}×{Euler 6 序}×{handed±1} 选误差最小 | 平移<tol_pos、角<tol_rot 且拉开次优；写 `forward_axis/euler_order/handedness` |
| **P6** M_ue2dis | ≥3 非共线对应 pose，Umeyama 求 4×4 | 残差 RMS<tol_pos；scale 合理（cm→m≈0.01） |
| **P7** FOV 轴 | 写已知 FOV→回读 frustum；aspect16:9 验 H/V | 先验水平；写 `fov_axis`；确认驱动 global FOV 非 zoom scale |
| **P8** 时间映射 | `timeToBeat(t)`、`trackTime()` | 秒→beat 单调；frame0 落 start_offset |
| **P9** key 类型 | 取 Linear 枚举；写一对帧验插值线性 | 写 `linear_key_type`；确定 `setFloat` 后设类型的 API |
| **P10** 端到端回读 | 抽样 `fseq.eval` + VC pose 比对 | max 平移<tol_pos、角<tol_rot、FOV<tol_fov；超阈非零退出 |

---

## 7. CLI / Contract Manifest / 输出契约 / 退出码 / Skill

### 7.1 operations + Contract Manifest（单一事实源，完整版，修正 F4）
operations：`convert`、`probe`、`targets.list`、`vc.list`、`config.init`、`config.show`、`config.validate`、`meta.manifest`、`meta.schema`、`meta.version`、`meta.completion`。

`vcam manifest --output json` 输出**完整 Contract Manifest**（依 `CLI_DESIGN_SPEC.md` §2.1，**不采用 tracksim 的轻量版**——因 vcam 有 `convert`/`probe` 等写真机的破坏性操作，AI/CI/Skill 必须能机读其 destructive/idempotent/dry-run 契约才能安全门控）。每个 operation 含：`operation_id, summary, input_schema, output_schema, error_schema, side_effects{writes, external_calls, idempotent, destructive}, exit_codes, cli{supports_dry_run, supports_stdin}`，敏感字段标 `_meta.sensitive`。
- `convert`：`side_effects{writes:true, external_calls:true, idempotent:true（段内清理+重放）, destructive:true}`、`supports_dry_run:true`。
- `probe`：`writes:true, destructive:true`（受 §6.0 scratch+restore 约束）、`supports_dry_run:true`。
- `targets.list`/`vc.list`/`config.show`/`config.validate`/`meta.*`：`writes:false`（只读）。
- `config.init`：`writes:true`（本地文件，非真机）、`idempotent:true`。

一致性测试（§9）**不止比 operation_id**——还校验各 operation 的 input/output schema、`supports_dry_run`、destructive policy 与实际 CLI/Skill 行为一致。

### 7.2 全局 flags
`--output text|json|ndjson`（别名 stream-json）、`--director H:P`、`--config PATH`、`--dry-run`、`--yes`、`--no-input`、`--log-level`、`--verbose/-v`、`--quiet/-q`、`--no-color`、`--version`、`--help`；env `AI_AGENT=1` → 默认 json（spec §3.4，不靠 TTY 隐式推断）。

### 7.3 convert 子命令
```
vcam convert --fbx PATH [--fps N] [--source ue]
  --director H:P (--target-uid UID | --select) --vc-uid UID
  [--start-tc TC | --at-playhead] [--pivot-distance focus|const=V]
  [--chunk-size N] [--config config.yaml] [--overwrite]
  [--dry-run] [--verify --tol-pos 0.001 --tol-rot 0.05 --tol-fov 0.05]
```
convert 用 **ndjson 流式**报告每 chunk 进度（`type:progress` + 最终 `type:result, final:true`）。

**probe 子命令**：
```
vcam probe --director H:P [--probe-layer NAME] [--vc-uid UID]
  [--allow-destructive-probe] [--config config.yaml] [--dry-run]
```
跑 P0–P9，受 §6.0 scratch + snapshot/restore + 破坏性闸门约束，落地 `config.yaml`。

**破坏性确认（spec §9）**：`convert`/`probe` 为写真机操作，默认需确认（除非 `--yes` 或 `--dry-run`）；Skill 对写操作**强制先 `--dry-run` 摘要确认**（§7.6）。

### 7.4 输出契约（spec §4）
成功/错误信封 `{schema_version, status, operation_id, data|error, meta{request_id,duration_ms,timestamp}}`；`--output json|ndjson` 时 **stdout 仅结构化数据**，日志/进度走 **stderr**；时间 ISO-8601、UTF-8、`.` 小数点。

### 7.5 退出码
`0` ok、`1` 内部、`2` usage、`3` config、`4` auth、`5` not-found、`6` conflict、`7` timeout、`8` external(Designer/Blender)、`9` partial；app 专用：`10` probe-failed、`11` verify-tolerance-exceeded、`12` convention-lock-failed、`13` invalid-fbx；`130` SIGINT。

### 7.6 Skill 包
`.claude/skills/vcam-bridge/`（一个主 Skill）：transport policy = cli-first（`vcam <cmd> --output json --no-color --no-input`，复杂输入走 stdin JSON，只解析 stdout JSON）；error policy = 按 `exit_code`/`error.code`/`retryable` 判断，不猜自然语言；写操作（convert）先 `--dry-run` 摘要确认；引用同步的 `reference/contract-manifest.json`。提供 `vcam skill generate/verify`（可选）。

---

## 8. 错误处理 / 日志

- 输入校验：FBX 含相机/动画/fps；Director 连通；目标层存在且 `moduleType()==ACC`；**所有 field_map 名 `findSequence` 非 None（批量写前 fail-fast）**；Global 已设。
- **注入输入信任校验（F3）**：uid 严格 hex；field 名来自 P2 live map 且匹配 `^[A-Za-z0-9_.]+$`；payload 仅经单一 JSON 字面量进脚本；任一不符 fail-fast，不生成脚本。
- **probe 状态保护（F1）**：写入前 snapshot 受影响状态，`finally` restore；自建 scratch 层结束删除；restore 失败本身视为高优错误并显著报告。
- 异常分类不静默：连接/鉴权、/execute `status.code`（行号 −10）、setFloat 抛错、Blender 子进程 rc≠0/超时 → 映射 exit code + `error.details`。
- 日志逐阶段 INFO 走 stderr；P10/§5.7 汇总报告；`--dry-run` 落地脚本 + CSV。
- 幂等：`--overwrite` 先清同段既有 keyframe；chunk 段内清理（§5.4c）保证重放幂等。

---

## 9. 测试计划

**单元（无 Designer/无 Blender）**
- 分解可逆性：随机 (C,R,d)→参数→重建，平移<1e-6 m、角<1e-4°。
- `M_ue2dis` 基变换手算断言；Umeyama 合成 M+噪声回解有界。
- FOV H↔V（aspect16:9）断言；时间映射单调、frame0 落 start。
- **Py2.7 codegen 合法性**：断言生成脚本不含推导式/`print`/walrus（AST 解析校验）。
- **codegen 注入安全（F3）**：构造含 `'`、`"`、`\n`、`{}`、反斜杠的 field 名/payload，断言生成脚本仍是合法 Py2.7、payload 经 `json.loads` 原样还原、无代码逃逸；非法 uid/field 名被 fail-fast 拒绝。
- **chunk 重放幂等（F2）**：同一 chunk 写两次，断言 key 集合与值不变（段内清理生效）。
- **manifest 完整一致性（F4）**：每 operation 的 input/output schema、`side_effects`、`supports_dry_run`、destructive policy 与 CLI/Skill 行为一致（不止 operation_id 集合）。

**集成（真机 R33+，CSV/JSON 前端免 Blender）**
- P1/P2 字段集符合预期；P5 唯一选出有效约定；写 N 帧→P10 **全 beat** 字段校验 max 误差<tol；VC world pose 端到端<tol。
- **probe restore（F1）**：在 scratch 层跑 P5/P7/P9 后断言受影响状态（key、Camera target、coord/FOV/zoom）已还原；中途注入异常仍 restore；自建 scratch 层被删除。
- **timeout 续写（F2）**：模拟 chunk 中途超时，断言回读续写后 key 完整无重复、无半帧字段。

**Golden**
- 已知 **UE 5.7** FBX（直线 dolly + pan + FOV 推拉）→ 预计算 ACC 参数 → 断言一致（含 Blender extract 路径）。

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| execute 超时 + 主线程冻结 | 分块注入；超时回读续写（非盲重试），自适应缩小 chunk |
| **超时/中断后部分写入 → 半帧/重复 key**（F2） | 段内清理 + 幂等重放 + 回读续写 + P10 全 beat 校验 |
| **probe 改坏 production ACC/VC**（F1） | scratch 专用层 + snapshot/restore + 破坏性闸门 |
| **codegen 拼接动态值 → 脚本破坏 / RCE**（F3） | 固定模板 + 单一 JSON payload + uid hex/field 名校验 + 安全单测 |
| **manifest 不足以让 Skill 安全门控写操作**（F4） | 完整 Contract Manifest（side_effects/dry-run/exit_codes/schema） |
| Py2.7 AST 限制（无推导式/print/walrus） | codegen lint + 单测断言 |
| UE FBX 导出约定无明文 | Blender importer 归一 + 轴常量 + Umeyama(P6) 吸收 |
| legacy vs 新 VC 工作流字段集不同 | P0 复核 flag；P2 真机取字段集；FOV 路径据 P0/P7 |
| rotation 顺序/forward 轴/handedness 猜错 | P5 convention-lock 自动锁定 |
| FOV 轴判错 | P7 写已知值回读；aspect16:9 换算 |
| designer-plugin 元类打包后失效 | 直连 REST |
| Blender 依赖缺失 | CSV/JSON fallback + 明确报错指引（定位 Blender 路径） |
| 超远距离大坐标 float 精度 | M_ue2dis 拉近工作原点；超阈告警 |
| 重投影约束（cardboard 扭曲/出框裁切/推近像素化/parent 快动不连续） | 属分镜设计；可选告警（VC 相对 parent 大偏角提示） |

---

## 11. 实现顺序（里程碑）

1. 脚手架：克隆 tracksim 形态（pyproject/uv、src 布局、`envelope`、`domain/errors`、`manifest`、cli 骨架、config schema）。
2. ingest：先 CSV/JSON fallback 跑通全链路 → 再 Blender `extract`/`fbx`。
3. transform + decompose + fov + **§9 单测**。
4. 连接层（REST + solo/director 路由 + 错误解析 + retry）+ 连通性测试。
5. probe P0–P9 → 落地 `config.yaml`。
6. 目标枚举/选择（tracks REST + layers/VC via execute，按 uid）。
7. 注入（分块，先 `--dry-run`）+ P10 验证闭环。
8. 真机端到端（UE 5.7 FBX + R33 Designer）标定，固化 tolerance + `config.yaml`。
9. Skill 包 + manifest 一致性测试 + 自描述命令（`manifest`/`schema`/`completion`）。

---

## 12. 开放项 / 待真机确认

- `setFloat` 后设 Linear 插值的确切 API（P9）。
- `setFloat(beat,v)` 是 **replace-at-beat 还是 append**（P9）——决定 §5.4(c) 段内清理是否必需（按"两者都幂等"设计，故清理恒做）。
- keyframe 写入是否必须 `markDirty/saveOnDelete`。
- ACC `moduleType()` 内部枚举名、字段 decorated 名（P1/P2）。
- VC zoom scale 中性值（≈1.0?）。
- ACC "view angle" 是否同为水平（P7）。
- `pythonApiExecutionTimeout` 默认值（标定 chunk_size 用）。
- `guisystem.selectedlayers` 真机是否可经 /execute 读。

---

## 13. 修订记录（adversarial review 后，v2）

2026-06-03 Codex adversarial review 后的取舍（逐条技术评估，非盲从）：

- **F1（采纳）probe 隔离/回滚**：新增 §6.0 探测安全——`--probe-layer` scratch 层 + snapshot/restore + 破坏性闸门（`--allow-destructive-probe`）；§8 加状态保护；§9 加 probe restore 集成测试。
- **F2（采纳核心、推回 staging）超时重试幂等**：§5.4 改为段内清理 + 幂等重放 + **回读续写（不盲减半重试）**；§5.7 P10 改为**全 beat** 字段校验。**推回**评审的 "staging layer + 原子 swap"——当前 d3 API 无文档化的 keyframe 跨层原子交换，不可行且过重。
- **F3（采纳）codegen 信任边界**：§5.4(a) 固定 Py2.7 模板 + 单一 `json.loads` payload + uid hex/field 名校验 + 字段名作数据非代码；§8/§9 加注入安全校验与单测。
- **F4（采纳，偏离早先决定）完整 Contract Manifest**：§7.1 由"轻量版（同 tracksim）"升级为含 `input/output/error_schema、side_effects、exit_codes、cli.supports_dry_run、sensitive` 的完整 manifest。
  > **偏离说明**：早先与你确认"manifest 走 tracksim 轻量版"。本次因评审指出 vcam 有 `convert`/`probe` 写真机的**破坏性操作**，Skill/AI 须机读 destructive/dry-run 契约才能安全门控——这是比 tracksim（多为只读/流式）更强的安全需求，故升级。如你更倾向保持轻量版，可改回。

## 附录：知识库证据索引

- keyframe/层/时间 API：`disguise_python_api/04,05,09,10`
- execute 环境/超时/solo-director/REST：`disguise_python_api/03,05`、`developer-disguise-one/01`
- ACC 字段模型：`help-disguise-one/88`
- VC 工作流 / Global-Relative / FOV-horizontal / zoom-scale / legacy flag：`help-disguise-one/264`（L2867-2939）
- 层改名记录：`help-disguise-one/115`
- UE 坐标系/相机/FBX：`ue56-docs/778,720,239`（5.7 同源）
- designer-plugin 源码：`python-plugin/src/designer_plugin/{d3sdk/session.py,d3sdk/function.py,d3sdk/ast_utils.py,api.py,models.py}`
- 架构参照：`tracksim`（`src/tracksim/{envelope,manifest,domain/errors,cli/main,infra/blender_fbx,infra/blender_extract}.py`）
