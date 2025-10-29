#!/usr/bin/env python3
import os
import sys
import random
import subprocess
import time
import threading
import pathlib
from evdev import InputDevice, categorize, ecodes

# --- CONFIGURATION ---
CURRENT_DIR = pathlib.Path(__file__).parent.resolve()
# CURRENT_DIR = pathlib.Path.cwd()
WELCOME_DIR = CURRENT_DIR / "welcome-videos"
ERROR_DIR = CURRENT_DIR / "error-videos"
SHOWS_DIR = CURRENT_DIR / "shows"
INPUT_DEVICE_PATH = "/dev/input/event0"

# 9 (1), 8 (2), 7 (3), 6 (SKIP)
# 5 (4), 4 (5), 3 (6), 2 (7)

KEY_MAP = {
    2: {"short": "The Simpsons", "long": "Futurama"},
    3: {"short": "King of the Hill", "long": "American Dad"},
    4: {"short": "Cheers", "long": "MASH"},
    5: {"short": "Sex and the City", "long": "Joe Pera Talks to You"},
    6: "SKIP",  # This is a seperate thing
    7: {"short": "Music", "long": "Documentaries"},
    8: {"short": "Jeopardy", "long": "Match Game"},
    9: {"short": "Seinfeld", "long": "It's Always Sunny in Philadelphia"},
}

SKIP_KEY_CODE = 6
LONG_PRESS_SECONDS = 0.75
LONGER_PRESS_SECONDS = 2

# --- GLOBAL STATE ---
current_process = None
process_lock = threading.Lock()
welcome_looping = False
shuffle_all = False
current_show = None

# To control restart and exiting of run_jukebox
exit_requested = False

# --- FUNCTIONS ---
def scan_shows():
    print("\n--- SHOWS LOADED ---")
    all_shows = {}
    total_episodes = 0

    for show in sorted(os.listdir(SHOWS_DIR)):
        show_path = os.path.join(SHOWS_DIR, show)
        if os.path.isdir(show_path):
            episodes = get_episodes(show)
            if episodes:
                all_shows[show] = episodes
                total_episodes += len(episodes)

    for show, episodes in all_shows.items():
        percent = (len(episodes) / total_episodes * 100) if total_episodes else 0
        print(f"{show}: {len(episodes)} episodes ({percent:.1f}%)")

    print(f"Total episodes: {total_episodes}")
    print("--- END SHOW SCAN ---\n")

def get_random_file(path):
    files = [f for f in os.listdir(path) if f.lower().endswith((".mp4", ".mkv", ".avi", ".webm"))]
    return os.path.join(path, random.choice(files)) if files else None

def get_episodes(show_name):
    show_path = os.path.join(SHOWS_DIR, show_name)
    episodes = []
    for root, dirs, files in os.walk(show_path):
        for f in files:
            if f.lower().endswith((".mp4", ".mkv", ".avi", ".webm")):
                episodes.append(os.path.join(root, f))
    return episodes

def stop_current_video():
    global current_process
    with process_lock:
        if current_process and current_process.poll() is None:
            print("Stopping current video...")
            current_process.terminate()
            try:
                current_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                current_process.kill()
        current_process = None

def play_video(filepath, osd_message=None, loop=False):
    global current_process
    stop_current_video()

    filename = os.path.basename(filepath)
    name_without_ext = os.path.splitext(filename)[0]

    cmd = [
        "cvlc", "--fullscreen", "--quiet", "--video-on-top", "--gain=3",
        "--no-video-title-show", "--intf", "dummy", "--aout", "alsa",
        "--no-sub-autodetect-file", "--no-spu", "--play-and-exit", filepath
    ]

    if loop:
        cmd += ["--loop"]
    else:
        marquee_text = osd_message or name_without_ext
        cmd += [
            "--sub-source=marq",
            f"--marq-marquee={marquee_text}",
            "--marq-timeout=2000",
            "--marq-position=0",
            "--marq-size=0",
            "--marq-opacity=255",
            "--marq-color=0xFFFFFF"
        ]
        print(f"Playing video: {filepath} with OSD: {marquee_text}")

    process = subprocess.Popen(cmd)
    with process_lock:
        current_process = process

def play_error_video(reason: str):
    """Play a single error video (if available) with on-screen reason then exit.

    Falls back to printing if no error videos exist.
    """
    if not ERROR_DIR.exists():
        print(f"ERROR (no directory): {reason}")
        return
    path = get_random_file(ERROR_DIR)
    if not path:
        print(f"ERROR (no videos): {reason}")
        return
    print(f"Playing error video: {path} -> {reason}")
    play_video(path, osd_message=reason, loop=False)
    # Wait until finished (or terminated)
    while True:
        with process_lock:
            proc = current_process
        if not proc or proc.poll() is not None:
            break
        time.sleep(0.25)

def next_episode(osd=None):
    global current_show, shuffle_all

    if shuffle_all:
        all_eps = []
        for show in os.listdir(SHOWS_DIR):
            show_path = os.path.join(SHOWS_DIR, show)
            if os.path.isdir(show_path):
                all_eps += get_episodes(show)
        if all_eps:
            episode = random.choice(all_eps)
            play_video(episode, osd or "|SHUFFLE| ALL SHOWS")
    elif current_show:
        episodes = get_episodes(current_show)
        if episodes:
            episode = random.choice(episodes)
            play_video(episode, osd or f"|SHUFFLE| {current_show}")

def loop_welcome_video():
    global welcome_looping, exit_requested
    welcome_looping = True

    while welcome_looping and not exit_requested:
        path = get_random_file(WELCOME_DIR)
        if path:
            print(f"Selected welcome video: {path}")
            play_video(path, loop=True)
            while current_process and current_process.poll() is None and welcome_looping and not exit_requested:
                time.sleep(1)

def monitor_video_end():
    global welcome_looping, exit_requested
    while not exit_requested:
        time.sleep(1)
        with process_lock:
            proc = current_process
        if proc and proc.poll() is not None and not welcome_looping and not exit_requested:
            print("Video ended. Starting next episode...")
            next_episode()

def handle_key_press(code, long_press=False):
    """Handle press selecting short or long show mapping.

    long_press indicates duration exceeded LONG_PRESS_SECONDS threshold (but not LONGER_PRESS_SECONDS).
    """
    global current_show, shuffle_all, welcome_looping

    if code not in KEY_MAP:
        print(f"Unknown key code: {code}")
        return

    mapping = KEY_MAP[code]
    if mapping == "SKIP":
        return  # Skip handled elsewhere

    # Decide which show based on press duration
    show = mapping["long" if long_press else "short"]
    print(f"Key pressed: {code} -> {'LONG' if long_press else 'SHORT'} -> {show}")

    welcome_looping = False
    current_show = show
    shuffle_all = False
    next_episode()

def start_welcome_loop():
    global welcome_looping
    welcome_looping = True
    threading.Thread(target=loop_welcome_video, daemon=True).start()

def run_jukebox():
    global shuffle_all, current_show, welcome_looping, exit_requested

    exit_requested = False
    shuffle_all = False
    current_show = None
    welcome_looping = True

    # Verify input device presence before proceeding.
    if not os.path.exists(INPUT_DEVICE_PATH):
        msg = "DEVICE MISSING: Check USB connection"
        print(f"WARNING: {msg}")
        play_error_video(msg)
        return False

    try:
        dev = InputDevice(INPUT_DEVICE_PATH)
    except Exception as e:
        msg = f"DEVICE ERROR: {e}"
        print(f"WARNING: {msg}")
        play_error_video(msg)
        return False

    # Only start welcome loop and monitor threads after device confirmed.
    start_welcome_loop()
    monitor_thread = threading.Thread(target=monitor_video_end, daemon=True)
    monitor_thread.start()

    print(f"Listening for input on {INPUT_DEVICE_PATH} ({dev.name})...")

    skip_pressed_time = None
    # store key down times for non-skip keys to measure duration and choose short vs long show
    key_pressed_times = {}

    for event in dev.read_loop():
        if exit_requested:
            print("Exit requested, breaking input loop.")
            stop_current_video()
            break

        if event.type == ecodes.EV_KEY and event.code in KEY_MAP:
            # Key down
            if event.value == 1:
                if event.code == SKIP_KEY_CODE:
                    skip_pressed_time = time.time()
                else:
                    key_pressed_times[event.code] = time.time()
            # Key up
            elif event.value == 0:
                # Handle SKIP release logic
                if event.code == SKIP_KEY_CODE:
                    if skip_pressed_time:
                        duration = time.time() - skip_pressed_time
                        skip_pressed_time = None
                        if duration >= LONGER_PRESS_SECONDS:
                            print("Very long SKIP press — returning to welcome loop.")
                            shuffle_all = False
                            current_show = None
                            exit_requested = True
                            stop_current_video()
                        elif duration >= LONG_PRESS_SECONDS:
                            print("Long SKIP press — shuffle ALL shows.")
                            shuffle_all = True
                            current_show = None
                            welcome_looping = False
                            next_episode("|SHUFFLE| ALL SHOWS")
                        else:
                            if shuffle_all:
                                next_episode("|SHUFFLE| ALL SHOWS")
                            elif current_show:
                                next_episode(f"|SHUFFLE| {current_show}")
                else:
                    # Non-skip key release: determine duration
                    pressed_time = key_pressed_times.pop(event.code, None)
                    if pressed_time:
                        duration = time.time() - pressed_time
                        long_press = duration >= LONG_PRESS_SECONDS
                        handle_key_press(event.code, long_press=long_press)

    return True

def main():
    scan_shows()
    while True:
        success = run_jukebox()
        if not success:
            # Device missing or inaccessible; exit program.
            sys.exit(1)
        print("Restarting TV Jukebox...")

if __name__ == "__main__":
    main()
