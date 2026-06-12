# Change Detection Plugin for WebODM

时序正射影像与 DEM 差分检测。在 WebODM 任务地图上点一下，对比当前任务和
项目里另一个早期任务，自动算出变化区域（新增/减少/抬升/沉降）。

## 功能

| 图层 | 输入 | 输出 | 适用隐患 |
|---|---|---|---|
| 像素差分 | `orthophoto.tif` × 2 | GeoJSON 变化多边形（颜色区分方向）| 违建、植被砍伐、地表变化 |
| 高程差分 | `dsm.tif` × 2 | GeoJSON 多边形（红色=抬升，绿色=沉降）| 滑坡、沉降、堆填、违建加层 |

两层可独立开关，阈值可在 UI 调整。

## 安装

### 1. 把插件放到 WebODM 的 coreplugins

```bash
# 假设 WebODM 源码在 ~/WebODM
cp -r changedetect ~/WebODM/coreplugins/
```

### 2. 注册到 INSTALLED_APPS

编辑 `webodm/settings.py`，在 `INSTALLED_APPS` 列表末尾加：

```python
'coreplugins.changedetect.apps.ChangeDetectConfig',
```

### 3. 加 bind-mount（生产模式必须）

`docker-compose.yml` 里 `webapp.volumes` 加一行：

```yaml
- ./coreplugins/changedetect:/webodm/coreplugins/changedetect:z
```

`worker` 服务同样加一行（worker 也需要能 import 插件，否则 Celery
任务跑不起来）。

### 4. 跑迁移 + 重启

```bash
docker exec webapp python manage.py migrate changedetect
./webodm.sh restart webapp worker
```

启动日志应出现：

```
INFO Registered [coreplugins.changedetect.plugin]
```

### 5. 在 WebODM 后台启用插件

`/admin/app/plugin/` → 找到 "Change Detection" → 勾选 enabled。

## 使用

1. 打开一个任务的 2D 地图视图（必须有 `orthophoto.tif`，DSM 差分另需
   `dsm.tif`，处理任务时勾选 `--dsm`）。
2. 右上角工具栏点变化检测图标（两个相交的圆）。
3. 在面板里选"对比任务"——会自动列出同项目里其他已完成任务。
4. 调阈值（像素阈值、最小面积、高程阈值），点 **Run comparison**。
5. 进度条完成后，地图上叠加 GeoJSON 变化区域，弹窗显示方向 + 面积。
6. 每层有下载按钮（GeoJSON），可单独下载或叠加在 QGIS 里看。

## URL / API

所有端点挂载在 `/api/plugins/changedetect/` 下。

| Method | URL | 用途 |
|---|---|---|
| `POST` | `project/<project_id>/changedetect/create` | 创建对比对，启动 worker |
| `GET`  | `project/<project_id>/changedetect/list` | 列出项目下所有对比对 |
| `GET`  | `changedetect/<pair_id>/status` | 查状态 + 进度 + 结果 ID |
| `GET`  | `changedetect/<pair_id>/result/<result_id>/download` | 下载结果 GeoJSON |

### POST create 请求体

```json
{
  "task_before": "<uuid>",
  "task_after":  "<uuid>",
  "name":        "Q1 vs Q3",
  "options": {
    "pixel_threshold":    0.15,
    "pixel_min_area_m2":  10,
    "dsm_min_h_m":        0.5,
    "dsm_min_area_m2":    25,
    "enable_pixel":       true,
    "enable_dsm":         true,
    "crop_geojson":       null
  }
}
```

### POST create 响应

```json
{ "id": 42, "celery_task_id": "...", "status": "QUEUED", "name": "Q1 vs Q3" }
```

### Status 响应

```json
{
  "id": 42,
  "status": "DONE",
  "error_message": "",
  "updated_at": "2026-06-12T...",
  "results": [
    { "id": 7, "layer_type": "pixel", "stats": { "polygon_count": 23, "total_area_m2": 412.3, ... } },
    { "id": 8, "layer_type": "dsm",   "stats": { "polygon_count":  4, "total_area_m2":  98.1, ... } }
  ]
}
```

## 数据模型

| 表 | 用途 | 关键字段 |
|---|---|---|
| `changedetect_changepair` | 一对时序对比 | `task_before_id`, `task_after_id`, `status`, `options` (jsonb), `celery_task_id` |
| `changedetect_changeresult` | 一层结果 | `pair_id`, `layer_type` (pixel/dsm/dtm), `geojson_path`, `stats` (jsonb) |

ORM 而非 JSON 文件（参考 flight-planner/road-attributes 的约定）——
gunicorn 多 worker 共享，django-guardian 权限检查直接复用。

## 关键文件

```
coreplugins/changedetect/
├── __init__.py            # 懒加载 plugin（__getattr__，防 AppRegistryNotReady）
├── apps.py                # AppConfig (label=changedetect)
├── manifest.json
├── plugin.py              # 4 个 MountPoint
├── models.py              # ChangePair, ChangeResult
├── migrations/0001_initial.py
├── api.py                 # DRF views (4 个端点)
├── worker.py              # 时序差分管线 (gdalwarp → numpy diff → shapely)
└── public/
    ├── main.js            # 注册到 PluginsAPI.Map.willAddControls
    ├── Changedetect.jsx   # Leaflet 控件（地图工具栏按钮）
    ├── ChangedetectPanel.jsx
    ├── Changedetect.scss / ChangedetectPanel.scss
    └── icon.svg
```

## 算法细节

1. **公共范围对齐**：`gdalwarp -t_sps <b.crs> -tap -r bilinear` 把两
   幅正射/DSM 都投影到 `task_after` 的坐标系并对齐像素。
2. **像素差分**：按 band 归一化（uint8 → /255）后算 `|a-b|`，跨 band
   取均值，`> threshold` 即变化。`signed = mean(a) - mean(b)` 区分
   "变亮"（红色）和"变暗"（蓝色）。
3. **高程差分**：`dsm_after - dsm_before`，`> min_h` 算变化。`+1` 表
   示抬升（红色，如新建/堆填），`-1` 表示沉降（绿色，如开挖/塌陷）。
4. **矢量化**：`rasterio.features.shapes` 把布尔 mask 转 polygon。
5. **过滤**：按 `min_area_m2` 过滤小斑块；用 `pyproj` 投影到 EPSG:4326
   用于 GeoJSON，shapely 在源 CRS 算真实面积。
6. **进度上报**：`run_function_async(..., with_progress=True)` 注入
   `progress_callback`，worker 每步调用，前端 1.5s 轮询。

## 限制与待办

- L3 语义变化（SAM/SegFormer）暂未实现，按需要后续加。
- 两任务必须空间有重叠，否则返回 `No spatial overlap`。
- 大面积任务（>2GB ortho）建议分块；当前实现用 windowed read 但
  全图 diff 一次性加载到内存，>20k x 20k 像素的 GSD<2cm 数据集
  可能爆内存。
- 前端假设任务地图有 orthophoto，**当前任务** = `task_after`。
  对比列表只显示同项目其他已完成任务。
- 结果 GeoJSON 存到 `${MEDIA_ROOT}/changedetect/pair_<id>/`，
  不会自动清理——长期使用建议加 cron 清理过期 pair。

## 测试

Django 测试客户端快速冒烟（容器里）：

```python
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'webodm.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
admin = User.objects.filter(is_superuser=True).first()
c = Client()
c.force_login(admin)

# 列表（空）
print(c.get('/api/plugins/changedetect/project/1/changedetect/list').content)
# 状态
print(c.get('/api/plugins/changedetect/changedetect/1/status').content)
```

## 调试

- Celery worker 日志：`docker logs worker -f | grep changedetect`
- 结果文件位置：`docker exec webapp ls /webodm/app/media/changedetect/`
- 失败原因：API 状态返回 `error_message`，worker 写 `pair.error_message`
  字段（带 traceback 前 1500 字符）。
