# FlyLitchi Hub 功能迁移到 WebODM 的可行性分析

> **声明**：本分析基于公开资料（flylitchi.com 官方介绍、App Store / Google Play 应用描述、第三方教程），未对 `hub.flylitchi.com` 做逆向抓取。FlyLitchi Hub 是一个需要登录的单页应用 (SPA)，静态搜索无法索引其内部 UI，准确的页面功能清单需用户登录后提供截图或授权访问。

---

## 一、FlyLitchi Hub 的核心功能（业界已知）

| 类别 | 功能 | 说明 |
|------|------|------|
| **任务类型** | Waypoint（航点飞行） | 多点串联，每点可设高度/速度/航向/云台/动作 |
| | Orbit（环绕/POI） | 兴趣点为中心，圆形/螺旋轨迹，自动对焦点 |
| | Panorama（全景） | 球面/柱面/航拍全景，按网格自动拍多张 |
| | Cable Cam（虚拟索道） | 两点间虚拟索道，可重复 6DOF 飞行 |
| | Follow Me（跟随） | 基于手机 GPS 的跟随 |
| | Tap to Fly | 在地图上点哪飞哪 |
| | Corkscrew（螺旋上升） | 边飞边螺旋上升的复合任务 |
| | VR Mode | 配合 VR 眼镜的第一人称操控 |
| **航点参数** | 高度/海拔 | 相对起飞点或绝对海拔 |
| | 速度 / 爬升率 | 起飞/巡航/转弯分别可调 |
| | 航向模式 | Auto / Custom / Initial / Manual |
| | 云台俯仰 | 每点独立 |
| | 动作 | 拍照 / 录像 / 悬停 / 转向 |
| | 转弯曲率 | 圆角过渡 vs 锐角 |
| | 任务完成动作 | 返航 / 悬停 / 降落 |
| **地图** | 多源地图 | Google Maps / Mapbox / 高德 / Bing 卫星图（按机型/区域） |
| | 3D 地形 | 全球 3D 地形预览（基于 SRTM/Mapbox） |
| | 高度剖面 | 沿航线显示地形起伏 |
| | KML/KMZ 导入导出 | 与 Google Earth、DJI GS Pro 互通 |
| **模拟** | 飞行模拟器 | 桌面端 3D 模拟，含相机/云台预览 |
| **云端** | 账号同步 | 任务文件云端保存、跨设备 |
| | 任务共享 | 公开链接分享 |
| **机型** | DJI 全系 | Mavic 2/3, Air 2/2S, Mini 2/3/4, Phantom 4, Inspire 1/2, M30/M300, Avata, FPV 等 |

---

## 二、迁移到 WebODM 的根本性困难

### 1. 产品定位错位
- **WebODM** = 航拍**后处理**（空三、密集匹配、3D 重建、正射、点云）
- **FlyLitchi Hub** = 航拍**前规划**（任务生成、地图编辑、机型指令下发）
- 两者之间没有重叠，迁移 ≈ 重新写一个 DJI 任务规划器

### 2. 法律 / 合规障碍
- FlyLitchi 的核心壁垒是 **DJI 私有协议**的航点指令格式（KMZ 内嵌 XMP + DJI 自定义 schema），该格式未经 DJI 授权反向工程
- 直接复制 FlyLitchi 的 KMZ 模板、机型参数、UI 交互 → 版权 + 商标 + 商业外观侵权
- 合法路径只能是：从零设计兼容标准 KMZ/KML/ArduPilot Mission Planner 文件格式的"类 FlyLitchi"工具，并明确不依赖 DJI 私有协议

### 3. 技术栈鸿沟
| FlyLitchi Hub | WebODM |
|---|---|
| Vue/Angular SPA + Cesium/Mapbox | Django + Node.js + 静态前端 |
| 实时 WebGL 3D 渲染 | 主要服务端处理 |
| 强机型绑定（DJI） | 强数据绑定（图像+GPS+IMU） |
| 单用户/小团队协作 | 多用户/任务队列/Node 节点 |

把 FlyLitchi 嵌入 WebODM 需要：
- 替换 WebODM 的 Django Admin 为地图规划前端
- 新增 KMZ 解析/生成模块
- 新增机型数据库
- 新增云台/相机/航线几何算法
- 改写 ~50% 的代码库

### 4. 闭环不可达
- 即便前端复刻了 FlyLitchi，没有 DJI SDK 端，**任务下不到飞行器**
- 这只是"画图工具"而非"规划平台"
- 实际用户仍必须用 Litchi App（付费订阅）+ 飞控硬件才能用

---

## 三、可以合法且可落地的"白盒"实现范围

如果目标是"开源版 Litchi Hub（不绑定 DJI 私有协议）"作为 WebODM 的**伴生项目**，以下功能 1-2 人月可完成基础版：

| 功能 | 实现路径 | 工时估 |
|------|----------|--------|
| 地图选点 + 航点编辑 | Leaflet + 拖拽控件，存为 JSON | 3 天 |
| 高度剖面 | EGM96/Mapbox Terrain-RGB | 2 天 |
| KMZ 导入导出 | KML 标准 schema（不嵌入 DJI 私有字段） | 3 天 |
| Orbit/Cable Cam 几何计算 | 解析参数后生成多航点 | 2 天 |
| Panorama 网格 | 根据 FoV/重叠率生成网格航点 | 2 天 |
| Corkscrew | 极坐标参数化航点 | 1 天 |
| 任务完成动作 | JSON 元数据 | 1 天 |
| 模拟飞行 | Cesium 3D 轨迹回放 | 5 天 |
| WebODM 集成 | 任务→输出 3D tiles→在规划器内查看 | 5 天 |

**合计约 25 个工作日**，但需明确：
- 不支持 DJI 私有协议任务下发（需要 DJI 官方 Mobile SDK 授权）
- 不绑定特定机型
- 输出标准 KMZ，可被 QGroundControl / Mission Planner / Ardupilot 接收

---

## 四、推荐路线

### 路线 A：仅做"开源任务规划器"（推荐起点）
- 在 `~/WebODM/` 平级目录新建 `mission-planner/`
- 技术栈：Vue 3 + Vite + Leaflet + Cesium（仅开源 3D 地形）+ Python FastAPI 后端
- 输入：GeoJSON / 标准 KML
- 输出：标准 KML（不含 DJI 私有字段）+ 可选 GPX / ArduPilot waypoint.planner
- 与 WebODM 联动：上传任务输出区域的 KML → WebODM 拉框处理

### 路线 B：在 WebODM 内部做插件
- 利用 WebODM 的 plugin 机制（`coreplugins/`、`node_modules/odm/`）
- 写一个 `mission-planner` 插件挂在项目管理页
- 优点：用户账号、权限、文件存储复用
- 缺点：与 DJI 解耦，体验比 FlyLitchi 弱

### 路线 C：放弃此方向
- 如果您的实际需求是 **处理 FlyLitchi 规划的航拍数据**（即 Litchi 飞完 → 拿到照片 → WebODM 重建），这条链路已经天然成立，无需"迁移"
- 只需把 Litchi App 飞完的照片丢进 WebODM 即可

---

## 五、决策表

| 您的实际需求 | 推荐路线 |
|--------------|----------|
| 我要一个免费替代 Litchi 的规划工具 | A |
| 我要把 WebODM 改造为一体化平台 | B（长期） |
| 我只是要把 Litchi 拍的照片用 WebODM 处理 | C（现状即可） |
| 我要复刻 FlyLitchi Hub 全部功能 | ❌ 不推荐（法律 + 工程双重不可行） |

---

## 六、下一步

请确认您要走哪条路线，我再开始具体实施。建议先用 `claude` 或 `delegate_task` 启动路线 A 的脚手架。
