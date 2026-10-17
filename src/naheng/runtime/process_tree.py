"""Own one subprocess tree; never enumerate or terminate unrelated processes."""
import os
import signal
import subprocess


class ProcessTree:
    def __init__(self, proc):
        self.proc = proc
        self.job = None
        self.assignment_error = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class BasicLimits(ctypes.Structure):
                _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                            ("flags", wintypes.DWORD), ("minimum_ws", ctypes.c_size_t),
                            ("maximum_ws", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                            ("scheduling", wintypes.DWORD)]

            class Counters(ctypes.Structure):
                _fields_ = [(name, ctypes.c_ulonglong) for name in
                            ["read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes"]]

            class ExtendedLimits(ctypes.Structure):
                _fields_ = [("basic", BasicLimits), ("io", Counters),
                            ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                            ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            api.CreateJobObjectW.restype = wintypes.HANDLE
            api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            api.SetInformationJobObject.restype = wintypes.BOOL
            api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            api.AssignProcessToJobObject.restype = wintypes.BOOL
            api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            api.TerminateJobObject.restype = wintypes.BOOL
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.CloseHandle.restype = wintypes.BOOL
            self.api = api
            job = api.CreateJobObjectW(None, None)
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (job and api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                    and api.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle)))):
                self.job = job
            else:
                self.assignment_error = ctypes.get_last_error()
                if job:
                    api.CloseHandle(job)

    def terminate(self):
        if self.job is not None:
            if not self.api.TerminateJobObject(self.job, 1):
                raise OSError("Failed to terminate the owned Windows Job Object")
            return {"method": "windows_job_object", "exit_code": 0}
        if os.name == "nt":
            killed = subprocess.run(["taskkill.exe", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            return {"method": "taskkill_fallback", "exit_code": killed.returncode,
                    "assignment_error": self.assignment_error,
                    "stdout": killed.stdout.decode(errors="replace"),
                    "stderr": killed.stderr.decode(errors="replace")}
        os.killpg(self.proc.pid, signal.SIGKILL)
        return {"method": "posix_owned_process_group", "exit_code": 0}

    def close(self):
        if self.job is not None:
            self.api.CloseHandle(self.job)
            self.job = None
