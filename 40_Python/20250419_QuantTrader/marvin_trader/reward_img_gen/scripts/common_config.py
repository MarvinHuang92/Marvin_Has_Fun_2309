# -*- coding: utf-8 -*-

GUI_TITLE = "收益截图生成器"
TAB_NAMES = ["日收益", "月收益", "年收益"]
BUTTON_EXTRACT_TEXT = "提取数据"
BUTTON_CHECK_TEXT = "格式校验"
BUTTON_CALCULATE_TEXT = "计算新数据"
BUTTON_GEN_IMAGE_TEXT = "生成截图"
BUTTON_EXPORT_TEXT = "导出报告"
WINDOW_WIDTH = 960
WINDOW_HEIGHT = 800

# 用于定位要修改数值的关键文字
LOCATE_KEYWORD = "周一"

# 相对于 keyword 的位置偏移量（区域1：网格原点(92,826) - 关键词(144,618) 换算，即从关键词到网格原点的偏移）
LOCATE_DELTA_DAILY_1 = -52, 208
# 区域2/3：X 相对关键词；Y 相对「区域1 网格底边」的间隙（下方内容随区域1 行数变化而整体上移/下移）
LOCATE_DELTA_DAILY_2 = 298, 134
LOCATE_DELTA_DAILY_3 = 588, 694
LOCATE_DELTA_MONTHLY_1 = 100, 200
LOCATE_DELTA_ANNUAL_1 = 100, 200

# 截图区域的大小（区域1 单元格尺寸 = 166 宽 x 48 高）
SIZE_DAILY_1 = 166, 48
SIZE_DAILY_2 = 280, 48
SIZE_DAILY_3 = 300, 60
SIZE_MONTHLY_1 = 300, 400
SIZE_ANNUAL_1 = 300, 400

# 定位优化：优先在上次关键词位置附近的小区域搜索（找不到再全图搜索）
LOCATE_ROI_SIZE = 200, 200  # 搜索区域宽高
LOCATE_ROI_PAD = 50, 50     # 从上次位置左上角再往左/上偏移的起始点

# 无数值标记：识别区域出现这些内容时视为"无数值"（如"休"=休市/休息日，不开盘）
NO_VALUE_MARKERS = ["休"]

# 单元格 OCR 重试用的默认二值化阈值（某些格子孤立识别不佳，二值化后更清晰）
OCR_RETRY_THRESHOLD = 128

LAST_SAVED_RELATIVE_PATH = "..\\data\\last_saved.txt"

# ---- 输入输出（相对项目根目录 reward_img_gen/）----
INPUT_DIR = "input"
OUTPUT_DIR = "output"
DEFAULT_INPUT_IMAGE = "input\\input.png"
DEFAULT_OUTPUT_IMAGE = "output\\output.png"

# ---- 日收益页默认参数（GUI 首次打开 / 无参数时的默认值）----
# 公共参数所有区域共用；区域各自的偏移/尺寸/网格在 region_1/2/3 下独立配置
DAILY_DEFAULTS = {
    "keyword": LOCATE_KEYWORD,
    "scale": 0.5,
    "min_value": -9999999.0,
    "max_value": 9999999.0,
    "decimal_places": 2,
    "is_percent": False,
    "font_size": 0,          # 0 表示按区域自动适配字号
    # 区域1（交易日）
    "region_1": {
        "delta": LOCATE_DELTA_DAILY_1,   # 网格原点（第1行第1列，反推）
        "size": SIZE_DAILY_1,
        "grid_rows": 5,     # 5x5 网格行数
        "grid_cols": 5,     # 5x5 网格列数
        "row_spacing": 198, # 行间距（由 第2行第1列(92,1024) 与 第5行第5列(868,1620) 反推，取整）
        "col_spacing": 194, # 列间距
        "use_thousands": False,  # 区域1 回填数值不带千分位
        "keep_plus": False,      # 区域1 正值不保留 + 号
        "max_text_height": 28,   # 渲染最大文字高度(px)
        # 区域1 含高亮：红, 绿, 红(高亮), 绿(高亮), 灰(0收益), 灰(高亮)
        "fg_colors": ["#e03136", "#129e6b", "#ffffff", "#ffffff", "#333333", "#ffffff"],
        "bg_colors": ["#feedee", "#e3f6ef", "#e03136", "#129e6b", "#f5f5f5", "#999999"],
    },
    # 区域2（月收益）——无高亮，仅红/绿/灰
    "region_2": {
        "delta": LOCATE_DELTA_DAILY_2,
        "size": SIZE_DAILY_2,
        "use_thousands": True,   # 区域2 回填数值带千分位
        "keep_plus": True,       # 区域2 正值保留 + 号
        "max_text_height": 32,   # 渲染最大文字高度(px)
        "fg_colors": ["#e03136", "#129e6b", "#333333"],   # 红, 绿, 灰
        "bg_colors": ["#f8f8f8", "#f8f8f8", "#f8f8f8"],   # 区域2 测试图：文字色深色，背景统一浅灰 #f8f8f8
    },
    # 区域3（个股收益）——无高亮，仅红/绿/灰
    "region_3": {
        "delta": LOCATE_DELTA_DAILY_3,
        "size": SIZE_DAILY_3,
        "grid_rows": 5,     # 行数(最多)，边界 [1,5]
        "row_spacing": 166, # 行间距
        "use_thousands": True,   # 区域3 回填数值带千分位
        "keep_plus": True,       # 区域3 正值保留 + 号
        "max_text_height": 36,   # 渲染最大文字高度(px)
        "fg_colors": ["#e03136", "#129e6b", "#333333"],   # 红, 绿, 灰
        "bg_colors": ["#ffffff", "#ffffff", "#ffffff"],   # 区域3 测试图：背景纯白
    },
}

# ---- 文字渲染（生成图片）参数 ----
# FONT_DIR = "C:/Windows/Fonts"
FONT_DIR = "fonts"
# 生成截图时数值所用的字体（尽量贴近原截图数字字体，如 Arial Bold）
# FONT_NAME = "bahnschrift.ttf"
# FONT_NAME = "HarmonyOS_Sans_SC_Regular.ttf"
FONT_NAME = "HarmonyOS_Sans_SC_Bold.ttf"
# 模板匹配定位关键词时，渲染关键词所用的字体（关键词多为中文，需用中文字体）
LOCATE_FONT_NAME = "msyhbd.ttc"
FONT_SIZE = 60
# 数值渲染时的高度缩放倍率（某些字体渲染偏矮，放大高度更贴近原截图）
RENDER_HEIGHT_SCALE = 1.2
DEFAULT_FG_COLOR = (255, 0, 0)
DEFAULT_BG_COLOR = (255, 255, 255)

# ---- 报告导出 ----
REPORT_FILENAME_PATTERN = "report_{ts}.txt"
