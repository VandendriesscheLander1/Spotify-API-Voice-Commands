import speech_recognition as sr
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import threading
import json
import re
import logging
import sys
import os
import time
import tkinter as tk
from tkinter import StringVar, ttk, HORIZONTAL

# Setup logging
logging.basicConfig(filename='assistant_errors.log', level=logging.ERROR)

# Function to get resource path for config file
def get_resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

# Load configuration file with Spotify credentials
config_path = get_resource_path('config.json')
with open(config_path) as config_file:
    config = json.load(config_file)

client_id = config['SPOTIFY_CLIENT_ID']
client_secret = config['SPOTIFY_CLIENT_SECRET']

sp_oauth = SpotifyOAuth(
    client_id=client_id,
    client_secret=client_secret,
    redirect_uri='http://localhost',
    scope='user-modify-playback-state user-read-playback-state'
)

def get_access_token():
    token_info = sp_oauth.get_cached_token()

    if not token_info or sp_oauth.is_token_expired(token_info):
        if token_info and 'refresh_token' in token_info:
            token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        else:
            auth_url = sp_oauth.get_authorize_url()
            print(f"Please navigate here to authorize: {auth_url}")
            response = input("Enter the URL you were redirected to: ")
            code = sp_oauth.parse_response_code(response)
            token_info = sp_oauth.get_access_token(code)
    
    return token_info['access_token']

# Initialize Spotify client with authentication
sp = spotipy.Spotify(auth=get_access_token())

# Tkinter window setup
class SpotifyAssistantGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Spotify Voice Assistant")
        self.geometry("500x350")
        self.configure(bg="#1DB954")

        # StringVar to display the last executed command
        self.command_var = StringVar()
        self.command_var.set("Waiting for voice command...")

        # Label to display the current track
        self.track_var = StringVar()
        self.track_var.set("No track playing")

        # Label to display the current volume
        self.volume_var = StringVar()
        self.volume_var.set("Volume: 50%")

        # Label to display the last executed command
        self.command_label = tk.Label(self, textvariable=self.command_var, font=('Arial', 14), fg="white", bg="#1DB954")
        self.command_label.pack(pady=10)

        # Label to display the current track
        self.track_label = tk.Label(self, textvariable=self.track_var, font=('Arial', 12), fg="white", bg="#1DB954")
        self.track_label.pack(pady=5)

        # Volume control slider
        self.volume_slider = ttk.Scale(self, from_=0, to=100, orient=HORIZONTAL, command=self.set_volume)
        self.volume_slider.set(50)  # Default volume
        self.volume_slider.pack(pady=10)

        # Label to display the current volume
        self.volume_label = tk.Label(self, textvariable=self.volume_var, font=('Arial', 12), fg="white", bg="#1DB954")
        self.volume_label.pack(pady=5)

        # Label to display available voice commands
        commands = ("Available Commands:\n"
                    "- Play\n"
                    "- Pause\n"
                    "- Skip\n"
                    "- Previous\n"
                    "- Volume Up\n"
                    "- Volume Down\n"
                    "- Exit")
        self.commands_label = tk.Label(self, text=commands, font=('Arial', 10), fg="white", bg="#1DB954")
        self.commands_label.pack(pady=10)

        # Track the last time the volume was manually adjusted
        self.last_volume_update = time.time()

        # Start background threads
        self.stop_event = threading.Event()

        # Start assistant thread to recognize and execute commands
        self.assistant_thread = threading.Thread(target=self.run_assistant_in_background)
        self.assistant_thread.daemon = True
        self.assistant_thread.start()

        # Start token refresh thread
        self.token_refresh_thread = threading.Thread(target=self.refresh_token_periodically)
        self.token_refresh_thread.daemon = True
        self.token_refresh_thread.start()

        # Start track and volume update thread
        self.update_thread = threading.Thread(target=self.update_track_and_volume)
        self.update_thread.daemon = True
        self.update_thread.start()

        # Setup for graceful exit
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # Function to recognize and execute commands
    def recognize_and_execute(self):
        recognizer = sr.Recognizer()
        mic = sr.Microphone()

        with mic as source:
            self.command_var.set("Listening for commands...")
            self.update()

            recognizer.adjust_for_ambient_noise(source)
            try:
                audio = recognizer.listen(source, timeout=5)
                command = recognizer.recognize_google(audio).lower()
                self.command_var.set(f"Recognized: {command}")
                self.update()

                # Handle different voice commands
                if re.search(r'\bplay\b', command):
                    sp.start_playback()
                    self.command_var.set("Executed: Play")
                elif re.search(r'\bpause\b', command):
                    sp.pause_playback()
                    self.command_var.set("Executed: Pause")
                elif re.search(r'\bskip\b', command):
                    sp.next_track()
                    self.command_var.set("Executed: Skip")
                elif re.search(r'\bprevious\b', command):
                    sp.previous_track()
                    self.command_var.set("Executed: Previous")
                elif re.search(r'\bvolume up\b', command):
                    self.adjust_volume(10)
                    self.command_var.set("Executed: Volume Up")
                elif re.search(r'\bvolume down\b', command):
                    self.adjust_volume(-10)
                    self.command_var.set("Executed: Volume Down")
                elif re.search(r'\bexit\b', command):
                    self.command_var.set("Exit command received. Shutting down...")
                    self.stop_event.set()
                    self.on_close()
                else:
                    self.command_var.set("Command not recognized. Try again.")
            except sr.WaitTimeoutError:
                self.command_var.set("No command detected. Listening again...")
            except sr.RequestError as e:
                logging.error(f"Could not request results from Google Speech Recognition service; {e}")
            except spotipy.exceptions.SpotifyException as e:
                logging.error(f"Spotify API error: {e}")
            except Exception as e:
                logging.error(f"Unexpected error: {e}")

    # Function to adjust volume up or down
    def adjust_volume(self, adjustment):
        try:
            current_volume = int(self.volume_slider.get())
            new_volume = max(0, min(100, current_volume + adjustment))
            self.volume_slider.set(new_volume)
            self.set_volume(new_volume)
        except Exception as e:
            logging.error(f"Error adjusting volume: {e}")

    # Run the assistant in the background
    def run_assistant_in_background(self):
        while not self.stop_event.is_set():
            self.recognize_and_execute()

    # Periodically refresh the Spotify token
    def refresh_token_periodically(self):
        while not self.stop_event.wait(1800):  # Wait 30 minutes or until stop_event is set
            try:
                token_info = sp_oauth.get_cached_token()
                if sp_oauth.is_token_expired(token_info):
                    token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
                    sp.auth = token_info['access_token']
            except Exception as e:
                logging.error(f"Error refreshing token: {e}")

    # Update the track and volume display
    def update_track_and_volume(self):
        while not self.stop_event.is_set():
            try:
                playback = sp.current_playback()
                if playback and playback['is_playing']:
                    track_name = playback['item']['name']
                    artist_name = playback['item']['artists'][0]['name']
                    self.track_var.set(f"Now Playing: {track_name} - {artist_name}")

                    # Update the volume slider only if it hasn't been manually adjusted recently
                    if time.time() - self.last_volume_update > 1:  # 1 second threshold
                        volume = playback['device']['volume_percent']
                        self.volume_slider.set(volume)
                        self.volume_var.set(f"Volume: {volume}%")
                else:
                    self.track_var.set("No track playing")
            except Exception as e:
                logging.error(f"Error updating track and volume: {e}")
            time.sleep(2)  # Update every 2 seconds

    # Set volume using the slider
    def set_volume(self, volume):
        try:
            self.last_volume_update = time.time()  # Record the time of the manual adjustment
            sp.volume(int(float(volume)))
            self.volume_var.set(f"Volume: {int(float(volume))}%")
        except Exception as e:
            logging.error(f"Error setting volume: {e}")

    # Handle closing the application
    def on_close(self):
        self.stop_event.set()
        if self.assistant_thread.is_alive():
            self.assistant_thread.join()
        if self.token_refresh_thread.is_alive():
            self.token_refresh_thread.join()
        if self.update_thread.is_alive():
            self.update_thread.join()
        self.destroy()

# Run the Tkinter app
if __name__ == "__main__":
    app = SpotifyAssistantGUI()
    app.mainloop()
