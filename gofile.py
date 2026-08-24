import ast
import hashlib
import logging
import os
import re
import time
import urllib.parse
import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.gofile.io"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
DEFAULT_SALT = "12af056dacea0b"

_CACHED_SALT = None
_SALT_CACHED_AT = 0.0
_CACHED_ACCOUNT_TOKEN = None


def fetch_current_salt(timeout: float = 10.0) -> str:
    """Dynamically parses and extracts the latest salt from gofile's wt.obf.js."""
    global _CACHED_SALT, _SALT_CACHED_AT
    now = time.time()
    if _CACHED_SALT and (now - _SALT_CACHED_AT < 3600):
        return _CACHED_SALT

    env_salt = os.environ.get("GOFILE_WT_SALT")
    if env_salt:
        _CACHED_SALT = env_salt
        _SALT_CACHED_AT = now
        return _CACHED_SALT

    try:
        url = "https://gofile.io/js/wt.obf.js"
        resp = requests.get(url, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
        code = resp.text

        pos1 = code.find("var _0x145a46=[") + len("var _0x145a46=")
        pos2 = code.find("];a0_0x38b3=") + 1
        arr = ast.literal_eval(code[pos1:pos2])

        def js_parseInt(s):
            m = re.match(r"^\s*([+-]?\d+)", str(s))
            return int(m.group(1)) if m else None

        def js_b64(s):
            table = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/="
            t = ""
            u = ""
            i = 0
            mod = 0
            acc = 0
            while i < len(s):
                c = s[i]
                i += 1
                pos = table.find(c)
                if pos == -1:
                    continue
                if mod % 4:
                    acc = acc * 64 + pos
                else:
                    acc = pos
                old_mod = mod
                mod += 1
                if old_mod % 4:
                    shift = (-2 * mod) & 6
                    byte = (acc >> shift) & 0xff
                    t += chr(byte)
            for c in t:
                u += "%" + ("00" + hex(ord(c))[2:])[-2:]
            return urllib.parse.unquote(u)

        def rc4(s_decoded, key):
            S = list(range(256))
            j = 0
            for i in range(256):
                j = (j + S[i] + ord(key[i % len(key)])) % 256
                S[i], S[j] = S[j], S[i]
            i = 0
            j = 0
            out = ""
            for c in s_decoded:
                i = (i + 1) % 256
                j = (j + S[i]) % 256
                S[i], S[j] = S[j], S[i]
                out += chr(ord(c) ^ S[(S[i] + S[j]) % 256])
            return out

        curr = list(arr)
        for _ in range(len(arr)):
            try:
                def t(idx, key):
                    idx_adj = idx - 0x188
                    val = curr[idx_adj]
                    b64_dec = js_b64(val)
                    return rc4(b64_dec, key)

                v1 = js_parseInt(t(0x1c6, "a$2m"))
                v2 = js_parseInt(t(0x1e3, "1ARU"))
                v3 = js_parseInt(t(0x1f6, "FzMC"))
                v4 = js_parseInt(t(0x219, "0$(%"))
                v5 = js_parseInt(t(0x1d9, "xXED"))
                v6 = js_parseInt(t(0x229, "8K]F"))
                v7 = js_parseInt(t(0x1f9, "pWr#"))
                v8 = js_parseInt(t(0x1f7, "Mioo"))
                v9 = js_parseInt(t(0x1ee, "R5mm"))

                if all(x is not None for x in [v1, v2, v3, v4, v5, v6, v7, v8, v9]):
                    calc = v1 // 1 * (v2 // 2) + v3 // 3 - v4 // 4 + (v5 // 5) * (v6 // 6) + v7 // 7 - v8 // 8 - v9 // 9
                    if calc == 0xed5d1:
                        break
            except Exception:
                pass
            curr.append(curr.pop(0))

        p_start = code.find("function generateWT")
        p_end = code.find("window[", p_start)
        gen_slice = code[p_start:p_end]
        for m in re.finditer(r"a0_0x1b44\((0x[0-9a-fA-F]+),\s*[\x27\"]([^\x27\"]+)[\x27\"]\)", gen_slice):
            idx = int(m.group(1), 16)
            k = bytes(m.group(2), "ascii").decode("unicode_escape")
            val = t(idx, k)
            if len(val) == 14 and all(c in "0123456789abcdef" for c in val):
                _CACHED_SALT = val
                _SALT_CACHED_AT = now
                return _CACHED_SALT
    except Exception as e:
        logger.warning(f"Could not extract dynamic salt from gofile.io: {e}")

    _CACHED_SALT = DEFAULT_SALT
    _SALT_CACHED_AT = now
    return _CACHED_SALT


def generate_website_token(user_agent: str, account_token: str) -> str:
    """Generates the dynamic X-Website-Token required by the gofile.io API."""
    time_slot = int(time.time()) // 14400
    salt = fetch_current_salt()
    raw = f"{user_agent}::en-US::{account_token}::{time_slot}::{salt}"
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
        self._account_token = token or self._get_or_create_account_token()
        self._session.headers.update({"Authorization": f"Bearer {self._account_token}"})

    def _get_or_create_account_token(self) -> str:
        global _CACHED_ACCOUNT_TOKEN
        if _CACHED_ACCOUNT_TOKEN:
            return _CACHED_ACCOUNT_TOKEN
        token = self._create_account_token()
        _CACHED_ACCOUNT_TOKEN = token
        return token

    def _create_account_token(self) -> str:
        wt = generate_website_token(DEFAULT_USER_AGENT, "")
        response = self._session.post(
            f"{API_BASE}/accounts",
            headers={
                "X-Website-Token": wt,
                "X-BL": "en-US",
            },
            timeout=self._timeout,
        )
        if response.status_code == 429:
            raise RuntimeError("Gofile account creation rate limited. Please set GF_TOKEN in configuration.")
        payload = response.json()
        if payload.get("status") != "ok":
            raise RuntimeError(f"Failed to create a gofile.io account token: {payload.get('status')}")
        return payload["data"]["token"]

    def _content_headers(self) -> dict:
        return {
            "X-Website-Token": generate_website_token(DEFAULT_USER_AGENT, self._account_token),
            "X-BL": "en-US",
            "Authorization": f"Bearer {self._account_token}",
        }

    def _get_content(self, content_id: str, password_hash: str | None = None, retries: int = 3) -> dict:
        url = f"{API_BASE}/contents/{content_id}?page=1&pageSize=100&sortField=name&sortDirection=1"
        if password_hash:
            url += f"&password={password_hash}"

        for attempt in range(retries):
            response = self._session.get(url, headers=self._content_headers(), timeout=self._timeout)
            if response.status_code == 429:
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RuntimeError("Gofile API rate limit reached (HTTP 429). Please try again shortly.")
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or {}
            if data.get("passwordStatus") and data["passwordStatus"] != "passwordOk":
                raise PermissionError("This gofile.io content is password protected.")
            return payload

        raise RuntimeError("Failed to fetch gofile.io content after retries.")

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
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Authorization": f"Bearer {self._account_token}",
        }
        with self._session.get(link, headers=headers, stream=True, timeout=self._timeout) as response:
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
