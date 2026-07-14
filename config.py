import os

# Telegram API Credentials (Required for Pyrogram to bypass the 20MB file limit)
API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# AnyKernel3 Repository Configuration
ANYKERNEL_REPO = os.environ.get("ANYKERNEL_REPO", "https://github.com/osm0sis/AnyKernel3.git")
ANYKERNEL_BRANCH = os.environ.get("ANYKERNEL_BRANCH", "master")

# Workspace configurations
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
MAGISKBOOT_PATH = os.path.join(WORKSPACE_DIR, "magiskboot")
