"""MP3 轉檔。

把音訊或影片裡的聲音轉成 MP3。轉檔直接交給 FFmpeg，
不會把整段音訊載進記憶體，介面也不會在轉檔時凍結。

可在 Windows 與 Linux 執行。需要 customtkinter、tkinterdnd2，
以及含 libmp3lame 的 FFmpeg。Linux 另外需要系統的 Tk（python3-tk）。
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError as exc:
    raise SystemExit(
        "請先安裝介面套件：python -m pip install customtkinter tkinterdnd2"
    ) from exc

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HIDDEN_WINDOW = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}

FONT_CANDIDATES = (
    "Microsoft JhengHei UI",
    "Microsoft JhengHei",
    "Noto Sans CJK TC",
    "Noto Sans CJK JP",
    "Noto Sans CJK SC",
    "Source Han Sans TC",
    "Source Han Sans",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "PingFang TC",
    "Noto Sans",
    "DejaVu Sans",
)

BITRATES = {
    "128 kbps": "128k",
    "192 kbps": "192k",
    "256 kbps": "256k",
    "320 kbps": "320k",
}
SAMPLE_RATES = {
    "原樣": None,
    "32 kHz": 32000,
    "44.1 kHz": 44100,
    "48 kHz": 48000,
}
CHANNELS = {
    "原樣": None,
    "立體聲": 2,
    "單聲道": 1,
}

AUDIO_FILETYPES = [
    (
        "音訊與影片",
        "*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.oga *.opus *.wma "
        "*.aiff *.aif *.aifc *.mp4 *.m4v *.mov *.mkv *.webm *.avi",
    ),
    ("所有檔案", "*.*"),
]
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi"}

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
TIMESTAMP_RE = re.compile(r"(\d+):(\d+):(\d+(?:\.\d+)?)")
APP_VERSION = "1.0.0"


class ConversionError(Exception):
    """FFmpeg 無法完成轉檔。"""


class ConversionCancelled(Exception):
    """使用者取消轉檔。"""


@dataclass
class MediaInfo:
    duration: float | None
    summary: str
    has_audio: bool
    has_cover: bool


def application_directory() -> str:
    """原始碼執行時是程式所在資料夾；打包後是執行檔所在資料夾。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _executable_file(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def bundled_ffmpeg_path() -> str | None:
    """優先使用跟程式放在一起的 ffmpeg，讓 release 套件不必另外安裝。"""
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = [os.path.join(application_directory(), name)]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, name))
    for path in candidates:
        if _executable_file(path):
            return path
    return None


def ffmpeg_candidates() -> list[str]:
    """PATH 找不到時，依作業系統檢查常見安裝位置。"""
    here = application_directory()
    home = os.path.expanduser("~")
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        return [
            os.path.join(program_files, "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(program_files_x86, "ffmpeg", "bin", "ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
            os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
            os.path.join(here, "ffmpeg.exe"),
        ]
    return [
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/snap/bin/ffmpeg",
        os.path.join(home, ".local", "bin", "ffmpeg"),
        os.path.join(here, "ffmpeg"),
    ]


def find_ffmpeg() -> str | None:
    """先找隨套件附上的 ffmpeg，再找 PATH 與常見安裝位置。"""
    bundled = bundled_ffmpeg_path()
    if bundled:
        return bundled

    found = shutil.which("ffmpeg")
    if found:
        return found

    for path in ffmpeg_candidates():
        if _executable_file(path):
            return path

    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    return bundled if bundled and os.path.isfile(bundled) else None


def choose_ui_font() -> str | None:
    """挑一個目前系統有安裝、且能顯示中文的字型。"""
    try:
        available = {name.casefold(): name for name in tkfont.families()}
    except tkinter.TclError:
        return None
    for name in FONT_CANDIDATES:
        found = available.get(name.casefold())
        if found:
            return found
    return None


def ffmpeg_missing_text() -> str:
    if os.name == "nt":
        return "找不到 FFmpeg。請安裝並加入 PATH，或放到 C:\\Program Files\\ffmpeg\\bin\\"
    return "找不到 FFmpeg。請用套件管理員安裝 ffmpeg，並確認終端機能執行 ffmpeg -version。"


def reveal_in_file_manager(path: str) -> None:
    """在系統檔案總管中顯示檔案。Linux 會依已安裝的檔案管理員選擇。"""
    path = os.path.normpath(os.path.abspath(path))
    directory = os.path.dirname(path) or "."
    if sys.platform == "win32":
        subprocess.run(["explorer", "/select,", path], check=False)
        return
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", path], check=False)
        return
    if shutil.which("nautilus"):
        subprocess.run(["nautilus", "--select", path], check=False)
    elif shutil.which("dolphin"):
        subprocess.run(["dolphin", "--select", path], check=False)
    elif shutil.which("nemo"):
        subprocess.run(["nemo", path], check=False)
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", directory], check=False)


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_timestamp(value: str) -> float | None:
    match = TIMESTAMP_RE.fullmatch(value.strip())
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_drop_paths(data: str) -> list[str]:
    """拆開 tkinterdnd2 傳來的檔案清單。含空白的路徑會包在大括號裡。"""
    paths: list[str] = []
    token: list[str] = []
    in_brace = False
    for char in data.strip():
        if char == "{" and not in_brace:
            in_brace = True
            token = []
        elif char == "}" and in_brace:
            in_brace = False
            if token:
                paths.append("".join(token))
            token = []
        elif char == " " and not in_brace:
            if token:
                paths.append("".join(token))
                token = []
        else:
            token.append(char)
    if token:
        paths.append("".join(token))
    return paths


def parse_media_text(stderr: str) -> MediaInfo:
    duration = None
    match = DURATION_RE.search(stderr)
    if match:
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if duration <= 0:
            duration = None

    audio_line = ""
    for line in stderr.splitlines():
        if "Audio:" in line:
            audio_line = line
            break

    has_audio = bool(audio_line)
    has_cover = "attached pic" in stderr.lower()
    return MediaInfo(
        duration=duration,
        summary=_summarize_audio(duration, audio_line, has_audio),
        has_audio=has_audio,
        has_cover=has_cover,
    )


def _summarize_audio(duration: float | None, audio_line: str, has_audio: bool) -> str:
    if not has_audio:
        return "找不到音訊軌"
    parts: list[str] = []
    if duration is not None:
        parts.append(format_duration(duration))
    codec = audio_line.split("Audio:", 1)[-1].split(",", 1)[0].strip()
    codec = re.sub(r"\s*\([^)]*\)", "", codec).strip()
    codec = {
        "aac": "AAC",
        "mp3": "MP3",
        "flac": "FLAC",
        "opus": "Opus",
        "vorbis": "Vorbis",
        "pcm_s16le": "PCM",
        "pcm_s24le": "PCM",
        "wmav2": "WMA",
    }.get(codec.lower(), codec)
    if codec:
        parts.append(codec)
    sample_rate = re.search(r"(\d+)\s*Hz", audio_line)
    if sample_rate:
        khz = int(sample_rate.group(1)) / 1000
        parts.append(f"{khz:g} kHz")
    channels = re.search(r"Hz,\s*([^,]+)", audio_line)
    if channels:
        label = channels.group(1).strip()
        parts.append({"stereo": "立體聲", "mono": "單聲道"}.get(label, label))
    bitrate = re.search(r"(\d+(?:\.\d+)?)\s*kb/s", audio_line)
    if bitrate:
        parts.append(f"{bitrate.group(1)} kbps")
    return " · ".join(parts) if parts else "已讀取音訊"


def probe_media(ffmpeg: str, path: str) -> MediaInfo:
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path],
            capture_output=True,
            timeout=60,
            **HIDDEN_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError("讀取檔案資訊逾時。") from exc
    except OSError as exc:
        raise ConversionError(f"無法執行 FFmpeg：{exc}") from exc
    text = completed.stderr.decode("utf-8", errors="replace")
    return parse_media_text(text)


def build_command(
    ffmpeg: str,
    source: str,
    destination: str,
    *,
    bitrate: str,
    sample_rate: int | None,
    channels: int | None,
    keep_metadata: bool,
    has_cover: bool,
) -> list[str]:
    """組出轉檔命令。封面只在來源真的有附圖時才一併複製。"""
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        source,
        "-map",
        "0:a:0",
    ]
    if keep_metadata and has_cover:
        command += [
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-disposition:v:0",
            "attached_pic",
        ]
    if keep_metadata:
        command += ["-map_metadata", "0", "-id3v2_version", "3"]
    else:
        command += ["-map_metadata", "-1"]
    if not (keep_metadata and has_cover):
        command.append("-vn")
    command += ["-c:a", "libmp3lame", "-b:a", bitrate]
    if sample_rate:
        command += ["-ar", str(sample_rate)]
    if channels:
        command += ["-ac", str(channels)]
    command += ["-progress", "pipe:1", "-nostats", destination]
    return command


def source_note(path: str) -> str:
    extension = os.path.splitext(path)[1].lower()
    if extension == ".mp3":
        return "來源已是 MP3，再編碼一次會損失一些細節。"
    if extension in VIDEO_EXTENSIONS:
        return "將取出影片中的音訊。"
    return ""


def friendly_ffmpeg_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return "FFmpeg 沒有留下錯誤訊息。"
    interesting = [
        line
        for line in lines
        if any(word in line.lower() for word in ("error", "invalid", "no such", "failed"))
    ]
    chosen = interesting[-4:] if interesting else lines[-6:]
    return "\n".join(chosen)


def convert_to_mp3(
    ffmpeg: str,
    source: str,
    destination: str,
    *,
    bitrate: str,
    sample_rate: int | None,
    channels: int | None,
    keep_metadata: bool,
    has_cover: bool,
    duration: float | None,
    cancel: threading.Event,
    on_progress,
    proc_slot: dict,
) -> None:
    """轉成 MP3。先寫到同資料夾的暫存檔，成功後才取代目標。"""
    directory = os.path.dirname(os.path.abspath(destination)) or "."
    fd, temp_path = tempfile.mkstemp(prefix=".mp3conv-", suffix=".mp3", dir=directory)
    os.close(fd)
    replaced = False
    process = None
    try:
        if cancel.is_set():
            raise ConversionCancelled()
        command = build_command(
            ffmpeg,
            source,
            temp_path,
            bitrate=bitrate,
            sample_rate=sample_rate,
            channels=channels,
            keep_metadata=keep_metadata,
            has_cover=has_cover,
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **HIDDEN_WINDOW,
        )
        proc_slot["proc"] = process
        stderr_parts: list[bytes] = []

        def read_stderr() -> None:
            assert process.stderr is not None
            stderr_parts.append(process.stderr.read())

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        speed = ""
        last_emit = 0.0
        assert process.stdout is not None
        for raw_line in process.stdout:
            if cancel.is_set():
                process.terminate()
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line.startswith("out_time="):
                current = parse_timestamp(line.split("=", 1)[1])
                fraction = None
                if current is not None and duration and duration > 0:
                    fraction = min(current / duration, 0.99)
                tick = time.monotonic()
                if tick - last_emit >= 0.1:
                    last_emit = tick
                    on_progress(fraction, speed)
            elif line.startswith("speed="):
                speed = line.split("=", 1)[1].strip()
            elif line == "progress=end":
                on_progress(1.0, speed)

        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            if cancel.is_set():
                raise ConversionCancelled()
            raise ConversionError("FFmpeg 沒有在時間內結束。")
        stderr_thread.join(timeout=5)
        if cancel.is_set():
            raise ConversionCancelled()
        if process.returncode != 0:
            detail = b"".join(stderr_parts).decode("utf-8", errors="replace")
            raise ConversionError(friendly_ffmpeg_error(detail))
        os.replace(temp_path, destination)
        replaced = True
        on_progress(1.0, speed)
    except ConversionCancelled:
        if process is not None and process.poll() is None:
            process.terminate()
        raise
    except ConversionError:
        raise
    except OSError as exc:
        raise ConversionError(f"無法寫入輸出檔：{exc}") from exc
    finally:
        proc_slot["proc"] = None
        if process is not None and process.poll() is None:
            process.kill()
        if not replaced:
            try:
                os.remove(temp_path)
            except OSError:
                pass


class AudioConverterApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title(f"MP3 轉檔 {APP_VERSION}")
        self.geometry("720x860")
        self.minsize(680, 780)
        self.configure(fg_color=("#fafafa", "#09090b"))

        ui_font = choose_ui_font()
        font_family = {"family": ui_font} if ui_font else {}
        self.font_title = ctk.CTkFont(size=28, weight="bold", **font_family)
        self.font_body = ctk.CTkFont(size=14, **font_family)
        self.font_small = ctk.CTkFont(size=12, **font_family)
        self.font_button = ctk.CTkFont(size=15, weight="bold", **font_family)

        self.input_path = tkinter.StringVar()
        self.output_path = tkinter.StringVar()
        self.bitrate = tkinter.StringVar(value="192 kbps")
        self.sample_rate = tkinter.StringVar(value="原樣")
        self.channels = tkinter.StringVar(value="原樣")
        self.keep_metadata = tkinter.BooleanVar(value=True)

        self.ffmpeg = find_ffmpeg()
        self._auto_output = True
        self._busy = False
        self._probe_generation = 0
        self._media: MediaInfo | None = None
        self._media_path = ""
        self._cancel = threading.Event()
        self._proc_slot: dict = {"proc": None}
        self._events: queue.Queue = queue.Queue()
        self._last_output = ""
        self._drop_enabled = False

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Return>", lambda _event: self._convert())
        self.bind("<Escape>", lambda _event: self._cancel_convert())
        self.after(50, self._enable_drop)
        self.after(50, self._pump_events)
        self._refresh_ffmpeg_state()

    def _build(self) -> None:
        muted = ("#52525b", "#a1a1aa")
        card = {"fg_color": ("#ffffff", "#18181b"), "corner_radius": 16, "border_width": 1, "border_color": ("#e4e4e7", "#27272a")}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 8))
        ctk.CTkLabel(header, text="MP3 轉檔", font=self.font_title, anchor="w").pack(fill="x")
        ctk.CTkLabel(
            header,
            text="把音訊或影片的聲音轉成 MP3。轉檔在背景進行，整段音訊不會載入記憶體。",
            font=self.font_small,
            text_color=muted,
            anchor="w",
            wraplength=680,
            justify="left",
        ).pack(fill="x", pady=(4, 0))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(4, 0))

        source = ctk.CTkFrame(body, **card)
        source.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(source, text="來源", font=self.font_body, anchor="w").pack(fill="x", padx=18, pady=(16, 8))

        self.drop_zone = ctk.CTkFrame(
            source,
            fg_color=("#f8fafc", "#0f172a"),
            corner_radius=12,
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
        )
        self.drop_zone.pack(fill="x", padx=18, pady=(0, 8))
        self.drop_title = ctk.CTkLabel(
            self.drop_zone,
            text="將檔案拖到這裡",
            font=self.font_body,
            wraplength=620,
        )
        self.drop_title.pack(pady=(20, 2), padx=16)
        self.drop_hint = ctk.CTkLabel(
            self.drop_zone,
            text="或按下方按鈕選擇。支援 wav、flac、m4a、mp3，以及 mp4、mkv 等影片。",
            font=self.font_small,
            text_color=muted,
            wraplength=620,
        )
        self.drop_hint.pack(pady=(0, 18), padx=16)

        source_actions = ctk.CTkFrame(source, fg_color="transparent")
        source_actions.pack(fill="x", padx=18, pady=(4, 16))
        self.browse_input_btn = ctk.CTkButton(
            source_actions,
            text="選擇檔案",
            width=120,
            font=self.font_body,
            command=self._browse_input,
        )
        self.browse_input_btn.pack(side="right")
        self.meta_label = ctk.CTkLabel(
            source_actions,
            text="尚未選擇檔案",
            font=self.font_small,
            text_color=muted,
            anchor="w",
        )
        self.meta_label.pack(side="left", fill="x", expand=True, padx=(0, 12))

        output = ctk.CTkFrame(body, **card)
        output.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(output, text="輸出", font=self.font_body, anchor="w").pack(fill="x", padx=18, pady=(16, 8))
        output_row = ctk.CTkFrame(output, fg_color="transparent")
        output_row.pack(fill="x", padx=18)
        self.output_entry = ctk.CTkEntry(
            output_row,
            textvariable=self.output_path,
            height=38,
            font=self.font_body,
            placeholder_text="輸出的 MP3 路徑",
        )
        self.output_entry.pack(side="left", fill="x", expand=True)
        self.output_entry.bind("<Key>", self._mark_output_manual)
        self.browse_output_btn = ctk.CTkButton(
            output_row,
            text="瀏覽",
            width=88,
            height=38,
            font=self.font_body,
            command=self._browse_output,
        )
        self.browse_output_btn.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            output,
            text="選擇來源後會自動建議同資料夾、同檔名的 MP3。",
            font=self.font_small,
            text_color=muted,
            anchor="w",
        ).pack(fill="x", padx=18, pady=(8, 16))

        quality = ctk.CTkFrame(body, **card)
        quality.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(quality, text="音質", font=self.font_body, anchor="w").pack(fill="x", padx=18, pady=(16, 4))
        self.bitrate_buttons = self._option_row(quality, "位元率", list(BITRATES), self.bitrate)
        self.rate_buttons = self._option_row(quality, "取樣率", list(SAMPLE_RATES), self.sample_rate)
        self.channel_buttons = self._option_row(quality, "聲道", list(CHANNELS), self.channels)
        self.meta_check = ctk.CTkCheckBox(
            quality,
            text="保留標題、演出者與封面",
            variable=self.keep_metadata,
            font=self.font_body,
        )
        self.meta_check.pack(anchor="w", padx=18, pady=(10, 18))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=28, pady=(0, 16))

        self.progress = ctk.CTkProgressBar(footer, height=8, corner_radius=8)
        self.progress.pack(fill="x")
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            footer,
            text="準備就緒",
            font=self.font_small,
            anchor="w",
            text_color=muted,
        )
        self.status_label.pack(fill="x", pady=(8, 10))

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.pack(fill="x")
        self.reveal_btn = ctk.CTkButton(
            actions,
            text="在檔案總管中顯示",
            font=self.font_body,
            fg_color="transparent",
            border_width=1,
            text_color=("gray10", "gray90"),
            command=self._reveal,
            state="disabled",
        )
        self.reveal_btn.pack(side="left")
        self.convert_btn = ctk.CTkButton(
            actions,
            text="開始轉換",
            width=140,
            height=42,
            font=self.font_button,
            command=self._convert,
        )
        self.convert_btn.pack(side="right")
        self.cancel_btn = ctk.CTkButton(
            actions,
            text="取消",
            width=88,
            height=42,
            font=self.font_body,
            fg_color="transparent",
            border_width=1,
            text_color=("gray10", "gray90"),
            command=self._cancel_convert,
            state="disabled",
        )
        self.cancel_btn.pack(side="right", padx=(0, 8))

        self.ffmpeg_label = ctk.CTkLabel(
            footer,
            text="",
            font=self.font_small,
            text_color=muted,
            anchor="w",
        )
        self.ffmpeg_label.pack(fill="x", pady=(10, 0))

        self._lockable = [
            self.browse_input_btn,
            self.browse_output_btn,
            self.output_entry,
            self.bitrate_buttons,
            self.rate_buttons,
            self.channel_buttons,
            self.meta_check,
            self.convert_btn,
        ]

    def _option_row(self, parent, label: str, values: list[str], variable: tkinter.StringVar):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=6)
        ctk.CTkLabel(row, text=label, width=64, anchor="w", font=self.font_body).pack(side="left")
        buttons = ctk.CTkSegmentedButton(
            row,
            values=values,
            variable=variable,
            font=self.font_small,
            height=32,
            dynamic_resizing=True,
        )
        buttons.pack(side="left", fill="x", expand=True, padx=(8, 0))
        return buttons

    def _enable_drop(self) -> None:
        if TkinterDnD is None or DND_FILES is None:
            self.drop_hint.configure(text="這台環境沒有拖放支援。請按「選擇檔案」。")
            return
        try:
            TkinterDnD.require(self)
        except Exception:
            self.drop_hint.configure(text="拖放元件載入失敗。請按「選擇檔案」。")
            return
        for widget in (self.drop_zone, self.drop_title, self.drop_hint):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        self._drop_enabled = True

    def _refresh_ffmpeg_state(self) -> None:
        if self.ffmpeg:
            self.ffmpeg_label.configure(text=f"FFmpeg  {self.ffmpeg}")
            return
        self.ffmpeg_label.configure(text=ffmpeg_missing_text())
        self._set_status("找不到 FFmpeg，無法轉換。", "error")
        self.convert_btn.configure(state="disabled")

    def _mark_output_manual(self, _event=None) -> None:
        self._auto_output = False

    def _browse_input(self) -> None:
        if self._busy:
            return
        initial = os.path.dirname(self.input_path.get()) or os.path.expanduser("~")
        path = filedialog.askopenfilename(filetypes=AUDIO_FILETYPES, initialdir=initial)
        if path:
            self._set_input(path)

    def _browse_output(self) -> None:
        if self._busy:
            return
        current = self.output_path.get().strip()
        initial_dir = os.path.dirname(current) or os.path.dirname(self.input_path.get()) or os.path.expanduser("~")
        initial_file = os.path.basename(current) or "output.mp3"
        path = filedialog.asksaveasfilename(
            defaultextension=".mp3",
            filetypes=[("MP3", "*.mp3")],
            initialdir=initial_dir,
            initialfile=initial_file,
        )
        if path:
            self._auto_output = False
            self.output_path.set(path)

    def _on_drop(self, event):
        if self._busy:
            return "copy"
        paths = [path for path in parse_drop_paths(event.data) if os.path.isfile(path)]
        if not paths:
            self._set_status("拖放的項目不是檔案。", "error")
            return "copy"
        self._set_input(paths[0])
        if len(paths) > 1:
            self._set_status("已使用第一個檔案。這個工具一次轉換一個檔案。", "normal")
        return "copy"

    def _set_input(self, path: str) -> None:
        path = os.path.abspath(path)
        self.input_path.set(path)
        self.drop_title.configure(text=os.path.basename(path))
        self.drop_hint.configure(text=os.path.dirname(path))
        self.drop_zone.configure(border_color=("#3b82f6", "#3b82f6"))
        note = source_note(path)
        self.meta_label.configure(text=note or "正在讀取音訊資訊…")
        self._media = None
        self._media_path = ""
        if self._auto_output or not self.output_path.get().strip():
            stem = os.path.splitext(path)[0]
            self.output_path.set(stem + ".mp3")
            self._auto_output = True
        self._set_status("已選擇來源", "normal")
        self._probe_generation += 1
        generation = self._probe_generation
        if not self.ffmpeg:
            self.meta_label.configure(text=note or "尚未讀取音訊資訊")
            return
        threading.Thread(
            target=self._probe_worker,
            args=(path, generation),
            daemon=True,
        ).start()

    def _probe_worker(self, path: str, generation: int) -> None:
        try:
            info = probe_media(self.ffmpeg, path)
        except ConversionError as exc:
            self._events.put(("probe", (path, generation, None, str(exc))))
            return
        self._events.put(("probe", (path, generation, info, "")))

    def _apply_probe(self, path: str, generation: int, info: MediaInfo | None, error: str) -> None:
        if generation != self._probe_generation:
            return
        note = source_note(path)
        if error:
            self.meta_label.configure(text=error)
            return
        assert info is not None
        self._media = info
        self._media_path = path
        text = info.summary
        if note:
            text = f"{text}　{note}" if text else note
        self.meta_label.configure(text=text)

    def _set_status(self, text: str, kind: str) -> None:
        colors = {
            "normal": ("#52525b", "#a1a1aa"),
            "work": ("#1d4ed8", "#93c5fd"),
            "ok": ("#15803d", "#86efac"),
            "error": ("#b91c1c", "#fca5a5"),
        }
        self.status_label.configure(text=text, text_color=colors.get(kind, colors["normal"]))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for widget in self._lockable:
            widget.configure(state=state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        if busy:
            self.reveal_btn.configure(state="disabled")
        elif self._last_output and os.path.isfile(self._last_output):
            self.reveal_btn.configure(state="normal")
        if not busy and not self.ffmpeg:
            self.convert_btn.configure(state="disabled")

    def _convert(self) -> None:
        if self._busy:
            return
        if not self.ffmpeg:
            messagebox.showerror("找不到 FFmpeg", "請先安裝 FFmpeg（需包含 libmp3lame），再重新開啟這個工具。")
            return

        source = self.input_path.get().strip()
        destination = self.output_path.get().strip()
        if not source:
            messagebox.showerror("尚未選擇來源", "請拖放或選擇要轉換的檔案。")
            return
        source = os.path.abspath(source)
        if not os.path.isfile(source):
            messagebox.showerror("找不到來源", "來源檔案不存在，請重新選擇。")
            return
        if not destination:
            messagebox.showerror("尚未指定輸出", "請指定 MP3 的儲存位置。")
            return
        if not destination.lower().endswith(".mp3"):
            destination += ".mp3"
        destination = os.path.abspath(destination)
        self.output_path.set(destination)
        if os.path.normcase(source) == os.path.normcase(destination):
            messagebox.showerror("輸出路徑相同", "請把 MP3 存成另一個檔名。")
            return
        output_dir = os.path.dirname(destination)
        if output_dir and not os.path.isdir(output_dir):
            messagebox.showerror("資料夾不存在", "輸出資料夾不存在，請另選一個位置。")
            return
        if os.path.exists(destination):
            overwrite = messagebox.askyesno("覆蓋檔案", f"已經有這個檔案，要覆蓋嗎？\n\n{destination}")
            if not overwrite:
                return
        if self._media_path == source and self._media and not self._media.has_audio:
            messagebox.showerror("沒有音訊", "這個檔案裡沒有可轉換的音訊軌。")
            return

        settings = (
            BITRATES[self.bitrate.get()],
            SAMPLE_RATES[self.sample_rate.get()],
            CHANNELS[self.channels.get()],
            bool(self.keep_metadata.get()),
        )
        self._cancel.clear()
        self._set_busy(True)
        self.progress.set(0)
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self._set_status("正在轉換…", "work")
        threading.Thread(
            target=self._convert_worker,
            args=(source, destination, settings),
            daemon=True,
        ).start()

    def _convert_worker(self, source: str, destination: str, settings: tuple) -> None:
        bitrate, sample_rate, channels, keep_metadata = settings
        try:
            info = self._media if self._media_path == source and self._media else None
            if info is None:
                info = probe_media(self.ffmpeg, source)
            if not info.has_audio:
                raise ConversionError("這個檔案裡沒有可轉換的音訊軌。")
            if info.duration:
                self._events.put(("determinate", ()))
            convert_to_mp3(
                self.ffmpeg,
                source,
                destination,
                bitrate=bitrate,
                sample_rate=sample_rate,
                channels=channels,
                keep_metadata=keep_metadata,
                has_cover=info.has_cover,
                duration=info.duration,
                cancel=self._cancel,
                on_progress=lambda fraction, speed: self._events.put(("progress", (fraction, speed))),
                proc_slot=self._proc_slot,
            )
        except ConversionCancelled:
            self._events.put(("cancelled", ()))
        except ConversionError as exc:
            self._events.put(("failed", (str(exc),)))
        except Exception as exc:
            self._events.put(("failed", (str(exc),)))
        else:
            self._events.put(("success", (destination,)))

    def _pump_events(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "probe":
                    self._apply_probe(*payload)
                elif kind == "determinate":
                    self._use_determinate_progress()
                elif kind == "progress":
                    self._show_progress(*payload)
                elif kind == "success":
                    self._on_success(*payload)
                elif kind == "failed":
                    self._on_failed(*payload)
                elif kind == "cancelled":
                    self._on_cancelled()
        except queue.Empty:
            pass
        try:
            self.after(50, self._pump_events)
        except tkinter.TclError:
            return

    def _use_determinate_progress(self) -> None:
        if not self._busy:
            return
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)

    def _show_progress(self, fraction: float | None, speed: str) -> None:
        if not self._busy:
            return
        if fraction is None:
            detail = "正在轉換…"
        else:
            self.progress.set(fraction)
            detail = f"正在轉換… {int(fraction * 100)}%"
        if speed and speed not in {"0x", "N/A"}:
            detail = f"{detail}    {speed}"
        self._set_status(detail, "work")

    def _on_success(self, destination: str) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1)
        self._last_output = destination
        self._set_busy(False)
        self._set_status(f"已完成　{destination}", "ok")

    def _on_failed(self, message: str) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self._set_busy(False)
        self._set_status("轉換失敗", "error")
        messagebox.showerror("轉換失敗", message)

    def _on_cancelled(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self._set_busy(False)
        self._set_status("已取消", "normal")

    def _cancel_convert(self) -> None:
        if not self._busy:
            return
        self._cancel.set()
        process = self._proc_slot.get("proc")
        if process is not None and process.poll() is None:
            process.terminate()
        self._set_status("正在取消…", "work")

    def _reveal(self) -> None:
        if not self._last_output or not os.path.isfile(self._last_output):
            return
        reveal_in_file_manager(self._last_output)

    def _on_close(self) -> None:
        self._cancel.set()
        process = self._proc_slot.get("proc")
        if process is not None and process.poll() is None:
            process.terminate()
        self.destroy()


def main() -> None:
    app = AudioConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
