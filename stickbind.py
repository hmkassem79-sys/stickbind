"""StickBind v0.1 - bind flight-sim controller buttons by pressing them.

Works on Microsoft Flight Simulator 2024 and 2020 (Microsoft Store / Game Pass versions).
It edits the control profiles MSFS keeps on your PC, always after a full backup.
Free to use. No warranty: close MSFS before saving, and keep the backups.
"""
import ctypes
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

VERSION = "0.2"
SIMS = [("MSFS 2024", "Microsoft.Limitless_8wekyb3d8bbwe"), ("MSFS 2020", "Microsoft.FlightSimulator_8wekyb3d8bbwe")]
BACKUPS = Path.home() / "Documents" / "StickBind backups"

# What a button can do. (menu text, MSFS action)
ACTIONS = [("Autopilot on/off (one press on, next off)", "KEY_AP_MASTER"),
           ("Autopilot disconnect", "KEY_AUTOPILOT_OFF"),
           ("Brakes (hold)", "KEY_BRAKES"),
           ("Parking brake on/off", "KEY_PARKING_BRAKES"),
           ("Gear up/down", "KEY_GEAR_TOGGLE"),
           ("Flaps up one step", "KEY_FLAPS_DECR"),
           ("Flaps down one step", "KEY_FLAPS_INCR"),
           ("Elevator trim up", "KEY_ELEV_TRIM_UP"),
           ("Elevator trim down", "KEY_ELEV_TRIM_DN"),
           ("Spoilers arm", "KEY_SPOILERS_ARM_TOGGLE"),
           ("Reverse thrust (hold)", "KEY_THROTTLE_REVERSE_THRUST_HOLD")]


def btn(n):                 # MSFS "Joystick Button N" is stored as code N-1
    return (f"Joystick Button {n}", n - 1, 2)


AX = {"LX": ("Joystick L-Axis X ", 1026), "LY": ("Joystick L-Axis Y ", 1042), "LZ": ("Joystick L-Axis Z ", 1058),
      "RX": ("Joystick R-Axis X ", 770), "RY": ("Joystick R-Axis Y ", 786), "RZ": ("Joystick R-Axis Z ", 802)}


def axis(a, reverse=False):  # flag 4 = axis, 132 = reversed axis
    return AX[a] + (132 if reverse else 4,)


# Ready-made presets, matched on the start of the device name. They only fill actions that are still empty.
PRESETS = {
    "MOZA AB6": ("MOZA AB6 (from MOZA's own MSFS file)", [
        ("KEY_AXIS_AILERONS_SET", axis("LX")), ("KEY_AXIS_ELEVATOR_SET", axis("LY")),
        ("KEY_ELEV_TRIM_UP", btn(9)), ("KEY_ELEV_TRIM_DN", btn(7)),
        ("KEY_AILERON_TRIM_LEFT", btn(10)), ("KEY_AILERON_TRIM_RIGHT", btn(8)),
        ("KEY_AUTOPILOT_OFF", btn(2)), ("KEY_BRAKES", btn(3))]),
    "MOZA MTQ": ("MOZA MTQ throttle (from MOZA's own X-Plane file)", [
        ("KEY_THROTTLE1_AXIS_SET_EX1", axis("RX", True)), ("KEY_THROTTLE2_AXIS_SET_EX1", axis("LZ", True)),
        ("KEY_AXIS_FLAPS_SET", axis("LY", True)), ("KEY_AXIS_SPOILER_SET", axis("LX")),
        ("KEY_GEAR_UP", btn(29)), ("KEY_GEAR_DOWN", btn(30)), ("KEY_THROTTLE_REVERSE_THRUST_HOLD", btn(34))]),
}


# ---------------------------------------------------------------- MSFS profile store

class Profile:
    def __init__(self, store, folder, blob):
        self.store, self.folder, self.blob = store, folder, blob
        head = blob.read_bytes()[:3000].decode("utf-8", "ignore")
        dev = re.search(r'<Device DeviceName="([^"]*)"[^>]*>', head)
        pid = re.search(r'ProductID="(\d+)"', dev.group(0)) if dev else None
        name = re.search(r'<FriendlyName[^>]*>([^<]*)<', head)
        self.device = dev.group(1) if dev else "?"
        self.pid = int(pid.group(1)) if pid else None
        self.name = name.group(1) if name else "?"


class Store:
    def __init__(self, sim, path):
        self.sim, self.path = sim, path
        self.backed_up = None

    def index(self):
        return bytearray((self.path / "containers.index").read_bytes())

    def profiles(self):
        idx, out = self.index(), []
        for d in sorted(self.path.iterdir()):
            try:
                if not d.is_dir() or idx.find(uuid.UUID(d.name).bytes_le) < 0:
                    continue        # folders MSFS no longer lists are leftovers
            except ValueError:
                continue
            blobs = [p for p in d.iterdir() if not p.name.startswith("container.")]
            if len(blobs) == 1 and b"<Device DeviceName=" in blobs[0].read_bytes()[:3000]:
                out.append(Profile(self, d.name, blobs[0]))
        return out

    def backup(self):
        if not self.backed_up:
            dest = BACKUPS / f"{self.sim.replace(' ', '')}_{datetime.now():%Y%m%d_%H%M%S}"
            shutil.copytree(self.path, dest / self.path.name)
            self.backed_up = dest
            print(f"   backup saved: {dest}")

    def save(self, prof, text):
        self.backup()
        idx, raw, data = self.index(), prof.blob.read_bytes(), text.encode("utf-8")
        g = uuid.UUID(prof.folder).bytes_le
        pos = idx.find(g)
        if pos < 0 or idx.find(g, pos + 1) != -1 or struct.unpack_from("<Q", idx, pos + 32)[0] != len(raw):
            raise SystemExit("MSFS's index doesn't match this profile. Nothing was saved.")
        struct.pack_into("<Q", idx, pos + 16, int((time.time() + 11644473600) * 10_000_000))
        struct.pack_into("<Q", idx, pos + 32, len(data))
        prof.blob.write_bytes(data)
        (self.path / "containers.index").write_bytes(bytes(idx))


def find_stores():
    if os.environ.get("STICKBIND_STORE"):                    # for testing on a copy
        return [Store("TEST", Path(os.environ["STICKBIND_STORE"]))]
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
    out = []
    for sim, pkg in SIMS:
        for idx in (root / pkg / "SystemAppData" / "wgs").glob("*_*/containers.index"):
            out.append(Store(sim, idx.parent))
    return out


# ---------------------------------------------------------------- editing the profile XML

def action_re(action):
    return re.compile(r'(\t*)<Action ActionName="%s"([^>]*?)(/>|>.*?</Action>)' % re.escape(action), re.S)


def set_action(text, action, key, only_if_empty=False):
    """Bind an action to one input (key = (info, code, flag)), or clear it when key is None."""
    m = action_re(action).search(text)
    if not m:
        return text, "not in this profile"
    if only_if_empty and m.group(3) != "/>":
        return text, "already set, kept"
    tabs = m.group(1)
    if key is None:
        attrs = m.group(2).rstrip()
        new = f'{tabs}<Action ActionName="{action}"{attrs}/>'
    else:
        info, code, flag = key
        attrs = re.sub(r'Flag="\d+"', f'Flag="{flag}"', m.group(2)).rstrip()
        new = (f'{tabs}<Action ActionName="{action}"{attrs}>\n{tabs}\t<Primary>\n'
               f'{tabs}\t\t<KEY Information="{info}">{code}</KEY>\n{tabs}\t</Primary>\n{tabs}</Action>')
    return text[:m.start()] + new + text[m.end():], "set"


def bindings(text):
    for m in re.finditer(r'<Action ActionName="([^"]*)"[^>]*[^/]>(.*?)</Action>', text, re.S):
        keys = re.findall(r'Information="([^"]*)"', m.group(2))
        if keys:
            yield m.group(1), [k.strip() for k in keys]


# ---------------------------------------------------------------- reading the stick
# pygame (SDL) sees up to 128 buttons and hats; Windows' built-in winmm only buttons 1-32.
# Either way the result is (product id, what was pressed): ("button", n) 1-based like MSFS, or ("hat", None).

def pygame_reader():
    try:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
    except ImportError:
        return None
    pygame.init()
    pygame.joystick.init()
    sticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
    for js in sticks:
        js.init()

    def pid(js):            # SDL GUID bytes 8-9 hold the USB product id
        try:
            g = bytes.fromhex(js.get_guid())
            return int.from_bytes(g[8:10], "little")
        except Exception:
            return None

    def snap():
        pygame.event.pump()
        return {i: ({b for b in range(js.get_numbuttons()) if js.get_button(b)},
                    any(js.get_hat(h) != (0, 0) for h in range(js.get_numhats()))) for i, js in enumerate(sticks)}

    return [(i, pid(js)) for i, js in enumerate(sticks)], snap


def winmm_reader():
    from ctypes import wintypes
    winmm = ctypes.WinDLL("winmm")

    class JOYINFOEX(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD)] + \
                   [(n, wintypes.DWORD) for n in ("x", "y", "z", "r", "u", "v")] + \
                   [("dwButtons", wintypes.DWORD), ("dwButtonNumber", wintypes.DWORD), ("dwPOV", wintypes.DWORD),
                    ("r1", wintypes.DWORD), ("r2", wintypes.DWORD)]

    class JOYCAPSW(ctypes.Structure):
        _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("szPname", wintypes.WCHAR * 32)] + \
                   [(f"u{i}", wintypes.UINT) for i in range(19)] + \
                   [("szRegKey", wintypes.WCHAR * 32), ("szOEMVxD", wintypes.WCHAR * 260)]

    def read(jid):
        info = JOYINFOEX(dwSize=ctypes.sizeof(JOYINFOEX), dwFlags=0xFF)
        if winmm.joyGetPosEx(jid, ctypes.byref(info)) != 0:
            return None
        btns = {b for b in range(32) if info.dwButtons >> b & 1}
        if info.dwButtonNumber > len(btns):
            btns.add(99)    # something above button 32 is down; winmm can't say which
        return btns, info.dwPOV != 0xFFFF

    def pid(jid):
        caps = JOYCAPSW()
        return caps.wPid if winmm.joyGetDevCapsW(jid, ctypes.byref(caps), ctypes.sizeof(caps)) == 0 else None

    ids = [j for j in range(16) if read(j) is not None]
    return [(j, pid(j)) for j in ids], lambda: {j: read(j) or (set(), False) for j in ids}


def wait_press(timeout=30):
    """Wait for one press. Returns (product id, ("button", n) or ("hat", None)), or None."""
    reader = pygame_reader()
    if not reader or not reader[0]:
        reader = winmm_reader()
    devices, snap = reader
    if not devices:
        print("   Windows can't see any controller. Check the USB cable.")
        return None
    pids = dict(devices)
    base = snap()
    print(f"   >> press and hold the button now ({timeout}s, Ctrl+C to go back) ", end="", flush=True)
    end, dot = time.time() + timeout, time.time()
    while time.time() < end:
        now = snap()
        for j, (btns, hat) in now.items():
            new = btns - base[j][0]
            if new:
                b = min(new)
                print()
                if b == 99:
                    print("   That button is above number 32, which this mode can't read.")
                    print("   Fix: run  pip install pygame  once, then try again.")
                    return None
                while b in snap()[j][0]:
                    time.sleep(0.02)
                return pids[j], ("button", b + 1)
            if hat and not base[j][1]:
                print()
                return pids[j], ("hat", None)
        if time.time() - dot > 1:
            print(".", end="", flush=True)
            dot = time.time()
        time.sleep(0.02)
    print("\n   Nothing came in. If you pressed something, run  pip install pygame  once and try again.")
    return None


# ---------------------------------------------------------------- menus

def ask(prompt, n):
    while True:
        a = input(prompt).strip()
        if a.isdigit() and 0 <= int(a) <= n:
            return int(a)


def msfs_running():
    r = subprocess.run('tasklist | find /i "FlightSimulator"', shell=True, capture_output=True)
    return r.returncode == 0


def confirm_save(prof, text, summary):
    print(f"\n   {summary}")
    if input("   Type y and Enter to save: ").strip().lower() != "y":
        print("   not saved.")
        return
    while msfs_running():
        input("   MSFS is open. Close it fully, then press Enter ...")
    prof.store.save(prof, text)
    print("   saved. Start MSFS and pick this profile in Controls.")


def teach(profiles):
    print("\nPress the button you want to set up.")
    try:
        got = wait_press()
    except KeyboardInterrupt:
        print("\n   back to the menu.")
        return
    if not got:
        return
    pid, (kind, n) = got
    if kind == "hat":
        print("   That's the hat. MSFS keeps camera and view controls in a separate file, so set the hat in")
        print("   the sim: Controls > your device > search 'look' or 'free look' > click the slot > push the hat.")
        return
    match = [p for p in profiles if p.pid == pid] or profiles
    prof = match[0] if len(match) == 1 else match[ask("   Which device is that? " + "  ".join(
        f"{i}) {p.device}" for i, p in enumerate(match)) + ": ", len(match) - 1)]
    print(f"   Button {n} on {prof.device}. What should it do?")
    for i, (label, _) in enumerate(ACTIONS, 1):
        print(f"   {i:2d}) {label}")
    print("    0) cancel")
    c = ask("   > ", len(ACTIONS))
    if not c:
        return
    label, action = ACTIONS[c - 1]
    text = prof.blob.read_bytes().decode("utf-8")
    others = [a for a, keys in bindings(text) if f"Joystick Button {n}" in keys and a != action]
    text, st = set_action(text, action, btn(n))
    if st != "set":
        print(f"   {action} is {st}.")
        return
    if others:
        print(f"   Button {n} also does: {', '.join(others)}")
        if input("   Remove those so it only does the new job? (y/n): ").strip().lower() == "y":
            for a in others:
                text, _ = set_action(text, a, None)
    confirm_save(prof, text, f"Button {n} = {label}")


def preset(profiles):
    usable = [(p, key) for p in profiles for key in PRESETS if p.device.startswith(key)]
    if not usable:
        print("\n   No ready-made preset for your devices yet. Use 'teach a button' instead.")
        return
    for i, (p, key) in enumerate(usable, 1):
        print(f"   {i}) {PRESETS[key][0]} -> profile '{p.name}'")
    c = ask("   > (0 cancels) ", len(usable))
    if not c:
        return
    prof, key = usable[c - 1]
    text = prof.blob.read_bytes().decode("utf-8")
    done = 0
    used = {k: a for a, keys in bindings(text) for k in keys}
    for action, k in PRESETS[key][1]:
        if k[0].strip() in used and used[k[0].strip()] != action:
            st = f"skipped, {k[0].strip()} already does {used[k[0].strip()]}"
        else:
            text, st = set_action(text, action, k, only_if_empty=True)
        print(f"   {action:36s} {st}")
        done += st == "set"
    if done:
        confirm_save(prof, text, f"{done} bindings from the {key} preset")


def show(profiles):
    for i, p in enumerate(profiles, 1):
        print(f"   {i}) {p.device}  '{p.name}'")
    c = ask("   > (0 cancels) ", len(profiles))
    if c:
        for action, keys in bindings(profiles[c - 1].blob.read_bytes().decode("utf-8")):
            print(f"   {action:40s} {', '.join(keys)}")


def main():
    print(f"StickBind {VERSION} - free. Close your sim before saving changes.\n")
    stores = find_stores()
    if not stores:
        raise SystemExit("No MSFS 2024/2020 (Microsoft Store / Game Pass) control profiles found on this PC.\n"
                         "Open the sim once, go to Controls and save a profile, then run StickBind again.")
    store = stores[0] if len(stores) == 1 else stores[ask("Which sim? " + "  ".join(
        f"{i}) {s.sim}" for i, s in enumerate(stores)) + ": ", len(stores) - 1)]
    while True:
        profiles = store.profiles()
        print(f"\n{store.sim}: {len(profiles)} controller profile(s)")
        for p in profiles:
            print(f"   - {p.device}  '{p.name}'")
        if not profiles:
            raise SystemExit("In MSFS go to Controls, change any binding on your device and save, then run again.")
        print("\n 1) Teach a button (press it, pick what it does)\n 2) Ready-made preset\n"
              " 3) Show what a profile has bound\n 0) Quit")
        c = ask("> ", 3)
        if c == 0:
            return
        [teach, preset, show][c - 1](profiles)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        print("\nStickBind hit an error. Nothing was saved after the last 'saved' line.")
    finally:
        if sys.stdin.isatty():
            input("\nPress Enter to close.")
