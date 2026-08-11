import os

# Telegram API Credentials (Required for Pyrogram to bypass the 20MB file limit)
API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Bot Owner's Telegram User ID (Exempt from daily limits)
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# AnyKernel3 Repository Configuration
ANYKERNEL_REPO = os.environ.get("ANYKERNEL_REPO", "https://github.com/osm0sis/AnyKernel3.git")
ANYKERNEL_BRANCH = os.environ.get("ANYKERNEL_BRANCH", "master")

# Gofile.io downloader configuration
# Optional account token (a temporary anonymous account is created per download when empty)
GF_TOKEN = os.environ.get("GF_TOKEN")
# Connection/read timeout in seconds for gofile.io requests
GF_TIMEOUT = float(os.environ.get("GF_TIMEOUT", "15.0"))

# Workspace configurations
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
MAGISKBOOT_PATH = os.path.join(WORKSPACE_DIR, "magiskboot")
