"""Test Chrome cookie DB extraction approaches."""
import sqlite3
import os
import tempfile

cookies_db = os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies')
print('DB exists:', os.path.exists(cookies_db))
print('DB size:', os.path.getsize(cookies_db) if os.path.exists(cookies_db) else 0)

# Approach 1: immutable mode (read-only, no journal files)
try:
    conn = sqlite3.connect(f'file:{cookies_db}?immutable=1', uri=True)
    cur = conn.execute("SELECT count(*) FROM cookies WHERE host_key LIKE '%tiktok.com'")
    count = cur.fetchone()[0]
    print(f'immutable mode: {count} TikTok cookies in DB')
    cur = conn.execute("SELECT host_key, name FROM cookies WHERE host_key LIKE '%tiktok.com' LIMIT 15")
    for row in cur:
        print(f'  {row[0]:35s} {row[1]}')
    conn.close()
    print('immutable mode SUCCESS')
except Exception as e:
    print(f'immutable mode FAILED: {e}')

# Approach 2: use Windows API to copy with FILE_SHARE_READ
if False:  # skip for now
    import ctypes
    from ctypes import wintypes
    
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 1
    FILE_SHARE_WRITE = 2
    FILE_SHARE_DELETE = 4
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    
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
    if handle == -1:
        print(f'CreateFileW failed: {kernel32.GetLastError()}')
    else:
        print(f'Got handle: {handle}')
        # Read and write to temp file
        tmp = tempfile.mktemp(suffix='.db')
        buf = ctypes.create_string_buffer(4096)
        bytes_read = wintypes.DWORD()
        with open(tmp, 'wb') as out:
            while kernel32.ReadFile(handle, buf, 4096, ctypes.byref(bytes_read), None) and bytes_read.value > 0:
                out.write(buf.raw[:bytes_read.value])
        kernel32.CloseHandle(handle)
        print(f'Copied to {tmp}, size={os.path.getsize(tmp)}')
        
        conn = sqlite3.connect(tmp)
        cur = conn.execute("SELECT host_key, name FROM cookies WHERE host_key LIKE '%tiktok.com' LIMIT 10")
        for row in cur:
            print(f'  {row[0]:35s} {row[1]}')
        conn.close()
