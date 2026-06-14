#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 转 TXT 工具 — 图形界面版
基于 pdfplumber 引擎，无需接触任何代码。
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

# ── 拖放支持 ──────────────────────────────────────────────────────────
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAVE_DND = True
except ImportError:
    HAVE_DND = False

# ── 第三方引擎 ──────────────────────────────────────────────────────────
try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ═══════════════════════════════════════════════════════════════════════
#  核心转换引擎（用户不直接接触）
# ═══════════════════════════════════════════════════════════════════════
class PdfEngine:
    """封装 pdfplumber 的提取逻辑，对外只暴露 convert() 一个入口。"""

    @staticmethod
    def convert(pdf_path: str, output_dir: str, options: dict) -> list[str]:
        """
        转换一个 PDF 文件，返回生成的 TXT 文件路径列表。
        options 支持：
          - layout    : bool   — 保留原始版面（逐行位置感知）
          - per_page  : bool   — 每页一个 TXT
          - page_mark : bool   — 在输出中插入页码标记
          - merge     : bool   — 所有页合并为一个 TXT
          - tables    : bool   — 提取表格区域文本
          - paragraph : bool   — 自然段落排版（合并碎行）
          - continuous: bool   — 连续全文（无分页分隔）
        """
        if pdfplumber is None:
            raise RuntimeError("pdfplumber 未安装，无法执行转换。")

        pages_text = []

        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            for idx, page in enumerate(pdf.pages):
                page_num = idx + 1
                text = ""

                # ── 版面模式 ──────────────────────────────────────────
                if options.get("layout"):
                    text = page.dedupe_chars().extract_text(
                        x_tolerance=3, y_tolerance=3
                    ) or ""
                else:
                    text = page.extract_text() or ""

                # ── 表格文本 ──────────────────────────────────────────
                if options.get("tables"):
                    table_text = PdfEngine._extract_tables(page)
                    if table_text:
                        text += "\n\n[表格内容]\n" + table_text

                # ── 自然段落排版 ────────────────────────────────────
                if options.get("paragraph"):
                    text = PdfEngine._to_paragraphs(text)

                # ── 页码标记 ──────────────────────────────────────────
                if options.get("page_mark"):
                    marker = f"\n\n{'═' * 40}\n—— 第 {page_num}/{total} 页 ——\n{'═' * 40}\n\n"
                    if options.get("layout"):
                        text = marker + text
                    else:
                        text = marker + text

                pages_text.append((page_num, text))

        # ── 写出文件 ──────────────────────────────────────────────────
        stem = Path(pdf_path).stem
        out_files = []
        continuous = options.get("continuous")

        if continuous:
            # ── 连续全文模式（无分页无标记，直接拼）───────────────────
            all_text = ""
            for pn, pt in pages_text:
                all_text += pt + "\n"
            out_path = os.path.join(output_dir, f"{stem}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(all_text.strip())
            out_files.append(out_path)
        elif options.get("merge"):
            # ── 合并模式：一个 TXT ────────────────────────────────────
            all_text = ""
            for pn, pt in pages_text:
                all_text += pt + "\n\n"
            out_path = os.path.join(output_dir, f"{stem}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(all_text.strip())
            out_files.append(out_path)
        elif options.get("per_page"):
            # ── 分页模式：每页一个 TXT ────────────────────────────────
            for pn, pt in pages_text:
                out_path = os.path.join(output_dir, f"{stem}_第{pn}页.txt")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(pt.strip())
                out_files.append(out_path)
        else:
            # ── 单文件模式（默认）─────────────────────────────────────
            all_text = ""
            for pn, pt in pages_text:
                all_text += pt + "\n\n"
            out_path = os.path.join(output_dir, f"{stem}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(all_text.strip())
            out_files.append(out_path)

        return out_files

    # ── 内部：段落合并 ────────────────────────────────────────────────
    @staticmethod
    def _to_paragraphs(text: str) -> str:
        """
        将 PDF 提取的碎行智能合并为自然段落。
        处理流程：
          1. 修复连字符断词 (word-\\nword → wordword)
          2. 按段尾标点（。！？.!?）识别段落边界
          3. 未结束的行合并到当前段落
        """
        # ── 第1步：修复连字符断词 ─────────────────────────────────────
        import re
        text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)

        # ── 第2步：按行分割并合并为段落 ───────────────────────────────
        lines = text.split("\n")
        paragraphs = []
        current = ""

        for line in lines:
            stripped = line.strip()
            if not stripped:
                # 空行 → 段落结束
                if current:
                    paragraphs.append(current)
                    current = ""
                continue

            if current:
                # 判断当前段落是否已结束（以段尾标点结尾）
                para_end = re.search(r'[。！？\.\!\?]$', current)
                if para_end:
                    # 段落结束，新行另起一段
                    paragraphs.append(current)
                    current = stripped
                else:
                    # 段落未结束，追加当前行
                    current += " " + stripped
            else:
                current = stripped

        # 最后一个段落
        if current:
            paragraphs.append(current)

        return "\n\n".join(paragraphs)

    # ── 内部：表格提取 ────────────────────────────────────────────────
    @staticmethod
    def _extract_tables(page) -> str:
        """从页面提取表格，返回纯文本表示。"""
        tables = page.extract_tables()
        if not tables:
            return ""

        lines = []
        for ti, table in enumerate(tables, 1):
            lines.append(f"  【表格 {ti}】")
            for row in table:
                cells = [
                    (cell.strip() if cell else "")
                    for cell in row
                ]
                lines.append("  | " + " | ".join(cells) + " |")
            lines.append("")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
#  图形界面
# ═══════════════════════════════════════════════════════════════════════
class Pdf2TxtApp:
    """主窗口，所有控件都是中文标签 + 开关/选择器，没有任何代码痕迹。"""

    # ── 配色 ──────────────────────────────────────────────────────────
    BG = "#f5f5f0"          # 米白底
    FG = "#1e1e1e"          # 深灰字
    ACCENT = "#2b5797"      # 蓝色主色
    CARD_BG = "#ffffff"     # 卡片白
    BORDER = "#d0d0d0"      # 边框灰
    SUCCESS = "#2e7d32"     # 绿色
    ERROR = "#c62828"       # 红色

    def __init__(self):
        # ── 拖放支持：如果底层 tkdnd 库不可用则静默降级 ──────────────
        self.have_dnd = HAVE_DND
        if self.have_dnd:
            try:
                self.root = TkinterDnD.Tk()
            except Exception:
                self.have_dnd = False
                self.root = tk.Tk()
        else:
            self.root = tk.Tk()
        self.root.title("PDF 转 TXT 工具")
        self.root.geometry("780x720")
        self.root.minsize(700, 650)
        self.root.configure(bg=self.BG)

        # 尝试设置图标（忽略失败）
        try:
            self.root.iconbitmap(default=__file__)
        except Exception:
            pass

        # ── 状态变量 ──────────────────────────────────────────────────
        self.pdf_paths: list[str] = []       # 待处理的文件列表
        self.output_dir: str = ""            # 输出目录
        self.running = False                 # 是否正在运行

        # ── 选项变量（全部是开关/下拉）────────────────────────────────
        self.opt_layout = tk.BooleanVar(value=True)   # 保留版面
        self.opt_tables = tk.BooleanVar(value=False)  # 提取表格
        self.opt_page_mark = tk.BooleanVar(value=False) # 页码标记（默认关闭）
        self.opt_paragraph = tk.BooleanVar(value=True) # 自然段落排版（默认开启）
        self.opt_mode = tk.StringVar(value="continuous")   # 输出模式: continuous / merge / per_page / single

        # ── 构建界面 ──────────────────────────────────────────────────
        self._build_ui()

        # ── 拖放支持 ──────────────────────────────────────────────────
        self._enable_drag_drop()

        # ── 启动主循环 ────────────────────────────────────────────────
        self.root.mainloop()

    # ══════════════════════════════════════════════════════════════════
    #  界面构建
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self):
        """自上而下构建所有界面元素。"""
        # ── 标题栏 ────────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=self.ACCENT, height=56)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header, text="📄  PDF → TXT  转换工具",
            fg="white", bg=self.ACCENT,
            font=("微软雅黑", 16, "bold")
        ).pack(side=tk.LEFT, padx=20, pady=10)
        tk.Label(
            header, text="基于 pdfplumber 引擎",
            fg="#c0d0e0", bg=self.ACCENT,
            font=("微软雅黑", 9)
        ).pack(side=tk.RIGHT, padx=20)

        # ── 主内容区（带滚动）──────────────────────────────────────────
        main_canvas = tk.Canvas(self.root, bg=self.BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=main_canvas.yview)
        self.scroll_frame = tk.Frame(main_canvas, bg=self.BG)

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        main_canvas.create_window((0, 0), window=self.scroll_frame, anchor=tk.NW)
        main_canvas.configure(yscrollcommand=scrollbar.set)

        main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ── 绑定鼠标滚轮 ──────────────────────────────────────────────
        def _on_mousewheel(event):
            main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.root.bind_all("<MouseWheel>", _on_mousewheel)

        body = self.scroll_frame

        # ── 卡片：文件选择 ────────────────────────────────────────────
        self._card_start(body, "📂  选择 PDF 文件")
        self._file_selector(body)
        self._card_end(body)

        # ── 文件列表 ──────────────────────────────────────────────────
        self._card_start(body, "📋  待转换列表")
        self._file_list(body)
        self._card_end(body)

        # ── 卡片：输出设置 ────────────────────────────────────────────
        self._card_start(body, "📁  输出设置")
        self._output_selector(body)
        self._card_end(body)

        # ── 卡片：转换选项 ────────────────────────────────────────────
        self._card_start(body, "⚙️  转换选项")
        self._options_panel(body)
        self._card_end(body)

        # ── 底部操作栏 ────────────────────────────────────────────────
        self._action_bar(body)

        # ── 进度条 ────────────────────────────────────────────────────
        self._progress_section(body)

        # ── 日志输出 ──────────────────────────────────────────────────
        self._card_start(body, "📝  运行日志")
        self._log_area(body)
        self._card_end(body)

    # ── 卡片辅助 ────────────────────────────────────────────────────
    def _card_start(self, parent, title):
        card = tk.Frame(parent, bg=self.CARD_BG, bd=0,
                        highlightbackground=self.BORDER,
                        highlightthickness=1)
        card.pack(fill=tk.X, padx=16, pady=(8, 2))
        self._current_card = card

        header = tk.Frame(card, bg=self.CARD_BG)
        header.pack(fill=tk.X, padx=12, pady=(8, 0))
        tk.Label(
            header, text=title,
            bg=self.CARD_BG, fg=self.FG,
            font=("微软雅黑", 11, "bold")
        ).pack(anchor=tk.W)

        self._card_body = tk.Frame(card, bg=self.CARD_BG)
        self._card_body.pack(fill=tk.X, padx=12, pady=(4, 10))

    def _card_end(self, parent):
        pass  # 卡片由 pack 自动布局

    # ── 文件选择 ────────────────────────────────────────────────────
    def _file_selector(self, parent):
        row = tk.Frame(self._card_body, bg=self.CARD_BG)
        row.pack(fill=tk.X, pady=2)

        btn_style = {"font": ("微软雅黑", 9), "bd": 0, "cursor": "hand2"}

        tk.Button(row, text="📄  选择文件…", bg="#e8e8e8",
                  command=self._add_files, **btn_style).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(row, text="📁  选择文件夹…", bg="#e8e8e8",
                  command=self._add_folder, **btn_style).pack(side=tk.LEFT, padx=6)
        tk.Button(row, text="🗑️  清空列表", bg="#fde8e8", fg=self.ERROR,
                  command=self._clear_list, **btn_style).pack(side=tk.LEFT, padx=6)

        # 拖拽提示 — HOVER 时高亮
        self.dnd_hint = tk.Label(
            row,
            text="（📥 拖放 PDF 文件或文件夹到窗口任意位置）",
            bg=self.CARD_BG, fg="#999", font=("微软雅黑", 8)
        )
        self.dnd_hint.pack(side=tk.RIGHT, padx=6)

        # 给窗口注册进入/离开事件（视觉反馈）
        if self.have_dnd:
            self.root.dnd_bind("<<DragEnter>>",
                lambda e: self.dnd_hint.config(
                    text="📥 松开鼠标添加文件", bg="#e3f2fd", fg=self.ACCENT
                ))
            self.root.dnd_bind("<<DragLeave>>",
                lambda e: self.dnd_hint.config(
                    text="（📥 拖放 PDF 文件或文件夹到窗口任意位置）",
                    bg=self.CARD_BG, fg="#999"
                ))
            self.root.dnd_bind("<<Drop>>",
                lambda e: self.dnd_hint.config(
                    text="（📥 拖放 PDF 文件或文件夹到窗口任意位置）",
                    bg=self.CARD_BG, fg="#999"
                ))

    # ── 文件列表 ────────────────────────────────────────────────────
    def _file_list(self, parent):
        frame = tk.Frame(self._card_body, bg=self.CARD_BG)
        frame.pack(fill=tk.X, pady=2)

        # 带滚动条的列表框
        list_frame = tk.Frame(frame, bg=self.CARD_BG)
        list_frame.pack(fill=tk.X)

        self.file_listbox = tk.Listbox(
            list_frame, height=5, font=("Consolas", 9),
            bg="#fafafa", fg=self.FG,
            selectbackground=self.ACCENT, selectforeground="white",
            relief=tk.FLAT, bd=0,
            highlightbackground=self.BORDER, highlightthickness=1
        )
        self.file_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)

        list_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                     command=self.file_listbox.yview)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.configure(yscrollcommand=list_scroll.set)

        # 底部统计
        self.file_count_label = tk.Label(
            frame, text="共 0 个文件", bg=self.CARD_BG, fg="#666",
            font=("微软雅黑", 8)
        )
        self.file_count_label.pack(anchor=tk.W, pady=(4, 0))

    # ── 输出目录 ────────────────────────────────────────────────────
    def _output_selector(self, parent):
        row = tk.Frame(self._card_body, bg=self.CARD_BG)
        row.pack(fill=tk.X, pady=2)

        self.output_label = tk.Label(
            row, text="（未设置，默认使用 PDF 所在目录）",
            bg=self.CARD_BG, fg="#999", font=("微软雅黑", 9),
            anchor=tk.W
        )
        self.output_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Button(row, text="📁  选择目录…", bg="#e8e8e8",
                  font=("微软雅黑", 9), bd=0, cursor="hand2",
                  command=self._choose_output_dir).pack(side=tk.RIGHT)

    # ── 选项面板 ────────────────────────────────────────────────────
    def _options_panel(self, parent):
        """全是开关（Checkbutton）+ 单选，没有代码。"""
        body = self._card_body

        # 第1行：保留版面 + 提取表格
        row1 = tk.Frame(body, bg=self.CARD_BG)
        row1.pack(fill=tk.X, pady=2)

        self._switch(row1, "📐  保留原始版面", self.opt_layout,
                     "按原始排版提取文本（推荐复杂PDF）")
        self._switch(row1, "📊  提取表格文本", self.opt_tables,
                     "同时提取表格区域的内容")

        # 第2行：输出模式（单选按钮组）
        row2 = tk.Frame(body, bg=self.CARD_BG)
        row2.pack(fill=tk.X, pady=(8, 2))

        tk.Label(row2, text="📄  输出模式：", bg=self.CARD_BG,
                 font=("微软雅黑", 9)).pack(side=tk.LEFT)

        modes = [
            ("📖  连续全文", "continuous", "所有页从头到尾连在一起，无页码无分隔"),
            ("合并为一个 TXT", "merge", "所有页内容合并在同一个文件中"),
            ("每页一个 TXT", "per_page", "每一页单独保存为一个文件"),
            ("每文件一个 TXT", "single", "每个 PDF 生成一个 TXT（不拆分）"),
        ]
        for text, val, tip in modes:
            rb = tk.Radiobutton(
                row2, text=text, variable=self.opt_mode, value=val,
                bg=self.CARD_BG, font=("微软雅黑", 9),
                activebackground=self.CARD_BG,
                cursor="hand2"
            )
            rb.pack(side=tk.LEFT, padx=(0, 12))
            self._add_tooltip(rb, tip)

        # 第3行：自然段落 + 页码标记
        row3 = tk.Frame(body, bg=self.CARD_BG)
        row3.pack(fill=tk.X, pady=2)

        self._switch(row3, "📝  自然段落排版", self.opt_paragraph,
                     "自动合并零散行，按自然段落组织文本（推荐）")
        self._switch(row3, "🔢  添加页码标记", self.opt_page_mark,
                     "在每个页面的开始处标注页码")

    def _switch(self, parent, label, var, tooltip=""):
        """生成一个开关样式的 Checkbutton。"""
        cb = tk.Checkbutton(
            parent, text=label, variable=var,
            bg=parent["bg"], font=("微软雅黑", 9),
            activebackground=parent["bg"],
            cursor="hand2",
            selectcolor="#e0e8f0"
        )
        cb.pack(side=tk.LEFT, padx=(0, 16))
        if tooltip:
            self._add_tooltip(cb, tooltip)
        return cb

    # ── 操作栏 ──────────────────────────────────────────────────────
    def _action_bar(self, parent):
        frame = tk.Frame(parent, bg=self.BG)
        frame.pack(fill=tk.X, padx=16, pady=(12, 4))

        self.start_btn = tk.Button(
            frame, text="🚀  开始转换",
            bg=self.ACCENT, fg="white",
            font=("微软雅黑", 13, "bold"),
            bd=0, cursor="hand2",
            padx=30, pady=8,
            activebackground="#1a3f6e",
            activeforeground="white",
            command=self._start_conversion
        )
        self.start_btn.pack(side=tk.LEFT)

        self.status_label = tk.Label(
            frame, text="就绪，请添加 PDF 文件",
            bg=self.BG, fg="#666", font=("微软雅黑", 9)
        )
        self.status_label.pack(side=tk.LEFT, padx=16)

    # ── 进度条 ──────────────────────────────────────────────────────
    def _progress_section(self, parent):
        frame = tk.Frame(parent, bg=self.BG)
        frame.pack(fill=tk.X, padx=16, pady=4)

        # 进度百分比
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_label = tk.Label(
            frame, text="0%", bg=self.BG, fg="#666",
            font=("Consolas", 8)
        )
        self.progress_label.pack(anchor=tk.W)

        self.progress_bar = ttk.Progressbar(
            frame, variable=self.progress_var, maximum=100,
            length=0  # fill=tk.X 会处理宽度
        )
        self.progress_bar.pack(fill=tk.X, pady=2)

    # ── 日志 ──────────────────────────────────────────────────────────
    def _log_area(self, parent):
        self.log = scrolledtext.ScrolledText(
            self._card_body,
            height=10,
            font=("Consolas", 9),
            bg="#fafafa", fg=self.FG,
            relief=tk.FLAT, bd=0,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            wrap=tk.WORD
        )
        self.log.pack(fill=tk.X, pady=2)

        # 日志颜色标签
        self.log.tag_config("info", foreground="#1a1a1a")
        self.log.tag_config("success", foreground=self.SUCCESS)
        self.log.tag_config("error", foreground=self.ERROR, font=("Consolas", 9, "bold"))
        self.log.tag_config("title", foreground=self.ACCENT,
                            font=("微软雅黑", 9, "bold"))

    # ══════════════════════════════════════════════════════════════════
    #  事件处理
    # ══════════════════════════════════════════════════════════════════

    def _add_files(self):
        """弹出文件选择对话框，添加 PDF。"""
        files = filedialog.askopenfilenames(
            title="选择 PDF 文件",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")]
        )
        if not files:
            return
        added = 0
        for f in files:
            if f.lower().endswith(".pdf") and f not in self.pdf_paths:
                self.pdf_paths.append(f)
                added += 1
        self._refresh_file_list()
        if added:
            self.log_write(f"✅ 已添加 {added} 个 PDF 文件", "success")
        self._update_status()

    def _add_folder(self):
        """选择文件夹，自动扫描所有 PDF。"""
        folder = filedialog.askdirectory(title="选择包含 PDF 的文件夹")
        if not folder:
            return
        found = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(".pdf"):
                    full = os.path.join(root, f)
                    if full not in self.pdf_paths:
                        found.append(full)
        if not found:
            messagebox.showinfo("提示", "该文件夹中未找到 PDF 文件。")
            return
        self.pdf_paths.extend(found)
        self._refresh_file_list()
        self.log_write(f"✅ 已添加文件夹中的 {len(found)} 个 PDF 文件", "success")
        self._update_status()

    def _clear_list(self):
        """清空文件列表。"""
        self.pdf_paths.clear()
        self._refresh_file_list()
        self.log_write("🗑️ 已清空文件列表", "info")
        self._update_status()

    def _choose_output_dir(self):
        """选择输出目录。"""
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.output_dir = d
            self.output_label.config(text=f"📁  {d}", fg="#1a1a1a")
            self.log_write(f"📁 输出目录已设置为：{d}", "info")

    def _refresh_file_list(self):
        """刷新文件列表显示。"""
        self.file_listbox.delete(0, tk.END)
        for f in self.pdf_paths:
            name = os.path.basename(f)
            folder = os.path.dirname(f)
            self.file_listbox.insert(tk.END, f"📄  {name}  —  {folder}")
        self.file_count_label.config(text=f"共 {len(self.pdf_paths)} 个文件")

    def _update_status(self):
        """更新底部状态栏。"""
        n = len(self.pdf_paths)
        if n == 0:
            self.status_label.config(text="请添加 PDF 文件", fg="#666")
        else:
            self.status_label.config(
                text=f"已就绪 — {n} 个文件等待转换",
                fg=self.ACCENT
            )

    # ── 拖放支持 ────────────────────────────────────────────────────
    def _enable_drag_drop(self):
        """用 tkinterdnd2 注册文件拖放。"""
        if not self.have_dnd:
            return
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind("<<Drop>>", self._handle_drop)

    def _handle_drop(self, event):
        """处理拖放进来的文件。"""
        if self.running:
            self.log_write("⏳ 转换进行中，请等待完成后再拖放文件", "error")
            return
        # tkinterdnd2 传回的 data 是用 "{} " 分隔的文件路径字符串
        raw = event.data
        paths = []
        # 解析带引号或不带引号的文件路径
        i = 0
        while i < len(raw):
            if raw[i] == "{":
                end = raw.find("}", i)
                if end == -1:
                    break
                paths.append(raw[i+1:end])
                i = end + 1
            elif raw[i] == "\"":
                end = raw.find("\"", i+1)
                if end == -1:
                    break
                paths.append(raw[i+1:end])
                i = end + 1
            elif not raw[i].isspace():
                end = i + 1
                while end < len(raw) and not raw[end].isspace():
                    end += 1
                paths.append(raw[i:end])
                i = end
            else:
                i += 1

        added = 0
        for p in paths:
            p = p.strip()
            # 如果是目录，递归扫描 PDF
            if os.path.isdir(p):
                for root_dir, dirs, files in os.walk(p):
                    for f in files:
                        if f.lower().endswith(".pdf"):
                            full = os.path.join(root_dir, f)
                            if full not in self.pdf_paths:
                                self.pdf_paths.append(full)
                                added += 1
            elif p.lower().endswith(".pdf"):
                if p not in self.pdf_paths:
                    self.pdf_paths.append(p)
                    added += 1

        if added:
            self._refresh_file_list()
            self.log_write(f"📥 拖放添加了 {added} 个 PDF 文件", "success")
            self._update_status()

    # ── 日志写入 ────────────────────────────────────────────────────
    def log_write(self, msg, tag="info"):
        """向日志区域追加一行。"""
        self.log.insert(tk.END, msg + "\n", tag)
        self.log.see(tk.END)
        self.root.update_idletasks()

    # ── 气泡提示 ────────────────────────────────────────────────────
    _tooltip = None

    def _add_tooltip(self, widget, text):
        """鼠标悬停时显示气泡提示。"""
        def show(event):
            if self._tooltip:
                return
            x = event.x_root + 12
            y = event.y_root + 8
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tip.configure(bg="#333")
            lbl = tk.Label(tip, text=text, bg="#333", fg="white",
                           font=("微软雅黑", 8),
                           padx=8, pady=4, wraplength=280)
            lbl.pack()
            self._tooltip = tip

        def hide(event):
            if self._tooltip:
                self._tooltip.destroy()
                self._tooltip = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    # ══════════════════════════════════════════════════════════════════
    #  核心转换（后台线程）
    # ══════════════════════════════════════════════════════════════════

    def _start_conversion(self):
        """校验并启动转换（在后台线程运行）。"""
        if not self.pdf_paths:
            messagebox.showwarning("提示", "请先添加 PDF 文件。")
            return
        if self.running:
            messagebox.showinfo("提示", "正在转换中，请等待完成。")
            return

        # 检查引擎
        if pdfplumber is None:
            messagebox.showerror("错误", "pdfplumber 未安装。\n请在命令行执行：pip install pdfplumber")
            return

        # 确定输出目录
        out_dir = self.output_dir
        if not out_dir:
            # 默认使用第一个 PDF 所在目录
            out_dir = os.path.dirname(self.pdf_paths[0])

        # 收集选项
        mode = self.opt_mode.get()
        options = {
            "layout": self.opt_layout.get(),
            "tables": self.opt_tables.get(),
            "page_mark": self.opt_page_mark.get(),
            "paragraph": self.opt_paragraph.get(),
            "continuous": mode == "continuous",
            "per_page": mode == "per_page",
            "merge": mode == "merge",
        }

        # UI 状态
        self.running = True
        self.start_btn.config(text="⏳  转换中…", state=tk.DISABLED)
        self.progress_var.set(0)
        self.log_write("", "info")  # 空行
        self.log_write("═" * 50, "title")
        self.log_write("🚀  开始批量转换", "title")

        files = self.pdf_paths.copy()

        # 启动后台线程
        thread = threading.Thread(
            target=self._convert_all,
            args=(files, out_dir, options),
            daemon=True
        )
        thread.start()

    def _convert_all(self, files: list[str], out_dir: str, options: dict):
        """后台批量转换（在子线程运行）。"""
        total = len(files)
        success_count = 0
        error_count = 0

        for idx, pdf_path in enumerate(files):
            # ── 进度更新 ──────────────────────────────────────────────
            pct = int((idx / total) * 100)
            self.root.after(0, self._update_progress, pct, idx + 1, total)

            # ── 显示当前文件 ──────────────────────────────────────────
            name = os.path.basename(pdf_path)
            self.log_write(f"\n[{idx+1}/{total}] 📄  {name}", "info")

            try:
                out_files = PdfEngine.convert(pdf_path, out_dir, options)
                success_count += 1
                for of in out_files:
                    self.log_write(f"   ✅  → {of}", "success")
            except Exception as e:
                error_count += 1
                self.log_write(f"   ❌  错误：{e}", "error")

        # ── 完成 ──────────────────────────────────────────────────────
        self.root.after(0, self._conversion_done, success_count, error_count)

    def _update_progress(self, pct, current, total):
        """UI 线程：更新进度条。"""
        self.progress_var.set(pct)
        self.progress_label.config(text=f"{pct}%  ({current}/{total})")
        self.status_label.config(
            text=f"正在转换… {current}/{total}",
            fg=self.ACCENT
        )

    def _conversion_done(self, success: int, error: int):
        """UI 线程：转换完成。"""
        self.running = False
        self.start_btn.config(text="🚀  开始转换", state=tk.NORMAL)
        self.progress_var.set(100)
        self.progress_label.config(text="100%  完成")

        total = success + error
        if error == 0:
            msg = f"🎉  全部完成！{total} 个文件转换成功。"
            tag = "success"
            self.status_label.config(text=msg, fg=self.SUCCESS)
        elif success > 0:
            msg = f"⚠️  完成：{success} 成功，{error} 失败。"
            tag = "error"
            self.status_label.config(text=msg, fg="#e65100")
        else:
            msg = f"❌  全部失败，请检查日志。"
            tag = "error"
            self.status_label.config(text=msg, fg=self.ERROR)

        self.log_write("", "info")
        self.log_write(msg, tag)
        self.log_write("═" * 50, "title")

        # 弹出通知
        if error == 0 and total > 0:
            messagebox.showinfo("完成", f"全部 {total} 个文件转换成功！")
        elif error > 0:
            messagebox.showwarning("完成",
                f"转换完成。\n成功：{success}\n失败：{error}\n\n请查看日志了解详情。")

    # ══════════════════════════════════════════════════════════════════
    #  工具：生成 EXE 的入口提示
    # ══════════════════════════════════════════════════════════════════
    @staticmethod
    def show_exe_guide():
        """如果想打包成独立 exe 文件，可参考此方法。"""
        print("使用 PyInstaller 打包：")
        print("  pip install pyinstaller")
        print("  pyinstaller --onefile --windowed --name PDF转TXT工具 PDF转TXT工具.py")


# ═══════════════════════════════════════════════════════════════════════
#  启动入口
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    Pdf2TxtApp()
