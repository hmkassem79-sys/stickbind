# StickBind

**Set up your flight sim controller by pressing the button you want to use.** No digging through menus.

StickBind 0.2 works with **Microsoft Flight Simulator 2024 and 2020** (the Microsoft Store and Game Pass versions) on Windows. Steam, X-Plane and DCS support is planned.

## What it does

- **Teach a button.** Press a button on your stick, throttle or yoke, then pick what it should do: autopilot on/off, brakes, parking brake, gear, flaps, trim, spoilers or reverse thrust. If that button already does something else, StickBind tells you and can clear the old job.
- **Ready-made presets.** For devices it knows, it fills in the usual bindings. Anything you've already set is left alone. This version includes MOZA AB6 and MOZA MTQ presets based on MOZA's published layouts.
- **Show bindings.** Lists everything a profile has bound, so you can see what each button does.

## How to use

1. In the sim, go to Controls, select your device and save a profile once, so the sim writes it to disk.
2. Close the sim completely.
3. Run `stickbind.py` (Python 3.9+). For buttons above 32, install pygame once with `pip install pygame`. An `.exe` with everything included is coming.
4. Start the sim and pick your profile in Controls.

## Safety

Before its first change, StickBind copies all your sim control profiles to `Documents\StickBind backups`. It won't save while the sim is running, and it won't save at all if the sim's index file doesn't match the profile. To undo, close the sim and copy the backup folder back.

StickBind isn't made by or affiliated with Microsoft, Asobo or any hardware maker. Use it at your own risk.

## Known limits (0.2)

- Without pygame, only buttons 1 to 32 can be read. StickBind tells you when you press a higher one.
- Camera and hat views live in a different sim file. StickBind recognises the hat and tells you how to set it in the sim.
- Only the Microsoft Store and Game Pass versions of the sims are supported.

Free. Found a bug, or want a preset for your device? Open an issue.
