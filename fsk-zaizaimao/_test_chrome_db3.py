"""Test Chrome cookie DB copy - fixed comparison."""
import ctypes
from ctypes import wintypes
import os
import tempfile
import sqlite3

cookies_db = os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies')
print(f'Source: {cookies_db} ({os.path.getsize(cookies_db)} bytes)')

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
FILE_SHARE_DELETE = 4
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_FILE_SIZE = 0xFFFFFFFF

kernel32 = ctypes.windll.kernel32

# Use CreateFileW with proper types
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]

handle = kernel32.CreateFileW(
    cookies_db,
    GENERIC_READ,
    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
    None,
    OPEN_EXISTING,
    FILE_ATTRIBUTE_NORMAL,
    None,
)

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
print(f'handle={handle}, INVALID={INVALID_HANDLE_VALUE}, equal={handle==INVALID_HANDLE_VALUE}')

if handle == INVALID_HANDLE_VALUE or handle is None:
    err = kernel32.GetLastError()
    print(f'CreateFileW FAILED with error {err}')
    # Try without FILE_SHARE_DELETE
    handle2 = kernel32.CreateFileW(
        cookies_db, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
    )
    if handle2 == INVALID_HANDLE_VALUE or handle2 is None:
        err2 = kernel32.GetLastError()
        print(f'CreateFileW (no delete share) FAILED with error {err2}')
        
        # Try just FILE_SHARE_READ
        handle3 = kernel32.CreateFileW(
            cookies_db, GENERIC_READ,
            FILE_SHARE_READ,
            None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
        )
        if handle3 == INVALID_HANDLE_VALUE or handle3 is None:
            err3 = kernel32.GetLastError()
            print(f'CreateFileW (read share only) FAILED with error {err3}')
            print('Chrome has exclusive lock on cookies DB.')
        else:
            print(f'Success with FILE_SHARE_READ only! handle={handle3}')
            _copy_and_read(handle3)
            kernel32.CloseHandle(handle3)
    else:
        print(f'Success without delete share! handle={handle2}')
        _copy_and_read(handle2)
        kernel32.CloseHandle(handle2)
else:
    print(f'Success! handle={handle}')
    _copy_and_read(handle)
    kernel32.CloseHandle(handle)
