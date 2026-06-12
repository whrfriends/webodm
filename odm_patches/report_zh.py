import logging
import os
import subprocess
import tempfile

import PIL
from fpdf import FPDF
from opensfm import io
from opensfm.dataset import DataSet
from typing import Any, Dict

logger: logging.Logger = logging.getLogger(__name__)


# 中文字体（Noto Sans CJK 支持简繁体及日韩文）
ZH_FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
ZH_FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
ZH_FONT_FAMILY = "NotoSansCJK"


class Report:
    def __init__(self, data: DataSet, stats=None) -> None:
        self.output_path = os.path.join(data.data_path, "stats")
        self.dataset_name = os.path.basename(data.data_path)
        self.io_handler = data.io_handler

        self.mapi_light_light_green = [255, 255, 255]
        self.mapi_light_green = [0, 0, 0]
        self.mapi_light_grey = [243, 244, 247]
        self.mapi_dark_grey = [0, 0, 0]
        self.border_color = [100, 100, 100]

        self.pdf = FPDF("P", "mm", "A4")
        # 注册中文字体（仅当文件存在时）
        if os.path.isfile(ZH_FONT_REGULAR):
            try:
                self.pdf.add_font(ZH_FONT_FAMILY, "", ZH_FONT_REGULAR)
                if os.path.isfile(ZH_FONT_BOLD):
                    self.pdf.add_font(ZH_FONT_FAMILY, "B", ZH_FONT_BOLD)
                self.default_font = ZH_FONT_FAMILY
            except Exception as e:
                logger.warning("无法注册中文字体,回退到 Helvetica: %s" % e)
                self.default_font = "Helvetica"
        else:
            self.default_font = "Helvetica"
        self.pdf.add_page()

        self.title_size = 20
        self.h1 = 16
        self.h2 = 13
        self.h3 = 10
        self.text = 10
        self.small_text = 8
        self.margin = 10
        self.cell_height = 7
        self.total_size = 190

        if stats is not None:
            self.stats = stats
        else:
            self.stats = self._read_stats_file("stats.json")

        self.version = data.config["report_version"]
        self.name = data.config["report_name"]

    def save_report(self, filename: str) -> None:
        # pyre-fixme[28]: Unexpected keyword argument `dest`.
        bytestring = self.pdf.output(dest="S")
        if isinstance(bytestring, str):
            bytestring = bytestring.encode("utf8")

        with self.io_handler.open(
            os.path.join(self.output_path, filename), "wb"
        ) as fwb:
            fwb.write(bytestring)

    def _make_table(self, columns_names, rows, row_header=False) -> None:
        if len(rows) == 0:
            logger.warning("Cannot make table (rows missing)")
            return

        self.pdf.set_font(self.default_font, "", self.h3)
        self.pdf.set_line_width(0.3)

        columns_sizes = [int(self.total_size / len(rows[0]))] * len(rows[0])

        if columns_names:
            self.pdf.set_draw_color(*self.border_color)
            self.pdf.set_fill_color(*self.mapi_light_grey)
            for col, size in zip(columns_names, columns_sizes):
                self.pdf.rect(
                    self.pdf.get_x(),
                    self.pdf.get_y(),
                    size,
                    self.cell_height,
                    style="FD",
                )
                self.pdf.set_text_color(*self.mapi_dark_grey)
                # 表头用粗体
                self.pdf.set_font(self.default_font, "B", self.h3)
                self.pdf.cell(size, self.cell_height, col, align="C")
                self.pdf.set_font(self.default_font, "", self.h3)

        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.cell_height)

        for row in rows:
            for i, (col, size) in enumerate(zip(row, columns_sizes)):
                if i == 0 and row_header:
                    self.pdf.set_draw_color(*self.border_color)
                    self.pdf.set_fill_color(*self.mapi_light_light_green)
                self.pdf.cell(size, self.cell_height, col, align="L")
            self.pdf.set_xy(self.margin, self.pdf.get_y() + self.cell_height)

    def _read_stats_file(self, filename) -> Dict[str, Any]:
        file_path = os.path.join(self.output_path, filename)
        with self.io_handler.open_rt(file_path) as fin:
            return io.json_load(fin)

    def _read_gcp_stats_file(self, filename):
        file_path = os.path.join(self.output_path, "ground_control_points.json")

        with self.io_handler.open_rt(file_path) as fin:
            return io.json_load(fin)

    def _make_section(self, title: str) -> None:
        self.pdf.set_font(self.default_font, "B", self.h1)
        self.pdf.set_text_color(*self.mapi_dark_grey)
        self.pdf.cell(0, self.margin, title, align="L")
        self.pdf.set_xy(self.margin, self.pdf.get_y() + 1.5 * self.margin)

    def _make_subsection(self, title: str) -> None:
        self.pdf.set_xy(self.margin, self.pdf.get_y() - 0.5 * self.margin)
        self.pdf.set_font(self.default_font, "B", self.h2)
        self.pdf.set_text_color(*self.mapi_dark_grey)
        self.pdf.cell(0, self.margin, title, align="L")
        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin)

    def _make_centered_image(self, image_path: str, desired_height: float) -> None:
        with tempfile.TemporaryDirectory() as tmp_local_dir:
            local_image_path = os.path.join(tmp_local_dir, os.path.basename(image_path))
            with self.io_handler.open(local_image_path, "wb") as fwb:
                with self.io_handler.open(image_path, "rb") as f:
                    fwb.write(f.read())

            width, height = PIL.Image.open(local_image_path).size
            resized_width = width * desired_height / height
            if resized_width > self.total_size:
                resized_width = self.total_size
                desired_height = height * resized_width / width

            self.pdf.image(
                local_image_path,
                self.pdf.get_x() + self.total_size / 2 - resized_width / 2,
                self.pdf.get_y(),
                h=desired_height,
            )
            self.pdf.set_xy(
                self.margin, self.pdf.get_y() + desired_height + self.margin
            )

    def make_title(self) -> None:
        # 标题
        self.pdf.set_font(self.default_font, "B", self.title_size)
        self.pdf.set_text_color(*self.mapi_light_green)
        self.pdf.cell(0, self.margin, "质量报告", align="C")
        self.pdf.set_xy(self.margin, self.title_size)

        # 版本号
        version = f"版本 {self.version}" if self.version != "" else ""

        self.pdf.set_font(self.default_font, "", self.small_text)
        self.pdf.set_text_color(*self.mapi_dark_grey)
        self.pdf.cell(
            0, self.margin, f"使用 {self.name} {version} 处理".strip(), align="R"
        )
        self.pdf.set_xy(self.margin, self.pdf.get_y() + 2 * self.margin)

    def make_dataset_summary(self) -> None:
        self._make_section("数据集概览")

        rows = [
            #["数据集", self.dataset_name],
            ["日期", self.stats["processing_statistics"]["date"]],
            [
                "覆盖面积",
                f"{self.stats['processing_statistics']['area']/1e6:.6f} 平方公里",
            ],
            [
                "处理耗时",
                #f"{self.stats['processing_statistics']['steps_times']['Total Time']:.2f} 秒",
                self.stats['odm_processing_statistics']['total_time_human'],
            ],
            ["拍摄开始", self.stats["processing_statistics"]["start_date"]],
            ["拍摄结束", self.stats["processing_statistics"]["end_date"]],
        ]
        self._make_table(None, rows, True)
        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)

    def _has_meaningful_gcp(self) -> bool:
        return (
            self.stats["reconstruction_statistics"]["has_gcp"]
            and "average_error" in self.stats["gcp_errors"]
        )

    def make_processing_summary(self) -> None:
        self._make_section("处理结果概览")

        rec_shots, init_shots = (
            self.stats["reconstruction_statistics"]["reconstructed_shots_count"],
            self.stats["reconstruction_statistics"]["initial_shots_count"],
        )
        rec_points, init_points = (
            self.stats["reconstruction_statistics"]["reconstructed_points_count"],
            self.stats["reconstruction_statistics"]["initial_points_count"],
        )

        geo_string = []
        if self.stats["reconstruction_statistics"]["has_gps"]:
            geo_string.append("GPS")
        if self._has_meaningful_gcp():
            geo_string.append("GCP(地面控制点)")

        if "align" in self.stats:
            geo_string = ["对齐(Alignment)"]

        if len(geo_string) == 0:
            geo_string = ["无"]

        ratio_shots = rec_shots / init_shots * 100 if init_shots > 0 else -1
        rows = [
            [
                "重建影像",
                f"{rec_shots} / {init_shots} 张 ({ratio_shots:.1f}%)",
            ],
            [
                "稀疏重建点数",
                f"{rec_points} / {init_points} 个 ({rec_points/init_points*100:.1f}%)",
            ],
            [
                "检测特征点",
                f"{self.stats['features_statistics']['detected_features']['median']:,} 个",
            ],
            [
                "匹配特征点",
                f"{self.stats['features_statistics']['reconstructed_features']['median']:,} 个",
            ],
            ["地理参考", " 和 ".join(geo_string)],
        ]

        # 稠密点云(若可用)
        if self.stats.get('point_cloud_statistics'):
            if self.stats['point_cloud_statistics'].get('dense'):
                rows.insert(2, [
                    "稠密重建点数",
                    f"{self.stats['point_cloud_statistics']['stats']['statistic'][0]['count']:,} 个"
                ])

        # GSD(若可用)
        if self.stats['odm_processing_statistics'].get('average_gsd'):
            rows.insert(3, [
                "平均地面采样距离 (GSD)",
                f"{self.stats['odm_processing_statistics']['average_gsd']:.1f} 厘米"
            ])

        row_gps_gcp = [" / ".join(geo_string) + " 误差"]
        geo_errors = []

        if not "align" in self.stats:
            if self.stats["reconstruction_statistics"]["has_gps"]:
                geo_errors.append(f"{self.stats['gps_errors']['average_error']:.2f}")
            if self._has_meaningful_gcp():
                geo_errors.append(f"{self.stats['gcp_errors']['average_error']:.2f}")
        else:
            geo_errors.append(f"{(self.stats['align']['coarse']['rmse_3d'] + self.stats['align']['fine']['rmse_3d']):.2f}")

        if len(geo_errors) > 0:
            row_gps_gcp.append(" / ".join(geo_errors) + " 米")
            rows.append(row_gps_gcp)

        self._make_table(None, rows, True)
        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)

        topview_height = 110
        topview_grids = [
            f for f in self.io_handler.ls(self.output_path) if f.startswith("topview")
        ]
        if topview_grids:
            self._make_centered_image(
                os.path.join(self.output_path, topview_grids[0]), topview_height
            )

        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin)

    def make_processing_time_details(self) -> None:
        self._make_section("处理时间详情")

        # 阶段名中英对照
        stage_name_map = {
            "dataset": "数据集",
            "split": "分块",
            "merge": "合并",
            "opensfm": "OpenSfM 重建",
            "openmvs": "OpenMVS 稠密化",
            "odm_filterpoints": "点云过滤",
            "odm_meshing": "网格重建",
            "odm_texturing": "纹理映射",
            "odm_georeferencing": "地理参考",
            "odm_dem": "DEM 生成",
            "odm_orthophoto": "正射影像",
            "odm_report": "报告生成",
            "odm_postprocess": "后处理",
            "Total Time": "总时间",
        }
        original_columns = list(self.stats["processing_statistics"]["steps_times"].keys())
        columns_names = [stage_name_map.get(k, k) for k in original_columns]
        formatted_floats = []
        for v in self.stats["processing_statistics"]["steps_times"].values():
            formatted_floats.append(f"{v:.2f} 秒")
        rows = [formatted_floats]
        self._make_table(columns_names, rows)
        self.pdf.set_xy(self.margin, self.pdf.get_y() + 2 * self.margin)

    def make_gcp_error_details(self):
        self._make_section("地面控制点(GCP)详情")

        gcp_stats = self._read_gcp_stats_file("ground_control_points.json")

        gcp_rows = []
        chk_rows = []

        column_names = ["编号", "X 误差 (米)", "Y 误差 (米)", "Z 误差 (米)"]

        for gcp in gcp_stats:
            gcp_id = ''.join(c if ord(c) < 256 else '?' for c in gcp["id"])
            row = [gcp_id]
            row.append(f"{gcp['error'][0]:.3f}")
            row.append(f"{gcp['error'][1]:.3f}")
            row.append(f"{gcp['error'][2]:.3f}")

            if gcp_id.startswith("CHK-"):
                chk_rows.append(row)
            else:
                gcp_rows.append(row)

        self._make_table(column_names, gcp_rows)
        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)

        if len(chk_rows) > 0:
            self._make_section("检查点(Checkpoints)")
            self._make_table(column_names, chk_rows)
            self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)

    def make_gps_details(self) -> None:
        self._make_section("GPS / GCP / 3D 误差详情")

        type_name_map = {"gps": "GPS", "gcp": "GCP", "3d": "3D"}
        col_name_map = {
            "Mean": "平均值",
            "Standard Deviation": "标准差",
            "RMS Error": "均方根误差",
        }
        comp_name_map = {
            "x": "X 误差 (米)",
            "y": "Y 误差 (米)",
            "z": "Z 误差 (米)",
        }

        # GPS / GCP / 3D
        table_count = 0
        for error_type in ["gps", "gcp", "3d"]:
            rows = []
            base_columns = [type_name_map[error_type].upper(), "平均值", "标准差", "均方根误差"]
            if "average_error" not in self.stats[error_type + "_errors"]:
                continue
            for comp in ["x", "y", "z"]:
                row = [comp_name_map[comp]]
                row.append(f"{self.stats[error_type + '_errors']['mean'][comp]:.3f}")
                row.append(f"{self.stats[error_type +'_errors']['std'][comp]:.3f}")
                row.append(f"{self.stats[error_type +'_errors']['error'][comp]:.3f}")
                rows.append(row)

            rows.append(
                [
                    "总计",
                    "",
                    "",
                    f"{self.stats[error_type +'_errors']['average_error']:.3f}",
                ]
            )
            self._make_table(base_columns, rows)
            self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)
            table_count += 1

        if table_count > 0:
            abs_error_type = "gps" if table_count == 2 else "gcp"

            a_ce90 = self.stats[abs_error_type + "_errors"].get("ce90", 0)
            a_le90 = self.stats[abs_error_type + "_errors"].get("le90", 0)
            r_ce90 = self.stats["3d_errors"].get("ce90", 0)
            r_le90 = self.stats["3d_errors"].get("le90", 0)

            rows = []
            if a_ce90 > 0 and a_le90 > 0:
                rows += [[
                    "水平精度 CE90 (米)",
                    f"{a_ce90:.3f}",
                    f"{r_ce90:.3f}" if r_ce90 > 0 else "-",
                ],[
                    "垂直精度 LE90 (米)",
                    f"{a_le90:.3f}",
                    f"{r_le90:.3f}" if r_le90 > 0 else "-",
                ]]

            if rows:
                if table_count > 2:
                    self.add_page_break()
                self._make_table(["", "绝对", "相对"], rows, True)
                self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)

        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)

    def make_align_details(self) -> None:
        self._make_section("对齐误差详情")

        rows = []
        columns_names = ["", "DSM (粗)", "ICP (精)", "均方根误差"]
        comp_label = {"x": "X 误差 (米)", "y": "Y 误差 (米)", "z": "Z 误差 (米)", "3d": "3D 误差 (米)"}
        for comp in ["x", "y", "z", "3d"]:
            row = [comp_label[comp]]
            row.append(f"{self.stats['align']['coarse']['rmse_' + comp]:.3f}")
            row.append(f"{self.stats['align']['fine']['rmse_' + comp]:.3f}")
            row.append(f"{(self.stats['align']['coarse']['rmse_' + comp] + self.stats['align']['fine']['rmse_' + comp]):.3f}")
            rows.append(row)

        self._make_table(columns_names, rows)
        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)

        dsm_feature_matches = os.path.join(self.output_path, "codem", "dsm_feature_matches.png")
        if os.path.isfile(dsm_feature_matches):
            self._make_centered_image(dsm_feature_matches, 80)

    def make_features_details(self) -> None:
        self._make_section("特征点详情")

        heatmap_height = 60
        heatmaps = [
            f for f in self.io_handler.ls(self.output_path) if f.startswith("heatmap")
        ]
        if heatmaps:
            self._make_centered_image(
                os.path.join(self.output_path, heatmaps[0]), heatmap_height
            )
        if len(heatmaps) > 1:
            logger.warning("Please implement multi-model display")

        # 显示用的中文表头 + 内部 lookup key 一一对应
        columns_display = ["", "最小", "最大", "平均", "中位"]
        columns_lookup = ["min", "max", "mean", "median"]
        comp_label = {"detected_features": "检测", "reconstructed_features": "匹配"}
        rows = []
        for comp in ["detected_features", "reconstructed_features"]:
            row = [comp_label[comp]]
            for key in columns_lookup:
                row.append(
                    f"{self.stats['features_statistics'][comp][key]:.0f}"
                )
            rows.append(row)
        self._make_table(columns_display, rows)

        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin)

    def make_reconstruction_details(self) -> None:
        self._make_section("重建详情")

        rows = [
            [
                "平均重投影误差 (归一化 / 像素 / 角度)",
                (
                    f"{self.stats['reconstruction_statistics']['reprojection_error_normalized']:.2f} / "
                    f"{self.stats['reconstruction_statistics']['reprojection_error_pixels']:.2f} / "
                    f"{self.stats['reconstruction_statistics']['reprojection_error_angular']:.5f}"
                ),
            ],
            [
                "平均轨迹长度",
                f"{self.stats['reconstruction_statistics']['average_track_length']:.2f} 张影像",
            ],
            [
                "平均轨迹长度 (> 2)",
                f"{self.stats['reconstruction_statistics']['average_track_length_over_two']:.2f} 张影像",
            ],
        ]
        self._make_table(None, rows, True)
        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 1.5)

        residual_histogram_height = 60
        residual_histogram = [
            f
            for f in self.io_handler.ls(self.output_path)
            if f.startswith("residual_histogram")
        ]
        if residual_histogram:
            self._make_centered_image(
                os.path.join(self.output_path, residual_histogram[0]),
                residual_histogram_height,
            )
        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin)

    def make_camera_models_details(self) -> None:
        self._make_section("相机模型详情")

        for camera, params in self.stats["camera_errors"].items():
            residual_grids = [
                f
                for f in self.io_handler.ls(self.output_path)
                if f.startswith("residuals_" + str(camera.replace("/", "_")))
            ]
            if not residual_grids:
                continue

            initial = params["initial_values"]
            optimized = params["optimized_values"]
            names = [""] + list(initial.keys())
            names = [n if n != "aspect_ratio" else "长宽比" for n in names]

            rows = []
            rows.append(["初始"] + [f"{x:.4f}" for x in initial.values()])
            rows.append(["优化后"] + [f"{x:.4f}" for x in optimized.values()])

            self._make_subsection(camera)
            self._make_table(names, rows)
            self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)

            residual_grid_height = 100
            self._make_centered_image(
                os.path.join(self.output_path, residual_grids[0]), residual_grid_height
            )

    def make_rig_cameras_details(self) -> None:
        if len(self.stats["rig_errors"]) == 0:
            return

        self._make_section("相机阵列详情")

        columns_names = [
            "X 平移",
            "Y 平移",
            "Z 平移",
            "X 旋转",
            "Y 旋转",
            "Z 旋转",
        ]
        for rig_camera_id, params in self.stats["rig_errors"].items():
            initial = params["initial_values"]
            optimized = params["optimized_values"]

            rows = []
            r_init, t_init = initial["rotation"], initial["translation"]
            r_opt, t_opt = optimized["rotation"], optimized["translation"]
            rows.append(
                [
                    f"{t_init[0]:.4f} 米",
                    f"{t_init[1]:.4f} 米",
                    f"{t_init[2]:.4f} 米",
                    f"{r_init[0]:.4f}",
                    f"{r_init[1]:.4f}",
                    f"{r_init[2]:.4f}",
                ]
            )
            rows.append(
                [
                    f"{t_opt[0]:.4f} 米",
                    f"{t_opt[1]:.4f} 米",
                    f"{t_opt[2]:.4f} 米",
                    f"{r_opt[0]:.4f}",
                    f"{r_opt[1]:.4f}",
                    f"{r_opt[2]:.4f}",
                ]
            )

            self._make_subsection(rig_camera_id)
            self._make_table(columns_names, rows)
            self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)

    def make_tracks_details(self) -> None:
        self._make_section("轨迹详情")
        matchgraph_height = 80
        matchgraph = [
            f
            for f in self.io_handler.ls(self.output_path)
            if f.startswith("matchgraph")
        ]
        if matchgraph:
            self._make_centered_image(
                os.path.join(self.output_path, matchgraph[0]), matchgraph_height
            )

        histogram = self.stats["reconstruction_statistics"]["histogram_track_length"]
        start_length, end_length = 2, 10
        row_length = ["长度"]
        for length, _ in sorted(histogram.items(), key=lambda x: int(x[0])):
            if int(length) < start_length or int(length) > end_length:
                continue
            row_length.append(length)
        row_count = ["数量"]
        for length, count in sorted(histogram.items(), key=lambda x: int(x[0])):
            if int(length) < start_length or int(length) > end_length:
                continue
            row_count.append(f"{count}")

        self._make_table(None, [row_length, row_count], True)

        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin)

    def add_page_break(self) -> None:
        self.pdf.add_page("P")

    def make_survey_data(self):
        self._make_section("航测重叠度")

        self._make_centered_image(
            os.path.join(self.output_path, "overlap.png"), 90
        )
        self._make_centered_image(
            os.path.join(self.output_path, "overlap_diagram_legend.png"), 3
        )

        self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin / 2)


    def _add_image_label(self, text):
        self.pdf.set_font_size(self.small_text)
        self.pdf.set_font(self.default_font, "", self.small_text)
        self.pdf.text(self.pdf.get_x() + self.total_size / 2 - self.pdf.get_string_width(text) / 2, self.pdf.get_y() - 5, text)


    def make_preview(self):
        ortho = os.path.join(self.output_path, "ortho.png")
        dsm = os.path.join(self.output_path, "dsm.png")
        dtm = os.path.join(self.output_path, "dtm.png")
        count = 0

        if os.path.isfile(ortho) or os.path.isfile(dsm):
            self._make_section("预览图")

            if os.path.isfile(ortho):
                self._make_centered_image(
                    os.path.join(self.output_path, ortho), 110
                )
                self._add_image_label("正射影像")
                count += 1

            if os.path.isfile(dsm) and self.stats.get('dsm_statistics'):
                self._make_centered_image(
                    os.path.join(self.output_path, dsm), 110
                )
                self._add_image_label("数字表面模型(DSM)")

                self._make_centered_image(
                    os.path.join(self.output_path, "dsm_gradient.png"), 4
                )
                self.pdf.set_font_size(self.small_text)
                self.pdf.set_font(self.default_font, "", self.small_text)
                min_text = "{:,.2f}米".format(self.stats['dsm_statistics']['min'])
                max_text = "{:,.2f}米".format(self.stats['dsm_statistics']['max'])
                self.pdf.text(self.pdf.get_x() + 40, self.pdf.get_y() - 5, min_text)
                self.pdf.text(self.pdf.get_x() + 40 + 110.5 - self.pdf.get_string_width(max_text), self.pdf.get_y() - 5, max_text)
                count += 1

            if os.path.isfile(dtm) and self.stats.get('dtm_statistics'):
                if count >= 2:
                    self.add_page_break()

                self._make_centered_image(
                    os.path.join(self.output_path, dtm), 110
                )
                self._add_image_label("数字高程模型(DTM)")

                self._make_centered_image(
                    os.path.join(self.output_path, "dsm_gradient.png"), 4
                )
                self.pdf.set_font_size(self.small_text)
                self.pdf.set_font(self.default_font, "", self.small_text)
                min_text = "{:,.2f}米".format(self.stats['dtm_statistics']['min'])
                max_text = "{:,.2f}米".format(self.stats['dtm_statistics']['max'])
                self.pdf.text(self.pdf.get_x() + 40, self.pdf.get_y() - 5, min_text)
                self.pdf.text(self.pdf.get_x() + 40 + 110.5 - self.pdf.get_string_width(max_text), self.pdf.get_y() - 5, max_text)

            self.pdf.set_xy(self.margin, self.pdf.get_y() + self.margin)

            return True

    def generate_report(self) -> None:
        self.make_title()
        self.make_dataset_summary()
        self.make_processing_summary()
        self.add_page_break()

        if self.make_preview():
            self.add_page_break()

        if os.path.isfile(os.path.join(self.output_path, "overlap.png")):
            self.make_survey_data()

        if "align" not in self.stats:
            self.make_gps_details()

            if os.path.isfile(os.path.join(self.output_path, "ground_control_points.json")):
                self.make_gcp_error_details()
        else:
            self.make_align_details()

        self.add_page_break()

        self.make_features_details()
        self.make_reconstruction_details()
        self.add_page_break()

        self.make_tracks_details()
        self.make_camera_models_details()
        #self.make_rig_cameras_details()
