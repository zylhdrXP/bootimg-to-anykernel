import os
import sys
import shutil
import tempfile
import subprocess
import zipfile
import urllib.request
import json
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Validate credentials
if not config.BOT_TOKEN or not config.API_ID or not config.API_HASH:
    logger.error("TELEGRAM_BOT_TOKEN, TELEGRAM_API_ID, or TELEGRAM_API_HASH is missing!")
    sys.exit(1)

# Initialize Pyrogram Bot Client
app = Client(
    "repacker_bot",
    api_id=int(config.API_ID),
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    workdir=config.WORKSPACE_DIR
)

def fetch_magiskboot():
    """Fetches magiskboot binary from the latest Magisk release APK on GitHub."""
    if os.path.exists(config.MAGISKBOOT_PATH):
        logger.info(f"magiskboot binary already exists at: {config.MAGISKBOOT_PATH}")
        return True

    logger.info("magiskboot not found. Attempting to download the latest Magisk APK...")
    apk_url = None
    
    try:
        api_url = "https://api.github.com/repos/topjohnwu/Magisk/releases/latest"
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            release_info = json.loads(response.read().decode())
            for asset in release_info.get("assets", []):
                if asset.get("name", "").endswith(".apk"):
                    apk_url = asset.get("browser_download_url")
                    break
    except Exception as e:
        logger.warning(f"Failed to fetch latest release from GitHub API: {e}. Falling back to default URL.")

    if not apk_url:
        apk_url = "https://github.com/topjohnwu/Magisk/releases/download/v27.0/Magisk-v27.0.apk"
        logger.info(f"Using fallback Magisk APK URL: {apk_url}")

    temp_apk_path = os.path.join(config.WORKSPACE_DIR, "magisk_temp.apk")
    try:
        logger.info(f"Downloading APK from: {apk_url}")
        urllib.request.urlretrieve(apk_url, temp_apk_path)

        logger.info("Extracting libmagiskboot.so from APK...")
        with zipfile.ZipFile(temp_apk_path, "r") as zip_ref:
            target_so = "lib/x86_64/libmagiskboot.so"
            if target_so in zip_ref.namelist():
                with zip_ref.open(target_so) as source, open(config.MAGISKBOOT_PATH, "wb") as dest:
                    shutil.copyfileobj(source, dest)
                os.chmod(config.MAGISKBOOT_PATH, 0o755)
                logger.info(f"magiskboot binary extracted and set to executable at: {config.MAGISKBOOT_PATH}")
                return True
            else:
                logger.error(f"{target_so} not found in Magisk APK.")
                return False
    except Exception as e:
        logger.error(f"Error during magiskboot retrieval: {e}")
        return False
    finally:
        if os.path.exists(temp_apk_path):
            try:
                os.remove(temp_apk_path)
            except Exception:
                pass

@app.on_message(filters.command(["start", "help"]))
async def send_welcome(client: Client, message: Message):
    """Sends welcome message and usage instructions."""
    welcome_text = (
        "🤖 **Boot.img to AnyKernel Flashable Zip Bot**\n\n"
        "Send me a `boot.img` file as a document, and I will extract the kernel "
        "and package it into a flashable AnyKernel zip file.\n\n"
        "📌 **How to use:**\n"
        "1. Upload your kernel's `boot.img` as a document.\n"
        "2. The bot will automatically unpack it, pull AnyKernel, swap the kernel, and pack it.\n"
        "3. You will receive the compiled flashable zip file in seconds.\n\n"
        "⚠️ **Note**: This bot uses MTProto, meaning it supports files up to **2 GB**!"
    )
    await message.reply_text(welcome_text)

@app.on_message(filters.document)
async def handle_boot_img(client: Client, message: Message):
    """Handles the incoming boot.img file, unpacks, replaces kernel, and repacks."""
    document = message.document
    file_name = document.file_name
    
    if not file_name.lower().endswith(".img"):
        await message.reply_text("❌ Invalid file! Please upload a `.img` file (e.g., `boot.img`).")
        return

    status_msg = await message.reply_text("⏳ Downloading your boot image...")

    temp_dir = tempfile.mkdtemp(dir=config.WORKSPACE_DIR)
    boot_path = os.path.join(temp_dir, "boot.img")

    try:
        # Pyrogram handles large downloads natively
        await client.download_media(document, file_name=boot_path)

        await status_msg.edit_text("🔧 Verifying magiskboot tool...")
        if not fetch_magiskboot():
            await status_msg.edit_text("❌ Internal Error: Failed to retrieve or prepare the `magiskboot` binary.")
            return

        await status_msg.edit_text("📦 Unpacking boot image...")
        
        unpack_process = subprocess.run(
            [config.MAGISKBOOT_PATH, "unpack", "boot.img"],
            cwd=temp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if unpack_process.returncode != 0:
            err_msg = unpack_process.stderr or "Unknown unpack error."
            logger.error(f"magiskboot unpack failed: {err_msg}")
            await status_msg.edit_text(f"❌ Failed to unpack the boot image!\n\n**Error details:**\n`{err_msg[:300]}`")
            return

        kernel_path = os.path.join(temp_dir, "kernel")
        if not os.path.exists(kernel_path):
            await status_msg.edit_text("❌ Kernel was not found in the unpacked boot image. Make sure you uploaded a valid boot.img.")
            return

        image_path = os.path.join(temp_dir, "Image")
        os.rename(kernel_path, image_path)

        await status_msg.edit_text("🗂️ Cloning AnyKernel repository...")

        anykernel_dir = os.path.join(temp_dir, "AnyKernel")
        clone_cmd = [
            "git", "clone", "--depth", "1",
            "-b", config.ANYKERNEL_BRANCH,
            config.ANYKERNEL_REPO,
            anykernel_dir
        ]
        clone_process = subprocess.run(clone_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if clone_process.returncode != 0:
            err_msg = clone_process.stderr or "Unknown git clone error."
            logger.error(f"Git clone failed: {err_msg}")
            await status_msg.edit_text(f"❌ Failed to clone the AnyKernel repository!\n\n**Error details:**\n`{err_msg[:300]}`")
            return

        dest_image_path = os.path.join(anykernel_dir, "Image")
        shutil.copy2(image_path, dest_image_path)
        logger.info(f"Replaced Image in AnyKernel: {dest_image_path}")

        await status_msg.edit_text("🤐 Creating flashable zip archive...")

        zip_base_name = os.path.join(temp_dir, "AnyKernel_Flashable")
        shutil.make_archive(zip_base_name, "zip", anykernel_dir)
        zip_file_path = zip_base_name + ".zip"

        if not os.path.exists(zip_file_path):
            await status_msg.edit_text("❌ Failed to package the zip archive.")
            return

        await status_msg.edit_text("📤 Uploading zip archive...")

        await client.send_document(
            chat_id=message.chat.id,
            document=zip_file_path,
            reply_to_message_id=message.id,
            caption="✅ **AnyKernel Flashable Zip compiled successfully!**"
        )

        await status_msg.delete()

    except Exception as e:
        logger.exception("Exception occurred during boot image processing:")
        await status_msg.edit_text(f"❌ An error occurred: {str(e)}")
    finally:
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"Temporary directory cleaned: {temp_dir}")
            except Exception as e:
                logger.error(f"Failed to remove temp dir {temp_dir}: {e}")

if __name__ == "__main__":
    logger.info("Initializing bot resources...")
    fetch_magiskboot()
    
    logger.info("Starting bot client...")
    app.run()
