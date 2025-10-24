#!/usr/bin/env python3
import os
import random
import subprocess
import time
import threading
import pathlib
from evdev import InputDevice, categorize, ecodes

# --- CONFIGURATION ---
CURRENT_DIR = pathlib.Path(__file__).parent.resolve()
WELCOME_DIR = CURRENT_DIR / "welcome-videos"
SHOWS_DIR = CURRENT_DIR / "shows"
INPUT_DEVICE_PATH = "/dev/input/event0"  # Adjust as needed

KEY_MAP = {
    2: "The Simpsons",
    3: "King of the Hill",
    4: "Cheers",
    5: "Sex and the City",
    6: "SKIP",
    7: "The Nanny",
    8: "It's Always Sunny in Philadelphia",
    9: "Seinfeld"
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
    files = [f for f in os.listdir(path) if f.lower().endswith((".mp4", ".mkv", ".avi"))]
    return os.path.join(path, random.choice(files)) if files else None

def get_episodes(show_name):
    show_path = os.path.join(SHOWS_DIR, show_name)
    episodes = []
    for root, dirs, files in os.walk(show_path):
        for f in files:
            if f.lower().endswith((".mp4", ".mkv", ".avi")):
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

def handle_key_press(code):
    global current_show, shuffle_all, welcome_looping

    if code not in KEY_MAP:
        print(f"Unknown key code: {code}")
        return

    key = KEY_MAP[code]
    print(f"Key pressed: {code} -> {key}")

    if key == "SKIP":
        return  # Skip handled separately

    welcome_looping = False
    current_show = key
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

    start_welcome_loop()

    monitor_thread = threading.Thread(target=monitor_video_end, daemon=True)
    monitor_thread.start()

    dev = InputDevice(INPUT_DEVICE_PATH)
    print(f"Listening for input on {INPUT_DEVICE_PATH} ({dev.name})...")

    skip_pressed_time = None

    for event in dev.read_loop():
        if exit_requested:
            print("Exit requested, breaking input loop.")
            stop_current_video()
            break

        if event.type == ecodes.EV_KEY and event.code in KEY_MAP:
            if event.value == 1:  # Key down
                if event.code == SKIP_KEY_CODE:
                    skip_pressed_time = time.time()
                else:
                    handle_key_press(event.code)

            elif event.value == 0 and event.code == SKIP_KEY_CODE:  # Key up
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

def main():
    scan_shows()
    while True:
        run_jukebox()
        print("Restarting TV Jukebox...")

if __name__ == "__main__":
    main()
