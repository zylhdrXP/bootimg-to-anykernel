import hashlib
import time

import requests

import config

API_BASE = "https://api.gofile.io"
DEFAULT_USER_AGENT = "Mozilla/5.0"


def generate_website_token(user_agent: str, account_token: str) -> str:
    """Generates the dynamic X-Website-Token required by the gofile.io API."""
    time_slot = int(time.time()) // 14400
    raw = f"{user_agent}::en-US::{account_token}::{time_slot}::9844d94d963d30"
    return hashlib.sha256(raw.encode()).hexdigest()


class GofileDownloader:
    def __init__(self, token: str | None = None, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Accept-Encoding": "gzip",
            "User-Agent": DEFAULT_USER_AGENT,
            "Connection": "keep-alive",
            "Accept": "*/*",
            "Origin": "https://gofile.io",
            "Referer": "https://gofile.io/",
        })
        self._account_token = token or self._create_account_token()

    def _create_account_token(self) -> str:
        response = self._session.post(
            f"{API_BASE}/accounts",
            headers={
                "X-Website-Token": generate_website_token(DEFAULT_USER_AGENT, ""),
                "X-BL": "en-US",
            },
            timeout=self._timeout,
        ).json()
        if response.get("status") != "ok":
            raise RuntimeError("Failed to create a gofile.io account token.")
        return response["data"]["token"]

    def _content_headers(self) -> dict:
        return {
            "X-Website-Token": generate_website_token(DEFAULT_USER_AGENT, self._account_token),
            "X-BL": "en-US",
        }

    def _get_content(self, content_id: str, password_hash: str | None = None) -> dict:
        url = f"{API_BASE}/contents/{content_id}?cache=true&sortField=createTime&sortDirection=1"
        if password_hash:
            url += f"&password={password_hash}"
        response = self._session.get(url, headers=self._content_headers(), timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        if data.get("passwordStatus") and data["passwordStatus"] != "passwordOk":
            raise PermissionError("This gofile.io content is password protected.")
        return payload

    def list_files(self, content_id: str, password: str | None = None) -> list[tuple[str, str]]:
        password_hash = hashlib.sha256(password.encode()).hexdigest() if password else None
        files: list[tuple[str, str]] = []
        visited = set()

        def walk(cid: str) -> None:
            if cid in visited:
                return
            visited.add(cid)
            data = self._get_content(cid, password_hash).get("data") or {}
            if not data:
                return
            if data.get("type") == "file":
                files.append((data.get("name", cid), data.get("link")))
                return
            for child in (data.get("children") or {}).values():
                if child.get("type") == "folder":
                    walk(child.get("id"))
                else:
                    files.append((child.get("name", ""), child.get("link")))

        walk(content_id)
        return files

    def download_file(
        self,
        link: str,
        dest_path: str,
        chunk_size: int = 2097152,
        progress_callback=None,
    ) -> str:
        with self._session.get(link, stream=True, timeout=self._timeout) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            with open(dest_path, "wb") as out_file:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total)
        return dest_path


def extract_content_id(url: str) -> str:
    parts = url.rstrip("/").split("/")
    if len(parts) < 2 or parts[-2] != "d":
        raise ValueError(f"Not a valid gofile.io content url: {url}")
    return parts[-1]


def pick_boot_img(files: list[tuple[str, str]]) -> tuple[str, str] | None:
    for name, link in files:
        if name and name.lower() == "boot.img":
            return name, link
    for name, link in files:
        if name and name.lower().endswith(".img"):
            return name, link
    return None


def download_bootimg(
    url: str,
    dest_path: str,
    password: str | None = None,
    token: str | None = None,
    timeout: float = 15.0,
    progress_callback=None,
) -> str:
    content_id = extract_content_id(url)
    downloader = GofileDownloader(token=token, timeout=timeout)
    files = downloader.list_files(content_id, password=password)
    if not files:
        raise RuntimeError("No files found in the gofile.io content.")
    target = pick_boot_img(files)
    if not target:
        raise RuntimeError("No boot.img file found in the gofile.io content.")
    downloader.download_file(target[1], dest_path, progress_callback=progress_callback)
    return dest_path
