#!/usr/bin/env python3
"""GIM RENDER — Tkinter-based native GUI."""
from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from constants import (
    DEFAULT_BANDS,
    DEFAULT_CRF,
    DEFAULT_ENCODER_PRESET,
    DEFAULT_FPS,
    DEFAULT_OVERLAY_THICKNESS,
    DEFAULT_OVERLAY_TYPE,
    DEFAULT_RESOLUTION,
    DEFAULT_THREADS,
    DEFAULT_VIDEO_ENCODER,
)
from render import render_batch, render_combined_folder, render_preview, render_video
from utils import find_batch_pairs


class VisualizerApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("GIM RENDER")
        self.root.geometry("780x860")
        self.root.minsize(600, 700)
        self.root.configure(bg="#101418")
        icon_path = Path(__file__).resolve().parent / "assets" / "GIM_RENDER.png"
        if icon_path.exists():
            img = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, img)
            self._icon_img = img
            import sys
            if sys.platform == "darwin":
                try:
                    from Cocoa import NSApplication, NSImage, NSObject
                    NSApplication.sharedApplication().setActivationPolicy_(0)
                    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                    ns_img = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
                    NSApplication.sharedApplication().setApplicationIconImage_(ns_img)
                    from Foundation import NSProcessInfo
                    NSProcessInfo.processInfo().setProcessName_("GIM RENDER")
                except Exception:
                    pass
            elif sys.platform == "win32":
                try:
                    import ctypes
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("gimblong.gimrender")
                except Exception:
                    pass

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#101418")
        style.configure("TLabel", background="#101418", foreground="#d1d7e0", font=("Helvetica", 11))
        style.configure("TButton", background="#2dd4bf", foreground="#061412", font=("Helvetica", 11, "bold"), borderwidth=0, padding=8)
        style.map("TButton", background=[("active", "#5eead4")], foreground=[("active", "#061412")])
        style.configure("TCheckbutton", background="#101418", foreground="#d1d7e0", font=("Helvetica", 11))
        style.configure("TCombobox",
            fieldbackground="#2a3441", background="#2a3441", foreground="#ffffff",
            arrowcolor="#ffffff", selectbackground="#2dd4bf", selectforeground="#061412",
            bordercolor="#3a4555", lightcolor="#2a3441", darkcolor="#2a3441",
        )
        style.map("TCombobox", fieldbackground=[("readonly", "#2a3441")])
        style.configure("TEntry",
            fieldbackground="#2a3441", foreground="#ffffff", insertcolor="#ffffff",
            bordercolor="#3a4555",
        )
        style.configure("TSpinbox",
            fieldbackground="#2a3441", foreground="#ffffff", arrowcolor="#ffffff",
            bordercolor="#3a4555",
        )
        style.configure("Title.TLabel", background="#101418", foreground="#edf2f7", font=("Helvetica", 20, "bold"))
        style.configure("Heading.TLabel", background="#101418", foreground="#edf2f7", font=("Helvetica", 13, "bold"))
        style.configure("Section.TLabel", background="#101418", foreground="#2dd4bf", font=("Helvetica", 11, "bold"))
        style.configure("Small.TLabel", background="#101418", foreground="#9facba", font=("Helvetica", 10))
        style.configure("Horizontal.TProgressbar", background="#2dd4bf", troughcolor="#0f1419", borderwidth=0, thickness=10)
        style.configure("TNotebook", background="#101418", borderwidth=0)
        style.configure("TLabelframe", background="#101418", foreground="#9facba", bordercolor="#2a3441")
        style.configure("TLabelframe.Label", background="#101418", foreground="#7a8b9e", font=("Helvetica", 9, "bold"))
        style.configure("TNotebook.Tab",
            background="#1a2332", foreground="#9facba", padding=(20, 8), font=("Helvetica", 11),
            borderwidth=0,
        )
        style.map("TNotebook.Tab",
            background=[("selected", "#2a3441")],
            foreground=[("selected", "#2dd4bf")],
        )

        self._build_ui()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=0)
        main.pack(fill="both", expand=True)

        # Navbar
        navbar = ttk.Frame(main)
        navbar.pack(fill="x")
        navbar_inner = ttk.Frame(navbar, padding=(16, 12, 16, 8))
        navbar_inner.pack(fill="x")
        ttk.Label(navbar_inner, text="GIM RENDER", style="Title.TLabel").pack(side="left")
        ttk.Separator(main, orient="horizontal").pack(fill="x")

        # Content area with scroll
        content_frame = ttk.Frame(main)
        content_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(content_frame, bg="#101418", highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
        self.scroll_frame = ttk.Frame(canvas)
        self.scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw", tags="content")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig("content", width=e.width - 4) if canvas.winfo_exists() else None)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.root.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        inner = ttk.Frame(self.scroll_frame, padding=16)
        inner.pack(fill="x")

        # Tabs for mode selection
        self.notebook = ttk.Notebook(inner)
        self.notebook.pack(fill="x", pady=(0, 12))

        single_tab = ttk.Frame(self.notebook, padding=12)
        multi_tab = ttk.Frame(self.notebook, padding=12)
        queue_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(single_tab, text="Single Render")
        self.notebook.add(multi_tab, text="Multi Render")
        self.notebook.add(queue_tab, text="Queue")

        self._build_single_inputs(single_tab)
        self._build_multi_inputs(multi_tab)
        self._build_queue_inputs(queue_tab)

        # Shared settings
        self._build_settings(inner)

        # Action buttons
        btn_row = ttk.Frame(inner)
        btn_row.pack(fill="x", pady=(12, 8))
        ttk.Button(btn_row, text="Render MP4", command=self._start_render).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Preview 5s", command=self._start_preview).pack(side="left")

        self.preview_frame = ttk.Frame(inner)
        self.preview_label = ttk.Label(self.preview_frame, text="", style="Small.TLabel")
        self.preview_label.pack(side="left", padx=(0, 8))
        self.preview_btn = ttk.Button(self.preview_frame, text="▶ Play Preview")
        self.preview_btn.pack(side="left")

        # Progress + Footer (fixed at bottom, outside scroll)
        bottom_bar = ttk.Frame(main)
        bottom_bar.pack(fill="x", side="bottom")
        self._build_progress(bottom_bar)

        footer = ttk.Frame(bottom_bar)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Separator(footer, orient="horizontal").pack(fill="x", pady=(0, 4))
        ttk.Label(footer, text="© GIMBLONG", foreground="#4a5568", background="#101418", font=("Helvetica", 9)).pack(pady=(0, 4))

    def _build_single_inputs(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Choose MP3 and cover image", style="Section.TLabel").pack(anchor="w", pady=(0, 6))

        self.mp3_var = tk.StringVar()
        self.image_var = tk.StringVar()
        self.bg_var = tk.StringVar()
        self.output_var = tk.StringVar(value="output_gim_video")
        self.use_mp3_name_var = tk.BooleanVar(value=False)

        for label, var, pattern, title in [
            ("MP3 file", self.mp3_var, "*.mp3", "MP3 files"),
            ("Cover image", self.image_var, "*.jpg *.jpeg *.png *.webp *.bmp", "Image files"),
            ("Background (optional)", self.bg_var, "*.jpg *.jpeg *.png *.mp4 *.mov *.mkv", "Image/Video files"),
        ]:
            self._file_row(parent, label, var, pattern, title)

        drop_zone = ttk.Frame(parent)
        drop_zone.pack(fill="x", pady=6)
        drop_label = tk.Label(drop_zone, text="Click to browse or drop files here", anchor="center",
            bg="#1a2332", fg="#5eead4", font=("Helvetica", 11), padx=12, pady=12,
            cursor="hand2", relief="ridge", bd=2)
        drop_label.pack(fill="x")
        drop_label.bind("<Button-1>", lambda e: self._browse_files())

        self._output_row(parent, "Output name", self.output_var)
        ttk.Checkbutton(parent, text="Use MP3 filename as output name", variable=self.use_mp3_name_var).pack(anchor="w", pady=(2, 0))

    def _build_multi_inputs(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Render all MP3 files in a folder", style="Section.TLabel").pack(anchor="w", pady=(0, 6))

        self.folder_var = tk.StringVar(value="assets")
        self.outdir_var = tk.StringVar(value="output")
        self.combined_var = tk.StringVar(value="output/combined.mp4")
        self.fbg_var = tk.StringVar()

        self._folder_row(parent, "Folder path", self.folder_var, browse_folder=True)
        self._output_row(parent, "Output dir", self.outdir_var)
        self._output_row(parent, "Combined output", self.combined_var)
        self._file_row(parent, "Background (optional)", self.fbg_var, "*.jpg *.jpeg *.png *.mp4 *.mov *.mkv", "Image/Video files")

        checks = ttk.Frame(parent)
        checks.pack(fill="x", pady=4)
        self.random_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(checks, text="Random image when no match", variable=self.random_var).pack(side="left", padx=(0, 16))
        self.combine_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(checks, text="Combine all into one video", variable=self.combine_var).pack(side="left")

    def _build_queue_inputs(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Add MP3 + Image logo + Background", style="Section.TLabel").pack(anchor="w", pady=(0, 6))

        self.queue_items = []

        add_frame = ttk.Frame(parent)
        add_frame.pack(fill="x", pady=(0, 4))
        ttk.Button(add_frame, text="+ Add", command=self._add_queue_item).pack(side="left")

        self.queue_listbox = tk.Listbox(parent, height=6, bg="#1a2332", fg="#edf2f7",
            selectbackground="#2dd4bf", selectforeground="#061412", font=("Helvetica", 10),
            activestyle="none", borderwidth=1, relief="solid")
        self.queue_listbox.pack(fill="x", pady=(4, 4))

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="Remove", command=self._remove_queue_item).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Clear All", command=self._clear_queue).pack(side="left")

        self.queue_combine_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Combine all into one video", variable=self.queue_combine_var).pack(anchor="w", pady=(4, 0))

    def _add_queue_item(self) -> None:
        mp3 = filedialog.askopenfilename(title="Select MP3", filetypes=[("MP3 files", "*.mp3")])
        if not mp3:
            return
        img_dir = str(Path(mp3).parent)
        image = filedialog.askopenfilename(title="Select cover image", initialdir=img_dir,
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp *.bmp")])
        if not image:
            return
        bg = filedialog.askopenfilename(title="Select background (optional, cancel to skip)", initialdir=img_dir,
            filetypes=[("Image/Video files", "*.jpg *.jpeg *.png *.mp4 *.mov *.mkv")])
        self.queue_items.append((mp3, image, bg or None))
        bg_name = Path(bg).name if bg else "-"
        self.queue_listbox.insert("end", f"{Path(mp3).name}  +  {Path(image).name}  |  bg: {bg_name}")

    def _remove_queue_item(self) -> None:
        sel = self.queue_listbox.curselection()
        if sel:
            idx = sel[0]
            self.queue_listbox.delete(idx)
            self.queue_items.pop(idx)

    def _clear_queue(self) -> None:
        self.queue_listbox.delete(0, "end")
        self.queue_items.clear()

    def _build_settings(self, parent: ttk.Frame) -> None:
        # Video
        self._section_label(parent, "Video")
        grid = ttk.Frame(parent)
        grid.pack(fill="x", pady=(2, 8))
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        self.resolution_var = self._combo(grid, 0, 0, "Resolution", ["1280x720", "1920x1080", "854x480", "426x240"], "1280x720")
        self.fps_var = self._combo(grid, 0, 1, "FPS", ["30", "24", "60"], "30")
        self.fast_var = self._check(grid, 0, 2, "Fast render", default=True)

        # Visual
        self._section_label(parent, "Visual Effects")
        grid = ttk.Frame(parent)
        grid.pack(fill="x", pady=(2, 8))
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        self.effect_var = self._combo(grid, 0, 0, "Image effect", ["flex", "none"], "flex")
        self.rotate_var = self._check(grid, 0, 1, "Rotate image")
        self.zoom_var = self._check(grid, 0, 2, "Video zoom")

        # Equalizer
        self._section_label(parent, "Equalizer")
        grid = ttk.Frame(parent)
        grid.pack(fill="x", pady=(2, 8))
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        self.arteq_var = self._check(grid, 0, 0, "Spectrum equalizer")
        self.color_var = self._combo(grid, 0, 1, "Equalizer color", ["default", "cyan", "pink", "amber", "green", "purple", "white", "blue", "red", "orange", "teal", "violet", "lime"], "default")
        self.eqbars_var = self._spin(grid, 0, 2, "Equalizer bars", 8, 128, DEFAULT_BANDS)
        grid2 = ttk.Frame(parent)
        grid2.pack(fill="x", pady=(0, 8))
        for i in range(3):
            grid2.columnconfigure(i, weight=1)
        self.bands_var = self._spin(grid2, 0, 0, "Bands", 16, 96, DEFAULT_BANDS)

        # Overlay
        self._section_label(parent, "Overlay")
        grid = ttk.Frame(parent)
        grid.pack(fill="x", pady=(2, 8))
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        self.overlay_var = self._check(grid, 0, 0, "Overlay effect")
        self.ovtype_var = self._combo(grid, 0, 1, "Overlay type", ["rain", "snow"], "rain")
        self.ovthick_var = self._combo(grid, 0, 2, "Overlay thickness", ["thin", "medium", "thick"], "medium")

        # Encoding
        self._section_label(parent, "Encoding")
        grid = ttk.Frame(parent)
        grid.pack(fill="x", pady=(2, 8))
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        self.preset_var = self._combo(grid, 0, 0, "Encoder preset", ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"], "ultrafast")
        self.venc_var = self._combo(grid, 0, 1, "Video encoder", ["auto", "libx264", "h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf", "h264_vaapi"], "auto")
        self.threads_var = self._spin(grid, 0, 2, "Threads", 1, 128, DEFAULT_THREADS)
        grid2 = ttk.Frame(parent)
        grid2.pack(fill="x", pady=(0, 8))
        for i in range(3):
            grid2.columnconfigure(i, weight=1)
        self.crf_var = self._spin(grid2, 0, 0, "CRF/Quality", 0, 51, DEFAULT_CRF)
        self.normalize_var = self._check(grid2, 0, 1, "Normalize audio")
        self.encoder_label_var = self._entry(grid2, 0, 2, "Encoder label", "Gim Studio 22")

    def _section_label(self, parent: ttk.Frame, text: str) -> None:
        sep = ttk.Frame(parent)
        sep.pack(fill="x", pady=(8, 0))
        ttk.Label(sep, text=text, style="Section.TLabel").pack(side="left")
        ttk.Separator(sep, orient="horizontal").pack(side="left", fill="x", expand=True, padx=(8, 0))

    def _build_progress(self, parent: ttk.Frame) -> None:
        self.progress_frame = ttk.Frame(parent)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(self.progress_frame, variable=self.progress_var, mode="determinate", style="Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x")

        self.status_var = tk.StringVar(value="")
        ttk.Label(self.progress_frame, textvariable=self.status_var, style="Small.TLabel").pack(anchor="w", pady=2)

    def _file_row(self, parent: ttk.Frame, label: str, var: tk.StringVar, pattern: str, title: str) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=22).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=(8, 4))
        ttk.Button(row, text="Browse", command=lambda: self._browse_file(var, title, pattern)).pack(side="left")

    def _output_row(self, parent: ttk.Frame, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=22).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=(8, 0))

    def _folder_row(self, parent: ttk.Frame, label: str, var: tk.StringVar, browse_folder: bool = False) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=22).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=(8, 4))
        ttk.Button(row, text="Browse", command=self._browse_folder).pack(side="left")

    def _combo(self, parent: ttk.Frame, row: int, col: int, label: str, values: list[str], default: str) -> tk.StringVar:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=col, sticky="ew", padx=4, pady=2)
        ttk.Label(frame, text=label, style="Small.TLabel").pack(anchor="w")
        var = tk.StringVar(value=default)
        cb = ttk.Combobox(frame, textvariable=var, values=values, state="readonly")
        cb.pack(fill="x")
        return var

    def _check(self, parent: ttk.Frame, row: int, col: int, label: str, default: bool = False) -> tk.BooleanVar:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=col, sticky="ew", padx=4, pady=2)
        ttk.Label(frame, text="", style="Small.TLabel").pack(anchor="w")
        var = tk.BooleanVar(value=default)
        ttk.Checkbutton(frame, text=label, variable=var).pack(anchor="w")
        return var

    def _spin(self, parent: ttk.Frame, row: int, col: int, label: str, min_val: int, max_val: int, default: int) -> tk.IntVar:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=col, sticky="ew", padx=4, pady=2)
        ttk.Label(frame, text=label, style="Small.TLabel").pack(anchor="w")
        var = tk.IntVar(value=default)
        sb = ttk.Spinbox(frame, from_=min_val, to=max_val, textvariable=var, width=6)
        sb.pack(fill="x")
        return var

    def _entry(self, parent: ttk.Frame, row: int, col: int, label: str, default: str) -> tk.StringVar:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=col, sticky="ew", padx=4, pady=2)
        ttk.Label(frame, text=label, style="Small.TLabel").pack(anchor="w")
        var = tk.StringVar(value=default)
        ttk.Entry(frame, textvariable=var).pack(fill="x")
        return var

    def _browse_files(self) -> None:
        mp3 = filedialog.askopenfilename(title="Select MP3", filetypes=[("MP3 files", "*.mp3")])
        if mp3:
            self.mp3_var.set(mp3)
            img_dir = str(Path(mp3).parent)
            image = filedialog.askopenfilename(title="Select cover image", initialdir=img_dir,
                filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp *.bmp")])
            if image:
                self.image_var.set(image)

    def _browse_file(self, var: tk.StringVar, title: str, pattern: str) -> None:
        path = filedialog.askopenfilename(title=title, filetypes=[(title, pattern)])
        if path:
            var.set(path)

    def _browse_folder(self) -> None:
        path = filedialog.askdirectory(title="Select folder")
        if path:
            self.folder_var.set(path)

    def _show_preview_player(self, video_path: Path) -> None:
        self.preview_label.config(text=f"Preview: {video_path.name}")
        self.preview_btn.config(command=lambda: subprocess.run(["open", str(video_path)]))
        self.preview_frame.pack(fill="x", pady=(0, 8))

    def _set_progress(self, value: float, message: str = "", current: int = 0, total: int = 0) -> None:
        if not self.progress_frame.winfo_ismapped():
            self.progress_frame.pack(fill="x", pady=(12, 0))
        pct = value * 100
        if pct < 5:
            stage = "Analyzing audio..."
        elif pct < 92:
            if total > 0:
                stage = f"Rendering frames... {current}/{total} ({pct:.0f}%)"
            else:
                stage = f"Rendering frames... ({pct:.0f}%)"
        else:
            stage = f"Encoding video... ({pct:.0f}%)"
        self.root.after(0, lambda: self.progress_var.set(pct))
        self.root.after(0, lambda: self.status_var.set(stage))
        self.root.after(0, lambda: self.preview_frame.pack_forget())

    def _settings(self) -> dict:
        res_str = self.resolution_var.get()
        w, h = map(int, res_str.split("x"))
        return dict(
            resolution=(w, h),
            fps=int(self.fps_var.get()),
            bands=self.bands_var.get(),
            rotate_image=self.rotate_var.get(),
            image_effect=self.effect_var.get(),
            artwork_equalizer=self.arteq_var.get(),
            equalizer_color=self.color_var.get(),
            equalizer_bars=self.eqbars_var.get(),
            video_zoom=self.zoom_var.get(),
            overlay_enabled=self.overlay_var.get(),
            overlay_type=self.ovtype_var.get(),
            overlay_thickness=self.ovthick_var.get(),
            fast_render=self.fast_var.get(),
            encoder_preset=self.preset_var.get(),
            threads=self.threads_var.get(),
            video_encoder=self.venc_var.get(),
            crf=self.crf_var.get(),
            encoder_label=self.encoder_label_var.get(),
            normalize=self.normalize_var.get(),
        )

    def _start_render(self) -> None:
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab == 0:
            self._start_single()
        elif current_tab == 2:
            self._start_queue()
        else:
            self._start_multi()

    def _start_single(self) -> None:
        mp3 = self.mp3_var.get().strip()
        image = self.image_var.get().strip()
        if not mp3 or not image:
            messagebox.showerror("Error", "MP3 and image are required.")
            return
        if not Path(mp3).exists():
            messagebox.showerror("Error", f"MP3 not found: {mp3}")
            return
        if not Path(image).exists():
            messagebox.showerror("Error", f"Image not found: {image}")
            return

        self._set_progress(0, "Rendering...")
        threading.Thread(target=self._run_single, daemon=True).start()

    def _run_single(self) -> None:
        try:
            s = self._settings()
            bg = Path(self.bg_var.get().strip()) if self.bg_var.get().strip() else None
            if self.use_mp3_name_var.get():
                output = Path("output") / f"{Path(self.mp3_var.get().strip()).stem}.mp4"
            else:
                output_name = self.output_var.get().strip()
                if not output_name:
                    output_name = Path(self.mp3_var.get().strip()).stem
                output = Path("output") / f"{Path(output_name).stem}.mp4"

            def progress(value, current=0, total=0):
                self._set_progress(value, current=current, total=total)

            result = render_video(
                mp3_path=Path(self.mp3_var.get().strip()),
                image_path=Path(self.image_var.get().strip()),
                background_path=bg,
                output_path=output,
                progress_callback=progress,
                **s,
            )
            self.root.after(0, lambda r=result: self._done(f"Created: {r}"))
        except Exception as e:
            self.root.after(0, lambda exc=e: self._error(str(exc)))

    def _start_preview(self) -> None:
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab != 0:
            messagebox.showerror("Error", "Preview only available in Single Render mode.")
            return
        mp3 = self.mp3_var.get().strip()
        image = self.image_var.get().strip()
        if not mp3 or not image:
            messagebox.showerror("Error", "MP3 and image are required.")
            return
        if not Path(mp3).exists() or not Path(image).exists():
            messagebox.showerror("Error", "File not found.")
            return

        if self.use_mp3_name_var.get():
            preview_path = Path("output") / f"{Path(self.mp3_var.get().strip()).stem}_preview.mp4"
        else:
            output_name = self.output_var.get().strip()
            if not output_name:
                output_name = Path(self.mp3_var.get().strip()).stem
            preview_path = Path("output") / f"{output_name}_preview.mp4"

        self._set_progress(0, "Rendering preview (5s)...")
        threading.Thread(target=self._run_preview, args=(preview_path,), daemon=True).start()

    def _run_preview(self, preview_path: Path) -> None:
        try:
            s = self._settings()
            bg = Path(self.bg_var.get().strip()) if self.bg_var.get().strip() else None

            def progress(value: float) -> None:
                self._set_progress(value, "Rendering preview (5s)...")

            result = render_preview(
                mp3_path=Path(self.mp3_var.get().strip()),
                image_path=Path(self.image_var.get().strip()),
                background_path=bg,
                output_path=preview_path,
                fast_render=True,
                progress_callback=progress,
                **{k: v for k, v in s.items() if k != "fast_render"},
            )
            subprocess.run(["open", str(result)])
            self.root.after(0, lambda r=result: self._show_preview_player(r))
            self.root.after(0, lambda: self._set_progress(1.0, "Preview ready"))
        except Exception as e:
            self.root.after(0, lambda exc=e: self._error(str(exc)))

    def _start_multi(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("Error", f"Folder not found: {folder}")
            return
        self._set_progress(0, "Rendering folder...")
        threading.Thread(target=self._run_multi, daemon=True).start()

    def _run_multi(self) -> None:
        try:
            s = self._settings()
            folder = Path(self.folder_var.get().strip())
            out_dir = Path(self.outdir_var.get().strip()) if self.outdir_var.get().strip() else None
            bg = Path(self.fbg_var.get().strip()) if self.fbg_var.get().strip() else None
            combine = self.combine_var.get()
            combined_out = Path(self.combined_var.get().strip()) if combine else None

            pairs = find_batch_pairs(folder, random_images=self.random_var.get())

            def progress(value: float) -> None:
                self._set_progress(value, "Rendering folder...")

            if combine and combined_out:
                result = render_combined_folder(
                    pairs=pairs, background_path=bg, output_path=combined_out,
                    progress_callback=progress, **s,
                )
                self.root.after(0, lambda r=result: self._done(f"Created: {r}"))
            else:
                results = render_batch(
                    pairs=pairs, background_path=bg, output_dir=out_dir,
                    progress_callback=progress, **s,
                )
                msg = "Created:\n" + "\n".join(str(p) for p in results)
                self.root.after(0, lambda m=msg: self._done(m))
        except Exception as e:
            self.root.after(0, lambda exc=e: self._error(str(exc)))

    def _start_queue(self) -> None:
        if not self.queue_items:
            messagebox.showerror("Error", "Add at least one MP3 + image pair.")
            return
        self._set_progress(0, "Rendering queue...")
        threading.Thread(target=self._run_queue, daemon=True).start()

    def _run_queue(self) -> None:
        try:
            s = self._settings()
            combine = self.queue_combine_var.get()
            pairs = [(Path(m), Path(i)) for m, i, _ in self.queue_items]
            bg_map = {Path(m): Path(b) if b else None for m, _, b in self.queue_items}

            def progress(value: float) -> None:
                self._set_progress(value, "Rendering queue...")

            if combine:
                # Combined mode with per-item backgrounds not supported, use first bg
                fallback_bg = bg_map.get(pairs[0][0]) if pairs else None
                combined_out = Path("output") / "combined_queue.mp4"
                result = render_combined_folder(
                    pairs=pairs, background_path=fallback_bg, output_path=combined_out,
                    progress_callback=progress, **s,
                )
                self.root.after(0, lambda r=result: self._done(f"Created: {r}"))
            else:
                results = []
                for mp3_path, img_path in pairs:
                    bg_path = bg_map.get(mp3_path)
                    r = render_video(
                        mp3_path=mp3_path, image_path=img_path, background_path=bg_path,
                        output_path=Path("output") / f"{mp3_path.stem}.mp4", progress_callback=progress, **s,
                    )
                    results.append(r)
                msg = "Created:\n" + "\n".join(str(p) for p in results)
                self.root.after(0, lambda m=msg: self._done(m))
        except Exception as e:
            self.root.after(0, lambda exc=e: self._error(str(exc)))

    def _done(self, message: str) -> None:
        self.progress_var.set(100)
        self.status_var.set("Done")
        messagebox.showinfo("Render complete", message)

    def _error(self, message: str) -> None:
        self.progress_var.set(0)
        self.status_var.set("Error")
        messagebox.showerror("Render failed", message)

    def run(self) -> None:
        self.root.mainloop()


def launch_gui_tkinter() -> int:
    app = VisualizerApp()
    app.run()
    return 0
