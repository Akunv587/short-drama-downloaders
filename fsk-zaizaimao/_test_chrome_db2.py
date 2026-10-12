"""Test Chrome cookie DB copy via Windows API (bypass file lock)."""
import ctypes
from ctypes import wintypes
import os
import tempfile
import sqlite3

cookies_db = os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies')
print(f'Source DB: {cookies_db}')
print(f'Source size: {os.path.getsize(cookies_db)}')

# Windows API constants
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

kernel32 = ctypes.windll.kernel32

handle = kernel32.CreateFileW(
    cookies_db,
    GENERIC_READ,
    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
    None,
    OPEN_EXISTING,
    FILE_ATTRIBUTE_NORMAL,
    None,
)

if handle == INVALID_HANDLE_VALUE:
    err = kernel32.GetLastError()
    print(f'CreateFileW failed with error: {err}')
    print('Trying alternative: VSS snapshot approach not available')
else:
    print(f'Opened file handle: {handle}')
    tmp = tempfile.mktemp(suffix='.db')
    
    buf = ctypes.create_string_buffer(65536)
    bytes_read = wintypes.DWORD()
    total = 0
    
    with open(tmp, 'wb') as out:
        while kernel32.ReadFile(handle, buf, 65536, ctypes.byref(bytes_read), None) and bytes_read.value > 0:
            out.write(buf.raw[:bytes_read.value])
            total += bytes_read.value
    
    kernel32.CloseHandle(handle)
    print(f'Copied {total} bytes to {tmp}')
    
    # Read cookies from copy
    try:
        conn = sqlite3.connect(f'file:{tmp}?immutable=1', uri=True)
        cur = conn.execute("SELECT count(*) FROM cookies WHERE host_key LIKE '%tiktok.com'")
        count = cur.fetchone()[0]
        print(f'TikTok cookies: {count}')
        
        cur = conn.execute("SELECT host_key, name FROM cookies WHERE host_key LIKE '%tiktok.com' LIMIT 20")
        for row in cur:
            print(f'  {row[0]:40s} {row[1]}')
        conn.close()
    except Exception as e:
        print(f'DB read failed: {e}')
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
