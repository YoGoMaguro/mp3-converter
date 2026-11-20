# 更新到 GitHub

這個資料夾是要放上 GitHub 的專案：`D:\mp3-converter`。

不要在 `D:\` 本身執行 `git init`。那裡還有其他檔案，整個磁碟不該變成一個倉庫。

下面的命令在 Windows 用 PowerShell。在 Linux 上進入同一個專案目錄後，把 `python` 換成 `python3` 即可，Git 指令相同。

## 第一次：登入並建立倉庫

### 1. 確認 Git 已安裝

```powershell
git --version
```

Windows 若沒有 Git，執行：

```powershell
winget install --id Git.Git -e
```

Linux（Debian / Ubuntu）：

```bash
sudo apt install git
```

### 2. 安裝 GitHub CLI 並登入你的帳號

這台電腦目前沒有 `gh`。Windows：

```powershell
winget install --id GitHub.cli -e
```

安裝後關掉終端機再打開，然後：

```powershell
gh auth login
```

依畫面選擇：

1. `GitHub.com`
2. `HTTPS`
3. `Login with a web browser`

瀏覽器會請你登入自己的 GitHub 帳號，並輸入終端機顯示的一次性代碼。

Linux 可改用發行版的 `gh` 套件，或依照 [GitHub CLI 安裝說明](https://github.com/cli/cli#installation) 安裝，同樣執行 `gh auth login`。

確認登入的是你要使用的帳號：

```powershell
gh auth status
```

### 3. 只替這個專案設定提交者

Git 提交需要名字與信箱。下面兩行只寫進這個專案，不會改到其他資料夾。請換成你的名字，以及 GitHub 帳號使用的信箱。

```powershell
cd D:\mp3-converter
git config user.name "你的名字"
git config user.email "you@example.com"
```

### 4. 做第一次提交

`D:\mp3-converter` 已經執行過 `git init -b main`，目前還沒有任何提交，也還沒有連到 GitHub。不要再執行一次 `git init`。

```powershell
cd D:\mp3-converter
git add .
git status
git commit -m "建立可在 Windows 與 Linux 使用的 MP3 轉檔工具"
```

`git status` 應列出程式、`README.md`、`requirements.txt` 與這份文件。不要加入 `.env`、密碼或轉好的 MP3。

### 5. 在你的帳號建立 GitHub 倉庫並推上去

私人倉庫（只有你看得到）：

```powershell
gh repo create mp3-converter --private --source=. --remote=origin --push
```

若要公開：

```powershell
gh repo create mp3-converter --public --source=. --remote=origin --push
```

完成後終端機會印出倉庫網址，形式像 `https://github.com/你的帳號/mp3-converter`。

## 之後每次更新

改完程式或文件後，在專案目錄執行：

```powershell
cd D:\mp3-converter
git status
git diff
git add .
git commit -m "簡短說明這次改了什麼"
git push
```

提交訊息寫原因，例如「修正 Linux 檔案總管無法選取輸出檔」。

推上去之前再看一次 `git status`。不該出現帳號密碼、權杖或 `.env`。

## 換一台電腦繼續改

```powershell
gh auth login
gh repo clone 你的帳號/mp3-converter
cd mp3-converter
python -m pip install -r requirements.txt
```

Linux 請先裝好 `python3-tk` 與 `ffmpeg`，啟動時用 `python3 convert_to_mp3_gui.py`。改完後同樣是 `git add`、`git commit`、`git push`。

## 沒有安裝 GitHub CLI 時

1. 登入 GitHub 網站，按 **New repository**。
2. 名稱填 `mp3-converter`。不要勾選 Add a README，避免和本機第一次提交衝突。
3. 建立後，在本機專案目錄執行網站顯示的指令。通常是：

   ```powershell
   git remote add origin https://github.com/你的帳號/mp3-converter.git
   git push -u origin main
   ```

之後的更新仍然是 `git add`、`git commit`、`git push`。
