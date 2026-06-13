"""
LLM client for the changedetect plugin.

We use the MiniMax-M3 model (the same one this codebase was authored
with) through the OpenAI-compatible chat-completions endpoint at
https://api.minimaxi.com/v1. The API key is read from
$MINIMAX_CN_API_KEY (set at container start by ufly_patches.py from
the host's ~/.hermes/.env), with a hard fallback to a dummy key that
will cause every LLM call to fail-fast with a clear error rather than
silently returning canned text.

Why a thin wrapper instead of using openai / anthropic SDKs directly?
The plugin's deployment target is the ufly embedded WebODM container,
which is intentionally slim — adding the openai SDK pulls in
httpx / pydantic / tqdm and bloats the image. A ~80-line urllib
client has no transitive deps and is trivially auditable.

Each public function returns a plain Python dict so the API layer can
JSON-serialize it without further wrapping. Errors are also returned
as dicts (never raised) so the caller's task-result JSON has a stable
shape and the UI can surface them as a toast.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Order of resolution: env var explicitly set on the container (ufly_patches
# forwards MINIMAX_CN_API_KEY from ~/.hermes/.env on every start) → hard
# default that lets imports succeed but every call returns a clear error.
API_KEY = (os.environ.get("MINIMAX_CN_API_KEY", "") or "").strip()
BASE_URL = os.environ.get("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/")
MODEL = os.environ.get("CHANGEDETECT_LLM_MODEL", "MiniMax-M3")
# Generous but bounded: AI summaries and change-recognition text fit
# comfortably in 1k tokens (the <think>...</think> block on top adds
# another ~500 tokens on the 4k model, so we still need some headroom
# for classify / recommend.  2048 covers all four functions in practice.
MAX_TOKENS = int(os.environ.get("CHANGEDETECT_LLM_MAX_TOKENS", "2048"))
# Default 120s — reasoning models often take 30-60s even on simple prompts.
# The previous 30s default was too tight: a few <think>…</think> blocks
# would push the response past 30s and we'd return a 500 to the user.
TIMEOUT_SEC = float(os.environ.get("CHANGEDETECT_LLM_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# Prompt templates
#
# Keep these in one place so we can iterate on the wording without
# scattering strings across the codebase. The {placeholders} match
# keys produced by `_format_*` helpers below.
# ---------------------------------------------------------------------------

# Used by `analyze_pair_changes` — produces a 1-2 paragraph
# Chinese-language interpretation of what the detected changes most
# likely represent, in plain prose suitable for pasting into a report.
PROMPT_ANALYZE = """你是无人机航测领域的资深分析员。请根据下面提供的两期正射影像变化检测结果，给出一段不超过 250 字的中文解读。要求：

1. 简洁直接，列出最显著的变化（按面积从大到小）
2. 对每类变化给出可能的原因推测（施工、拆除、季节性植被变化、临时堆场等）
3. 如果变化区域位于明显的人工地物（道路、建筑、桥梁）附近，提到这个位置关系
4. 避免使用"可能"、"或许"等模糊词汇，除非确实数据不足
5. 结尾给出一句话的"建议关注"（如建议现场核查的具体方向）

变化检测数据：
{change_data}

任务元数据：
- 项目：{project_name}
- 基准任务：{task_before_name}（{task_before_date} 航测）
- 对比任务：{task_after_name}（{task_after_date} 航测）
- 区域类型：{region_hint}

请直接输出解读，不要使用"以下是..."之类的开头。"""

# Used by `recommend_pairs` — for a project that has N tasks done, ask
# the LLM to pick the top-K pairs (ordered by usefulness) and explain
# each recommendation in one line.
PROMPT_RECOMMEND = """你是无人机航测规划助手。以下是一个项目里已完成的所有航测任务。请根据拍摄时间、命名、季节特征，推荐最多 {k} 对最适合做变化检测的 pair 组合。

要求：
1. 推荐顺序按"最可能发现显著变化"的可能性从高到低
2. 每对推荐给出 1 句话理由（时间间隔最合适 / 季节对比最强 / 命名显示明显建设阶段等）
3. 用 JSON 数组返回，格式：[{{"task_a_id": "uuid", "task_b_id": "uuid", "reason": "..."}}, ...]
4. 同一 task 不能在多对推荐里重复出现太多次（每 task 最多出现 2 次）
5. 基准任务（task_a）必须时间早于对比任务（task_b）
6. 只输出 JSON，不要其他文字

任务列表：
{tasks_json}"""

# Used by `summarize_for_report` — produces 2-3 sentence summary used
# as the first content page of the PDF report.
PROMPT_SUMMARY = """请根据以下无人机变化检测数据，写一段 100 字以内的中文摘要，用于 PDF 报告的"摘要"章节。要求：
1. 一句话概况（项目 + 任务对 + 变化规模）
2. 一句话主要发现（最显著的变化类型 + 位置/面积）
3. 一句话建议

变化检测数据：
{change_data}
任务对：{task_before_name} → {task_after_name}（{date_range}）"""

# ---------------------------------------------------------------------------
# Low-level HTTP wrapper
# ---------------------------------------------------------------------------

def _strip_think(text: str) -> str:
    """
    MiniMax-M3 (and a few other reasoning models) wraps its chain of
    thought in a <think>...</think> block even when asked for plain JSON.

    Gotcha: the model sometimes hits max_tokens *inside* the think block,
    leaving the response as an unclosed `<think>...` (no `</think>`).  A
    naive `re.sub(r"<think>.*?</think>", "", text, DOTALL)` will then
    *sweep the entire response* — the unclosed think absorbs the real
    answer, and the caller sees an empty string.

    Fix: only strip when we actually see a closing `</think>`.  If the
    block is unclosed, leave the text alone and log a warning so the
    caller can surface "answer truncated by max_tokens" to the user.
    """
    if not text or "<think>" not in text.lower():
        return text
    import re
    # Pair <think> with the LAST </think> (greedy from the *opening* is
    # what we want — non-greedy would match the empty string).  But we
    # also need to bail if there's no closing tag.
    m = re.search(r"<think>.*?</think>", text, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        # No closing tag — answer got truncated.  Preserve the text so
        # the caller still has *something* to parse / display.
        log.warning("_strip_think: <think> without closing </think>; "
                    "response likely truncated by max_tokens.  Preserving text.")
        return text.strip()
    return (text[:m.start()] + text[m.end():]).strip()


def _post_chat_completion(messages: List[Dict[str, str]],
                          temperature: float = 0.4,
                          max_tokens: int = MAX_TOKENS,
                          timeout: float = TIMEOUT_SEC,
                          response_format: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    POST to /chat/completions and return a normalized result dict:
        {ok: bool, text: str|None, error: str|None, model: str, usage: {...}, elapsed_ms: int}

    Never raises. Callers (worker / api) can branch on `ok`.
    """
    if not API_KEY:
        return {
            "ok": False,
            "text": None,
            "error": "MINIMAX_CN_API_KEY is not set in the container environment. "
                     "Run the ufly_patches.py sync from ~/.hermes/.env first.",
            "model": MODEL,
            "usage": {},
            "elapsed_ms": 0,
        }

    url = f"{BASE_URL}/chat/completions"
    body = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        body["response_format"] = response_format

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            "User-Agent": "webodm-changedetect/1.0",
        },
    )
    t0 = time.time()
    resp = None
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read().decode("utf-8")
        payload = json.loads(raw)
    except urllib.error.HTTPError as e:
        # Try to extract a meaningful error body
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message") or err_json.get("message") or err_body
        except Exception:
            err_msg = str(e)
        log.warning(f"LLM HTTP {e.code}: {err_msg[:300]}")
        return {
            "ok": False, "text": None,
            "error": f"HTTP {e.code}: {err_msg[:500]}",
            "model": MODEL, "usage": {}, "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except urllib.error.URLError as e:
        log.warning(f"LLM URLError: {e}")
        return {
            "ok": False, "text": None,
            "error": f"Network error reaching {BASE_URL}: {e.reason}",
            "model": MODEL, "usage": {}, "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except (TimeoutError, socket.timeout) as e:
        log.warning(f"LLM timeout after {timeout}s: {e}")
        return {
            "ok": False, "text": None,
            "error": f"请求 LLM 超时（{timeout}s）。这通常意味着模型思考时间过长或网络慢。"
                     "如需更长时间可通过 CHANGEDETECT_LLM_TIMEOUT 环境变量调大。",
            "model": MODEL, "usage": {}, "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except json.JSONDecodeError as e:
        log.warning(f"LLM transport JSON error: {e}")
        return {
            "ok": False, "text": None,
            "error": f"Transport error: {e}",
            "model": MODEL, "usage": {}, "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        # Catch-all: anything we forgot (SSL errors, ConnectionResetError,
        # RemoteDisconnected, etc.). Never let an LLM call raise into the
        # DRF view — it would surface as a 500 and the user would lose
        # whatever insight was being generated.
        import traceback
        log.warning(f"LLM unexpected error: {type(e).__name__}: {e}\n"
                    f"{traceback.format_exc()[:800]}")
        return {
            "ok": False, "text": None,
            "error": f"LLM 调用异常: {type(e).__name__}: {str(e)[:300]}",
            "model": MODEL, "usage": {}, "elapsed_ms": int((time.time() - t0) * 1000),
        }

    # Standard OpenAI-compatible shape
    try:
        choice = payload.get("choices", [{}])[0]
        text = (choice.get("message") or {}).get("content", "")
        usage = payload.get("usage", {})
        # Strip MiniMax-M3's <think>...</think> block (it always wraps reasoning
        # in one even with response_format=json_object; parsing the prose as
        # JSON then fails). We strip *before* the public functions do their
        # fence handling, so all callers see clean output.
        text = _strip_think(text)
        return {
            "ok": True,
            "text": text,
            "error": None,
            "model": payload.get("model", MODEL),
            "usage": usage,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except (KeyError, IndexError, TypeError) as e:
        log.warning(f"LLM response shape unexpected: {payload!r}")
        return {
            "ok": False, "text": None,
            "error": f"Unexpected response shape: {e}",
            "model": MODEL, "usage": {}, "elapsed_ms": int((time.time() - t0) * 1000),
        }


# ---------------------------------------------------------------------------
# Public domain helpers — each builds its own prompt from pair/project data.
# ---------------------------------------------------------------------------

def _format_change_data(pair, results) -> str:
    """
    Compact human-readable summary of a pair's results, suitable for
    stuffing into a prompt. The LLM gets totals, layer breakdown and
    the most prominent features per layer.
    """
    lines = []
    if pair.options:
        opts = pair.options
        if "pixel_threshold" in opts: lines.append(f"  像素阈值: {opts['pixel_threshold']}")
        if "dsm_min_h" in opts: lines.append(f"  DSM 最小 |Δh|: {opts['dsm_min_h']} m")
        if "min_area_m2" in opts: lines.append(f"  最小变化面积: {opts['min_area_m2']} m²")
    if not results:
        return "(无变化图层数据)"
    for r in results:
        stats = r.stats or {}
        lines.append(
            f"- 图层 {r.layer_type}: 共 {stats.get('polygon_count', 0)} 个变化区域, "
            f"总面积 {stats.get('total_area_m2', 0):.1f} m², "
            f"新增 {stats.get('added_area_m2', 0):.1f} m², "
            f"拆除 {stats.get('removed_area_m2', 0):.1f} m²"
        )
        # Include up to 3 largest features
        feats = []
        if r.geojson_path and os.path.exists(r.geojson_path):
            try:
                with open(r.geojson_path) as f:
                    geo = json.load(f)
                for ft in geo.get("features", []):
                    p = ft.get("properties") or {}
                    coords = (ft.get("geometry") or {}).get("coordinates") or []
                    centroid = None
                    if coords and isinstance(coords[0], list) and coords[0]:
                        ring = coords[0]
                        cx = sum(p[0] for p in ring) / len(ring)
                        cy = sum(p[1] for p in ring) / len(ring)
                        centroid = f"({cx:.5f}, {cy:.5f})"
                    feats.append({
                        "area_m2": p.get("area_m2", 0),
                        "centroid": centroid,
                        "direction": p.get("direction", "?"),
                    })
                feats.sort(key=lambda f: f.get("area_m2") or 0, reverse=True)
            except Exception as e:
                log.debug(f"could not read {r.geojson_path}: {e}")
        for i, f in enumerate(feats[:3]):
            lines.append(
                f"    #{i+1}: {f['area_m2']:.1f} m² {f['direction']} @ {f['centroid']}"
            )
    return "\n".join(lines) or "(无数据)"


def analyze_pair_changes(pair) -> Dict[str, Any]:
    """
    Generate a Chinese-language interpretation of a pair's change
    detection results, suitable for the report or for direct display
    in the UI as a "AI 解读" block.
    """
    project = pair.project
    results = list(pair.results.all())
    task_a = pair.task_before
    task_b = pair.task_after

    # Try to infer region from project name (very rough heuristic; better
    # than leaving the LLM with no context)
    pn = (project.name or "").lower()
    region_hint = "未指定"
    for kw, label in [("高速", "高速公路巡检"), ("路", "道路巡检"),
                      ("建筑", "建筑工地"), ("光伏", "光伏电站"),
                      ("电", "电力设施"), ("桥", "桥梁结构"),
                      ("矿", "矿区"), ("森林", "林业"), ("河", "河道"),
                      ("管道", "管道巡检")]:
        if kw in project.name or kw in pn:
            region_hint = label
            break

    prompt = PROMPT_ANALYZE.format(
        change_data=_format_change_data(pair, results),
        project_name=project.name or "(未命名项目)",
        task_before_name=task_a.name if task_a else "?",
        task_after_name=task_b.name if task_b else "?",
        task_before_date=task_a.created_at.strftime("%Y-%m-%d") if task_a else "?",
        task_after_date=task_b.created_at.strftime("%Y-%m-%d") if task_b else "?",
        region_hint=region_hint,
    )
    messages = [
        {"role": "system", "content": "你是严谨的中国无人机航测分析员，只基于给定数据回答。"},
        {"role": "user", "content": prompt},
    ]
    result = _post_chat_completion(messages, temperature=0.4, max_tokens=3000)
    if result["ok"] and result["text"]:
        result["text"] = result["text"].strip()
    return result


def recommend_pairs(project, k: int = 3) -> Dict[str, Any]:
    """
    Given a project's completed tasks, ask the LLM to recommend the
    top-k most useful pair combinations for change detection.

    Returns a dict that always includes an `ok` flag and either a
    `recommendations` list (ok=True) or an `error` string.
    """
    from app.models import Task
    tasks = list(
        Task.objects.filter(
            project=project,
            status__in=[Task.STATUSES.completed, 30, 40],  # tolerate ufly
        ).order_by("created_at")
    )
    if len(tasks) < 2:
        return {"ok": True, "recommendations": [],
                "model": MODEL, "elapsed_ms": 0,
                "note": "项目里任务少于 2 个，无法推荐 pair。"}

    # Build a compact JSON payload
    tasks_payload = []
    for t in tasks:
        # images_count may not exist on all WebODM forks (ufly removed it);
        # try a couple of common attribute paths, fall back to None.
        img_count = None
        for getter in (
            lambda: t.images_count() if callable(t.images_count) else t.images_count,
            lambda: t.pending_images.count(),
        ):
            try:
                img_count = getter()
                if img_count is not None:
                    break
            except Exception:
                continue
        tasks_payload.append({
            "id": str(t.id),
            "name": t.name or "(未命名)",
            "created_at": t.created_at.strftime("%Y-%m-%d") if t.created_at else "?",
            "status": "completed" if t.status in (30, 40) else str(t.status),
            "images_count": img_count,
        })

    prompt = PROMPT_RECOMMEND.format(k=k, tasks_json=json.dumps(tasks_payload, ensure_ascii=False, indent=2))
    messages = [
        {"role": "system", "content": "你是无人机航测规划助手，只输出 JSON。"},
        {"role": "user", "content": prompt},
    ]
    # JSON mode: tells the LLM to constrain output to JSON (model supports it)
    result = _post_chat_completion(
        messages, temperature=0.3, max_tokens=1200,
        response_format={"type": "json_object"},
    )
    if not result["ok"]:
        return result

    # Parse JSON; tolerate ```json fences or trailing prose
    text = result["text"].strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    try:
        # The model may wrap in a top-level object; unwrap common keys
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            for k_ in ("recommendations", "pairs", "results", "data"):
                if k_ in parsed and isinstance(parsed[k_], list):
                    parsed = parsed[k_]
                    break
            else:
                parsed = []
        if not isinstance(parsed, list):
            parsed = []
    except json.JSONDecodeError as e:
        log.warning(f"recommend_pairs: could not parse JSON: {e}; raw={text[:200]}")
        return {
            "ok": False, "text": text,
            "error": f"LLM 输出无法解析为 JSON: {e}",
            "model": result["model"], "usage": result["usage"],
            "elapsed_ms": result["elapsed_ms"],
        }

    # Validate IDs exist in our task set
    valid_ids = {str(t.id) for t in tasks}
    cleaned = []
    for r in parsed[:k]:
        if not isinstance(r, dict): continue
        a, b = r.get("task_a_id"), r.get("task_b_id")
        if a in valid_ids and b in valid_ids and a != b:
            cleaned.append({
                "task_a_id": a,
                "task_b_id": b,
                "reason": str(r.get("reason", ""))[:200],
            })
    result["recommendations"] = cleaned
    return result


def summarize_for_report(pair) -> Dict[str, Any]:
    """
    Short (≤100 字) Chinese summary used as the AI 摘要 page in the
    PDF report. Slightly lower max_tokens than analyze_pair_changes.
    """
    results = list(pair.results.all())
    task_a, task_b = pair.task_before, pair.task_after
    date_range = "—"
    if task_a and task_b:
        date_range = (f"{task_a.created_at.strftime('%Y-%m-%d')} → "
                      f"{task_b.created_at.strftime('%Y-%m-%d')}")
    prompt = PROMPT_SUMMARY.format(
        change_data=_format_change_data(pair, results),
        task_before_name=task_a.name if task_a else "?",
        task_after_name=task_b.name if task_b else "?",
        date_range=date_range,
    )
    messages = [
        {"role": "system", "content": "你是中国无人机航测报告写作助手。"},
        {"role": "user", "content": prompt},
    ]
    return _post_chat_completion(messages, temperature=0.4, max_tokens=400)


def classify_change_zone(zone: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classify a single detected change zone (a GeoJSON feature already
    computed by the change-detection worker) into a human-readable
    label + confidence.

    `zone` is a dict with keys:
        layer_type  (e.g. "pixel" or "dsm")
        area_m2     (float)
        direction   ("added" / "removed" / "changed")
        centroid    ([lng, lat])
        bbox        ([minx, miny, maxx, maxy])
        near_road   (bool, computed by the worker from the orthophoto)
        near_building (bool)
    Returns one of:
        {"ok": True, "label": "...", "confidence": 0.0-1.0, "rationale": "..."}
        or {"ok": False, "error": "..."}
    """
    allowed = {"building", "vehicle", "vegetation", "road", "construction",
               "demolition", "water", "bare_soil", "structure", "other"}
    prompt = f"""你是无人机变化检测分析员。下面是一个检测到的变化区域元数据，请根据这些信息判断它最可能是什么类型。

要求：
1. 从这些候选标签里选 1 个：{", ".join(sorted(allowed))}
2. 给出 0.0 到 1.0 的置信度
3. 1 句话理由（中文，最多 30 字）

变化区域元数据：
- 图层：{zone.get('layer_type', '?')}
- 面积：{zone.get('area_m2', 0):.1f} m²
- 方向：{zone.get('direction', '?')}
- 中心点：(经度 {zone.get('centroid', [0, 0])[0]:.5f}, 纬度 {zone.get('centroid', [0, 0])[1]:.5f})
- 临近道路：{zone.get('near_road', False)}
- 临近建筑：{zone.get('near_building', False)}
- 边界框：{zone.get('bbox', [])}

请严格按 JSON 输出，不要其他文字：
{{"label": "<候选之一>", "confidence": <0-1>, "rationale": "<一句话中文>"}}"""
    messages = [
        {"role": "system", "content": "你是严谨的航测分析员，严格输出 JSON。"},
        {"role": "user", "content": prompt},
    ]
    result = _post_chat_completion(
        messages, temperature=0.2, max_tokens=600,
        response_format={"type": "json_object"},
    )
    if not result["ok"]:
        return result
    text = result["text"].strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"未返回 JSON: {e}", "raw": text,
                "model": result["model"], "elapsed_ms": result["elapsed_ms"]}
    label = parsed.get("label", "other")
    if label not in allowed:
        label = "other"
    try:
        confidence = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    return {
        "ok": True,
        "label": label,
        "confidence": confidence,
        "rationale": str(parsed.get("rationale", ""))[:200],
        "model": result["model"],
        "elapsed_ms": result["elapsed_ms"],
    }
