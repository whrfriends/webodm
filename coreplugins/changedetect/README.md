# 变化检测插件 (changedetect)

`coreplugins/changedetect` — WebODM 多时相影像变化检测插件。

对同一项目里的两个已完成 task 自动做 **像素差分 + 高程差分**，
矢量化输出 GeoJSON 变化区域（颜色区分方向），并在地图上叠加显示。

适用于挖填土监测、违建识别、滑坡/沉降检测、植被砍伐等场景。

## 功能总览

| 模块 | 功能 |
|---|---|
| **时序差分算法** | 像素差分（orthophoto）+ 高程差分（DSM）|
| **矢量化输出** | GeoJSON Polygon + 方向属性（亮/暗、抬升/沉降）|
| **异步处理** | Celery 后台跑，前端轮询进度，不阻塞 WebODM |
| **三种入口** | ① 地图工具栏按钮 ② 项目列表 "View Map" 旁按钮 ③ 历史 pair 重跑 |
| **三层层叠反馈** | Pair 列表行状态 + Panel 内部绿色/黄色 banner + 右上角 Toast |
| **多语言** | gettext，`zh` / `en` 翻译 |
| **零侵入安装** | WebODM 自动扫描 `coreplugins/`，无需改 settings.py / INSTALLED_APPS |

## 三种入口（用户视角）

### 1. 地图工具栏按钮（老入口）

打开任务地图页（`/map/project/<id>/`），右上角工具栏点"两个相交的圆"
图标 → 弹出 panel → 选对比任务 + 调阈值 → Run comparison → 地图上
叠加 GeoJSON。

### 2. 项目列表 "View Map" 旁按钮（新入口，**核心改进**）

项目列表页（`/dashboard/`）每个有任务的 project 行，"View Map" 链接
右侧**直接**出现"变化检测"链接（DOM 注入，不依赖 WebODM 源码改动）：

```
┌────────────────────────────────────────────┐
│ 205  📷 8 张 · 12.3 GB                    │
│       [View Map] [变化检测] [Edit] [删除] │  ← 变化检测 是新加的
└────────────────────────────────────────────┘
```

点"变化检测" → 弹 Bootstrap modal：
- 选 T1（基准任务） + T2（对比任务）
- 像素差分阈值、最小面积
- 矢量化选项
- 点"提交" → 后台跑
- 模态框实时显示进度条
- 完成后弹绿色 Toast "pair #N 处理完成!"
- 点"查看"按钮 → 跳到 `/map/project/<id>/?cd_pair=<pair_id>` 自动加载
  该 pair 的所有变化叠加层

### 3. 历史 pair 行内按钮（panel 内）

Panel 内的 "Comparisons in this project:" 列表，对每行：
- **DONE** → `View` 按钮（渲染到地图）
- **FAILED** → `Retry` 按钮（重跑同样参数）
- **QUEUED / RUNNING** → 转圈 + "Running"

## 三层层叠反馈

| 层 | 触发 | 位置 | 视觉 |
|---|---|---|---|
| **Toast** | 提交/完成/失败/查看/重试 | 屏幕右上角 | 4 色（绿/橙/红/蓝）+ 图标 + 4.5s 自动消失 + × 关闭 |
| **Panel banner** | 加载叠加 / 叠加完成 | Panel 顶部 | 黄色 "叠加变化数据中…" → 绿色 "✓ 已叠加 pair #X — N 个变化区域 · XXX m²" + "清除" |
| **Pair list row** | 状态变化 | Panel 内列表 | cd-status-queued / running / done / failed 四色 badge |

```
╭─ Panel 顶部 ─────────────────────────────────╮
│  变化检测                                       │
│  Current task: 205_task_3 (2026-06-01)        │
│  ┌────────────────────────────────────────┐   │  ← Toast 后在右上角
│  │ ✓ 已叠加 pair #15 变化数据 — 12 个区域 │   │
│  │  · 850 m²                  [清除]      │   │
│  └────────────────────────────────────────┘   │
├──────────────────────────────────────────────┤
│  Comparisons in this project:  [15]            │
│  [DONE] 205 (May 1 → Jun 1)            [View]  │
│  [DONE] 205 (Apr 1 → May 1)            [View]  │
│  [RUNNING] 205 (Mar 1 → Apr 1)     [⟳ Running]│
│  [FAILED] 205 (Feb 1 → Mar 1)        [Retry]  │
├──────────────────────────────────────────────┤
│  Compare current task against:                │
│  [select task ▾]                              │
│  Pixel difference [✓]  Threshold 0.15         │
│  Height difference [✓]  Min |Δh| 0.5m         │
│                          [Run comparison]     │
╰──────────────────────────────────────────────╯
```

## 安装

WebODM 在 2.6+ 之后**自动扫描 `coreplugins/`** 目录加载插件。本插件
**无需**手动改 `INSTALLED_APPS`、无需改 `settings.py`、无需改
`docker-compose.yml`（开发模式自动 bind-mount，release 模式直接打
进镜像）。三步：

```bash
# 1. 把 changedetect/ 整个目录放到 WebODM 源码 coreplugins/
cp -r changedetect /path/to/WebODM/coreplugins/

# 2. 跑数据库迁移（新增 ChangePair / ChangeResult 两张表）
cd /path/to/WebODM
./webodm.sh shell webapp -- python manage.py migrate changedetect

# 3. 重启 webapp + worker 让 plugin 重新加载
./webodm.sh restart webapp worker
```

启动日志应出现：

```
INFO Registered [coreplugins.changedetect.plugin]
```

如果用 release 模式（`./webodm.sh start`），把插件打进镜像后：

```bash
./webodm.sh stop && ./webodm.sh start
```

**Worker 容器**需要 `shapely`（用于矢量化面积计算）。如果 worker
启动后 pair 一直 FAILED 且日志里有 `ImportError: No module named
shapely`：

```bash
docker exec worker pip install shapely
docker restart worker
```

## 启用

`/admin/app/plugin/` → 找到 "Change Detection" → 勾选 `enabled`。

或 API：`POST /api/plugins/changedetect/...` 第一次调用时会自动激活。

## 使用流程

### 快速跑一次

1. 项目列表点"变化检测"（或打开任务地图点工具栏图标）
2. modal / panel 里选 T1 + T2 + 阈值 → 提交
3. Toast 提示"已提交, 后台处理中…"
4. 几十秒到几分钟（取决于 ortho 大小）
5. 模态框切到完成视图，弹绿色 Toast "pair #N 处理完成!"
6. 点"查看" → 跳地图页 → 自动加载该 pair 的 GeoJSON 叠加层
7. 地图上红/蓝多边形出现；panel 顶部绿色 banner "✓ 已叠加 pair #N — N 个变化区域 · XXX m²"

### 重跑失败的 pair

失败原因在 pair `error_message` 字段（worker traceback 前 1500 字符）。
修好后（一般是补依赖、改路径），到 panel 历史列表点 [Retry]，
会用同样参数重跑。

### 跨页恢复

如果 pair 还在跑你切到别的页面——**后台继续跑**。回到项目页 panel
会自动通过 `loadPairs()` 拉一次列表，对 RUNNING pair 自动续轮询。

## API

所有端点挂 `/api/plugins/changedetect/`，CSRF 豁免（DRF dispatch
装饰），认证用 WebODM session。

| Method | URL | 用途 |
|---|---|---|
| `POST` | `project/<project_id>/changedetect/create` | 新建对比 pair，启动 worker |
| `GET`  | `project/<project_id>/changedetect/list` | 列项目下所有 pair |
| `GET`  | `changedetect/pair/<pair_id>/status` | 查状态 + 进度 + results |
| `POST` | `changedetect/pair/<pair_id>/run` | 重跑已存在的 pair |
| `GET`  | `changedetect/pair/<pair_id>/result/<result_id>/download` | 下载结果 GeoJSON |

### `POST create` 请求体

```json
{
  "task_before": "uuid-of-task-t1",
  "task_after":  "uuid-of-task-t2",
  "name":        "Q1 vs Q3",
  "options": {
    "pixel_threshold":   0.15,
    "pixel_min_area_m2": 10,
    "dsm_min_h_m":       0.5,
    "dsm_min_area_m2":   25,
    "enable_pixel":      true,
    "enable_dsm":        true
  }
}
```

### 响应

```json
{
  "pair_id": 17,
  "celery_task_id": "e3b9f32e-...",
  "status": "QUEUED"
}
```

### 状态响应

```json
{
  "id": 17,
  "status": "DONE",
  "task_a": "uuid...",
  "task_b": "uuid...",
  "error": "",
  "updated_at": "2026-06-12T15:23:18Z",
  "results": [
    {
      "id": 23,
      "layer_type": "pixel",
      "stats": { "polygon_count": 12, "total_area_m2": 850.2, "changed_pixels": 23018 }
    },
    {
      "id": 24,
      "layer_type": "dsm",
      "stats": { "polygon_count": 4, "total_area_m2": 98.1, "raised_pixels": 1230, "lowered_pixels": 870 }
    }
  ]
}
```

## 算法

1. **公共范围对齐**：`gdalwarp -t_srs <b.crs> -tr b.transform.a e -r bilinear`
   把两幅 ortho/DSM 投影到 `task_after` 的 CRS 并对齐像素。
2. **像素差分**：ortho band 归一化（uint8 → /255）后算 `|a-b|`，跨 band
   取均值，`> threshold` 即变化。`signed = mean(a) - mean(b)` 区分
   "变亮"（红色，红色多边形）和"变暗"（蓝色）。
3. **高程差分**：`dsm_after - dsm_before`，`|Δh| > min_h` 即变化。
   `+1` 抬升（红色，新建/堆填），`-1` 沉降（绿色，开挖/塌陷）。
4. **矢量化**：`rasterio.features.shapes` 把布尔 mask 转 polygon。
5. **过滤**：按 `min_area_m2` 过滤小斑块。
6. **面积计算**：shapely 在源 CRS 算真实面积（`pyproj` 投影到 EPSG:4326
   输出 GeoJSON）。

## 数据模型

ORM（不是 JSON 文件），gunicorn 多 worker 共享，django-guardian
权限检查直接复用。

| 表 | 用途 | 关键字段 |
|---|---|---|
| `changedetect_changepair` | 一对时序对比 | `task_before_id`, `task_after_id`, `project_id`, `status`, `name`, `options` (jsonb), `celery_task_id`, `error_message` |
| `changedetect_changeresult` | 一层结果 | `pair_id`, `layer_type` (pixel/dsm), `geojson_path`, `stats` (jsonb) |

迁移文件：`migrations/0001_initial.py`。

## 关键文件

```
coreplugins/changedetect/
├── __init__.py             # 懒加载 plugin（__getattr__）
├── apps.py                 # AppConfig (label=changedetect)
├── manifest.json
├── plugin.py               # 5 个 MountPoint（api）
├── models.py               # ChangePair, ChangeResult
├── migrations/0001_initial.py
├── api.py                  # DRF views (5 端点)
├── worker.py               # 时序差分管线 (gdalwarp + numpy + rasterio + shapely)
├── public/
│   ├── main.js             # ①地图工具栏控件 ②项目列表 DOM 注入按钮 ③Toast
│   ├── Changedetect.jsx    # Leaflet control 包装
│   ├── ChangedetectPanel.jsx  # Panel 组件，含 list/banner/form
│   ├── Changedetect.scss   # Leaflet 控件样式
│   ├── ChangedetectPanel.scss  # Panel + banner 样式
│   ├── icon.svg            # 两个相交圆
│   └── webpack.config.js   # Webpack 5
└── README.md               # 本文件
```

## 调试

| 问题 | 排查 |
|---|---|
| 工具栏图标不出现 | `docker exec webapp sh -c "cd /webodm/coreplugins/changedetect/public && rm -rf build && /usr/bin/webpack-cli"` 重新编译 |
| 项目列表没"变化检测"按钮 | 浏览器强刷（Ctrl+Shift+R） — webpack 缓存 |
| 提交后一直 QUEUED | `docker logs worker -f \| grep changedetect` 看 worker 是否拉起任务 |
| pair FAILED + `No module named shapely` | `docker exec worker pip install shapely && docker restart worker` |
| 重新加载后插件消失 | `docker compose restart webapp`（不要 HUP — gunicorn 缓存 `get_plugins()`） |
| JSX 改动没生效 | 删 build 目录重编：`rm -rf build && webpack-cli` |

## 限制与待办

- L3 语义变化（SAM/SegFormer）暂未实现，按需要后续加。
- 两任务必须空间有重叠，否则返回 `No spatial overlap`。
- 大面积任务（>2GB ortho）建议分块；当前实现用 windowed read 但
  全图 diff 一次性加载到内存，>20k x 20k 像素的 GSD<2cm 数据集
  可能爆内存。
- 像素阈值基于归一化差分 (0-1)，不是原始像素值。调阈值请按业务
  光照条件测试。
- 结果 GeoJSON 存到 `${MEDIA_ROOT}/changedetect/pair_<id>/`，
  不会自动清理 — 长期使用建议加 cron 清理过期 pair。

## 致谢

参考 [coreplugins/objdetect](../objdetect/) 的异步处理模式，
[coreplugins/flight-planner](../flight-planner/) 的 AppConfig
`label=` 解法，以及 [coreplugins/road-attributes](../road-attributes/)
的懒加载注册模式。
