# 实施方案:`vcam-bridge` — UE Sequencer FBX 相机 → Disguise AnimateCameraControl keyframe 注入工具

> 交付给 Claude Code 执行的 plan。**本工具不在 Disguise 内运行**;它是一个外部 Python 3 工具,通过 Disguise 的 HTTP/Python API 远程写入 keyframe。
> 工作名:repo `vcam-bridge`,CLI `vcam`(可一次 find-replace 改名)。
> 标注约定:**[FACT]** = 已由 Disguise 官方文档/API 文档证实;**[PROBE]** = 运行时通过 API 自查后确定,**禁止写死/臆造**;**[INFER]** = 工程推断,需在 verify 环节用硬件/软件验证。

## 本次已确定的参数
- **Designer/d3 版本:R33+**。R33+ 默认走**新 Virtual Camera 工作流**;`enableLegacyVirtualCameraWorkflow` 期望为 OFF,由 **P0** 复核。
- **MR Set 输出 aspect:16:9**(用于 FOV 的 H↔V 判定与换算,见 P7 / §5.6)。
- **知识库覆盖范围说明**:项目内官方文档约截至 r31.x;本方案依赖的 API/工作流特性在 ≤r31.x 已存在并稳定,因此适用于 R33+。**R33 的版本特定改动不在库内,由 P 系列 probe 在真实工程上兜底验证。**

---

## 0. 目标
把在 Unreal Engine Sequencer 里 K 好的相机动画(导出为 FBX)1:1 复现到 Disguise Designer 的一个 **AnimateCameraControl** layer 上,该 layer 驱动 xR **MR Set** 里的 **Virtual Camera**,用于现场 XR 拍摄中"超远距离、大画幅、带运动轨迹"的合成画面输出。

## 1. Scope / Non-goals
**In scope**
- 解析 FBX 相机的逐帧 world transform + FOV + fps。
- UE → Disguise 坐标/单位/旋转转换(Global stage space)。
- 自由相机 → AnimateCameraControl 的 pivot-orbit 参数分解。
- 通过 API 枚举项目内的 AnimateCameraControl layer,让用户按 **UID** 选择目标层。
- 通过 API 批量写入 keyframe + 往返误差自检。

**Non-goals(明确不做)**
- 不做 Virtual Camera 的 rig 搭建(Parent camera、Live action position marker、MR Set target 绑定属于现场手动 setup;本工具只产出"运动轨迹")。
- 不做镜头畸变/色彩;不处理实拍重投影伪影(属分镜设计,见 §9)。
- 不在 Disguise 内常驻;一次性注入。

---

## 2. 已确立的事实与约束(给 Claude Code 的硬背景)
| 项 | 结论 | 标注 |
|---|---|---|
| 目标层模型 | AnimateCameraControl 是 **pivot-orbit**:`Camera pivot (x,y,z)`(stage space, m)+`Camera rotation (x,y,z)`(elevation/heading/roll, deg)+`Distance from pivot`(m)+`Field of view`(deg)。**不是**自由相机 transform | [FACT] |
| 官方支持 | 文档明确 AnimateCameraControl 可驱动 Virtual Camera,并有 `Global`/`Relative` 坐标系开关;VC 下除标准属性外还可 keyframe **zoom scale** | [FACT] |
| 坐标系 | 要 1:1 复现 UE 的绝对路径,**必须用 Global 坐标系**(Relative 是相对 parent camera,会错) | [FACT] |
| 写入 API | layer → `findSequence(name)` → `.sequence` (KeySequence) → `setFloat(track_beat, value)`;写前须 `fseq.disableSequencing = False` | [FACT] |
| 时间单位 | keyframe 时间是 **beat (track time)**,非秒非帧。用 `track.timeToBeat(seconds)` 换算。**不需要用户输入 BPM** | [FACT] |
| 执行环境 | `/api/session/python/execute` 跑 **Python 2.7** + `d3` 模块。重计算放外部 Py3,仅 `setFloat` 在 2.7 内执行 | [FACT] |
| 层时间范围 | `addNewLayer(ModuleType, start_beats, length_beats, name)`、`layer.tStart/tEnd/tLength` 均为 **beats** | [FACT] |
| 定位 | Resource 可按 **uid**(稳定,不随改名变)或 name 定位;选定层后全程用 uid。`guisystem.selectedlayers` 在该版本可用,可作选层 UX | [FACT] |
| GUI 字段名(来自截图) | `Camera`(target)、`Camera pivot X/Y/Z`、`Camera rotation X/Y/Z`、`Distance from pivot`、`Field of view`、`Lock camera`;pivot 内部根名疑似 `camera_pivot` | [FACT]/[PROBE] |
| UE 约定 | 左手系、Z-up、X-forward、Y-right、单位 cm(1 uu = 1 cm)。Sequencer FBX 内嵌 fps(FbxGlobalSettings TimeMode) | [FACT] |

---

## 3. 开放项概览
所有未知项不写死,统一由 **§5.2 的执行时测试清单 P0–P10** 在真实工程上自查/标定后确定并缓存。用户无需预先提供 probe 输出。

---

## 4. 架构
```
[外部 Python 3 CLI: vcam]                                  [Disguise Director]
 ingest -> transform -> decompose -> fov-map  --POST-->  /api/session/python/execute
   |                                            (Py2.7)   layer.findSequence(f).sequence.setFloat(beat,v)
   |-- probe / convention-lock  <----read---->            (回读: fseq.eval / VC world pose)
   '-- target-enumerate (REST + /execute)
```
- **职责分离**:FBX 解析、矩阵运算、相似变换求解全部在外部 Py3(可用 numpy);注入脚本只含轻量 `setFloat` 循环,在内嵌 Py2.7 跑。
- **连接层**:优先用官方 `designer-plugin` 包封装(免手写 HTTP boilerplate);或直接 REST + WebSocket。两者皆可,接口隔离。

---

## 5. 分阶段规格

### 5.1 连接与环境
- Py3 venv;依赖:`numpy`、FBX 读取库(见 5.3)、HTTP 客户端 / `designer-plugin`、`pyyaml`。
- `--director HOST:PORT`;启动先做连通性与 API 可用性检查,失败给出明确指引(网络/CodeMeter/版本)。

### 5.2 执行时探测与标定测试清单(P0–P10)
> **P0–P9 每个 stage 标定一次,结果写入 `config.yaml` 复用;P10 每次 convert 后运行。** 全部在"`Camera` 已设为目标 Virtual Camera"的真实配置下进行(VC 与普通相机、legacy 与新工作流的字段集可能不同)。

**P0 — 连接与版本核验**
- 运行:连接 Director;读版本号;读 `enableLegacyVirtualCameraWorkflow`。
- 通过判据:版本 ≥ R33;legacy = OFF(期望)。
- 据此:若 legacy = ON,记录并在 P2/§5.6 走 legacy 分支(字段集/FOV 路径可能不同),其余流程不变。

**P1 — moduleType 识别**
- 运行:`l.moduleType()`(对一个已建好的 probe AnimateCameraControl 层)。
- 捕获:module 标识字符串/类(旧内部名疑为 `AnimateCamera*`,以实读为准)。
- 据此:写 `config.module_type`;用于 §5.7 枚举过滤与可选建层。

**P2 — 字段 decorated 名枚举**
- 运行:`print([s for s in l.sequences])`。
- 捕获:全部 FieldSequence 的 decorated 名。
- 据此:建立 `field_map`(pivot.x/y/z、rotation.x/y/z、distance、fov、camera-target、coordinate-system、可能的 zoom-scale);逐项 `findSequence(name) is not None` 断言,任一缺失即 fail-fast。

**P3 — Camera target 与坐标系设定**
- 运行:把 `Camera` target 设为目标 VC(by uid);把 coordinate system 设为 **Global**;回读确认。
- 据此:确认 target/coord 字段名与设值方式;锁定 Global。

**P4 — VC world pose 可读性**
- 运行:读取该 VC 的 world position/rotation 属性。
- 捕获:读法(属性名)。
- 据此:可读 → 用于 P5/P10 自动验证;不可读 → 降级为 stage visualiser 数值/可视人工验证,并在报告中标注。

**P5 — convention-lock(forward 轴 / Euler 顺序 / handedness)**
- 运行:写入 ≥6 个非退化已知 (pivot, rot, dist) → 回读 VC world pose;在候选集 {forward∈±X/±Y/±Z} × {Euler 6 序} × {handed ±1} 中,选使往返误差最小者。
- 通过判据:最佳候选平移误差 < `tol_pos`(默认 1 mm)、角度 < `tol_rot`(默认 0.05°),且与次优明显拉开。
- 据此:写 `config.forward_axis / euler_order / handedness`;失败则输出候选误差表,人工介入。

**P6 — M_ue2dis 标定(UE world → Disguise stage 相似变换)**
- 运行:用 ≥3 非共线对应 pose(UE 已知 ↔ 回读 Disguise),Umeyama/Kabsch(含 scale)最小二乘求解 M。
- 通过判据:残差 RMS < `tol_pos`;scale 接近预期(若 UE 场景与 stage 1:1 配准则 ≈ 0.01,cm→m)。
- 据此:写 `config.M_ue2dis`(4x4)。

**P7 — FOV 轴判定(H/V)**
- 运行:写已知 `Field of view` 值 → 回读 VC 结果 frustum/FOV;用 aspect=16:9 验证 H↔V 关系。
- 据此:写 `config.fov_axis`;若为 V,换算 `vFOV = 2·atan( tan(hFOV/2) / (16/9) )`。VC 下确认驱动的是 `Field of view`(global FOV)而非 `zoom scale`。

**P8 — 时间映射核验**
- 运行:`track.timeToBeat(t)`(若干 t)、`trackTime()`。
- 通过判据:秒→beat 单调正确;frame 0 落在 start_offset。
- 据此:确认时间映射(§5.8)。

**P9 — key_type(Linear)常量确认**
- 运行:从 d3 / KeySequence API 取 Linear 枚举;写一对 keyframe 验证插值为线性。
- 据此:写 `config.linear_key_type`。

**P10 — 端到端回读验证(每次 convert 后)**
- 运行:抽样 beat,`fseq.eval(beat, default)` 比对注入值;读 VC world pose 比对该帧目标 Disguise pose。
- 通过判据:max 平移 < `tol_pos`、角度 < `tol_rot`、FOV < `tol_fov`(默认 0.05°)。
- 据此:超阈值非零退出 + 误差报告。

### 5.3 FBX ingest(可插拔前端)
- 接口:`load_camera_track(path) -> {fps:float, frames:[{idx:int, T:mat4_world, fov_h_deg:float, focus_dist_m:float|None}]}`。`T` 为 UE world transform(UE 约定、cm)。
- **实现选型(推荐顺序)**:
  1. Autodesk **FBX Python SDK**(最权威,装环境较重)。
  2. `assimp` / `pyassimp`(轻量,需验证相机 FOV/animation 读取正确)。
  3. **中间格式 fallback**:接受 UE 直出的逐帧 CSV/JSON(idx, 4x4 或 loc+rot+FOV)。**先实现 fallback 跑通全链路,再补 FBX 原生读取。**
- 校验:必须含 camera、含 animation、fps 可得(否则报错或要求 `--fps`)。

### 5.4 坐标 / 单位变换:UE world → Disguise stage(Global)
- 用 4×4 相似变换 `M_ue2dis`(旋转 + 均匀 scale + 平移)把 UE world 映射到 Disguise stage world,**同时吸收**轴系(LH/Z-up → Y-up)、单位(cm→m)、UE 场景原点与 stage registration 的偏移/缩放。
- **求解(优先,见 P6)**:Umeyama(含 scale)最小二乘,不猜 handedness。
- **快速起步 fallback**:解析候选默认(UE LH/Z-up/cm → Y-up/m 基变换 + scale=0.01),先跑后替换。
- 输出:每帧 Disguise stage 下的 `C`(Vec3, m)、`R`(3×3)。

### 5.5 自由相机 → pivot-orbit 分解(确定性数学)
```
f        = R · forward_local            # forward_local 由 P5 确定
pivot    = C + d · f
distance = d
(elev, head, roll) = euler_from_R(R, order=euler_order)   # order 由 P5 确定
```
- `d` 选择([INFER]):有逐帧 focus distance 用之(pivot 落焦平面,操作直观);否则用常量(默认 1.0 m 或相机到 Live action marker 均值)。**任意 d 不影响 pose 精度**(分解可逆),仅影响 pivot 落点语义。

### 5.6 FOV 映射
- UE `fov_h_deg` 为水平 FOV。aspect 固定 **16:9**。
- 若 Disguise `Field of view` 为水平 → 直接写;若为垂直 → `vFOV = 2·atan( tan(hFOV/2) / (16/9) )`(轴向由 P7 定)。
- VC 配置:驱动 `Field of view`(global FOV),**不是** `zoom scale`;若 P2 显示存在 `zoom scale`,置中性(=1)或不写。

### 5.7 目标层枚举与选择(按 UID)
1. REST `GET /api/session/transport/tracks` → 所有 track 的 (uid, name)。
2. 每个 track 经 /execute 跑:`[(l.name, hex(l.uid)) for l in track.layers if l.moduleType() == ACC_MODULE]`(或 `track.getLeafLayers(ACCModule)`)。
3. 汇总 `(track 名, layer 名, layer uid)` 供用户选(交互、`--target-uid`,或读 `guisystem.selectedlayers`)。
4. 注入时按 **uid** 解析目标层;并设 `Camera` target = 选定 VC(by uid)、coordinate system = **Global**(字段名来自 P2/P3)。

### 5.8 时间映射(在注入脚本 Py2.7 内完成)
```
t_sec = start_offset_sec + frame_idx / fps
beat  = track.timeToBeat(t_sec)
```
- `start_offset_sec`:默认当前播放头 `trackTime()`;或 `--start-tc` 指定 TC 换算成秒。
- **不引入 BPM 参数**;`timeToBeat` 处理(兼容变速)。

### 5.9 注入(批量写帧)
- 每字段:`fseq = layer.findSequence(name)`;`fseq.disableSequencing = False`;循环 `fseq.sequence.setFloat(beat, value)`。
- 插值:逐帧 bake 后帧时刻取值与插值无关,仍设 **Linear** 避免子帧 overshoot(用 P9 的 key_type)。
- `--dry-run`:只生成 Py2.7 注入脚本 + `(frame, beat, pivot xyz, rot xyz, dist, fov)` CSV,不执行。

### 5.10 验证(闭环)
见 P10:`fseq.eval` 字段比对 + VC world pose 端到端比对;报告写入帧数、beat 范围、各字段 max/RMS 误差、VC world pose 误差、所用 FOV 轴与 `M_ue2dis`;超阈值非零退出。

---

## 6. CLI / 配置接口
```
vcam probe       --director H:P --probe-layer NAME            # 跑 P0–P9,生成/更新 config.yaml
vcam convert     --fbx PATH [--fps N] [--source ue]
                 --director H:P
                 (--target-uid UID | --select)                # §5.7 选层
                 --vc-uid UID                                  # 目标 Virtual Camera
                 [--start-tc TC | --at-playhead]
                 [--pivot-distance focus|const=VALUE]
                 [--config config.yaml]
                 [--overwrite]                                 # 注入前清理同段既有 keyframe
                 [--dry-run] [--verify --tol-pos 0.001 --tol-rot 0.05]
```
- `config.yaml` 持久化:`module_type`、`field_map`、`forward_axis`、`euler_order`、`handedness`、`fov_axis`、`linear_key_type`、`M_ue2dis`、`aspect=16:9`、`legacy_vc`。同一 stage 复用,免重标定。

---

## 7. 测试计划
**单元(无需 Designer)**
- 分解可逆性:随机 (C,R,d) → 参数 → 重建,断言平移 <1e-6 m、角度 <1e-4 deg。
- `M_ue2dis` 基变换:对手算已知向量断言映射。
- Umeyama 求解:合成已知 M + 噪声,断言回解误差有界。
- FOV H↔V(aspect=16:9):对已知 hFOV 断言 vFOV。
- 时间映射:单调、frame 0 落在 start。

**集成(需 live Designer)**
- P1/P2 返回字段集符合预期。
- P5 convention-lock 自动选出唯一有效约定(误差 < 阈值)。
- 写 N 帧 → P10 eval 回读 max 误差 < tol;VC world pose 端到端误差 < tol。

**Golden**
- 已知 UE FBX(直线 dolly + pan + FOV 推拉)→ 预计算 Disguise 参数 → 断言一致。

---

## 8. 错误处理 / 日志(Architect Mode)
- 输入校验:FBX 含相机/动画/fps;Director 连通;目标层存在且 `moduleType()==ACC`;**所有 field_map 名 `findSequence` 非 None(批量写前 fail-fast)**;Global 坐标已设。
- 异常:连接/鉴权失败、/execute 返回错误、setFloat 抛错("该属性不可设")——分类记录并中止,不静默。
- 日志:逐阶段 INFO;§5.10 / P10 汇总报告;`--dry-run` 落地脚本 + CSV。
- 幂等:`--overwrite` 时先 `stripToFirstKey()` 或清理同段既有 keyframe,避免叠帧。

---

## 9. 风险与缓解
| 风险 | 缓解 |
|---|---|
| **legacy vs 新 VC workflow**(R33+ 默认新;`enableLegacyVirtualCameraWorkflow`) | P0 复核 flag;P2 在真实配置下取字段集;FOV 路径据 P0/P7 定 |
| rotation 顺序 / forward 轴 / handedness 猜错 | P5 convention-lock 自动锁定,不写死 |
| `Field of view` 轴(H/V)判错 | P7 写已知值回读判定;aspect=16:9 换算 |
| **超远距离**下大坐标 float 精度劣化 | 用 `M_ue2dis` 把工作原点拉近 action;坐标超阈值告警 |
| 重投影约束(VC 偏离 parent → 真人"纸板"扭曲;真人出框被裁;向真人推近像素化;parent 快速运动不连续) | 属分镜设计;工具可选告警(检测到相对 parent 大偏角时提示);现场遵循:parent 基本静止、VC 做运动、Max zoom in factor、真人始终在 parent 取景框内 |
| R33 版本特定改动不在知识库 | 由 P0–P10 在真实工程兜底;字段/行为变化在 P2/P5 暴露 |
| Py2.7 注入环境生态受限 | 注入脚本仅含 `setFloat`/`eval`;重逻辑全在外部 Py3 |

---

## 10. 给 Claude Code 的执行顺序
1. 脚手架:Py3 工程(repo `vcam-bridge`,CLI `vcam`)+ venv + 依赖 + CLI 骨架 + `config.yaml` schema。
2. Designer 连接层(`designer-plugin` 或 REST/WS)+ 连通性测试。
3. `probe` 子命令:实现 **P0–P9**(moduleType + sequences dump、convention-lock、M_ue2dis、FOV 轴、key_type),落地 `config.yaml`。
4. ingest:先做 **CSV/JSON 中间格式** 跑通全链路,再补 FBX 原生读取。
5. transform(Umeyama + fallback 基变换)+ decompose + fov-map,**附 §7 单元测试**。
6. 目标层枚举/选择(REST + /execute,按 uid)。
7. 注入(先 `--dry-run`)+ **P10** 验证闭环。
8. 在样例 FBX 上对 live Designer 跑端到端,标定 tolerance,固化 `config.yaml`。

---

## 附:执行前置
- 版本 R33+(已知)、aspect 16:9(已知)。
- `enableLegacyVirtualCameraWorkflow` 状态 → 由 **P0** 在执行时核验。
- 字段名 / moduleType / 约定 / FOV 轴 → 由 **P1–P9** 在真实工程自查标定,**无需用户预先提供**。
