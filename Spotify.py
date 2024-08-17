import speech_recognition as sr
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import threading
import json
import re
import logging
import signal
import sys
import os
import time

# Setup logging
logging.basicConfig(filename='assistant_errors.log', level=logging.ERROR)

def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

# Load the configuration file with plain credentials
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

sp = spotipy.Spotify(auth=get_access_token())

def recognize_and_execute():
    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    with mic as source:
        print("Listening for commands...")
        recognizer.adjust_for_ambient_noise(source)
        try:
            audio = recognizer.listen(source, timeout=5)
            command = recognizer.recognize_google(audio).lower()
            print(f"Command recognized: {command}")

            if re.search(r'\bplay\b', command):
                sp.start_playback()
            elif re.search(r'\bpause\b', command):
                sp.pause_playback()
            elif re.search(r'\bskip\b', command):
                sp.next_track()
            elif re.search(r'\bprevious\b', command):
                sp.previous_track()
            elif re.search(r'\bexit\b', command):
                print("Exit command received. Shutting down...")
                stop_event.set()
            else:
                print("Command not recognized. Please try again.")
        except sr.WaitTimeoutError:
            print("No command detected. Listening again...")
        except sr.RequestError as e:
            logging.error(f"Could not request results from Google Speech Recognition service; {e}")
        except spotipy.exceptions.SpotifyException as e:
            logging.error(f"Spotify API error: {e}")
        except Exception as e:
            logging.error(f"Unexpected error: {e}")

def refresh_token_periodically():
    while not stop_event.wait(1800):  # Wait 30 minutes or until stop_event is set
        try:
            token_info = sp_oauth.get_cached_token()
            if sp_oauth.is_token_expired(token_info):
                token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
                sp.auth = token_info['access_token']
        except Exception as e:
            logging.error(f"Error refreshing token: {e}")

stop_event = threading.Event()

def run_assistant_in_background():
    while not stop_event.is_set():
        recognize_and_execute()

def signal_handler(sig, frame):
    print("Exiting...")
    stop_event.set()
    assistant_thread.join()
    token_refresh_thread.join()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

assistant_thread = threading.Thread(target=run_assistant_in_background)
assistant_thread.daemon = True
assistant_thread.start()

token_refresh_thread = threading.Thread(target=refresh_token_periodically)
token_refresh_thread.daemon = True
token_refresh_thread.start()

try:
    while not stop_event.is_set():
        time.sleep(1)  # Keep the main thread alive
except KeyboardInterrupt:
    signal_handler(signal.SIGINT, None)
