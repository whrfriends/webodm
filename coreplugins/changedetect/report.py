"""
Change detection report generator.

Builds a multi-page PDF report for a finished ChangePair:
  - Page 1: cover (project name, pair id, status, generated_at, author)
  - Page 2: pair metadata (T1 / T2 task names, options used, run timestamps)
  - Page 3: data table (per-result stats: area, polygon count, layer type)
  - Page 4+: per-result map screenshots (caller-supplied PNGs),
             captioned and laid out at full page width

We use reportlab for layout (no headless browser required on the server).
The browser-side (main.js / ChangedetectPanel) captures the leaflet map
via html2canvas and POSTs the base64 PNGs to the API endpoint.

Multi-language: report is mostly numeric + English labels, so we keep it
simple.  Pair name + project name may be Chinese — reportlab handles
UTF-8 fine when we register a CJK font.
"""
import io
import os
import base64
import logging
import tempfile
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
    Table, TableStyle, PageBreak, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

log = logging.getLogger(__name__)

# --- Font registration --------------------------------------------------
# Try to register a CJK font so Chinese project / task names render
# correctly.  Reportlab ships no CJK font; on Debian/Ubuntu
# fonts-noto-cjk installs /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc.
_CJK_FONT_NAME = "NotoSansCJK"
_CJK_FONT_PATH_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]
_CJK_FONT_REGISTERED = False
for _p in _CJK_FONT_PATH_CANDIDATES:
    if os.path.exists(_p):
        try:
            pdfmetrics.registerFont(TTFont(_CJK_FONT_NAME, _p))
            _CJK_FONT_REGISTERED = True
            log.info(f"Registered CJK font {_CJK_FONT_NAME} from {_p}")
            break
        except Exception as e:
            log.warning(f"Failed to register {_p}: {e}")
if not _CJK_FONT_REGISTERED:
    log.warning("No CJK font found — Chinese characters may render as '?'. "
                "Install fonts-noto-cjk to fix.")


# --- Style helpers ------------------------------------------------------
def _styles():
    s = getSampleStyleSheet()
    base_font = _CJK_FONT_NAME if _CJK_FONT_REGISTERED else "Helvetica"
    s["Title"].fontName = base_font
    s["Title"].fontSize = 22
    s["Title"].leading = 28
    s["Title"].alignment = TA_CENTER

    s["Heading2"].fontName = base_font
    s["Heading2"].fontSize = 14
    s["Heading2"].leading = 18
    s["Heading2"].textColor = colors.HexColor("#2c3e50")

    s["Normal"].fontName = base_font
    s["Normal"].fontSize = 10
    s["Normal"].leading = 14

    s.add(ParagraphStyle(
        name="Subtitle", parent=s["Normal"],
        fontSize=12, textColor=colors.HexColor("#7f8c8d"),
        alignment=TA_CENTER, leading=16, fontName=base_font,
    ))
    s.add(ParagraphStyle(
        name="Caption", parent=s["Normal"],
        fontSize=9, textColor=colors.HexColor("#555"),
        alignment=TA_CENTER, leading=12, fontName=base_font,
    ))
    s.add(ParagraphStyle(
        name="StatusOK", parent=s["Normal"],
        fontSize=11, textColor=colors.HexColor("#27ae60"),
        alignment=TA_CENTER, fontName=base_font, leading=14,
    ))
    s.add(ParagraphStyle(
        name="StatusFail", parent=s["Normal"],
        fontSize=11, textColor=colors.HexColor("#c0392b"),
        alignment=TA_CENTER, fontName=base_font, leading=14,
    ))
    return s


def _status_paragraph(text, styles):
    if text.upper() == "DONE":
        return Paragraph(f"状态: {text}", styles["StatusOK"])
    return Paragraph(f"状态: {text}", styles["StatusFail"])


def _fmt_area(m2):
    if m2 is None:
        return "-"
    if m2 < 1:
        return f"{m2 * 10000:.1f} cm²"
    if m2 < 10000:
        return f"{m2:.1f} m²"
    return f"{m2/10000:.2f} ha"


def _safe_decode_png(b64_str):
    """Decode a base64 PNG. Accepts both raw b64 and 'data:image/png;base64,...'.
    Tolerant: returns None if input is None, dict, list, or anything non-str.
    """
    if not b64_str or not isinstance(b64_str, str):
        return None
    if "," in b64_str and b64_str.lstrip().startswith("data:"):
        b64_str = b64_str.split(",", 1)[1]
    b64_str = b64_str.strip().replace("\n", "").replace("\r", "")
    try:
        return base64.b64decode(b64_str)
    except Exception as e:
        log.warning(f"base64 decode failed: {e}")
        return None


# --- Main entry point ---------------------------------------------------
def build_report(pair, project, screenshot_b64=None, map_b64=None,
                 style_b64=None, title_suffix=""):
    """
    Build a PDF for a ChangePair.

    Parameters
    ----------
    pair : ChangePair instance
    project : Project instance (we use .name and .id)
    screenshot_b64 : str or None
        Base64 PNG of the full page / dashboard with the change data
        overlaid on the map.  This is the headline image.
    map_b64 : str or None
        Base64 PNG of just the leaflet map.  Shown on page 2.
    style_b64 : str or None
        Optional style/legend image (renderer + legend overlay).
    title_suffix : str
        Optional text appended to "变化检测报告".

    Returns
    -------
    bytes : PDF file content
    """
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
        title="变化检测报告" + (f" - {title_suffix}" if title_suffix else ""),
        author="WebODM changedetect plugin",
    )

    story = []
    # --- Page 1: Cover ---
    story.append(Spacer(1, 4*cm))
    story.append(Paragraph("变化检测报告", styles["Title"]))
    story.append(Spacer(1, 0.5*cm))
    if title_suffix:
        story.append(Paragraph(title_suffix, styles["Subtitle"]))
    story.append(Spacer(1, 1*cm))

    story.append(Paragraph(f"项目: {project.name or '(无名称)'}", styles["Heading2"]))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph(f"Pair ID: <b>#{pair.id}</b>", styles["Normal"]))
    if pair.name:
        story.append(Paragraph(f"标签: {pair.name}", styles["Normal"]))
    story.append(Spacer(1, 0.3*cm))
    story.append(_status_paragraph(pair.status, styles))
    story.append(Spacer(1, 0.3*cm))

    # Quick stats summary on the cover
    summary_rows = [["结果数", str(pair.results.count())]]
    total_area = 0
    total_polys = 0
    for r in pair.results.all():
        stats = r.stats or {}
        total_area += stats.get("total_area_m2", 0) or 0
        total_polys += stats.get("polygon_count", 0) or 0
    summary_rows.append(["总变化面积", _fmt_area(total_area)])
    summary_rows.append(["总 polygon 数", str(total_polys)])
    summary_rows.append(["生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    summary_table = Table(summary_rows, colWidths=[5*cm, 8*cm])
    summary_table.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), _CJK_FONT_NAME if _CJK_FONT_REGISTERED else "Helvetica", 10),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#ecf0f1")),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#2c3e50")),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("INNERGRID", (0,0), (-1,-1), 0.4, colors.HexColor("#bdc3c7")),
        ("BOX", (0,0), (-1,-1), 0.6, colors.HexColor("#95a5a6")),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(summary_table)
    story.append(PageBreak())

    # --- Page 2: Pair metadata + screenshot ---
    story.append(Paragraph("任务信息", styles["Heading2"]))
    story.append(Spacer(1, 0.3*cm))

    task_a = pair.task_before
    task_b = pair.task_after
    meta_rows = [
        ["基准任务 (T1)", task_a.name if task_a else "(缺失)", (task_a.created_at.strftime("%Y-%m-%d %H:%M") if task_a else "-")],
        ["对比任务 (T2)", task_b.name if task_b else "(缺失)", (task_b.created_at.strftime("%Y-%m-%d %H:%M") if task_b else "-")],
        ["创建时间", pair.created_at.strftime("%Y-%m-%d %H:%M:%S"), ""],
        ["更新时间", pair.updated_at.strftime("%Y-%m-%d %H:%M:%S"), ""],
    ]
    opts = pair.options or {}
    pix = opts.get('pixel_threshold')
    if pix is not None:
        meta_rows.append(["像素阈值", f"{pix:.3f}", ""])
    m2 = opts.get('min_area_m2')
    if m2 is not None:
        meta_rows.append(["最小面积 (m²)", f"{m2:.1f}", ""])
    dh = opts.get('dsm_min_h')
    if dh is not None:
        meta_rows.append(["DSM 最小 |Δh| (m)", f"{dh:.2f}", ""])
    if pair.error_message:
        meta_rows.append(["错误信息", str(pair.error_message)[:120], ""])
    meta_table = Table(meta_rows, colWidths=[4*cm, 7*cm, 4*cm])
    meta_table.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), _CJK_FONT_NAME if _CJK_FONT_REGISTERED else "Helvetica", 9),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#ecf0f1")),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#2c3e50")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("INNERGRID", (0,0), (-1,-1), 0.4, colors.HexColor("#bdc3c7")),
        ("BOX", (0,0), (-1,-1), 0.6, colors.HexColor("#95a5a6")),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.6*cm))

    # Full-page screenshot of the project dashboard with overlay
    img = _safe_decode_png(screenshot_b64) if screenshot_b64 else None
    if img:
        try:
            from PIL import Image as PILImage
            pil = PILImage.open(io.BytesIO(img))
            # fit to A4 portrait inner area, max width 17.7cm
            max_w, max_h = 17.7*cm, 22*cm
            iw, ih = pil.size
            scale = min(max_w / iw, max_h / ih)
            rw, rh = iw * scale, ih * scale
            # reportlab.platypus.Image accepts a file-like object too —
            # we pass a BytesIO so we never have to leak a tempfile.
            from reportlab.platypus import Image as RLImage
            story.append(Paragraph("叠加图（含变化区域 / 图例 / 地图）", styles["Heading2"]))
            story.append(Spacer(1, 0.2*cm))
            story.append(RLImage(io.BytesIO(img), width=rw, height=rh))
        except Exception as e:
            log.exception("Failed to embed screenshot")
            story.append(Paragraph(f"[截图渲染失败: {e}]", styles["Caption"]))
    else:
        story.append(Paragraph("[未提供截图]", styles["Caption"]))
    story.append(PageBreak())

    # --- Page 3: Per-layer stats table ---
    story.append(Paragraph("结果数据", styles["Heading2"]))
    story.append(Spacer(1, 0.3*cm))
    if pair.results.count() == 0:
        story.append(Paragraph("本 pair 无 result。", styles["Normal"]))
    else:
        data = [["#", "图层类型", "变化面积", "Polygon 数", "GeoJSON 文件"]]
        for r in pair.results.all():
            stats = r.stats or {}
            data.append([
                str(r.id),
                r.layer_type or "-",
                _fmt_area(stats.get("total_area_m2")),
                str(stats.get("polygon_count", 0)),
                (os.path.basename(r.geojson_path) if r.geojson_path else "-")[:30],
            ])
        tbl = Table(data, colWidths=[1.2*cm, 3*cm, 3*cm, 2.5*cm, 7*cm])
        tbl.setStyle(TableStyle([
            ("FONT", (0,0), (-1,-1), _CJK_FONT_NAME if _CJK_FONT_REGISTERED else "Helvetica", 9),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#34495e")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONT", (0,0), (-1,0), _CJK_FONT_NAME if _CJK_FONT_REGISTERED else "Helvetica-Bold", 9),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("INNERGRID", (0,0), (-1,-1), 0.4, colors.HexColor("#bdc3c7")),
            ("BOX", (0,0), (-1,-1), 0.6, colors.HexColor("#95a5a6")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8f9fa")]),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))
        story.append(tbl)

    # --- Optional: standalone map page ---
    map_img = _safe_decode_png(map_b64) if map_b64 else None
    if map_img:
        story.append(PageBreak())
        story.append(Paragraph("地图视图", styles["Heading2"]))
        story.append(Spacer(1, 0.3*cm))
        try:
            from reportlab.lib.utils import ImageReader
            from PIL import Image as PILImage
            pil = PILImage.open(io.BytesIO(map_img))
            max_w, max_h = 17.7*cm, 22*cm
            iw, ih = pil.size
            scale = min(max_w / iw, max_h / ih)
            reader = ImageReader(io.BytesIO(map_img))
            story.append(RLImage(reader, width=iw*scale, height=ih*scale))
        except Exception as e:
            story.append(Paragraph(f"[地图截图渲染失败: {e}]", styles["Caption"]))

    # Build PDF
    doc.build(story)
    return buf.getvalue()
