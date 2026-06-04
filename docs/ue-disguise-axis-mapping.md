# UE → Disguise 相机轴向对应关系

> UE（CineCamera，Sequencer）导出 FBX → 导入 Disguise Designer → 驱动 Animator Camera Control。
> 通用对应关系参考，供后续开发直接采用，无需重复测试。

---

## 1. FBX 导出选项（UE Sequencer）

导出 FBX 时（FBX Export Options）：

- **Bake Camera and Light Animation = `Bake Transforms`** — 必选，将相机动画烘焙为逐帧世界变换。
- **Force Front XAxis = 关闭（不勾选）** — 关键前提。勾选会改变相机前向轴，下列对应关系全部失效。
- Fbx Export Compatibility = `FBX 2013`。
- 其余网格相关选项（Vertex Color / LOD / Collision / Morph Targets 等）对相机无影响。

## 2. 坐标系约定

| | Unreal Engine | Disguise |
|---|---|---|
| 上 Up | +Z | +Y |
| 前 Forward（视线）| +X | +Z |
| 右 Right | +Y | +X |
| 手性 | 左手系 | 右手系 |
| 单位 | 厘米 cm | 米 m |

「右 / 上 / 前」语义一一对应；映射为纯轴重排 + 单位换算，**无符号翻转、无镜像**，UE 相机可 1:1 还原。

## 3. 位置对应

```
Disguise_X = UE_Y / 100      (右 → 右)
Disguise_Y = UE_Z / 100      (上 → 上)
Disguise_Z = UE_X / 100      (前 → 前)
```

写入 ACC 时令 `distance from pivot = 0`，则 `camera pivot` 即相机世界坐标。

## 4. 旋转对应

UE `FRotator(Pitch, Yaw, Roll)` 与 ACC `rotation` 分量直接相等：

```
ACC rotation.x (elevation) = Pitch
ACC rotation.y (heading)   = Yaw
ACC rotation.z (roll)      = Roll
```

> Disguise 内部欧拉分解（intrinsic ZXY、heading 取反）与 UE 不同。中间计算请用 **look / up 朝向向量**校验，不要比对欧拉分量；只有最终按上表写入 ACC 字段的数值才与 UE 相等。

## 5. 焦距 / FOV

先从 FBX 的 **filmback Sensor Width + 焦距**算出 UE 的水平 FOV（robust，不受 Blender `sensor_fit` 影响）：

```
fov_h = 2 · atan(SensorWidth / (2 · FocalLength))
```

再写入 ACC 字段（FOV 角度才是视觉等价量；焦距 mm 会自动反算成 UE 的值）：

- **普通相机（Live Camera）**：FOV 由 ACC 的 **`view angle`** 字段驱动，且该字段 = **垂直 FOV（fovV）**。写入 `view angle = h_to_v(fov_h, aspect)`。相机焦距 mm 随之反算（disguise sensor 与 UE 一致时即为 UE 焦距，如干净的 35mm）。注意：直接设相机 lens 焦距**不生效**——ACC `view angle` 每帧重渲染会覆盖它。
- **VirtualCamera**：用 ACC `virtual camera zoom` 驱动（`view angle` 对其无效）。

> 两个字段都注入即可同时兼容两种相机（各取所需）。变焦动画天然支持（逐帧关键帧）。

**aspect 用哪个**：把水平 FOV 换成垂直 FOV(view angle) 用的 aspect，必须是相机的**渲染宽高比 = 输出分辨率的宽高比**（如 1920×1080 = 16/9，由用户在 Disguise 配，不一定等于传感器宽高比）。live 注入时自动读相机 `aspectRatio`，对任意输出分辨率都精确；offline 预览用 config 默认 16/9。

## 6. 实现注记

- **解析工具的额外轴转换**：若经 Blender 解析 FBX，其导入器会额外把 UE 的 Y 取反（X、Z 不变），需先撤销再套第 3 / 4 节映射。此为解析工具行为，与 UE↔Disguise 本身无关；换其它解析方式须重新核对该中间约定。
- **旋转矩阵约定**：Disguise 世界旋转矩阵满足「相机 look = `R^T·[0,0,1]`」（look / up / right 为矩阵的行），由方向向量构造矩阵时需相应转置。
- **ACC 坐标模式**：`virtual camera coordinates = 0 (Global)`，pivot / rotation 才按绝对 stage 空间解释。

## 7. 走 FreeD 协议时的额外转换（UE → FreeD → Disguise）

第 1–6 节针对「FBX 导入 Disguise → 直写 ACC」。若改用 **FreeD 协议实时传输**（如经 UDP 发 FreeD 给 Disguise），**不能直接照搬第 3 节**——FreeD 本身是 Z-up，Disguise 的 FreeD 接收端会再做一次坐标转换。实测结论如下。

### 7.1 FreeD 是 Z-up（Z=height），Disguise 接收自动 Y/Z 对调

FreeD（Vinten free-d）位置 X/Y/Z 中 **Z 是高度（up）**。Disguise FreeD 接收把 Z-up 转成自己的 Y-up：

```
Disguise_X(右) = FreeD_X
Disguise_Y(上) = FreeD_Z      # FreeD 的 height(Z) → Disguise 的 up(Y)
Disguise_Z(前) = FreeD_Y
```

即 Disguise 收包时把 FreeD 的 **Y/Z 对调**——直写 ACC 路径没有这一步，最容易踩。

### 7.2 位置：发送端把坐标打成 FreeD Z-up

```
FreeD_X(右)         = Disguise_X = UE_Y / 100
FreeD_Y(前)         = Disguise_Z = UE_X / 100
FreeD_Z(上/height)  = Disguise_Y = UE_Z / 100
```

直写 ACC 直接写 Disguise_X/Y/Z；走 FreeD 要把「上(Disguise Y)」放进 FreeD 的 Z、「前(Disguise Z)」放进 FreeD 的 Y。

### 7.3 旋转：直接对应，无额外处理

```
FreeD pan  → Disguise heading   = UE Yaw
FreeD tilt → Disguise elevation = UE Pitch
FreeD roll → Disguise roll      = UE Roll
```

与第 4 节一致（写入 ACC 层 = UE FRotator），不需要为 FreeD 翻转。

### 7.4 缩放：FreeD native 1:1

native 缩放（64 LSB/mm = 64000 LSB/m），Disguise 1:1 还原米，无需调 scale。

### 7.5 实测闭环（d3_060404 末帧 f150）

发 FreeD `(X=12.5, Y=-25, Z=5.2; pan=-26, tilt=-4.8, roll=5)` → Disguise `Offset(12.5, 5.2, -25)`、`Rotation(elev -4.8, heading -26, roll 5)`，与 UE ground truth `(-2500,1250,520)cm, (Pitch-4.8, Yaw-26, Roll5)` 一致。

> **调试法**：固定持续发某一已知帧，读 Disguise 实收的 Offset / Rotation，与发送的 FreeD 字段逐项对比，反推轴 / 符号 / 单位 —— 一次定位，无需盲调。
