"""
Chrome cookie database extraction (Windows only).

Reads TikTok cookies directly from Chrome's encrypted SQLite database.
No Chrome restart or debug port required — reads the DB file directly.
Cookie values are encrypted with AES-256-GCM; the key is protected by DPAPI.
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import shutil
import sqlite3
import tempfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_decrypt(encrypted_data: bytes) -> bytes:
    """Decrypt data using Windows DPAPI (CryptUnprotectData)."""
    blob_in = _DATA_BLOB(
        len(encrypted_data),
        ctypes.cast(encrypted_data, ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = _DATA_BLOB()

    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None, None, None, None,
        0,
        ctypes.byref(blob_out),
    ):
        raise OSError("CryptUnprotectData failed")

    result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree(blob_out.pbData)
    return result


def _get_chrome_user_data_dir() -> str | None:
    base = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    if os.path.isdir(base):
        return base
    return None


def _get_chrome_profile_dir() -> str | None:
    base = _get_chrome_user_data_dir()
    if not base:
        return None
    for profile in ("Default", "Profile 1", "Profile 2"):
        p = os.path.join(base, profile)
        if os.path.isdir(p):
            return p
    return None


def _get_chrome_encryption_key() -> bytes | None:
    base = _get_chrome_user_data_dir()
    if not base:
        return None
    local_state_path = os.path.join(base, "Local State")
    if not os.path.isfile(local_state_path):
        return None
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            local_state = json.load(f)
    except Exception:
        return None
    try:
        encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
    except KeyError:
        return None
    encrypted_key = base64.b64decode(encrypted_key_b64)
    if not encrypted_key.startswith(b"DPAPI"):
        return None
    try:
        key = _dpapi_decrypt(encrypted_key[5:])
        return key
    except Exception:
        return None


def _decrypt_cookie_value(encrypted_value: bytes, key: bytes) -> str | None:
    if not encrypted_value:
        return ""
    # v10 format: b"v10" + 12-byte nonce + ciphertext + 16-byte tag
    if encrypted_value.startswith(b"v10"):
        try:
            nonce = encrypted_value[3:15]
            ciphertext_with_tag = encrypted_value[15:]
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
            return plaintext.decode("utf-8", errors="replace")
        except Exception:
            pass
    # v11 format
    if encrypted_value.startswith(b"v11"):
        try:
            nonce = encrypted_value[3:15]
            ciphertext_with_tag = encrypted_value[15:]
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
            return plaintext.decode("utf-8", errors="replace")
        except Exception:
            pass
    # Plain text fallback
    try:
        return encrypted_value.decode("utf-8")
    except UnicodeDecodeError:
        pass
    return None


def extract_tiktok_cookies() -> tuple[bool, str, str]:
    """Extract TikTok cookies from Chrome database.
    Returns (success: bool, message: str, netscape_text: str)"""
    profile_dir = _get_chrome_profile_dir()
    if not profile_dir:
        return False, "Chrome profile directory not found", ""

    cookies_db_path = os.path.join(profile_dir, "Network", "Cookies")
    if not os.path.isfile(cookies_db_path):
        return False, f"Cookies database not found: {cookies_db_path}", ""

    key = _get_chrome_encryption_key()
    if not key:
        return False, "Failed to decrypt Chrome encryption key", ""

    # Copy DB (Chrome locks it)
    tmp_dir = tempfile.mkdtemp(prefix="zaizaicat_cookies_")
    tmp_db = os.path.join(tmp_dir, "Cookies")
    try:
        shutil.copy2(cookies_db_path, tmp_db)
    except Exception as e:
        return False, f"Failed to copy Chrome cookies DB: {e}", ""

    tik_cookies = []
    try:
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT host_key, name, value, encrypted_value, path, "
            "expires_utc, is_secure, is_httponly "
            "FROM cookies "
            "WHERE host_key LIKE '%tiktok.com'"
        )
        for row in cur:
            domain = row["host_key"] or ""
            name = row["name"] or ""
            encrypted = row["encrypted_value"]
            if isinstance(encrypted, memoryview):
                encrypted = bytes(encrypted)
            value = _decrypt_cookie_value(encrypted, key)
            if value is None:
                continue
            tik_cookies.append({
                "domain": domain,
                "name": name,
                "value": value,
                "path": row["path"] or "/",
                "secure": bool(row["is_secure"]),
                "httponly": bool(row["is_httponly"]),
                "expires": int(row["expires_utc"] or 0),
            })
        conn.close()
    except Exception as e:
        return False, f"Failed to read Chrome cookies DB: {e}", ""
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    if not tik_cookies:
        return False, (
            "No TikTok cookies found in Chrome. "
            "Please visit tiktok.com and log in first."
        ), ""

    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated by zaizaicat (Chrome DB)",
        "# https://curl.haxx.se/rfc/cookie_spec.html",
        "",
    ]
    for c in tik_cookies:
        domain = c["domain"]
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = int(c["expires"]) if c.get("expires", 0) > 0 else 2147483647
        is_domain = domain.startswith(".")
        flag = "TRUE" if is_domain else "FALSE"
        lines.append("\t".join([
            domain, flag, path, secure, str(expires), c["name"], c["value"],
        ]))
    netscape_text = "\n".join(lines) + "\n"

    return True, f"Extracted {len(tik_cookies)} TikTok cookies from Chrome", netscape_text


def ensure_cookies_from_chrome(force_refresh: bool = False, cookies_file: str = "") -> tuple[bool, str, str]:
    """Get TikTok cookies, preferring Chrome DB extraction.
    If cookies_file is given, save to it and check cache."""
    if cookies_file and not force_refresh:
        import time as _time
        try:
            st = os.stat(cookies_file)
            if st.st_size > 100 and (_time.time() - st.st_mtime) < 86400:
                text = open(cookies_file, "r", encoding="utf-8").read()
                return True, f"Cookie cache valid ({(_time.time()-st.st_mtime)/3600:.1f}h ago)", text
        except Exception:
            pass

    success, msg, text = extract_tiktok_cookies()
    if success and text and cookies_file:
        try:
            os.makedirs(os.path.dirname(cookies_file), exist_ok=True)
            with open(cookies_file, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
    return success, msg, text
