# MP3 轉檔

把音訊或影片裡的聲音轉成 MP3 的桌面小工具。轉檔交給 FFmpeg 在背景執行，不會把整段音訊載進記憶體，介面也不會卡住。

可在 **Windows** 與 **Linux** 使用。

## 需要先準備

- Python 3.11 或更新版本
- FFmpeg，且編碼器包含 `libmp3lame`
- 這個程式的 Python 套件：`customtkinter`、`tkinterdnd2`

Linux 的 Python 通常不附 Tk，還要另外安裝 `python3-tk`。要正常顯示中文，建議安裝 Noto CJK 字型。

## Windows

1. 安裝 Python 時勾選 **Add python.exe to PATH**。[python.org](https://www.python.org/downloads/) 的安裝檔已包含 Tk。
2. 安裝 FFmpeg：

   ```powershell
   winget install --id Gyan.FFmpeg -e
   ```

   安裝後重新開啟終端機，執行 `ffmpeg -version`。看得到版本就代表 PATH 已設定好。
3. 安裝介面套件並啟動：

   ```powershell
   cd D:\mp3-converter
   python -m pip install -r requirements.txt
   python convert_to_mp3_gui.py
   ```

## Linux

Debian、Ubuntu：

```bash
sudo apt update
sudo apt install python3 python3-tk python3-pip ffmpeg fonts-noto-cjk
cd /path/to/mp3-converter
python3 -m pip install -r requirements.txt
python3 convert_to_mp3_gui.py
```

Fedora：

```bash
sudo dnf install python3 python3-tkinter python3-pip ffmpeg google-noto-sans-cjk-tc-fonts
python3 -m pip install -r requirements.txt
python3 convert_to_mp3_gui.py
```

Arch Linux：

```bash
sudo pacman -S python python-pip tk ffmpeg noto-fonts-cjk
python -m pip install -r requirements.txt
python convert_to_mp3_gui.py
```

確認 FFmpeg 有 MP3 編碼器：

```bash
ffmpeg -hide_banner -encoders | grep libmp3lame
```

## 使用方式

1. 把音訊或影片拖進視窗，或按「選擇檔案」。
2. 確認輸出的 MP3 路徑。程式會先建議和來源同一個資料夾、同一個檔名。
3. 選擇位元率、取樣率與聲道。預設是 192 kbps，取樣率與聲道維持原檔。
4. 「保留標題、演出者與封面」預設是勾選的。
5. 按「開始轉換」。完成後可按「在檔案總管中顯示」。

輸出會先寫到同一個資料夾的暫存檔，成功後才取代目標檔案。

## Release 套件

在已安裝 Python、FFmpeg 與 `requirements.txt` 的電腦上執行：

```powershell
python scripts/build_release.py
```

完成後會出現兩個檔案：

- `release/mp3-converter-1.0.0-windows-x64.zip`：Windows 免安裝套件，含程式與 FFmpeg。解壓後執行 `mp3-converter.exe`。
- `release/mp3-converter-1.0.0-source.zip`：原始碼，給 Linux 或想自行用 Python 執行的人。

Linux 執行檔要在 Linux 上用同一支腳本打包。Windows 無法編出可用的 Linux 圖形介面程式。

## 更新到 GitHub

第一次上傳與之後每次更新的步驟寫在 [docs/github.md](docs/github.md)。
