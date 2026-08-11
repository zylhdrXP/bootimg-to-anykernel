import os
import sys
import shutil
import tempfile
import asyncio
import urllib.request
import json
import logging
import zipfile
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message

import config
import gofile

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

# Path to persistent usage limits file
USAGE_FILE = os.path.join(config.WORKSPACE_DIR, "usage.json")

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

def load_usage():
    """Loads usage data from file."""
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_usage(usage_data):
    """Saves usage data to file."""
    try:
        with open(USAGE_FILE, "w") as f:
            json.dump(usage_data, f)
    except Exception as e:
        logger.error(f"Failed to save usage file: {e}")

def check_and_increment_usage(user_id):
    """Checks if a user is within their daily limit and increments usage if allowed."""
    if user_id == config.OWNER_ID:
        return True, 0

    usage_data = load_usage()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    
    user_key = str(user_id)
    user_history = usage_data.get(user_key, {})
    today_count = user_history.get(today, 0)

    if today_count >= 3:
        return False, today_count

    # Increment and save
    usage_data[user_key] = {today: today_count + 1}
    save_usage(usage_data)
    
    return True, today_count + 1

async def process_boot_img(client: Client, message: Message, boot_path: str, temp_dir: str, status_msg: Message, remaining_runs: int):
    """Core repacking pipeline from an unpacked boot image path to final upload."""
    try:
        await status_msg.edit_text("🔧 Verifying magiskboot tool...")
        # Check and download magiskboot in executor to prevent blocking
        loop = asyncio.get_running_loop()
        magiskboot_ready = await loop.run_in_executor(None, fetch_magiskboot)
        if not magiskboot_ready:
            await status_msg.edit_text("❌ Internal Error: Failed to retrieve or prepare the `magiskboot` binary.")
            return

        await status_msg.edit_text("📦 Unpacking boot image...")
        
        # Execute magiskboot asynchronously
        unpack_process = await asyncio.create_subprocess_exec(
            config.MAGISKBOOT_PATH, "unpack", "boot.img",
            cwd=temp_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await unpack_process.communicate()

        if unpack_process.returncode != 0:
            err_msg = stderr.decode().strip() or "Unknown unpack error."
            logger.error(f"magiskboot unpack failed: {err_msg}")
            await status_msg.edit_text(f"❌ Failed to unpack the boot image!\n\n**Error details:**\n`{err_msg[:300]}`")
            return

        # Find extracted kernel
        kernel_path = os.path.join(temp_dir, "kernel")
        if not os.path.exists(kernel_path):
            await status_msg.edit_text("❌ Kernel was not found in the unpacked boot image. Make sure you uploaded a valid boot.img.")
            return

        # Rename kernel to Image
        image_path = os.path.join(temp_dir, "Image")
        os.rename(kernel_path, image_path)

        await status_msg.edit_text("🗂️ Cloning AnyKernel repository...")

        anykernel_dir = os.path.join(temp_dir, "AnyKernel")
        clone_process = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1",
            "-b", config.ANYKERNEL_BRANCH,
            config.ANYKERNEL_REPO,
            anykernel_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await clone_process.communicate()

        if clone_process.returncode != 0:
            err_msg = stderr.decode().strip() or "Unknown git clone error."
            logger.error(f"Git clone failed: {err_msg}")
            await status_msg.edit_text(f"❌ Failed to clone the AnyKernel repository!\n\n**Error details:**\n`{err_msg[:300]}`")
            return

        # Copy the extracted Image file into AnyKernel repo (overwriting any dummy Image)
        dest_image_path = os.path.join(anykernel_dir, "Image")
        shutil.copy2(image_path, dest_image_path)
        logger.info(f"Replaced Image in AnyKernel: {dest_image_path}")

        # Remove the .git directory (shallow clone) so it isn't included in the flashable zip
        git_dir = os.path.join(anykernel_dir, ".git")
        if os.path.exists(git_dir):
            shutil.rmtree(git_dir)
            logger.info("Removed .git directory from AnyKernel before archiving.")

        await status_msg.edit_text("🤐 Creating flashable zip archive...")

        zip_base_name = os.path.join(temp_dir, "AnyKernel_Flashable")
        
        # Run archiving in executor to keep loop non-blocking
        await loop.run_in_executor(None, lambda: shutil.make_archive(zip_base_name, "zip", anykernel_dir))
        zip_file_path = zip_base_name + ".zip"

        if not os.path.exists(zip_file_path):
            await status_msg.edit_text("❌ Failed to package the zip archive.")
            return

        await status_msg.edit_text("📤 Uploading zip archive...")

        caption = "✅ **AnyKernel Flashable Zip compiled successfully!**"
        if message.from_user.id != config.OWNER_ID:
            caption += f"\n📊 *Remaining runs today: {remaining_runs}*"

        await client.send_document(
            chat_id=message.chat.id,
            document=zip_file_path,
            reply_to_message_id=message.id,
            caption=caption
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

@app.on_message(filters.command(["start", "help"]))
async def send_welcome(client: Client, message: Message):
    """Sends welcome message and usage instructions."""
    welcome_text = (
        "🤖 **Boot.img to AnyKernel Flashable Zip Bot**\n\n"
        "Send me a `boot.img` file as a document **OR** send a direct download link "
        "starting with `http` or `https`.\n\n"
        "📌 **How to use:**\n"
        "1. Upload your kernel's `boot.img` as a document OR paste its direct download link.\n"
        "2. **Gofile.io links** (`https://gofile.io/d/...`) are also supported — add the password after the URL if the content is protected, e.g. `https://gofile.io/d/abc123 mypassword`.\n"
        "3. The bot will automatically download, unpack it, clone AnyKernel, swap the kernel, and pack it.\n"
        "4. You will receive the compiled flashable zip file in seconds.\n\n"
        "⚠️ **Note**: Users are limited to **3 compiles per day** (bot owner is exempt)."
    )
    await message.reply_text(welcome_text)

@app.on_message(filters.document)
async def handle_boot_img_file(client: Client, message: Message):
    """Handles the incoming boot.img file upload."""
    user_id = message.from_user.id
    document = message.document
    file_name = document.file_name
    
    if not file_name.lower().endswith(".img"):
        await message.reply_text("❌ Invalid file! Please upload a `.img` file (e.g., `boot.img`).")
        return

    # Check limit before processing
    allowed, count = check_and_increment_usage(user_id)
    if not allowed:
        await message.reply_text("🛑 **Limit Exceeded!** You have reached your daily limit of **3 compiles per day**.")
        return

    status_msg = await message.reply_text("⏳ Downloading your boot image...")
    temp_dir = tempfile.mkdtemp(dir=config.WORKSPACE_DIR)
    boot_path = os.path.join(temp_dir, "boot.img")

    try:
        await client.download_media(document, file_name=boot_path)
        await process_boot_img(client, message, boot_path, temp_dir, status_msg, 3 - count)
    except Exception as e:
        logger.error(f"Download failed: {e}")
        await status_msg.edit_text(f"❌ Failed to download file from Telegram: {e}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def handle_boot_img_link(client: Client, message: Message):
    """Handles incoming direct download links to a boot.img (incl. gofile.io links)."""
    user_id = message.from_user.id
    tokens = message.text.strip().split()
    url = tokens[0]
    password = tokens[1] if len(tokens) > 1 else None

    if not (url.startswith("http://") or url.startswith("https://")):
        await message.reply_text("❌ Please send a valid direct download link starting with `http://` or `https://`.")
        return

    is_gofile = "gofile.io" in url

    # Check limit before downloading
    allowed, count = check_and_increment_usage(user_id)
    if not allowed:
        await message.reply_text("🛑 **Limit Exceeded!** You have reached your daily limit of **3 compiles per day**.")
        return

    source_label = "gofile.io" if is_gofile else "link"
    status_msg = await message.reply_text(f"⏳ Downloading boot image from {source_label}...")
    temp_dir = tempfile.mkdtemp(dir=config.WORKSPACE_DIR)
    boot_path = os.path.join(temp_dir, "boot.img")

    try:
        # Download from URL in a separate thread/executor to prevent blocking the event loop
        def download_url():
            if is_gofile:
                gofile.download_bootimg(
                    url,
                    boot_path,
                    password=password,
                    token=config.GF_TOKEN,
                    timeout=config.GF_TIMEOUT,
                )
            else:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=120) as response, open(boot_path, "wb") as out_file:
                    shutil.copyfileobj(response, out_file)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, download_url)

        if not os.path.exists(boot_path) or os.path.getsize(boot_path) == 0:
            await status_msg.edit_text("❌ Downloaded file is empty or could not be retrieved.")
            shutil.rmtree(temp_dir)
            return

        await process_boot_img(client, message, boot_path, temp_dir, status_msg, 3 - count)
        
    except Exception as e:
        logger.error(f"Failed to download from link: {e}")
        await status_msg.edit_text(f"❌ Failed to download from the link. Make sure it is a direct download link or a valid gofile.io link (append the password after the URL if protected).\n\nError: `{e}`")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

if __name__ == "__main__":
    logger.info("Initializing bot resources...")
    fetch_magiskboot()
    
    logger.info("Starting bot client...")
    app.run()
