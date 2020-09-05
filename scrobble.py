from configparser import ConfigParser
from datetime import datetime
from math import ceil
from sys import exit

from pylast import LibreFMNetwork, SessionKeyGenerator
from spotipy import Spotify, SpotifyOAuth

CONFIG_FILENAME = "config.ini"
SCOPE = "user-read-recently-played"

if __name__ == "__main__":
    config = ConfigParser()
    config.read(CONFIG_FILENAME)

    spotify_conf = config["spotify"]
    auth = SpotifyOAuth(spotify_conf["CLIENT_ID"], spotify_conf["CLIENT_SECRET"], spotify_conf["REDIRECT_URI"], scope=SCOPE, username="666nobody666")
    auth.refresh_access_token(auth.get_cached_token()["refresh_token"])
    spotify = Spotify(auth_manager=auth)

    print("Searching recent tracks")
    spotify_tracks = []
    last_timestamp = spotify_conf.get("LAST_TIMESTAMP")
    more_items = True
    while more_items:
        recent_tracks = spotify.current_user_recently_played(after=last_timestamp)
        spotify_tracks.extend(recent_tracks["items"])
        more_items = len(recent_tracks["items"])
        cursors = recent_tracks["cursors"]
        last_timestamp = cursors["after"] if cursors is not None else last_timestamp
    config["spotify"]["LAST_TIMESTAMP"] = last_timestamp
    print(f"Found {len(spotify_tracks)} to scrobble!")

    print("Organizing tracks...")
    tracks = []
    for track in spotify_tracks:
        try:
            track_info = {
                "artist": track["track"]["artists"][0]["name"],
                "title": track["track"]["name"],
                "album": track["track"]["album"]["name"],
                "track_number": track["track"].get("track_number"),
                "duration": ceil(track["track"]["duration_ms"] / 1000),
                "timestamp": int(datetime.strptime(track["played_at"], "%Y-%m-%dT%H:%M:%S.%f%z").timestamp())
            }
            tracks.append(track_info)
        except Exception as err:
            print("ERROR!")
            print(err)
            print(track)
            exit(1)

    librefm_auth = {key.lower():value for key, value in config["libre.fm"].items()}
    if tracks:
        while True:
            librefm = LibreFMNetwork(**librefm_auth)
            print("Scrobbling tracks...")
            try:
                librefm.scrobble_many(tracks)
            except Exception as err:
                print("ERROR!")
                print(err)
                print("Getting new session...")
                skg = SessionKeyGenerator(librefm)
                url = skg.get_web_auth_url()
                print(f"Authorize the app: {url}")
                input("Press ENTER when done")
                session_key = skg.get_web_auth_session_key(url)
                librefm_auth["session_key"] = session_key
            else:
                print("Scrobbling successful!")
                config["libre.fm"]["SESSION_KEY"] = librefm_auth["session_key"]
                break

    with open(CONFIG_FILENAME, "w") as config_file:
        config.write(config_file)
    print("Saved config file! ;)")