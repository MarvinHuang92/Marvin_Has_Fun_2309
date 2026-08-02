# -*- coding: utf-8 -*-

import logging
import os
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox

import common_config as cfg
import img_gen as ig

IMAGE_FILETYPES = [
    ("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
    ("所有文件", "*.*"),
]

# 定位与裁剪区成对标签的固定宽度（文字左对齐）
NORMAL_LABEL_WIDTH = 10
PAIR_LABEL_WIDTH = 11

# 需要保存/加载到 last_saved.txt 的变量名
SAVED_VAR_NAMES = [
    "input_image_var", "output_image_var", "keyword_var", "locate_result_var",
    "delta_x_var_1", "delta_y_var_1", "grid_rows_var_1", "grid_cols_var_1", "row_spacing_var_1", "col_spacing_var_1",
    "size_w_var_1", "size_h_var_1",
    "delta_x_var_2", "delta_y_var_2", "size_w_var_2", "size_h_var_2",
    "delta_x_var_3", "delta_y_var_3", "grid_rows_var_3", "row_spacing_var_3", "size_w_var_3", "size_h_var_3",
    "use_thousands_var_1", "use_thousands_var_2", "use_thousands_var_3",
    "keep_plus_var_1", "keep_plus_var_2", "keep_plus_var_3",
    "max_text_height_var_1", "max_text_height_var_2", "max_text_height_var_3",
    "threshold_var", "scale_var", "min_value_var", "max_value_var",
    "decimal_places_var", "is_percent_var", "font_size_var", "render_height_scale_var",
    "fg_color_1_var", "fg_color_2_var", "fg_color_3_var", "fg_color_4_var", "fg_color_5_var", "fg_color_6_var",
    "bg_color_1_var", "bg_color_2_var", "bg_color_3_var", "bg_color_4_var", "bg_color_5_var", "bg_color_6_var",
    "fg_color_1_var_2", "fg_color_2_var_2", "fg_color_4_var_2",
    "bg_color_1_var_2", "bg_color_2_var_2", "bg_color_4_var_2",
    "fg_color_1_var_3", "fg_color_2_var_3", "fg_color_4_var_3",
    "bg_color_1_var_3", "bg_color_2_var_3", "bg_color_4_var_3",
]


def _default_path(rel_path):
    """把相对项目根目录的路径转成绝对路径（用于 GUI 默认值显示）。"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel_path))


def _browse_file(var):
    path = filedialog.askopenfilename(title="选择图片", filetypes=IMAGE_FILETYPES)
    if path:
        var.set(path)


def _browse_save(var):
    path = filedialog.asksaveasfilename(title="保存图片", filetypes=IMAGE_FILETYPES,
                                        defaultextension=".png")
    if path:
        var.set(path)


def _pick_color(var):
    _, hex_color = colorchooser.askcolor(color=var.get() or "#ffffff", title="选择颜色")
    if hex_color:
        var.set(hex_color)


def _add_file_row(parent, row, label_text, var, browse_cmd):
    ttk.Label(parent, text=label_text).grid(row=row, column=0, sticky="w", padx=(12, 8), pady=6)
    frame = ttk.Frame(parent)
    frame.grid(row=row, column=1, sticky="ew", padx=(8, 12), pady=6)
    frame.columnconfigure(0, weight=1)
    entry = ttk.Entry(frame, textvariable=var)
    entry.grid(row=0, column=0, sticky="ew")
    ttk.Button(frame, text="浏览", width=6, command=browse_cmd).grid(row=0, column=1, padx=(6, 0))


def _add_color_row(parent, row, label_text, var):
    ttk.Label(parent, text=label_text).grid(row=row, column=0, sticky="w", padx=(12, 8), pady=6)
    frame = ttk.Frame(parent)
    frame.grid(row=row, column=1, sticky="ew", padx=(8, 12), pady=6)
    frame.columnconfigure(0, weight=1)
    entry = ttk.Entry(frame, textvariable=var, width=12)
    entry.grid(row=0, column=0, sticky="w")
    ttk.Button(frame, text="选色", width=6, command=lambda: _pick_color(var)).grid(row=0, column=1, padx=(6, 0))


def _add_color_cell(grid, r, c, label_text, var):
    """在网格中放一个颜色单元格：上方标签，下方颜色输入 + 选色按钮。"""
    cell = ttk.Frame(grid)
    cell.grid(row=r, column=c, sticky="nsew", padx=4, pady=3)
    ttk.Label(cell, text=label_text).pack(anchor="w")
    rowf = ttk.Frame(cell)
    rowf.pack(fill="x", pady=(2, 0))
    rowf.columnconfigure(0, weight=1)
    entry = ttk.Entry(rowf, textvariable=var, width=10)
    entry.grid(row=0, column=0, sticky="ew")
    ttk.Button(rowf, text="选色", width=5, command=lambda: _pick_color(var)).grid(row=0, column=1, padx=(4, 0))


def _add_grid(parent, row, label_text, vars_2d, *, cell_width=8, readonly=True, frame_title=None):
    """在结果区放一个数值网格（如 5x5）。默认只读；readonly=False 时允许手动编辑。

    frame_title 非空时用 LabelFrame 包裹（标题=frame_title，label_text 与其不同则保留内部小标签），
    否则用普通标签 + 网格。返回下一行行号。
    """
    rows = len(vars_2d)
    cols = len(vars_2d[0]) if rows else 0

    if frame_title:
        box = ttk.LabelFrame(parent, text=frame_title)
        box.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
        box.columnconfigure(0, weight=1)
        inner_row = 0
        if label_text and label_text != frame_title:
            ttk.Label(box, text=label_text).grid(row=0, column=0, sticky="w", padx=12, pady=(4, 2))
            inner_row = 1
        gridf = ttk.Frame(box)
        gridf.grid(row=inner_row, column=0, sticky="ew", padx=12, pady=(0, 6))
        for c in range(cols):
            gridf.columnconfigure(c, weight=1)
        for r in range(rows):
            for c in range(cols):
                entry = ttk.Entry(gridf, textvariable=vars_2d[r][c],
                                  state="readonly" if readonly else "normal",
                                  justify="center", width=cell_width)
                entry.grid(row=r, column=c, sticky="ew", padx=2, pady=2)
        return row + 1

    ttk.Label(parent, text=label_text).grid(
        row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(6, 2))
    gridf = ttk.Frame(parent)
    gridf.grid(row=row + 1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
    for c in range(cols):
        gridf.columnconfigure(c, weight=1)
    for r in range(rows):
        for c in range(cols):
            entry = ttk.Entry(gridf, textvariable=vars_2d[r][c],
                              state="readonly" if readonly else "normal",
                              justify="center", width=cell_width)
            entry.grid(row=r, column=c, sticky="ew", padx=2, pady=2)
    return row + 2


def _run_action(fn):
    """统一包裹按钮动作：先校正区域1网格行列数边界[1,5]，再执行；捕获异常并弹窗提示。"""
    try:
        ig._clamp_grid_params()
        fn()
    except Exception as exc:
        logging.exception("Action failed: %s", exc)
        ig.set_status("出错: %s" % exc)
        messagebox.showerror("错误", str(exc))


def _save_last_saved():
    file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), cfg.LAST_SAVED_RELATIVE_PATH))
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as fh:
            for name in SAVED_VAR_NAMES:
                var = getattr(ig, name, None)
                if var is None:
                    continue
                try:
                    fh.write("%s=%s\n" % (name, var.get()))
                except Exception:
                    continue
        logging.info("Saved last inputs to %s", file_path)
    except Exception as exc:
        logging.info("Failed to save last inputs: %s", exc)


def _add_labeled_widget(parent, row, label_text, widget, *, label_style=None, label_width=None):
    kwargs = {"sticky": "w", "padx": (12, 8), "pady": 6}
    label_kwargs = {}
    if label_width:
        label_kwargs["width"] = label_width
        label_kwargs["anchor"] = "w"
    if label_style:
        ttk.Label(parent, text=label_text, style=label_style, **label_kwargs).grid(row=row, column=0, **kwargs)
    else:
        ttk.Label(parent, text=label_text, **label_kwargs).grid(row=row, column=0, **kwargs)
    widget.grid(row=row, column=1, sticky="ew", padx=(8, 12), pady=6)


def _add_pair_row(parent, row, pair1, pair2):
    """在同一行放两对 (标签, 变量)，横跨两列。pair = (label_text, var)。返回下一行行号。"""
    rowf = ttk.Frame(parent)
    rowf.grid(row=row, column=0, columnspan=2, sticky="ew", padx=(12, 12), pady=6)
    rowf.columnconfigure(0, weight=1)
    rowf.columnconfigure(1, weight=1)
    for col, (label_text, var) in enumerate((pair1, pair2)):
        cell = ttk.Frame(rowf)
        # 两列之间留间隔，避免右侧标签紧贴左侧输入框
        pad_x = (0, 12) if col == 0 else (12, 0)
        cell.grid(row=0, column=col, sticky="ew", padx=pad_x)
        # 标签固定宽度，文字左对齐
        ttk.Label(cell, text=label_text, width=PAIR_LABEL_WIDTH, anchor="w").pack(side="left", padx=(0, 6))
        entry = ttk.Entry(cell, textvariable=var)
        entry.pack(side="left", fill="x", expand=True)
    return row + 1


def _section_header(parent, row, text):
    ttk.Separator(parent, orient="horizontal").grid(
        row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=(14, 6)
    )
    ttk.Label(parent, text=text, style="Section.TLabel").grid(
        row=row + 1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 6)
    )
    return row + 2

def _load_last_saved():
    file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), cfg.LAST_SAVED_RELATIVE_PATH))
    if not os.path.exists(file_path):
        logging.info("No saved data file found: %s", file_path)
        return

    try:
        values = {}
        with open(file_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()

        for name, value in values.items():
            var = getattr(ig, name, None)
            if var is not None:
                var.set(value)

        logging.info("Loaded saved data from %s", file_path)
    except Exception as exc:
        logging.info("Failed to load saved data from %s: %s", file_path, exc)


def refresh_ui_state():
    """根据当前参数实时预览"计算后的数值"。"""
    ig.preview_new_value()


def _wire_live_refresh():
    watched_vars = [
        "scale_var",
        "min_value_var",
        "max_value_var",
        "decimal_places_var",
        "is_percent_var",
        "use_thousands_var_1",
    ]

    for var_name in watched_vars:
        var = getattr(ig, var_name, None)
        if var is not None:
            var.trace_add("write", lambda *_: refresh_ui_state())


def _scrollable_container(parent):
    """把 parent 变成可垂直滚动的容器，返回承载内容的 inner 帧。

    用法：inner = _scrollable_container(parent)，之后所有控件都放到 inner 上。
    """
    canvas = tk.Canvas(parent, highlightthickness=0)
    vbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vbar.set)
    vbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    inner = ttk.Frame(canvas)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_enter(_e):
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _on_leave(_e):
        canvas.unbind_all("<MouseWheel>")

    canvas.bind("<Enter>", _on_enter)
    canvas.bind("<Leave>", _on_leave)
    return inner


def _build_daily_reward_tab(parent):
    inner = _scrollable_container(parent)

    # 左右两栏：左=参数设置，右=结果（uniform 强制两栏等宽，不随内容/按钮变化，只在窗口缩放时变化）
    inner.columnconfigure(0, weight=1, uniform="halves")
    inner.columnconfigure(1, weight=1, uniform="halves")
    inner.rowconfigure(0, weight=1)
    left = ttk.Frame(inner)
    right = ttk.Frame(inner)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
    right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
    left.columnconfigure(0, weight=0)
    left.columnconfigure(1, weight=1)
    right.columnconfigure(0, weight=0)
    right.columnconfigure(1, weight=1)

    style = ttk.Style(parent)
    style.configure("Section.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("Hint.TLabel", foreground="#888888", font=("Microsoft YaHei UI", 9))
    style.configure("Status.TLabel", foreground="#0066cc", font=("Microsoft YaHei UI", 9))

    defaults = cfg.DAILY_DEFAULTS
    r1 = defaults["region_1"]
    r2 = defaults["region_2"]
    r3 = defaults["region_3"]
    row = 0

    # ---- 图片路径 ----（左栏）
    row = _section_header(left, row, "图片路径")
    ig.input_image_var = tk.StringVar(value=_default_path(cfg.DEFAULT_INPUT_IMAGE))
    ig.output_image_var = tk.StringVar(value=_default_path(cfg.DEFAULT_OUTPUT_IMAGE))
    _add_file_row(left, row, "输入图片", ig.input_image_var, lambda: _browse_file(ig.input_image_var))
    row += 1
    _add_file_row(left, row, "输出图片", ig.output_image_var, lambda: _browse_save(ig.output_image_var))
    row += 1

    # ---- 定位与裁剪 ----（左栏）
    row = _section_header(left, row, "定位与裁剪")
    ig.keyword_var = tk.StringVar(value=defaults["keyword"])
    kw_frame = ttk.Frame(left)
    kw_frame.columnconfigure(0, weight=1)
    kw_entry = ttk.Entry(kw_frame, textvariable=ig.keyword_var)
    kw_entry.grid(row=0, column=0, sticky="ew")
    ttk.Button(kw_frame, text="定位", width=6,
               command=lambda: _run_action(ig.locate_keyword_preview)).grid(row=0, column=1, padx=(6, 0))
    _add_labeled_widget(left, row, "关键词", kw_frame)
    row += 1
    ig.locate_result_var = tk.StringVar(value="")
    _add_labeled_widget(left, row, "关键词位置",
                        ttk.Entry(left, textvariable=ig.locate_result_var),
                        label_width=NORMAL_LABEL_WIDTH)
    row += 1
    # 区域1 参数分组框
    region_frame = ttk.LabelFrame(left, text="区域1-交易日")
    region_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
    region_frame.columnconfigure(0, weight=1)
    region_frame.columnconfigure(1, weight=1)
    rrow = 0
    ig.delta_x_var_1 = tk.StringVar(value=str(r1["delta"][0]))
    ig.delta_y_var_1 = tk.StringVar(value=str(r1["delta"][1]))
    rrow = _add_pair_row(region_frame, rrow, ("偏移 X", ig.delta_x_var_1), ("偏移 Y", ig.delta_y_var_1))
    ig.grid_rows_var_1 = tk.StringVar(value=str(r1["grid_rows"]))
    ig.row_spacing_var_1 = tk.StringVar(value=str(r1["row_spacing"]))
    rrow = _add_pair_row(region_frame, rrow, ("行数", ig.grid_rows_var_1), ("行间距", ig.row_spacing_var_1))
    ig.grid_cols_var_1 = tk.StringVar(value=str(r1["grid_cols"]))
    ig.col_spacing_var_1 = tk.StringVar(value=str(r1["col_spacing"]))
    rrow = _add_pair_row(region_frame, rrow, ("列数", ig.grid_cols_var_1), ("列间距", ig.col_spacing_var_1))
    ig.size_w_var_1 = tk.StringVar(value=str(r1["size"][0]))
    ig.size_h_var_1 = tk.StringVar(value=str(r1["size"][1]))
    rrow = _add_pair_row(region_frame, rrow, ("区域宽", ig.size_w_var_1), ("区域高", ig.size_h_var_1))
    ig.use_thousands_var_1 = tk.BooleanVar(value=r1.get("use_thousands", False))
    ig.keep_plus_var_1 = tk.BooleanVar(value=r1.get("keep_plus", False))
    ig.max_text_height_var_1 = tk.StringVar(value=str(r1.get("max_text_height", 28)))
    opt_row = ttk.Frame(region_frame)
    opt_row.grid(row=rrow, column=0, columnspan=2, sticky="w", padx=12, pady=(2, 6))
    ttk.Label(opt_row, text="最大高度", width=PAIR_LABEL_WIDTH + 1, anchor="w").pack(side="left")
    ttk.Spinbox(opt_row, textvariable=ig.max_text_height_var_1, from_=8, to=120, width=5).pack(side="left")
    ttk.Checkbutton(opt_row, text="千分位分隔符", variable=ig.use_thousands_var_1).pack(side="left", padx=(32, 0))
    ttk.Checkbutton(opt_row, text="正值保留+号", variable=ig.keep_plus_var_1).pack(side="left", padx=(32, 0))
    row += 1

    # 区域2 参数分组框（月收益）
    region2_frame = ttk.LabelFrame(left, text="区域2-月收益")
    region2_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
    region2_frame.columnconfigure(0, weight=1)
    region2_frame.columnconfigure(1, weight=1)
    rrow2 = 0
    ig.delta_x_var_2 = tk.StringVar(value=str(r2["delta"][0]))
    ig.delta_y_var_2 = tk.StringVar(value=str(r2["delta"][1]))
    rrow2 = _add_pair_row(region2_frame, rrow2, ("偏移 X", ig.delta_x_var_2), ("距底边 Y", ig.delta_y_var_2))
    ig.size_w_var_2 = tk.StringVar(value=str(r2["size"][0]))
    ig.size_h_var_2 = tk.StringVar(value=str(r2["size"][1]))
    rrow2 = _add_pair_row(region2_frame, rrow2, ("区域宽", ig.size_w_var_2), ("区域高", ig.size_h_var_2))
    ig.use_thousands_var_2 = tk.BooleanVar(value=r2.get("use_thousands", True))
    ig.keep_plus_var_2 = tk.BooleanVar(value=r2.get("keep_plus", True))
    ig.max_text_height_var_2 = tk.StringVar(value=str(r2.get("max_text_height", 32)))
    opt_row2 = ttk.Frame(region2_frame)
    opt_row2.grid(row=rrow2, column=0, columnspan=2, sticky="w", padx=12, pady=(2, 6))
    ttk.Label(opt_row2, text="最大高度", width=PAIR_LABEL_WIDTH + 1, anchor="w").pack(side="left")
    ttk.Spinbox(opt_row2, textvariable=ig.max_text_height_var_2, from_=8, to=120, width=5).pack(side="left")
    ttk.Checkbutton(opt_row2, text="千分位分隔符", variable=ig.use_thousands_var_2).pack(side="left", padx=(32, 0))
    ttk.Checkbutton(opt_row2, text="正值保留+号", variable=ig.keep_plus_var_2).pack(side="left", padx=(32, 0))
    row += 1

    # 区域3 参数分组框（个股收益）
    region3_frame = ttk.LabelFrame(left, text="区域3-个股收益")
    region3_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
    region3_frame.columnconfigure(0, weight=1)
    region3_frame.columnconfigure(1, weight=1)
    rrow3 = 0
    ig.delta_x_var_3 = tk.StringVar(value=str(r3["delta"][0]))
    ig.delta_y_var_3 = tk.StringVar(value=str(r3["delta"][1]))
    rrow3 = _add_pair_row(region3_frame, rrow3, ("偏移 X", ig.delta_x_var_3), ("距底边 Y", ig.delta_y_var_3))
    ig.grid_rows_var_3 = tk.StringVar(value=str(r3["grid_rows"]))
    ig.row_spacing_var_3 = tk.StringVar(value=str(r3["row_spacing"]))
    rrow3 = _add_pair_row(region3_frame, rrow3, ("行数(最多)", ig.grid_rows_var_3), ("行间距", ig.row_spacing_var_3))
    ig.size_w_var_3 = tk.StringVar(value=str(r3["size"][0]))
    ig.size_h_var_3 = tk.StringVar(value=str(r3["size"][1]))
    rrow3 = _add_pair_row(region3_frame, rrow3, ("区域宽", ig.size_w_var_3), ("区域高", ig.size_h_var_3))
    ig.use_thousands_var_3 = tk.BooleanVar(value=r3.get("use_thousands", True))
    ig.keep_plus_var_3 = tk.BooleanVar(value=r3.get("keep_plus", True))
    ig.max_text_height_var_3 = tk.StringVar(value=str(r3.get("max_text_height", 40)))
    opt_row3 = ttk.Frame(region3_frame)
    opt_row3.grid(row=rrow3, column=0, columnspan=2, sticky="w", padx=12, pady=(2, 6))
    ttk.Label(opt_row3, text="最大高度", width=PAIR_LABEL_WIDTH + 1, anchor="w").pack(side="left")
    ttk.Spinbox(opt_row3, textvariable=ig.max_text_height_var_3, from_=8, to=120, width=5).pack(side="left")
    ttk.Checkbutton(opt_row3, text="千分位分隔符", variable=ig.use_thousands_var_3).pack(side="left", padx=(32, 0))
    ttk.Checkbutton(opt_row3, text="正值保留+号", variable=ig.keep_plus_var_3).pack(side="left", padx=(32, 0))
    row += 1

    # ---- OCR 设置 ----（左栏）
    row = _section_header(left, row, "OCR 设置")
    ig.threshold_var = tk.StringVar(value="")
    _add_labeled_widget(left, row, "灰度阈值", ttk.Entry(left, textvariable=ig.threshold_var, width=10))
    row += 1
    ttk.Label(left, text="（留空则不二值化，直接识别；填数值时按暗→黑/亮→白处理）",
              style="Hint.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 4))
    row += 1

    # ---- 数值计算 ----（左栏）
    row = _section_header(left, row, "数值计算")
    ig.scale_var = tk.StringVar(value=str(defaults["scale"]))
    ig.decimal_places_var = tk.StringVar(value=str(defaults["decimal_places"]))
    row = _add_pair_row(left, row, ("缩放倍率", ig.scale_var), ("小数位", ig.decimal_places_var))
    ig.min_value_var = tk.StringVar(value=str(defaults["min_value"]))
    ig.max_value_var = tk.StringVar(value=str(defaults["max_value"]))
    row = _add_pair_row(left, row, ("最小边界", ig.min_value_var), ("最大边界", ig.max_value_var))
    ig.is_percent_var = tk.BooleanVar(value=defaults["is_percent"])
    _add_labeled_widget(left, row, "识别百分比",
                        ttk.Checkbutton(left, text="文本中包含 %", variable=ig.is_percent_var))
    row += 1

    # ---- 生成样式 ----（左栏）
    row = _section_header(left, row, "生成样式")
    ig.font_size_var = tk.StringVar(value=str(defaults["font_size"]))
    ig.render_height_scale_var = tk.StringVar(value=str(cfg.RENDER_HEIGHT_SCALE))
    row = _add_pair_row(left, row, ("字号(0=自动)", ig.font_size_var), ("高度缩放倍率", ig.render_height_scale_var))

    # 颜色：区域1 全套(红/绿/灰 × 前景/背景 × 普通/高亮) + 区域2/3(红/绿/灰 × 前景/背景)
    color_grid = ttk.Frame(left)
    color_grid.grid(row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
    for c in range(3):
        color_grid.columnconfigure(c, weight=1)
    color_rows = [
        # 区域1（6 组全部）
        [("区域1-前景色-红", "fg_color_1_var", "fg_colors", 0),
         ("区域1-前景色-绿", "fg_color_2_var", "fg_colors", 1),
         ("区域1-前景色-灰", "fg_color_5_var", "fg_colors", 4)],
        [("区域1-背景色-红", "bg_color_1_var", "bg_colors", 0),
         ("区域1-背景色-绿", "bg_color_2_var", "bg_colors", 1),
         ("区域1-背景色-灰", "bg_color_5_var", "bg_colors", 4)],
        [("区域1-前景色-红(高亮)", "fg_color_3_var", "fg_colors", 2),
         ("区域1-前景色-绿(高亮)", "fg_color_4_var", "fg_colors", 3),
         ("区域1-前景色-灰(高亮)", "fg_color_6_var", "fg_colors", 5)],
        [("区域1-背景色-红(高亮)", "bg_color_3_var", "bg_colors", 2),
         ("区域1-背景色-绿(高亮)", "bg_color_4_var", "bg_colors", 3),
         ("区域1-背景色-灰(高亮)", "bg_color_6_var", "bg_colors", 5)],
        # 区域2（红/绿/灰）
        [("区域2-前景色-红", "fg_color_1_var_2", "fg_colors", 0),
         ("区域2-前景色-绿", "fg_color_2_var_2", "fg_colors", 1),
         ("区域2-前景色-灰", "fg_color_4_var_2", "fg_colors", 2)],
        [("区域2-背景色-红", "bg_color_1_var_2", "bg_colors", 0),
         ("区域2-背景色-绿", "bg_color_2_var_2", "bg_colors", 1),
         ("区域2-背景色-灰", "bg_color_4_var_2", "bg_colors", 2)],
        # 区域3（红/绿/灰）
        [("区域3-前景色-红", "fg_color_1_var_3", "fg_colors", 0),
         ("区域3-前景色-绿", "fg_color_2_var_3", "fg_colors", 1),
         ("区域3-前景色-灰", "fg_color_4_var_3", "fg_colors", 2)],
        [("区域3-背景色-红", "bg_color_1_var_3", "bg_colors", 0),
         ("区域3-背景色-绿", "bg_color_2_var_3", "bg_colors", 1),
         ("区域3-背景色-灰", "bg_color_4_var_3", "bg_colors", 2)],
    ]
    for r_i, cells in enumerate(color_rows):
        for c_i, (label, var_name, palette_key, color_idx) in enumerate(cells):
            if var_name.endswith("_2"):
                palette = defaults["region_2"][palette_key]
            elif var_name.endswith("_3"):
                palette = defaults["region_3"][palette_key]
            else:
                palette = defaults["region_1"][palette_key]
            var = tk.StringVar(value=palette[color_idx])
            setattr(ig, var_name, var)
            _add_color_cell(color_grid, r_i, c_i, label, var)
    row += 1

    # ---- 识别结果 / 计算数值 ----（右栏）
    rrow = 0
    rrow = _section_header(right, rrow, "识别结果")
    # 区域1：5x5；区域2：1格；区域3：1行5列（内部变量，不入 last_saved）
    ig.recognized_grid_vars = [[tk.StringVar() for _ in range(5)] for _ in range(5)]
    ig.recognized_region2_vars = [[tk.StringVar()]]
    ig.recognized_region3_vars = [[tk.StringVar() for _ in range(5)]]
    ig.cell_color_grid_vars = [[tk.StringVar() for _ in range(5)] for _ in range(5)]  # 内部：每格颜色类型(0-5)
    rrow = _add_grid(right, rrow, "区域1-交易日", ig.recognized_grid_vars,
                     readonly=False, frame_title="区域1-交易日")
    rrow = _add_grid(right, rrow, "区域2-月收益", ig.recognized_region2_vars,
                     readonly=False, frame_title="区域2-月收益")
    rrow = _add_grid(right, rrow, "区域3-个股收益", ig.recognized_region3_vars,
                     readonly=False, frame_title="区域3-个股收益")

    rrow = _section_header(right, rrow, "计算数值")
    ig.new_value_grid_vars = [[tk.StringVar() for _ in range(5)] for _ in range(5)]
    ig.new_value_region2_vars = [[tk.StringVar()]]
    ig.new_value_region3_vars = [[tk.StringVar() for _ in range(5)]]
    rrow = _add_grid(right, rrow, "区域1-交易日", ig.new_value_grid_vars,
                     frame_title="区域1-交易日")
    rrow = _add_grid(right, rrow, "区域2-月收益", ig.new_value_region2_vars,
                     frame_title="区域2-月收益")
    rrow = _add_grid(right, rrow, "区域3-个股收益", ig.new_value_region3_vars,
                     frame_title="区域3-个股收益")

    ig.status_var = tk.StringVar(value="就绪")
    ttk.Label(right, textvariable=ig.status_var, style="Status.TLabel",
              wraplength=420, justify="left").grid(
        row=rrow, column=0, columnspan=2, sticky="ew", padx=12, pady=6)

    _wire_live_refresh()
    refresh_ui_state()
    _load_last_saved()


def create_main_window():
    root = tk.Tk()
    root.title(cfg.GUI_TITLE)
    root.geometry(f"{cfg.WINDOW_WIDTH}x{cfg.WINDOW_HEIGHT}")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=10, pady=10)

    for tab_name in cfg.TAB_NAMES:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=tab_name)
        if tab_name == "日收益":
            _build_daily_reward_tab(frame)
        else:
            inner = _scrollable_container(frame)
            placeholder = ttk.Label(inner, text=f"{tab_name} 页面内容", anchor="center")
            placeholder.pack(expand=True, fill="both", padx=20, pady=40)

    button_frame = ttk.Frame(root)
    button_frame.pack(side="bottom", fill="x", padx=10, pady=10)

    extract_button = ttk.Button(button_frame, text=cfg.BUTTON_EXTRACT_TEXT, command=lambda: _run_action(ig.extract_data))
    check_button = ttk.Button(button_frame, text=cfg.BUTTON_CHECK_TEXT, command=lambda: _run_action(ig.run_format_checks_now))
    calculate_button = ttk.Button(button_frame, text=cfg.BUTTON_CALCULATE_TEXT, command=lambda: _run_action(ig.calculate_new_data))
    gen_image_button = ttk.Button(button_frame, text=cfg.BUTTON_GEN_IMAGE_TEXT, command=lambda: _run_action(ig.generate_image))
    export_button = ttk.Button(button_frame, text=cfg.BUTTON_EXPORT_TEXT, command=lambda: _run_action(ig.export_report))

    extract_button.pack(side="left", expand=True, fill="x", padx=(0, 5))
    check_button.pack(side="left", expand=True, fill="x", padx=(5, 5))
    calculate_button.pack(side="left", expand=True, fill="x", padx=(5, 5))
    gen_image_button.pack(side="left", expand=True, fill="x", padx=(5, 5))
    export_button.pack(side="right", expand=True, fill="x", padx=(5, 0))

    root.protocol("WM_DELETE_WINDOW", lambda: (_save_last_saved(), root.destroy()))

    return root


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("Launching Marvin Trade Assist GUI")
    main_window = create_main_window()
    main_window.mainloop()
