# 🤖 Boot.img to AnyKernel Telegram Bot

A fully automated Telegram bot designed to unpack an Android `boot.img` file, extract its kernel, and repack it into an AnyKernel flashable zip file ready for recovery flashing (e.g. TWRP/OrangeFox).

This bot uses Pyrogram (MTProto client) rather than standard HTTP Bot API, allowing you to bypass the hard **20 MB download limit** and support files up to **2 GB** (essential since modern `boot.img` files are usually 32MB to 128MB).

---

## ⚙️ How it Works

1. **User Interaction**: The user starts the bot using `/start` or `/help` and uploads a `.img` file (e.g. `boot.img`), sends a direct download link, or a [gofile.io](https://gofile.io) link (`https://gofile.io/d/<content_id>`).
2. **Usage Limit Checks**: The bot checks if the user is within their daily usage limit of **3 runs per day**. If the user matches the configured `OWNER_ID`, the limit check is bypassed entirely.
3. **Magiskboot Extraction**: The bot automatically resolves and extracts `magiskboot` (x86_64 host binary) from the latest Magisk APK released on GitHub.
4. **Unpacking**: The bot runs `./magiskboot unpack boot.img` inside an isolated temporary directory unique to the session (ensuring multiple users can run jobs simultaneously).
5. **Renaming & AnyKernel Integration**: The extracted `kernel` is renamed to `Image` and integrated into a freshly cloned clone of the AnyKernel repository.
6. **Repacking**: The AnyKernel folder contents are zipped (with files placed at the root level).
7. **Delivery & Cleanup**: The flashable zip is uploaded to the user, and the temporary workspace is immediately deleted to ensure security and disk space efficiency.

---

## 📂 Repository Structure

- `bot.py` — Core bot application handling Telegram updates, downloading files, executing subprocesses, and compiling the zip.
- `gofile.py` — gofile.io downloader (content tree resolution, token generation, streaming download).
- `config.py` — Central configuration logic sourcing setup parameters from environment variables.
- `.env.example` — Template configuration file for local or VPS deployment.
- `requirements.txt` — Python dependencies (Pyrogram and Tgcrypto).
- `.github/workflows/main.yml` — GitHub Actions workflow for serverless deployment.

---

## 🚀 Setup & credentials

Because this bot runs on MTProto, you need a **Bot Token**, your personal **Telegram API ID/Hash**, and your **Telegram User ID** if you want to bypass usage limits.

### 1. Get a Bot Token
1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the instructions.
3. Copy the provided **HTTP API Bot Token**.

### 2. Get API ID and API Hash
1. Log in to your Telegram account at [https://my.telegram.org](https://my.telegram.org).
2. Go to **API development tools**.
3. Create a new application (you can fill in random values for name and URL).
4. Copy your **App api_id** and **App api_hash**.

### 3. Get Your Telegram User ID (for Owner Bypass)
1. Open Telegram and search for [@userinfobot](https://t.me/userinfobot) or [@raw_data_bot](https://t.me/raw_data_bot).
2. Send any message to the bot.
3. Copy the numeric **Id** returned (e.g. `123456789`). Set this as `OWNER_ID`.

---

## 🚀 Setup & Deployment

### A. Deploy on GitHub Actions (Serverless / 24/7 Free)

Since GitHub Actions has a 6-hour execution timeout limit per workflow run, this repository is configured with a **scheduled restart mechanism** and **concurrency controls** to keep the bot running indefinitely:
* **Cron Schedule**: Automatically launches the bot every 5 hours.
* **Concurrency Protection**: The workflow is configured to cancel the previous instance when a new one starts. This prevents duplicate bot instances from running simultaneously and causing Telegram message-polling conflicts.

#### Step-by-Step Setup:
1. Fork or push this repository to your GitHub account.
2. Go to **Settings** > **Secrets and Variables** > **Actions** in your GitHub repository.
3. Click **New repository secret** and add:
   - `TELEGRAM_BOT_TOKEN`: Paste your HTTP API Bot Token.
   - `TELEGRAM_API_ID`: Paste your `api_id`.
   - `TELEGRAM_API_HASH`: Paste your `api_hash`.
   - `OWNER_ID`: Paste your numeric Telegram User ID.
4. (Optional) Add the following repository secrets to customize:
   - `ANYKERNEL_REPO`: Custom AnyKernel Git repository (defaults to `https://github.com/osm0sis/AnyKernel3.git`).
   - `ANYKERNEL_BRANCH`: Custom repository branch (defaults to `master`).
5. Go to the **Actions** tab of your repository, select **Run Telegram Repacker Bot**, and click **Run workflow** to start the bot immediately. The scheduled cron will automatically run thereafter.

---

### B. Deploy on a Private VPS (Linux / Ubuntu)

For a persistent, self-hosted deployment:

#### System Dependencies
Ensure you have the required utilities installed:
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip git zip unzip cpio build-essential python3-dev
```

#### Bot Setup
1. Clone your repository to your server:
   ```bash
   git clone <your-repo-url> bootimg-to-anykernel
   cd bootimg-to-anykernel
   ```
2. Install Python dependencies:
   ```bash
   pip3 install -r requirements.txt
   ```
3. Copy the environment template and edit with your parameters:
   ```bash
   cp .env.example .env
   nano .env
   ```
4. Load environment variables and start the bot:
   ```bash
   export $(xargs < .env)
   python3 bot.py
   ```

#### 🛡️ Running as a System Daemon (Systemd)
To ensure the bot restarts automatically if the server reboots or crashes, create a systemd service:

1. Create a service file:
   ```bash
   sudo nano /etc/systemd/system/telegram-repacker.service
   ```
2. Paste the following configuration (replace `/path/to/...` and `your_username` with your actual paths/username):
   ```ini
   [Unit]
   Description=Telegram Boot.img to AnyKernel Repacker Bot
   After=network.target

   [Service]
   Type=simple
   User=your_username
   WorkingDirectory=/path/to/bootimg-to-anykernel
   EnvironmentFile=/path/to/bootimg-to-anykernel/.env
   ExecStart=/usr/bin/python3 bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
3. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable telegram-repacker.service
   sudo systemctl start telegram-repacker.service
   ```
4. Check status and logs:
   ```bash
   sudo systemctl status telegram-repacker.service
   journalctl -u telegram-repacker.service -f
   ```

---

## 📱 How to Use the Bot

1. Open a chat with your Telegram bot and send `/start`.
2. Attach and upload your `boot.img` file as a **Document**, OR send a direct download link, OR send a **gofile.io** link:
   - `https://gofile.io/d/abc123` (public content)
   - `https://gofile.io/d/abc123 mypassword` (password-protected content — append the password after the URL)
3. The bot will send live progress messages:
   - ⏳ *Downloading your boot image...*
   - 🔧 *Verifying magiskboot tool...*
   - 📦 *Unpacking boot image...*
   - 🗂️ *Cloning AnyKernel repository...*
   - 🤐 *Creating flashable zip archive...*
   - 📤 *Uploading zip archive...*
4. In moments, you will receive the compiled flashable zip file back.
5. Non-owner users are restricted to 3 successful compiles daily. The caption will report the remaining count.

### 📁 Gofile.io Support

When a gofile.io link is provided, the bot:
1. Creates a temporary anonymous gofile.io account (or uses your `GF_TOKEN` if configured).
2. Recursively walks the content tree to find the `boot.img` (falls back to the first `.img` file).
3. Streams it down to a temporary directory and feeds it into the normal repacking pipeline.

Optional environment variables (see `.env.example`):
- `GF_TOKEN` — your gofile.io account token (a temporary anonymous account is created when empty).
- `GF_TIMEOUT` — connection/read timeout in seconds (defaults to `15.0`).
