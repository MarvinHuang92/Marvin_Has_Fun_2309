# -*- coding: utf-8 -*-

import asyncio
import datetime
import io
import logging
import os
import re

from PIL import Image, ImageDraw, ImageFont

import common_config as cfg

# winsdk(Windows 自带 OCR)按需导入
try:
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    _WINSDK_AVAILABLE = True
except ImportError:
    _WINSDK_AVAILABLE = False


# =====================================================================
# 异步辅助
# =====================================================================

def _run_async(coro):
    """在临时事件循环中运行一个异步协程。

    在 Tkinter mainloop 里也能安全调用：每次新建并关闭一个事件循环。
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =====================================================================
# 模块状态与通用辅助
# =====================================================================

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))

# 跨按钮调用保留的中间状态
last_state = {
    "params": None,
    "box": None,            # 裁剪区域在整图中的位置 (x, y, w, h)
    "crop": None,           # 裁剪出的小图 (PIL.Image)
    "recognized": "",       # 识别到的文本
    "new_value": "",        # 计算后的文本
    "new_value_num": None,  # 计算后的数值（用于选色）
    "has_value": False,     # 当前区域是否有有效数值
    "grid_recognized": None,  # 5x5 识别文本网格（""=网格外，"未识别"=无效）
    "grid_new": None,         # 5x5 计算文本网格
    "grid_boxes": None,       # 5x5 每个格的区域 (x, y, w, h)
    "grid_crops": None,       # 5x5 每个格的裁剪图
    "grid_origin": None,      # 网格原点 (x, y)
    "cell_colors": None,      # 5x5 每个格的颜色类型(0-5)，未知=4(灰)
    "warnings": [],           # 提取/格式检查告警列表（颜色类型无法识别、高亮格数量不符等）
    "region2": None,          # 区域2（月收益）状态：{box, crop, recognized, color}
    "region2_new": "",       # 区域2 计算后的文本
    "region3": None,          # 区域3（个股收益）状态：{boxes, recognized, colors}
    "region3_new": [],        # 区域3 计算后的文本（1x5）
}


def _resolve_path(rel_path):
    """把相对于项目根目录(reward_img_gen/)的路径转成绝对路径。"""
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.abspath(os.path.join(_PROJECT_ROOT, rel_path))


def set_status(text):
    """把状态信息写到 GUI 的状态栏（没有 GUI 时只记日志）。"""
    var = globals().get("status_var")
    if var is not None:
        try:
            var.set(str(text))
        except Exception:
            pass
    logging.info("%s", text)


def _set_var(name, value):
    var = globals().get(name)
    if var is not None:
        try:
            var.set(value)
        except Exception:
            pass


def _set_grid_cell(grid_attr, row, col, value):
    """把值写入 2D 网格变量（GUI 结果区的 5x5 网格）。"""
    grid = globals().get(grid_attr)
    if grid is None:
        return
    try:
        if 0 <= row < len(grid) and 0 <= col < len(grid[row]):
            grid[row][col].set(value)
    except Exception:
        pass


def _get_grid_cell(grid_attr, row, col):
    """读取 2D 网格变量的单元格值；不存在或越界返回空串。"""
    grid = globals().get(grid_attr)
    if grid is None:
        return ""
    try:
        if 0 <= row < len(grid) and 0 <= col < len(grid[row]):
            cell = grid[row][col]
            return str(cell.get()).strip() if hasattr(cell, "get") else str(cell).strip()
    except Exception:
        pass
    return ""


def _get_var_text(name):
    var = globals().get(name)
    if var is None:
        return ""
    try:
        return str(var.get())
    except Exception:
        return ""


def _get_recognized_grid():
    """返回当前 5x5 识别文本网格。

    优先读 GUI 可编辑网格变量（用户可手改识别值），否则回退到 last_state。
    """
    grid = globals().get("recognized_grid_vars")
    if grid is not None:
        try:
            rows = []
            for row in grid:
                rows.append([str(cell.get()).strip() if hasattr(cell, "get") else str(cell).strip()
                             for cell in row])
            if len(rows) == 5 and all(len(r) == 5 for r in rows):
                return rows
        except Exception:
            pass
    return last_state.get("grid_recognized")


def _get_region2_recognized():
    """读取区域2 当前识别值：优先 GUI 可编辑网格（含用户手改），无 GUI 时回退 last_state。"""
    if globals().get("recognized_region2_vars") is not None:
        return _get_grid_cell("recognized_region2_vars", 0, 0)
    return (last_state.get("region2") or {}).get("recognized") or ""


def _get_region3_recognized():
    """读取区域3 当前识别值列表（5 个）：优先 GUI 可编辑网格（含用户手改），无 GUI 时回退 last_state。"""
    if globals().get("recognized_region3_vars") is not None:
        return [_get_grid_cell("recognized_region3_vars", 0, i) for i in range(5)]
    return (last_state.get("region3") or {}).get("recognized") or []


# =====================================================================
# 识别图片中的文字(OCR)
# =====================================================================

def _pil_to_software_bitmap(image):
    """把 PIL.Image 转成 winsdk 的 SoftwareBitmap。"""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(buf.getvalue())

    async def _convert():
        await writer.store_async()
        await writer.flush_async()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        return await decoder.get_software_bitmap_async()

    return _run_async(_convert())


def _pick_ocr_language(language="auto"):
    """按语言标签精确选择 OCR 引擎语言；找不到抛错。"""
    langs = list(OcrEngine.available_recognizer_languages)
    if not langs:
        return None
    for lang in langs:
        if lang.language_tag.lower() == language.strip().lower():
            return lang
    raise ValueError("OCR 语言不可用: %s(可用: %s)"
                     % (language, [l.language_tag for l in langs]))


def _create_engine_by_prefix(prefix):
    """创建指定语言前缀(如 zh / en)的 OCR 引擎；没有则返回 None。"""
    langs = list(OcrEngine.available_recognizer_languages)
    matches = [l for l in langs if l.language_tag.lower().startswith(prefix)]
    if not matches:
        return None
    best = max(matches, key=lambda l: l.language_tag)
    return OcrEngine.try_create_from_language(best)


def _recognize(engine, software_bitmap):
    """用指定引擎识别 SoftwareBitmap, 返回文本。"""
    if engine is None:
        return ""

    async def _run():
        result = await engine.recognize_async(software_bitmap)
        return result.text or ""

    return _run_async(_run()).strip()


def _is_clean_number(text):
    """宽松判断文本是否像"干净的数值/百分比"(可含正负号、小数点、千分位逗号、百分号)。"""
    if not text:
        return False
    s = text.replace(" ", "")
    # 同时允许半角%和全角％(中文引擎可能输出全角百分号，不是书写错误)
    allowed = set("0123456789+-.,%％")
    if not all(c in allowed for c in s):
        return False
    return any(c.isdigit() for c in s)


def _fullwidth_penalty(text):
    """计算文本里全角标点数量, 用于比较两个 OCR 结果的"数字干净度"。"""
    return sum(1 for c in text if c in "．，－％：；（）") # 这里列出全角标点，不是书写错误，不要改成半角！


def _auto_recognize(software_bitmap):
    """智能识别：数字区域用英文引擎(负号/小数点/千分位更准), 中文区域用中文引擎。"""
    texts = []  # (text, prefix)
    for prefix in ("zh", "en"):
        engine = _create_engine_by_prefix(prefix)
        if engine is not None:
            texts.append((_recognize(engine, software_bitmap), prefix))

    if not texts:
        return ""

    clean = [t for t, _p in texts if _is_clean_number(t)]
    if clean:
        # 都像数字时, 选全角标点更少的那个(英文引擎通常为 0)
        return min(clean, key=_fullwidth_penalty)

    zh = next((t for t, p in texts if p == "zh"), "")
    return zh or texts[0][0]


def extract_text_from_image(image, *, language="auto"):
    """识别图片中的文字, 返回文本字符串。

    参数：
        image    : PIL.Image, 或图片文件路径(str / os.PathLike)
        language : 识别语言标签, 如 "zh-CN"、"en-US";
                   默认 "auto"：自动判断 —— 数字区域优先英文引擎, 
                   含中文时用中文引擎
    返回：
        识别出的文本(去除首尾空白)
    """
    if not _WINSDK_AVAILABLE:
        raise RuntimeError(
            "未安装 winsdk, 无法使用 OCR。请先安装:\n"
            "  D:/Programming/Python_dir_38/python.exe -m pip install winsdk"
        )

    if isinstance(image, (str, os.PathLike)):
        image = Image.open(os.fspath(image))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    software_bitmap = _pil_to_software_bitmap(image)

    if language and language.strip().lower() != "auto":
        language_obj = _pick_ocr_language(language)
        engine = OcrEngine.try_create_from_language(language_obj)
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("无法创建 OCR 引擎(系统可能缺少 OCR 语言包)")
        return _recognize(engine, software_bitmap)

    return _auto_recognize(software_bitmap)


# =====================================================================
# 将文字生成为图片
# =====================================================================

def _normalize_color(color):
    """把颜色统一成 (r, g, b) 元组, 支持元组 / 列表 / '#RRGGBB' / 'RRGGBB'。"""
    if color is None:
        return (0, 0, 0)
    if isinstance(color, str):
        color = color.strip()
        if color.startswith("#"):
            color = color[1:]
        if len(color) == 6:
            return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
        if len(color) == 3:
            return tuple(int(c * 2, 16) for c in color)
        raise ValueError("无法解析颜色: %r" % color)
    return tuple(int(c) for c in color)


def _font_candidates(font_name):
    """根据字体名列出候选路径, 找不到就返回空列表。"""
    name = os.path.basename(font_name)
    candidates = []
    if os.path.isabs(font_name) or os.path.exists(font_name):
        candidates.append(font_name)
    for base in (getattr(cfg, "FONT_DIR", None), "C:/Windows/Fonts"):
        if not base:
            continue
        candidates.append(os.path.join(base, name))
        if not os.path.splitext(name)[1]:  # 没写扩展名时补上常见扩展名
            candidates.append(os.path.join(base, name + ".ttf"))
            candidates.append(os.path.join(base, name + ".ttc"))
    return candidates


def _load_font(font_name=None, font_size=None):
    """加载字体；找不到时回退到 PIL 默认字体。"""
    if font_name is None:
        font_name = cfg.FONT_NAME
    if font_size is None:
        font_size = cfg.FONT_SIZE

    for path in _font_candidates(font_name):
        if os.path.exists(path):
            return ImageFont.truetype(path, font_size)

    logging.warning("字体未找到: %s, 使用 PIL 默认字体", font_name)
    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:  # 老版本 PIL 不支持 size 参数
        return ImageFont.load_default()


def _measure_text(text, font):
    """测量文字实际宽高。"""
    probe = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(probe)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _fit_font(text, size, font_name, max_text_height=None):
    """在给定区域内二分查找能放下文字的最大字号，返回 ImageFont。

    max_text_height 不为 None 时，额外限制文字高度不超过该值（用于短数字
    被高度撑得过大时统一限高）。
    """
    pad_x, pad_y = 6, 4
    max_w = max(1, size[0] - 2 * pad_x)
    max_h = max(1, size[1] - 2 * pad_y)
    if max_text_height is not None and max_text_height > 0:
        max_h = min(max_h, int(max_text_height))
    lo, hi = 6, 300
    best_font = _load_font(font_name, lo)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(font_name, mid)
        tw, th = _measure_text(text, font)
        if tw <= max_w and th <= max_h:
            best_font = font
            lo = mid + 1
        else:
            hi = mid - 1
    return best_font


def render_text_to_image(text, *, size=None, fg_color=None, bg_color=None,
                         font_name=None, font_size=None, height_scale=None,
                         max_text_height=None, center_by_ink=True, align="center"):
    """把文字绘制成一张 PIL.Image。

    参数：
        text         : 要绘制的文字
        size         : (宽, 高)；为 None 时根据文字自动适配
        fg_color     : 前景色(文字颜色), RGB 元组 / '#RRGGBB' / 颜色名
        bg_color     : 背景色, 同上；默认白色
        font_name    : 字体文件路径或字体文件名(在 FONT_DIR 中查找)
        font_size    : 字号；指定 size 且 font_size 为 None 时自动适配
        height_scale : 渲染后高度缩放倍率（宽度不变，垂直拉伸）；None 表示不缩放
        max_text_height : 限制文字最大高度(px)；None 表示不限制
        center_by_ink : True=按墨迹实际包围盒定位(数值回填用)；
                        False=按 em 框定位(模板匹配等需保持稳定的场景用)
        align        : 水平对齐，'center'(默认) / 'left' / 'right'
    返回：
        PIL.Image
    """
    text = str(text)
    fg = _normalize_color(fg_color if fg_color is not None else cfg.DEFAULT_FG_COLOR)
    bg = _normalize_color(bg_color if bg_color is not None else cfg.DEFAULT_BG_COLOR)

    if size is not None and font_size is None:
        font = _fit_font(text, size, font_name, max_text_height=max_text_height)
    else:
        font = _load_font(font_name, font_size)

    text_w, text_h = _measure_text(text, font)

    if size is None:
        pad_x, pad_y = 8, 8
        width, height = text_w + 2 * pad_x, text_h + 2 * pad_y
    else:
        pad_x = 6
        width, height = int(size[0]), int(size[1])

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    if center_by_ink:
        # 先画文字到纯黑掩膜，求出"墨迹"实际包围盒，再按墨迹定位。
        # 直接按 textbbox 定位会把 em 框上方的空白也算进去，导致数字整体偏下。
        probe = Image.new("L", (width, height), 0)
        pdraw = ImageDraw.Draw(probe)
        pdraw.text((0, 0), text, font=font, fill=255)
        ink_bbox = probe.getbbox()
        if ink_bbox:
            left, top, right, bottom = ink_bbox
            ink_w = right - left
            ink_h = bottom - top
            if align == "left":
                x = pad_x
            elif align == "right":
                x = width - pad_x - ink_w
            else:
                x = (width - ink_w) // 2
            y = (height - ink_h) // 2
            draw.text((x - left, y - top), text, font=font, fill=fg)
        else:
            draw.text((0, 0), text, font=font, fill=fg)
    else:
        # 模板匹配等场景：按 em 框定位（保持稳定、与原行为一致）
        if align == "left":
            x = pad_x
        elif align == "right":
            x = width - pad_x - text_w
        else:
            x = (width - text_w) // 2
        y = (height - text_h) // 2
        draw.text((x, y), text, font=font, fill=fg)

    if height_scale and height_scale != 1:
        new_h = max(1, int(round(height * height_scale)))
        img = img.resize((width, new_h), Image.LANCZOS)
    return img


# =====================================================================
# 流程核心逻辑
# =====================================================================

_NUM_PATTERN = re.compile(r"^[+-]?[\d,]*\.?\d+$")


def _norm_text(s):
    """归一化 OCR 文本用于比较：去掉空格，全角标点转半角。"""
    if not s:
        return ""
    mapping = {"．": ".", "，": ",", "－": "-", "％": "%", "：": ":", "；": ";"}
    return "".join(mapping.get(ch, ch) for ch in s.replace(" ", ""))


def _word_box(word):
    r = word.bounding_rect
    return (int(r.x), int(r.y), int(r.width), int(r.height))


def locate_keyword(image, keyword):
    """在整图中定位 keyword，返回其包围盒 (x, y, w, h)；找不到返回 None。

    策略：
      1) OCR 中文引擎识别整图：先精确匹配单个词；
      2) 再把所有词归一化拼接，找包含 keyword 的词段（处理引擎在字之间插空格）；
      3) OCR 找不到时，用模板匹配（numpy 归一化互相关）兜底。
    """
    kw_norm = _norm_text(keyword)
    if not kw_norm:
        return None

    software_bitmap = _pil_to_software_bitmap(image)
    engine = _create_engine_by_prefix("zh") or _create_engine_by_prefix("en")
    if engine is not None:
        async def _run():
            return await engine.recognize_async(software_bitmap)

        result = _run_async(_run())
        words = [w for line in result.lines for w in line.words]
        parts = [(w, _norm_text(w.text)) for w in words if _norm_text(w.text)]

        # 1) 精确匹配单个词
        for w, n in parts:
            if n == kw_norm:
                return _word_box(w)

        # 2) 拼接后找包含 keyword 的词段
        concat = "".join(n for _w, n in parts)
        pos = concat.find(kw_norm)
        if pos >= 0:
            end = pos + len(kw_norm)
            spans = []
            cur = 0
            for w, n in parts:
                spans.append((w, cur, cur + len(n)))
                cur += len(n)
            sel = [w for w, s, e in spans if s < end and e > pos]
            if sel:
                x0 = min(_word_box(w)[0] for w in sel)
                y0 = min(_word_box(w)[1] for w in sel)
                x1 = max(_word_box(w)[0] + _word_box(w)[2] for w in sel)
                y1 = max(_word_box(w)[1] + _word_box(w)[3] for w in sel)
                return (x0, y0, x1 - x0, y1 - y0)

    # 3) 模板匹配兜底
    box = _template_match(image, keyword)
    if box is not None:
        return box
    return None


_POS_RE = re.compile(r"\(\s*(\d+)\s*,\s*(\d+)\s*\)")


def _get_last_keyword_position():
    """从 locate_result_var 解析上次关键词位置 (X, Y)；无有效值返回 None。"""
    text = _get_var_text("locate_result_var")
    m = _POS_RE.search(text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _locate_keyword_optimized(image, keyword):
    """定位关键词：优先在上次位置附近的小区域搜索，找不到再全图搜索。

    返回关键词包围盒 (x, y, w, h)；找不到返回 None。
    """
    roi = cfg.LOCATE_ROI_SIZE
    pad = cfg.LOCATE_ROI_PAD
    pos = _get_last_keyword_position()
    if pos is not None:
        x0 = max(0, pos[0] - pad[0])
        y0 = max(0, pos[1] - pad[1])
        x1 = min(image.width, x0 + roi[0])
        y1 = min(image.height, y0 + roi[1])
        if x1 > x0 and y1 > y0:
            region = image.crop((x0, y0, x1, y1))
            box = locate_keyword(region, keyword)
            if box is not None:
                return (box[0] + x0, box[1] + y0, box[2], box[3])
    return locate_keyword(image, keyword)


def _ncc_match(gray, t):
    """用 FFT + 积分图计算归一化互相关，返回 (最大得分, (x, y))。"""
    import numpy as np
    from numpy.fft import fft2, ifft2

    H, W = gray.shape
    th, tw = t.shape
    if th > H or tw > W:
        return -1.0, (0, 0)

    t_mean = t.mean()
    t_var = ((t - t_mean) ** 2).sum()

    fI = fft2(gray)
    fT = fft2(t[::-1, ::-1], s=(H, W))
    corr = ifft2(fI * fT).real

    # 二维积分图：S[i+1, j+1] = sum(gray[0:i+1, 0:j+1])
    S = np.zeros((H + 1, W + 1))
    S[1:, 1:] = np.cumsum(np.cumsum(gray, axis=0), axis=1)
    S2 = np.zeros((H + 1, W + 1))
    S2[1:, 1:] = np.cumsum(np.cumsum(gray * gray, axis=0), axis=1)

    sh, sw = H - th + 1, W - tw + 1
    y0 = np.arange(sh)[:, None]
    x0 = np.arange(sw)[None, :]
    y1, x1 = y0 + th, x0 + tw

    local_sum = S[y1, x1] - S[y0, x1] - S[y1, x0] + S[y0, x0]
    local_sum2 = S2[y1, x1] - S2[y0, x1] - S2[y1, x0] + S2[y0, x0]
    count = th * tw
    local_mean = local_sum / count
    local_var = local_sum2 / count - local_mean * local_mean

    # FFT 相关值的索引有 (th-1, tw-1) 偏移：窗口(x,y) 的和在 corr[y+th-1, x+tw-1]
    corr_win = corr[th - 1: th - 1 + sh, tw - 1: tw - 1 + sw]
    numerator = (corr_win - local_mean * t.sum()
                 - t_mean * local_sum + count * local_mean * t_mean)
    denom = np.sqrt(np.maximum(local_var * count, 0.0) * t_var)
    # 局部方差太小(接近纯色区域)时，NCC 会除零放大成假峰，这里置 0 屏蔽
    with np.errstate(divide="ignore", invalid="ignore"):
        ncc = np.where(denom > 1e-6, numerator / denom, 0.0)
    idx = np.unravel_index(np.argmax(ncc), ncc.shape)
    return float(ncc[idx]), (int(idx[1]), int(idx[0]))


def _template_match(image, keyword, font_name=None, threshold=0.6):
    """模板匹配定位 keyword（OCR 读不到时的备用方案）。

    用 LOCATE_FONT_NAME 渲染关键字做模板（关键词多为中文，需中文字体），
    按多种高度做归一化互相关(NCC)找最佳位置；最小模板高度 20（避免微小模板噪声），
    并用 OCR 校验候选区域：若读出了明显不同的文字，判定为误匹配并拒绝。
    返回 (x, y, w, h)；未找到返回 None。
    """
    if font_name is None:
        font_name = cfg.LOCATE_FONT_NAME

    try:
        import numpy as np
    except ImportError:
        logging.warning("未安装 numpy，无法使用模板匹配定位")
        return None

    gray = np.asarray(image.convert("L"), dtype=np.float64)
    H, W = gray.shape

    min_h = 20
    max_h = min(int(H * 0.6), 512)
    if max_h <= min_h:
        return None
    step = max(2, (max_h - min_h) // 40)

    best_score = -1.0
    best_box = None
    for th in range(min_h, max_h + 1, step):
        tmp_img = render_text_to_image(keyword, size=None, font_size=None,
                                      font_name=font_name, center_by_ink=False)
        if tmp_img.width <= 0 or tmp_img.height <= 0:
            continue
        tw = max(2, int(round(tmp_img.width * th / tmp_img.height)))
        if tw > W or th > H:
            continue
        t = np.asarray(tmp_img.convert("L").resize((tw, th)), dtype=np.float64)
        score, (x, y) = _ncc_match(gray, t)
        if score > best_score:
            best_score = score
            best_box = (int(x), int(y), tw, th)

    if best_score < threshold or best_box is None:
        return None

    # OCR 校验：候选区域若读出明显不同的文字，则拒绝（避免形状相似文字的误匹配）
    x, y, w, h = best_box
    margin = max(16, int(max(w, h) * 0.5))
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(image.width, x + w + margin), min(image.height, y + h + margin)
    crop = image.crop((x0, y0, x1, y1))
    try:
        region_text = extract_text_from_image(crop, language="zh")
    except Exception:
        region_text = ""
    norm = _norm_text(region_text)
    kw_norm = _norm_text(keyword)
    if norm and kw_norm not in norm:
        logging.info("模板匹配候选被 OCR 校验拒绝: %r 不包含 %r", region_text, keyword)
        return None
    return best_box


def crop_region(image, kw_box, delta, size):
    """按 keyword 包围盒 + 偏移 + 尺寸裁剪小图。

    返回：(小图, 整图中的区域 (x, y, w, h))
    """
    img_w, img_h = image.size
    x = kw_box[0] + delta[0]
    y = kw_box[1] + delta[1]
    w, h = size
    x = max(0, min(x, img_w - 1))
    y = max(0, min(y, img_h - 1))
    w = min(w, img_w - x)
    h = min(h, img_h - y)
    if w <= 0 or h <= 0:
        raise ValueError("裁剪区域尺寸无效或超出图片范围: x=%d y=%d w=%d h=%d" % (x, y, w, h))
    crop = image.crop((x, y, x + w, y + h))
    return crop, (x, y, w, h)


def _crop_at(image, xy, size):
    """按绝对坐标裁剪（越界时收缩到图片内）。返回 (crop, (x, y, w, h))；区域无效返回 (None, None)。"""
    img_w, img_h = image.size
    x, y = xy
    w, h = size
    x = max(0, min(x, img_w - 1))
    y = max(0, min(y, img_h - 1))
    w = min(w, img_w - x)
    h = min(h, img_h - y)
    if w <= 0 or h <= 0:
        return None, None
    return image.crop((x, y, x + w, y + h)), (x, y, w, h)


def _preprocess_for_ocr(image, threshold=None):
    """可选：按灰度阈值二值化（暗→黑，亮→白）。threshold<=0 或 None 时不处理。"""
    if not threshold or threshold <= 0:
        return image
    gray = image.convert("L")
    return gray.point(lambda p: 0 if p <= threshold else 255).convert("RGB")


def parse_number(text, *, is_percent=False):
    """把 OCR 文本解析成数值；不是数值则抛 ValueError。

    is_percent=True 时忽略百分号，数值保持百分比单位（如 17.00 表示 17.00%）。
    """
    s = (text or "").strip()
    s = s.replace(" ", "").replace(",", "").replace("%", "").replace("％", "")
    if not s:
        raise ValueError("识别结果为空，无法转换为数值")
    if not _NUM_PATTERN.match(s):
        raise ValueError("识别结果不是数值: %r" % text)
    return float(s)


def format_number(value, decimal_places=2, *, is_percent=False, use_thousands=True, keep_plus=False):
    """把数值格式化为文本：金额加千分位，百分比加 %；keep_plus=True 时正数加 +。"""
    if is_percent:
        s = f"{value:.{decimal_places}f}%"
    elif use_thousands:
        s = f"{value:,.{decimal_places}f}"
    else:
        s = f"{value:.{decimal_places}f}"
    if keep_plus and value > 0:
        s = "+" + s
    return s


def _clamp(value, low, high):
    if low is not None and value < low:
        return low
    if high is not None and value > high:
        return high
    return value


def _compute_new_value_full(text, params):
    """文本 → 数值 → 缩放 → 边界 → 格式化。返回 (格式化文本, 数值)。"""
    value = parse_number(text, is_percent=params["is_percent"])
    new_value = value * params["scale"]
    new_value = _clamp(new_value, params["min_value"], params["max_value"])
    formatted = format_number(new_value, params["decimal_places"],
                              is_percent=params["is_percent"],
                              use_thousands=params.get("use_thousands", False),
                              keep_plus=params.get("keep_plus", False))
    return formatted, new_value


def _compute_new_value(text, params):
    formatted, _num = _compute_new_value_full(text, params)
    return formatted


def _compute_region_value(rec_text, params, region_key):
    """单个数值计算（区域2/3）：文本→数值→缩放→边界→格式化，用该区域的千分位/保留+号。

    返回格式化文本；无效（空/未识别/解析失败）返回空串。
    识别百分比(is_percent)仅对区域2 生效；区域3 始终按普通数值处理。
    """
    if not rec_text or rec_text == "未识别":
        return ""
    reg = params[region_key]
    calc = dict(params)
    calc["use_thousands"] = reg.get("use_thousands", True)
    calc["keep_plus"] = reg.get("keep_plus", False)
    if region_key == "region_3":
        calc["is_percent"] = False  # 区域3 始终按普通数值处理，不启用百分比
    try:
        formatted, _num = _compute_new_value_full(rec_text, calc)
        return formatted
    except Exception:
        return ""


def _compute_region2_new(rec_text, params):
    return _compute_region_value(rec_text, params, "region_2")


def _compute_region3_new(rec_text, params):
    return _compute_region_value(rec_text, params, "region_3")


def _read_params():
    """从 GUI 变量读取当前参数；没有 GUI 时回退到默认值。

    支持 Tk 变量（有 .get()）和普通字符串/数值两种赋值方式。
    """
    def _g(name, default=""):
        var = globals().get(name)
        if var is None:
            return default
        try:
            value = var.get() if hasattr(var, "get") else var
        except Exception:
            value = default
        return default if value is None else value

    def _i(name, default=0):
        s = str(_g(name, "")).strip()
        if not s:
            return default
        try:
            return int(float(s))
        except ValueError:
            raise ValueError("参数 %s 不是整数: %r" % (name, s))

    def _f(name, default=0.0):
        s = str(_g(name, "")).strip()
        if not s:
            return default
        try:
            return float(s)
        except ValueError:
            raise ValueError("参数 %s 不是数值: %r" % (name, s))

    def _b(name, default=False):
        value = _g(name, default)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "真")
        return bool(value)

    defaults = cfg.DAILY_DEFAULTS
    r1 = defaults["region_1"]
    r2 = defaults["region_2"]
    r3 = defaults["region_3"]
    r2_fg = r2.get("fg_colors", r1["fg_colors"][:3])
    r2_bg = r2.get("bg_colors", r1["bg_colors"][:3])
    r3_fg = r3.get("fg_colors", r1["fg_colors"][:3])
    r3_bg = r3.get("bg_colors", r1["bg_colors"][:3])
    return {
        "input_image": str(_g("input_image_var", cfg.DEFAULT_INPUT_IMAGE)).strip() or cfg.DEFAULT_INPUT_IMAGE,
        "output_image": str(_g("output_image_var", cfg.DEFAULT_OUTPUT_IMAGE)).strip() or cfg.DEFAULT_OUTPUT_IMAGE,
        "keyword": str(_g("keyword_var", defaults["keyword"])).strip() or defaults["keyword"],
        "delta": (_i("delta_x_var_1", r1["delta"][0]), _i("delta_y_var_1", r1["delta"][1])),
        "size": (_i("size_w_var_1", r1["size"][0]), _i("size_h_var_1", r1["size"][1])),
        "grid_rows": max(1, min(5, _i("grid_rows_var_1", r1["grid_rows"]))),
        "grid_cols": max(1, min(5, _i("grid_cols_var_1", r1["grid_cols"]))),
        "row_spacing": _i("row_spacing_var_1", r1["row_spacing"]),
        "col_spacing": _i("col_spacing_var_1", r1["col_spacing"]),
        "max_text_height": _i("max_text_height_var_1", r1["max_text_height"]),
        # 区域2（月收益）：偏移 + 区域尺寸（无高亮，仅红/绿/灰三色）
        "region_2": {
            "delta": (_i("delta_x_var_2", r2["delta"][0]), _i("delta_y_var_2", r2["delta"][1])),
            "size": (_i("size_w_var_2", r2["size"][0]), _i("size_h_var_2", r2["size"][1])),
            "use_thousands": _b("use_thousands_var_2", r2.get("use_thousands", True)),
            "keep_plus": _b("keep_plus_var_2", r2.get("keep_plus", True)),
            "max_text_height": _i("max_text_height_var_2", r2["max_text_height"]),
            "fg_colors": [
                _g("fg_color_1_var_2", r2_fg[0]) or r2_fg[0],
                _g("fg_color_2_var_2", r2_fg[1]) or r2_fg[1],
                _g("fg_color_4_var_2", r2_fg[2]) or r2_fg[2],
            ],
            "bg_colors": [
                _g("bg_color_1_var_2", r2_bg[0]) or r2_bg[0],
                _g("bg_color_2_var_2", r2_bg[1]) or r2_bg[1],
                _g("bg_color_4_var_2", r2_bg[2]) or r2_bg[2],
            ],
        },
        # 区域3（个股收益）：偏移 + 行数(最多)/行间距 + 区域尺寸（无高亮，仅红/绿/灰三色）
        "region_3": {
            "delta": (_i("delta_x_var_3", r3["delta"][0]), _i("delta_y_var_3", r3["delta"][1])),
            "grid_rows": max(1, min(5, _i("grid_rows_var_3", r3["grid_rows"]))),
            "row_spacing": _i("row_spacing_var_3", r3["row_spacing"]),
            "size": (_i("size_w_var_3", r3["size"][0]), _i("size_h_var_3", r3["size"][1])),
            "use_thousands": _b("use_thousands_var_3", r3.get("use_thousands", True)),
            "keep_plus": _b("keep_plus_var_3", r3.get("keep_plus", True)),
            "max_text_height": _i("max_text_height_var_3", r3["max_text_height"]),
            "fg_colors": [
                _g("fg_color_1_var_3", r3_fg[0]) or r3_fg[0],
                _g("fg_color_2_var_3", r3_fg[1]) or r3_fg[1],
                _g("fg_color_4_var_3", r3_fg[2]) or r3_fg[2],
            ],
            "bg_colors": [
                _g("bg_color_1_var_3", r3_bg[0]) or r3_bg[0],
                _g("bg_color_2_var_3", r3_bg[1]) or r3_bg[1],
                _g("bg_color_4_var_3", r3_bg[2]) or r3_bg[2],
            ],
        },
        "threshold": _i("threshold_var", -1),  # <=0 表示不启用
        "scale": _f("scale_var", defaults["scale"]),
        "min_value": _f("min_value_var", defaults["min_value"]),
        "max_value": _f("max_value_var", defaults["max_value"]),
        "decimal_places": _i("decimal_places_var", defaults["decimal_places"]),
        "is_percent": _b("is_percent_var", defaults["is_percent"]),
        "use_thousands": _b("use_thousands_var_1", r1.get("use_thousands", False)),
        "keep_plus": _b("keep_plus_var_1", r1.get("keep_plus", False)),
        "font_size": _i("font_size_var", defaults["font_size"]),
        "render_height_scale": _f("render_height_scale_var", cfg.RENDER_HEIGHT_SCALE),
        "fg_colors": [
            _g("fg_color_1_var", r1["fg_colors"][0]) or r1["fg_colors"][0],
            _g("fg_color_2_var", r1["fg_colors"][1]) or r1["fg_colors"][1],
            _g("fg_color_3_var", r1["fg_colors"][2]) or r1["fg_colors"][2],
            _g("fg_color_4_var", r1["fg_colors"][3]) or r1["fg_colors"][3],
            _g("fg_color_5_var", r1["fg_colors"][4]) or r1["fg_colors"][4],
            _g("fg_color_6_var", r1["fg_colors"][5]) or r1["fg_colors"][5],
        ],
        "bg_colors": [
            _g("bg_color_1_var", r1["bg_colors"][0]) or r1["bg_colors"][0],
            _g("bg_color_2_var", r1["bg_colors"][1]) or r1["bg_colors"][1],
            _g("bg_color_3_var", r1["bg_colors"][2]) or r1["bg_colors"][2],
            _g("bg_color_4_var", r1["bg_colors"][3]) or r1["bg_colors"][3],
            _g("bg_color_5_var", r1["bg_colors"][4]) or r1["bg_colors"][4],
            _g("bg_color_6_var", r1["bg_colors"][5]) or r1["bg_colors"][5],
        ],
    }


def locate_keyword_preview():
    """定位关键词并显示坐标（供 GUI 的"定位"按钮调用）。

    找到时把 "(X, Y)" 写到 locate_result_var，找不到则显示"未识别关键词"。
    """
    params = _read_params()
    input_path = _resolve_path(params["input_image"])
    if not os.path.exists(input_path):
        raise ValueError("输入图片不存在: %s" % input_path)

    image = Image.open(input_path)
    box = _locate_keyword_optimized(image, params["keyword"])
    if box is None:
        _set_var("locate_result_var", "未识别关键词")
        set_status("未找到关键词: %s" % params["keyword"])
        return
    _set_var("locate_result_var", "(%d, %d)" % (box[0], box[1]))
    set_status("关键词位于 (%d, %d)，包围区域 %s" % (box[0], box[1], (box[2], box[3])))


def _mark_no_value(params, box, crop, reason):
    """把当前区域标记为"无数值"：不计算、不渲染。"""
    last_state.update({
        "params": params,
        "box": box,
        "crop": crop,
        "recognized": "",
        "new_value": "",
        "new_value_num": None,
        "has_value": False,
    })
    _set_grid_cell("recognized_grid_vars", 0, 0, "")
    _set_grid_cell("new_value_grid_vars", 0, 0, "")
    set_status("%s：该区域无数值，跳过计算与生成" % reason)


def _clamp_grid_params():
    """把区域1 行数/列数限制在 [1,5]，超限则改写回 GUI 变量。返回 (rows, cols)。"""
    def _get_int(name, default):
        var = globals().get(name)
        if var is None:
            return default
        try:
            s = str(var.get() if hasattr(var, "get") else var).strip()
        except Exception:
            return default
        if not s:
            return default
        try:
            return int(float(s))
        except ValueError:
            return default

    rows = _get_int("grid_rows_var_1", 1)
    cols = _get_int("grid_cols_var_1", 1)
    rows = max(1, min(5, rows))
    cols = max(1, min(5, cols))
    _set_var("grid_rows_var_1", rows)
    _set_var("grid_cols_var_1", cols)
    # 区域3 行数(最多)同样限制 [1,5]
    rows3 = _get_int("grid_rows_var_3", 1)
    rows3 = max(1, min(5, rows3))
    _set_var("grid_rows_var_3", rows3)
    return rows, cols


def _number_quality(text):
    """数值候选质量分：越高越像规范数字（用于多候选都解析成功时选最干净的）。"""
    s = text.strip()
    if not s:
        return -10 ** 9
    junk = sum(1 for c in s if c not in "0123456789+-.,%％")  # 杂质（含空格）
    spaces = s.count(" ")
    dots = s.count(".") + s.count("．")
    # 恰好一个小数点更符合"收益带小数"的常见形态，给加分；多余小数点扣分
    has_decimal = 50 if dots == 1 else 0
    extra_dots = max(0, dots - 1) * 300
    return 1000 + has_decimal - junk * 200 - spaces * 150 - extra_dots - len(s)


def _recognize_cell(crop, threshold, is_percent):
    """识别一个单元格；返回文本，无法识别为数值则返回 '未识别'。

    对原图（或用户阈值）与二值化各识别一次，从"能解析成数值"的候选中
    选最干净的那个（杂质/空格/多余小数点最少），避免把噪声当数值。
    """
    candidates = []
    if threshold and threshold > 0:
        candidates.append(_preprocess_for_ocr(crop, threshold))
    else:
        candidates.append(crop)
    candidates.append(_preprocess_for_ocr(crop, cfg.OCR_RETRY_THRESHOLD))

    best_text = None
    best_quality = -10 ** 9
    for cimg in candidates:
        try:
            text = (extract_text_from_image(cimg, language="auto") or "").strip()
        except Exception:
            continue
        if not text:
            continue
        norm_text = _norm_text(text)
        if any(marker in norm_text for marker in cfg.NO_VALUE_MARKERS):
            return "未识别"  # 出现"休"等无数值标记，直接判定该格无数值
        try:
            parse_number(text, is_percent=is_percent)
        except ValueError:
            continue
        q = _number_quality(text)
        if q > best_quality:
            best_quality = q
            best_text = text
    return best_text if best_text is not None else "未识别"


def _color_dist(a, b):
    """RGB 欧氏距离。"""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _detect_color_type(crop, fg_colors=None, bg_colors=None):
    """检测单元格颜色类型（索引对应传入的 fg_colors/bg_colors 数组）；无法识别返回 None。

    背景色能唯一匹配（如高亮纯色底）就用背景；背景统一/无法唯一匹配时（如区域2/3
    靠文字色区分）改用前景（文字）色匹配。
    """
    if fg_colors is None:
        fg_colors = cfg.DAILY_DEFAULTS["region_1"]["fg_colors"]
    if bg_colors is None:
        bg_colors = cfg.DAILY_DEFAULTS["region_1"]["bg_colors"]

    from collections import Counter
    img = crop.convert("RGB")
    w = max(1, img.width // 2)
    h = max(1, img.height // 2)
    cnt = Counter(img.resize((w, h)).getdata())
    bg, _bg_count = cnt.most_common(1)[0]
    # 前景(文字)色 = 离背景最远的颜色
    fg = max(cnt, key=lambda px: _color_dist(px, bg))

    ref_bg = [_normalize_color(c) for c in bg_colors]
    ref_fg = [_normalize_color(c) for c in fg_colors]
    threshold = 50

    bg_hits = [i for i, ref in enumerate(ref_bg) if _color_dist(bg, ref) <= threshold]
    if len(bg_hits) == 1:
        return bg_hits[0]

    fg_hits = [i for i, ref in enumerate(ref_fg) if _color_dist(fg, ref) <= threshold]
    if len(fg_hits) == 1:
        return fg_hits[0]
    return None


def _run_format_checks(params, grid_recognized, cell_colors, rec2, rec3, warnings):
    """格式检查（私有）：检查结果追加到 warnings 列表。

    在「提取数据」结尾自动调用；也可由公开入口 run_format_checks_now 触发。
    1. 高亮格数量：整个网格应有且仅有 1 个高亮格（红高亮=2 / 绿高亮=3 / 灰高亮=5）；
    2. 求和检查：区域1 全部有效值之和 应与 区域2 一致（误差 >1 告警）；
    3. 区域2 未识别；
    4. 区域3 识别出的格子数量为 0。
    """
    # 检查1：整个网格应有且仅有 1 个高亮格（红高亮=2 / 绿高亮=3 / 灰高亮=5）
    hl = sum(1 for r in range(5) for c in range(5) if cell_colors[r][c] in (2, 3, 5))
    if hl != 1:
        warnings.append("格式检查：应有且仅有 1 个高亮格(红/绿/灰高亮)，实际 %d 个" % hl)

    # 检查2：区域1 全部有效值之和 应与 区域2 一致（误差 >1 告警）
    try:
        r1_sum = 0.0
        r1_cnt = 0
        for r in range(5):
            for c in range(5):
                t = grid_recognized[r][c]
                if t and t != "未识别":
                    r1_sum += parse_number(t, is_percent=params["is_percent"])
                    r1_cnt += 1
        if r1_cnt and rec2 and rec2 != "未识别":
            r2_val = parse_number(rec2, is_percent=params["is_percent"])
            if abs(r1_sum - r2_val) > 1:
                warnings.append("求和检查未通过，请检查区域1或区域2是否有识别错误（区域1合计 %.2f，区域2 %.2f）"
                                % (r1_sum, r2_val))
    except Exception:
        pass  # 任一侧无法解析成数值时不触发求和检查

    # 检查3：区域2 未识别
    if not rec2 or rec2 == "未识别":
        warnings.append("区域2 未识别（月收益）")

    # 检查4：区域3 识别出的格子数量为 0
    r3_cnt = sum(1 for t in rec3 if t and t != "未识别")
    if r3_cnt == 0:
        warnings.append("区域3 未识别到任何行（个股收益）")


def _popup_format_check(warnings):
    """格式校验结果弹窗：仅在发现问题时弹出（通过时不打扰）；无 GUI 时回退到状态栏。"""
    if not warnings:
        return  # 通过时不弹窗（状态栏已显示「通过」）
    body = "格式校验未通过，共 %d 个问题：\n\n%s" % (
        len(warnings), "\n".join("• %s" % w for w in warnings))
    try:
        from tkinter import messagebox
        messagebox.showwarning("格式校验", body)
    except Exception:
        set_status("格式校验：%s" % body)


def run_format_checks_now():
    """「格式校验」按钮入口：读取当前（可手动编辑后的）识别值重新跑格式检查。

    自动检查未通过、用户手动修正了识别格子（区域1 5x5 / 区域2）后，
    可再点此按钮复查；结果写入状态栏和 last_state['warnings']，并弹窗显示。
    """
    params = _read_params()
    grid_recognized = _get_recognized_grid()
    if not grid_recognized:
        raise ValueError("请先点击「提取数据」")
    cell_colors = last_state.get("cell_colors") or [[4 for _ in range(5)] for _ in range(5)]
    rec2 = _get_region2_recognized()
    rec3 = _get_region3_recognized()
    warnings = []
    _run_format_checks(params, grid_recognized, cell_colors, rec2, rec3, warnings)
    last_state["warnings"] = warnings
    if warnings:
        set_status("格式校验：发现 %d 个问题：%s" % (len(warnings), "; ".join(warnings)))
    else:
        set_status("格式校验：通过（高亮格 1 个，区域1合计与区域2 吻合）")
    _popup_format_check(warnings)
    return warnings


def extract_data():
    """步骤 1+2：定位关键词 → 逐格裁剪 → OCR 识别 5x5 网格。

    - 网格内行列数 < 5 时，超出范围（行≥行数 或 列≥列数）的格显示空字符串，不识别、不计算。
    - 网格内某格识别不到数值/百分比（含"休"等无数值标记），该格显示"未识别"，不计算。
    """
    params = _read_params()
    input_path = _resolve_path(params["input_image"])
    if not os.path.exists(input_path):
        raise ValueError("输入图片不存在: %s" % input_path)

    image = Image.open(input_path)
    kw_box = _locate_keyword_optimized(image, params["keyword"])
    if kw_box is None:
        raise ValueError("在图片中找不到关键词: %s" % params["keyword"])
    _set_var("locate_result_var", "(%d, %d)" % (kw_box[0], kw_box[1]))

    rows = params["grid_rows"]
    cols = params["grid_cols"]
    origin = (kw_box[0] + params["delta"][0], kw_box[1] + params["delta"][1])
    cw, ch = params["size"]
    cs = params["col_spacing"]
    rs = params["row_spacing"]
    threshold = params["threshold"]
    # 区域1 网格底边（区域2/3 的纵向基准）：最后一行单元格的下边缘
    grid_bottom = origin[1] + (rows - 1) * rs + ch

    grid_recognized = [["" for _ in range(5)] for _ in range(5)]
    grid_boxes = [[None for _ in range(5)] for _ in range(5)]
    grid_crops = [[None for _ in range(5)] for _ in range(5)]
    cell_colors = [[4 for _ in range(5)] for _ in range(5)]  # 默认灰
    warnings = []

    for r in range(rows):
        for c in range(cols):
            x = origin[0] + c * cs
            y = origin[1] + r * rs
            crop, box = _crop_at(image, (x, y), (cw, ch))
            grid_boxes[r][c] = box
            grid_crops[r][c] = crop
            if crop is None:
                grid_recognized[r][c] = "未识别"
                continue
            grid_recognized[r][c] = _recognize_cell(crop, threshold, params["is_percent"])
            color_idx = _detect_color_type(crop)
            if color_idx is None:
                color_idx = 4  # 识别不出颜色类型 -> 普通灰
                if grid_recognized[r][c] and grid_recognized[r][c] != "未识别":
                    warnings.append("格(%d,%d) 颜色类型无法识别，使用灰色" % (r + 1, c + 1))
            cell_colors[r][c] = color_idx

    # 区域2（月收益）：单个数值 + 自动识别颜色（Y 相对区域1网格底边）
    r2p = params["region_2"]
    ox2 = kw_box[0] + r2p["delta"][0]
    oy2 = grid_bottom + r2p["delta"][1]
    crop2, box2 = _crop_at(image, (ox2, oy2), r2p["size"])
    rec2 = "未识别"
    color2 = 2  # 区域2 的灰（3 色索引）
    if crop2 is not None:
        rec2 = _recognize_cell(crop2, threshold, params["is_percent"])
        ci = _detect_color_type(crop2, r2p["fg_colors"], r2p["bg_colors"])
        if ci is None:
            ci = 2  # 区域2 灰
            if rec2 and rec2 != "未识别":
                warnings.append("区域2 颜色类型无法识别，使用灰色")
        color2 = ci
    _set_grid_cell("recognized_region2_vars", 0, 0, rec2)
    _set_grid_cell("new_value_region2_vars", 0, 0, "")
    region2_state = {"box": box2, "crop": crop2, "recognized": rec2, "color": color2}

    # 区域3（个股收益）：多行一列（GUI 显示为一行多列），行数 1..5（Y 相对区域1网格底边）
    r3p = params["region_3"]
    rows3 = r3p["grid_rows"]
    ox3 = kw_box[0] + r3p["delta"][0]
    oy3 = grid_bottom + r3p["delta"][1]
    rs3 = r3p["row_spacing"]
    grid_rec3 = ["" for _ in range(5)]
    grid_colors3 = [2 for _ in range(5)]  # 区域3 灰 = 索引 2
    grid_boxes3 = [None for _ in range(5)]
    for i in range(rows3):
        y = oy3 + i * rs3
        crop3, box3 = _crop_at(image, (ox3, y), r3p["size"])
        grid_boxes3[i] = box3
        if crop3 is None:
            grid_rec3[i] = "未识别"
            continue
        rec3 = _recognize_cell(crop3, threshold, False)  # 区域3 始终按普通数值识别
        grid_rec3[i] = rec3
        ci = _detect_color_type(crop3, r3p["fg_colors"], r3p["bg_colors"])
        if ci is None:
            ci = 2  # 区域3 灰
            if rec3 and rec3 != "未识别":
                warnings.append("区域3 第%d行 颜色类型无法识别，使用灰色" % (i + 1))
        grid_colors3[i] = ci
    for i in range(5):
        _set_grid_cell("recognized_region3_vars", 0, i, grid_rec3[i])
        _set_grid_cell("new_value_region3_vars", 0, i, "")
    region3_state = {"boxes": grid_boxes3, "recognized": grid_rec3, "colors": grid_colors3}

    # 写回识别网格（5x5，网格外为 ""），清空计算网格，写回颜色类型
    for r in range(5):
        for c in range(5):
            _set_grid_cell("recognized_grid_vars", r, c, grid_recognized[r][c])
            _set_grid_cell("new_value_grid_vars", r, c, "")
            _set_grid_cell("cell_color_grid_vars", r, c, str(cell_colors[r][c]))

    # 格式检查（高亮格数量、区域1合计 vs 区域2、区域2/3 是否识别）——在 extract_data 结尾统一执行
    fc_warnings = []
    _run_format_checks(params, grid_recognized, cell_colors, rec2, grid_rec3, fc_warnings)
    warnings.extend(fc_warnings)
    _popup_format_check(fc_warnings)

    valid = sum(1 for r in range(5) for c in range(5)
                if grid_recognized[r][c] and grid_recognized[r][c] != "未识别")
    last_state.update({
        "params": params,
        "grid_recognized": grid_recognized,
        "grid_new": [["" for _ in range(5)] for _ in range(5)],
        "grid_boxes": grid_boxes,
        "grid_crops": grid_crops,
        "grid_origin": origin,
        "cell_colors": cell_colors,
        "warnings": warnings,
        "has_value": valid > 0,
        "region2": region2_state,
        "region2_new": "",
        "region3": region3_state,
        "region3_new": ["" for _ in range(5)],
    })
    r2_msg = "；区域2 %s" % rec2 if rec2 and rec2 != "未识别" else ""
    r3_valid = sum(1 for t in grid_rec3 if t and t != "未识别")
    r3_msg = "；区域3 %d/%d 行" % (r3_valid, rows3)
    if warnings:
        set_status("提取完成：识别到 %d/%d 个有效格（%d 行 x %d 列）%s%s；告警 %d 个：%s"
                   % (valid, rows * cols, rows, cols, r2_msg, r3_msg, len(warnings), "; ".join(warnings[:3])))
    else:
        set_status("提取完成：识别到 %d/%d 个有效格（%d 行 x %d 列）%s%s"
                   % (valid, rows * cols, rows, cols, r2_msg, r3_msg))


def preview_new_value():
    """根据当前参数实时预览"计算后的数值"网格（供 GUI 实时刷新；失败时静默）。"""
    grid_rec = _get_recognized_grid()
    if not grid_rec:
        return
    try:
        params = _read_params()
    except Exception as exc:
        set_status("预览失败: %s" % exc)
        return
    grid_new = [["" for _ in range(5)] for _ in range(5)]
    for r in range(5):
        for c in range(5):
            text = grid_rec[r][c]
            if not text or text == "未识别":
                continue
            try:
                formatted, _num = _compute_new_value_full(text, params)
                grid_new[r][c] = formatted
            except Exception:
                grid_new[r][c] = ""
    for r in range(5):
        for c in range(5):
            _set_grid_cell("new_value_grid_vars", r, c, grid_new[r][c])
    # 区域2 实时预览（优先用当前识别值，含手改）
    rec2 = _get_region2_recognized()
    new2 = _compute_region2_new(rec2, params)
    _set_grid_cell("new_value_region2_vars", 0, 0, new2)
    last_state["region2_new"] = new2
    # 区域3 实时预览（优先用当前识别值，含手改）
    rec3 = _get_region3_recognized()
    new3 = [_compute_region3_new(rec3[i], params) for i in range(5)]
    for i in range(5):
        _set_grid_cell("new_value_region3_vars", 0, i, new3[i])
    last_state["region3_new"] = new3
    last_state["grid_new"] = grid_new
    last_state["grid_recognized"] = grid_rec
    last_state["params"] = params


def calculate_new_data():
    """步骤 3：逐格 文本 → 数值 → 缩放 → 边界 → 格式化（只算有效识别格，含用户手改的识别值）。"""
    grid_rec = _get_recognized_grid()
    if not grid_rec:
        raise ValueError("请先点击「提取数据」")
    params = _read_params()
    grid_new = [["" for _ in range(5)] for _ in range(5)]
    count = 0
    for r in range(5):
        for c in range(5):
            text = grid_rec[r][c]
            if not text or text == "未识别":
                continue
            try:
                formatted, _num = _compute_new_value_full(text, params)
                grid_new[r][c] = formatted
                count += 1
            except Exception as exc:
                grid_new[r][c] = ""
                set_status("格(%d,%d) 计算失败: %s" % (r + 1, c + 1, exc))
    for r in range(5):
        for c in range(5):
            _set_grid_cell("new_value_grid_vars", r, c, grid_new[r][c])
    # 区域2 计算（优先用当前识别值，含手改）
    rec2 = _get_region2_recognized()
    new2 = _compute_region2_new(rec2, params)
    _set_grid_cell("new_value_region2_vars", 0, 0, new2)
    last_state["region2_new"] = new2
    # 区域3 计算（优先用当前识别值，含手改）
    rec3 = _get_region3_recognized()
    new3 = [_compute_region3_new(rec3[i], params) for i in range(5)]
    for i in range(5):
        _set_grid_cell("new_value_region3_vars", 0, i, new3[i])
    last_state["region3_new"] = new3
    last_state["grid_new"] = grid_new
    last_state["grid_recognized"] = grid_rec
    last_state["params"] = params
    msg = "计算完成：区域1 共 %d 个有效格" % count
    if new2:
        msg += "；区域2 %s" % new2
    r3_valid = [t for t in new3 if t]
    if r3_valid:
        msg += "；区域3 %d 行" % len(r3_valid)
    set_status(msg)


def _add_watermark(image):
    """在图片右下角叠加 45° 倾斜水印：『股市有风险，投资需谨慎』（宽≈原图 60%，颜色 #888888）。"""
    text = "股市有风险，投资需谨慎"
    img_w, img_h = image.size
    target_w = img_w * 0.6

    # 二分找字号：使文字宽度尽量接近原图宽 60%
    lo, hi = 10, 400
    best = _load_font(cfg.LOCATE_FONT_NAME, lo)
    while lo <= hi:
        mid = (lo + hi) // 2
        f = _load_font(cfg.LOCATE_FONT_NAME, mid)
        tw, _th = _measure_text(text, f)
        if tw <= target_w:
            best = f
            lo = mid + 1
        else:
            hi = mid - 1

    tw, th = _measure_text(text, best)
    pad = 10
    layer = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((pad, pad), text, font=best, fill=(0x88, 0x88, 0x88, 255))
    layer = layer.rotate(45, expand=True, resample=Image.BICUBIC)

    base = image.convert("RGBA")
    x = max(0, img_w - layer.width - 20)
    y = max(0, img_h - layer.height - 20)
    base.paste(layer, (x, y), layer)
    return base.convert("RGB")


def generate_image():
    """步骤 4+5：逐格渲染新数值小图 → 贴回原图 → 右下角加水印 → 保存。"""
    grid_new = last_state.get("grid_new")
    grid_boxes = last_state.get("grid_boxes")
    if not grid_new or not grid_boxes:
        raise ValueError("请先点击「提取数据」")
    params = _read_params()

    input_path = _resolve_path(params["input_image"])
    if not os.path.exists(input_path):
        raise ValueError("输入图片不存在: %s" % input_path)

    image = Image.open(input_path)
    font_size = params["font_size"] if params["font_size"] and params["font_size"] > 0 else None
    pasted = 0
    for r in range(5):
        for c in range(5):
            new_text = grid_new[r][c]
            box = grid_boxes[r][c]
            if not new_text or box is None:
                continue
            size = (box[2], box[3])
            # 选色：用识别时记录的颜色类型；无记录时按 0 收益用灰、否则红
            cell_colors = last_state.get("cell_colors")
            if cell_colors is not None:
                color_index = cell_colors[r][c]
            else:
                try:
                    new_value = parse_number(new_text, is_percent=params["is_percent"])
                except ValueError:
                    new_value = 0.0
                color_index = 4 if new_value == 0 else 0
            small = render_text_to_image(
                new_text,
                size=size,
                fg_color=params["fg_colors"][color_index],
                bg_color=params["bg_colors"][color_index],
                font_size=font_size,
                height_scale=params["render_height_scale"],
                max_text_height=params["max_text_height"],
            )
            image.paste(small, (box[0], box[1]))
            pasted += 1

    # 区域2：渲染单个数并贴回
    r2p = params["region_2"]
    r2_state = last_state.get("region2")
    if r2_state:
        new2 = last_state.get("region2_new") or _get_grid_cell("new_value_region2_vars", 0, 0)
        box2 = r2_state.get("box")
        if new2 and box2:
            ci = r2_state.get("color", 2)
            small2 = render_text_to_image(
                new2,
                size=(box2[2], box2[3]),
                fg_color=r2p["fg_colors"][ci],
                bg_color=r2p["bg_colors"][ci],
                font_size=font_size,
                height_scale=params["render_height_scale"],
                max_text_height=r2p["max_text_height"],
                align="left",
            )
            image.paste(small2, (box2[0], box2[1]))
            pasted += 1

    # 区域3：渲染各股数值贴回
    r3p = params["region_3"]
    r3_state = last_state.get("region3")
    if r3_state:
        new3 = last_state.get("region3_new") or []
        boxes3 = r3_state.get("boxes") or []
        colors3 = r3_state.get("colors") or []
        for i in range(len(new3)):
            txt3 = new3[i]
            box3 = boxes3[i] if i < len(boxes3) else None
            if not txt3 or box3 is None:
                continue
            ci = colors3[i] if i < len(colors3) else 2
            small3 = render_text_to_image(
                txt3,
                size=(box3[2], box3[3]),
                fg_color=r3p["fg_colors"][ci],
                bg_color=r3p["bg_colors"][ci],
                font_size=font_size,
                height_scale=params["render_height_scale"],
                max_text_height=r3p["max_text_height"],
                align="right",
            )
            image.paste(small3, (box3[0], box3[1]))
            pasted += 1

    # 右下角 45° 倾斜水印：股市有风险，投资需谨慎
    image = _add_watermark(image)

    output_path = _resolve_path(params["output_image"])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    image.save(output_path)
    set_status("生成完成：已回填 %d 格，保存到 %s" % (pasted, output_path))


def export_report():
    """导出报告：记录参数、逐格识别值/计算值、输出文件。"""
    params = _read_params()
    now = datetime.datetime.now()
    grid_rec = last_state.get("grid_recognized")
    grid_new = last_state.get("grid_new")

    def grid_lines(grid):
        if not grid:
            return []
        return ["  行%d: %s" % (r + 1, " | ".join(cell if cell else " " for cell in row))
                for r, row in enumerate(grid)]

    lines = [
        "收益截图生成器 - 处理报告",
        "生成时间: %s" % now.strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "【参数】",
        "输入图片: %s" % params["input_image"],
        "输出图片: %s" % params["output_image"],
        "关键词: %s" % params["keyword"],
        "网格: %d 行 x %d 列（行间距 %d，列间距 %d）" % (params["grid_rows"], params["grid_cols"], params["row_spacing"], params["col_spacing"]),
        "网格原点偏移: %s" % (params["delta"],),
        "单元格尺寸: %s" % (params["size"],),
        "OCR 阈值: %s" % (params["threshold"] if params["threshold"] and params["threshold"] > 0 else "不启用"),
        "缩放倍率: %s" % params["scale"],
        "数值边界: [%s, %s]" % (params["min_value"], params["max_value"]),
        "小数位: %s" % params["decimal_places"],
        "识别百分比: %s" % ("是" if params["is_percent"] else "否"),
        "前景色: %s" % ", ".join(params["fg_colors"]),
        "背景色: %s" % ", ".join(params["bg_colors"]),
        "",
        "【识别数值】",
    ] + grid_lines(grid_rec) + [
        "",
        "【计算数值】",
    ] + grid_lines(grid_new) + [
        "",
        "【区域2-月收益】",
        "识别数值: %s" % ((last_state.get("region2") or {}).get("recognized") or ""),
        "计算数值: %s" % (last_state.get("region2_new") or ""),
        "",
        "【区域3-个股收益】",
        "识别数值: %s" % " | ".join((last_state.get("region3") or {}).get("recognized") or []),
        "计算数值: %s" % " | ".join(last_state.get("region3_new") or []),
    ]

    report_name = cfg.REPORT_FILENAME_PATTERN.format(ts=now.strftime("%Y%m%d_%H%M%S"))
    report_path = _resolve_path(os.path.join(cfg.OUTPUT_DIR, report_name))
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    set_status("报告已导出：%s" % report_path)