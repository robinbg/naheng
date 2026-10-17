"""Read-only process identities; PID reuse never establishes a live owner.

Windows uses a process handle and its creation FILETIME. Linux uses the boot
UUID and /proc/<pid>/stat starttime. Unsupported or inaccessible identity
information stays unknown. These observations do not authorize killing a PID.
"""
import ctypes
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path
import sys
import uuid

SCHEMA_VERSION = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87
ERROR_NOT_FOUND = 1168


def _valid_pid(pid):
    return isinstance(pid, int) and not isinstance(pid, bool) and 0 < pid <= 0xFFFFFFFF


def _unknown(reason):
    return {"birth_id": None, "observed_alive": None, "capture_status": "unknown", "reason": reason}


@lru_cache(maxsize=1)
def _windows_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _windows_observation(pid):
    kernel = _windows_api()
    handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in (ERROR_INVALID_PARAMETER, ERROR_NOT_FOUND):
            return {"birth_id": None, "observed_alive": False, "capture_status": "absent",
                    "reason": "OpenProcess reports no process: " + str(error)}
        return _unknown("OpenProcess inaccessible: " + str(error))
    try:
        creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        has_times = bool(kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                                               ctypes.byref(kernel_time), ctypes.byref(user_time)))
        times_error = ctypes.get_last_error() if not has_times else None
        wait_result = kernel.WaitForSingleObject(handle, 0)
        wait_error = ctypes.get_last_error() if wait_result not in (WAIT_OBJECT_0, WAIT_TIMEOUT) else None
        alive = False if wait_result == WAIT_OBJECT_0 else True if wait_result == WAIT_TIMEOUT else None
        if not has_times:
            result = _unknown("GetProcessTimes unavailable: " + str(times_error))
            result["observed_alive"] = alive
            return result
        birth = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        if birth == 0:
            result = _unknown("Creation FILETIME was zero")
            result["observed_alive"] = alive
            return result
        return {"birth_id": "windows_filetime:" + str(birth), "observed_alive": alive,
                "capture_status": "captured", "reason": None if alive is not None else "WaitForSingleObject unavailable: " + str(wait_error)}
    finally:
        kernel.CloseHandle(handle)


def _parse_proc_stat(text):
    """Return Linux state and field 22; comm can itself contain spaces or ')'."""
    _, separator, tail = text.rpartition(")")
    fields = tail.split()
    if not separator or len(fields) < 20 or len(fields[0]) != 1:
        raise ValueError("Malformed /proc stat")
    starttime = int(fields[19])
    if starttime <= 0:
        raise ValueError("Invalid process starttime")
    return fields[0], starttime


def _linux_observation(pid):
    try:
        text = Path("/proc") / str(pid) / "stat"
        state, starttime = _parse_proc_stat(text.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"birth_id": None, "observed_alive": False, "capture_status": "absent", "reason": "/proc process stat absent"}
    except (OSError, ValueError, UnicodeError) as exc:
        return _unknown("Cannot read process stat: " + type(exc).__name__)
    try:
        boot_id = str(uuid.UUID(Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()))
    except (OSError, ValueError, UnicodeError) as exc:
        result = _unknown("Cannot read boot identity: " + type(exc).__name__)
        result["observed_alive"] = False if state in ("Z", "X", "x") else None
        return result
    return {"birth_id": "linux:" + boot_id + ":" + str(starttime), "observed_alive": state not in ("Z", "X", "x"),
            "capture_status": "captured", "reason": None}


def _observe(pid):
    try:
        if sys.platform == "win32":
            return _windows_observation(pid)
        if sys.platform.startswith("linux"):
            return _linux_observation(pid)
        return _unknown("Unsupported platform: " + sys.platform)
    except (OSError, ValueError, AttributeError) as exc:
        return _unknown("Process identity query unavailable: " + type(exc).__name__)


def capture_process_identity(pid):
    """Capture PID plus a birth identifier; unavailable evidence remains None."""
    identity = {"schema_version": SCHEMA_VERSION, "pid": pid if _valid_pid(pid) else None, "platform": sys.platform}
    identity.update(_observe(pid) if _valid_pid(pid) else _unknown("Invalid PID"))
    return identity


def _valid_birth(birth, platform):
    if not isinstance(birth, str) or len(birth) > 128:
        return False
    try:
        if platform == "win32":
            prefix, separator, number = birth.partition(":")
            return prefix == "windows_filetime" and bool(separator) and number.isascii() and number.isdecimal() and 0 < int(number) < (1 << 64)
        if platform.startswith("linux"):
            prefix, boot_id, starttime = birth.split(":")
            return prefix == "linux" and str(uuid.UUID(boot_id)) == boot_id and starttime.isascii() and starttime.isdecimal() and int(starttime) > 0
    except (ValueError, AttributeError):
        return False
    return False


def process_identity_alive(identity):
    """True=same live birth; False=dead/reused/absent; None=unverifiable.

    A malformed identity never proves absence. Permission failures likewise
    stay unknown so callers can preserve a potentially live job owner.
    """
    if not isinstance(identity, dict) or identity.get("schema_version") != SCHEMA_VERSION:
        return None
    pid, platform, birth = identity.get("pid"), identity.get("platform"), identity.get("birth_id")
    if not _valid_pid(pid) or not isinstance(platform, str) or platform != sys.platform or not _valid_birth(birth, platform):
        return None
    current = _observe(pid)
    if current["observed_alive"] is False:
        return False
    if current["birth_id"] is not None and current["birth_id"] != birth:
        return False
    if current["birth_id"] == birth and current["observed_alive"] is True:
        return True
    return None
