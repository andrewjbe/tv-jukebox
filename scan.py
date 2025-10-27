#!/usr/bin/env python3
import os
import pathlib

# --- CONFIGURATION ---
CURRENT_DIR = pathlib.Path(__file__).parent.resolve()
# git CURRENT_DIR = pathlib.Path.cwd()
WELCOME_DIR = CURRENT_DIR / "welcome-videos"
ERROR_DIR = CURRENT_DIR / "error-videos"
SHOWS_DIR = CURRENT_DIR / "shows"
INPUT_DEVICE_PATH = "/dev/input/event0"

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