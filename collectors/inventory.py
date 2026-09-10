import time
import os
import platform
import socket
import uuid
import subprocess
import sys
import psutil

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False


def _get_mac_address():
    mac = uuid.getnode()
    return ":".join(f"{(mac >> i) & 0xFF:02x}" for i in range(0, 48, 8))


def _get_installed_software():
    software = []
    if sys.platform == "win32" and HAS_WINREG:
        hive = winreg.HKEY_LOCAL_MACHINE
        uninstall_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        try:
            key = winreg.OpenKey(hive, uninstall_key)
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name)
                    name = winreg.QueryValueEx(subkey, "DisplayName")[0] if _has_value(subkey, "DisplayName") else None
                    version = winreg.QueryValueEx(subkey, "DisplayVersion")[0] if _has_value(subkey, "DisplayVersion") else None
                    if name:
                        software.append({"name": name, "version": version})
                    winreg.CloseKey(subkey)
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass
    else:
        try:
            result = subprocess.run(["dpkg", "--get-selections"], capture_output=True, text=True, timeout=30)
            for line in result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "install":
                    software.append({"name": parts[0], "version": None})
        except Exception:
            pass
        try:
            result = subprocess.run(["rpm", "-qa", "--queryformat", "%{NAME} %{VERSION}\n"],
                                    capture_output=True, text=True, timeout=30)
            for line in result.stdout.strip().split("\n"):
                parts = line.split(" ", 1)
                if len(parts) >= 1 and parts[0]:
                    software.append({"name": parts[0], "version": parts[1] if len(parts) > 1 else None})
        except Exception:
            pass

    return software


def _has_value(key, name):
    try:
        winreg.QueryValueEx(key, name)
        return True
    except OSError:
        return False


def get_inventory():
    uname = platform.uname()
    boot = psutil.boot_time()
    disk_io = psutil.disk_io_counters()

    inventory = {
        "hostname": uname.node,
        "fqdn": socket.getfqdn(),
        "mac_address": _get_mac_address(),
        "system": {
            "os": uname.system,
            "os_release": platform.release(),
            "os_version": platform.version(),
            "architecture": uname.machine,
            "kernel": uname.release,
        },
        "hardware": {
            "cpu_count": psutil.cpu_count(),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "cpu_freq_max": (psutil.cpu_freq().max if psutil.cpu_freq() else None),
            "total_memory_bytes": psutil.virtual_memory().total,
            "total_swap_bytes": psutil.swap_memory().total,
        },
        "network": {
            "interfaces": {},
        },
        "disk": {
            "partitions": [],
            "io_counters": {
                "read_bytes": disk_io.read_bytes if disk_io else 0,
                "write_bytes": disk_io.write_bytes if disk_io else 0,
            },
        },
        "uptime_seconds": int(time.time() - boot),
        "boot_time": boot,
        "python_version": platform.python_version(),
    }

    for name, addrs in psutil.net_if_addrs().items():
        addrs_list = []
        for a in addrs:
            addrs_list.append({
                "family": str(a.family),
                "address": a.address,
                "netmask": a.netmask,
            })
        inventory["network"]["interfaces"][name] = addrs_list

    for p in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(p.mountpoint)
            inventory["disk"]["partitions"].append({
                "device": p.device,
                "mountpoint": p.mountpoint,
                "fstype": p.fstype,
                "total_bytes": usage.total,
            })
        except PermissionError:
            continue

    inventory["installed_software"] = _get_installed_software()

    return inventory
