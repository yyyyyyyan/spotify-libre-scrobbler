import os
import pickle
import sys
from argparse import ArgumentParser
from configparser import ConfigParser
from datetime import datetime
from getpass import getpass
from hashlib import md5
from math import ceil

from pylast import LibreFMNetwork, SessionKeyGenerator, WSError
from spotipy import Spotify, SpotifyOAuth


def hash_librefm_password(password):
    return md5(password.encode("utf8")).hexdigest()


def init_config(**kwargs):
    config_filename = kwargs["config_file"]
    config = ConfigParser()
    print(
        "Follow the instructions and enter the requested information to create the config file\n"
    )

    spotify_conf = dict()
    print("-" * 27)
    print("Configuring Spotify API:\n")
    print(
        "1 - Create an app on Spotify for Developers (https://developer.spotify.com/dashboard/applications)"
    )
    print("2 - Input the following information (available on the app page):")
    spotify_conf["client_id"] = input("Client ID: ")
    spotify_conf["client_secret"] = input("Client Secret: ")
    print(
        "3 - On the app page, click on Edit Settings, enter a URI on the Redirect URIs field and save. (Note: the URI doesn't need to be accessible. By default we use http://localhost)"
    )
    print("4 - Input the following information:")
    spotify_conf["redirect_uri"] = (
        input("Redirect URI [http://localhost]: ") or "http://localhost"
    )
    spotify_conf["username"] = input("Spotify username: ")
    config["spotify"] = spotify_conf

    librefm_conf = dict()
    print("-" * 27)
    print("Configuring Libre.fm API:\n")
    librefm_conf["username"] = input("Libre.fm username: ")
    librefm_conf["password_hash"] = hash_librefm_password(
        getpass("Libre.fm password: ")
    )
    config["libre.fm"] = librefm_conf

    print("-" * 27)
    print(f"Saving config to {config_filename}")
    with open(config_filename, "w") as config_file:
        config.write(config_file)


def save_tracks(filename, tracks):
    with open(filename, "wb") as pickle_file:
        pickle.dump(tracks, pickle_file, pickle.HIGHEST_PROTOCOL)


def main(**kwargs):
    config_file = kwargs["config"]
    if len(sys.argv) <= 2 and not os.path.isfile(config_file):
        print(f"Default config file ({config_file}) not found and no arguments passed")
        print("Run the following command to generate a config file:")
        print(f"\t{sys.argv[0]} init")
        sys.exit(1)

    config = ConfigParser()
    if os.path.isfile(config_file):
        config.read(config_file)
    else:
        config["spotify"] = dict()
        config["libre.fm"] = dict()

    try:
        auth = SpotifyOAuth(
            kwargs["spotify_client_id"] or config["spotify"]["CLIENT_ID"],
            kwargs["spotify_client_secret"] or config["spotify"]["CLIENT_SECRET"],
            kwargs["spotify_redirect_uri"] or config["spotify"]["REDIRECT_URI"],
            username=kwargs["spotify_user"] or config["spotify"]["USERNAME"],
            scope="user-read-recently-played",
        )
    except KeyError as err:
        print(f"Missing Spotify config/parameter {err}")
        sys.exit(1)

    if kwargs["force_refresh_token"]:
        auth.refresh_access_token(auth.get_cached_token()["refresh_token"])
    spotify = Spotify(auth_manager=auth)

    print("Searching recent tracks")
    if kwargs["search_after"]:
        last_timestamp = int(
            datetime.strptime(
                kwargs["search_after"], kwargs["search_after_fmt"]
            ).timestamp()
            * 1000
        )
    else:
        last_timestamp = kwargs["last_timestamp"] or config["spotify"].get(
            "LAST_TIMESTAMP"
        )
    recent_tracks = spotify.current_user_recently_played(after=last_timestamp)
    cursors = recent_tracks["cursors"]
    last_timestamp = cursors["after"] if cursors is not None else last_timestamp
    config["spotify"]["LAST_TIMESTAMP"] = last_timestamp
    tracks_file = kwargs["tracks_file"]
    spotify_tracks = recent_tracks["items"]
    if kwargs["scrobble_remaining"] and os.path.isfile(tracks_file):
        with open(tracks_file, "rb") as pickle_file:
            spotify_tracks.extend(pickle.load(pickle_file))
    print(f"Found {len(spotify_tracks)} tracks to scrobble!")

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
                "timestamp": int(
                    datetime.strptime(
                        track["played_at"], "%Y-%m-%dT%H:%M:%S.%f%z"
                    ).timestamp()
                ),
            }
            tracks.append(track_info)
        except Exception as err:
            print("Error reading track metadata")
            print(err)
            print(track)
            print(f"Saving non-scrobbled tracks to {tracks_file}")
            save_tracks(tracks_file, spotify_tracks)
            sys.exit(1)

    librefm_auth = {key.lower(): value for key, value in config["libre.fm"].items()}
    librefm_auth["username"] = kwargs["librefm_user"] or librefm_auth["username"]
    librefm_auth["password_hash"] = (
        hash_librefm_password(kwargs["librefm_password"])
        if kwargs["librefm_password"]
        else librefm_auth["password_hash"]
    )
    if tracks:
        tries = 10
        while tries:
            tries -= 1
            librefm = LibreFMNetwork(**librefm_auth)
            print("Scrobbling tracks...")
            try:
                librefm.scrobble_many(tracks)
            except WSError:
                print(f"Error: Invalid session! {tries} tries remaining")
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
        else:
            print("Scrobbling unsuccessful :(")
            print(f"Saving non-scrobbled tracks to {tracks_file}")
            save_tracks(tracks_file, spotify_tracks)
            sys.exit(1)

    if kwargs["write_config"]:
        with open(config_file, "w") as config_file:
            config.write(config_file)
        print("Saved config file! ;)")


if __name__ == "__main__":
    parser = ArgumentParser()
    subparsers = parser.add_subparsers()

    scrobble_parser = subparsers.add_parser(
        "scrobble", help="Scrobble your Spotify's recently played tracks to libre.fm",
    )
    scrobble_parser.set_defaults(func=main)
    scrobble_parser.add_argument(
        "-c",
        "--config",
        default="config.ini",
        help="Config file to read script parameters (default: %(default)s)",
    )
    scrobble_parser.add_argument(
        "--no-write-config",
        dest="write_config",
        action="store_false",
        help="Don't write to config at the end",
    )
    scrobble_parser.add_argument(
        "--tracks-file",
        default=".tracks.pickle",
        help="File to save non-scrobbled tracks in case of any error",
    )
    scrobble_parser.add_argument(
        "--ignore-tracks-file",
        dest="scrobble_remaining",
        action="store_false",
        help="Don't try to scrobble remaining tracks saved on tracks-file",
    )

    spotify_group = scrobble_parser.add_argument_group(
        "Spotify", description="Spotify related parameters"
    )
    spotify_group.add_argument("--spotify-user", help="Your Spotify username")
    spotify_group.add_argument(
        "--spotify-redirect-uri",
        default="http://localhost",
        help="Spotify redirect URI set on your Spotify Developer's page - doesn't need to be accessible (default: %(default)s)",
    )
    spotify_group.add_argument("--spotify-client-id", help="Your Spotify Client ID")
    spotify_group.add_argument(
        "--spotify-client-secret", help="Your Spotify Client Secret"
    )
    spotify_group.add_argument(
        "--force-refresh-token",
        action="store_true",
        help="Force refresh your Spotify Client Token before starting the routine",
    )
    last_played = spotify_group.add_mutually_exclusive_group()
    last_played.add_argument(
        "--last-timestamp",
        type=int,
        help="UNIX timestamp (milliseconds) representing the date and time you listened the last scrobbled Spotify track",
    )
    last_played.add_argument(
        "--search-after",
        help="Only tracks played after this date and time will be scrobbled. Must follow search-after-fmt format",
    )
    spotify_group.add_argument(
        "--search-after-fmt",
        default="%Y-%m-%dT%H:%M:%S.%f%z",
        help="Datetime format (in strftime syntax) for search-after (default: %(default)s)",
    )

    librefm_group = scrobble_parser.add_argument_group(
        "Libre.fm", description="Libre.fm related parameters"
    )
    librefm_group.add_argument("--librefm-user", help="Your Libre.fm username")
    librefm_group.add_argument("--librefm-password", help="Your Libre.fm password")

    init_parser = subparsers.add_parser(
        "init", help="CLI wizard to generate a config file"
    )
    init_parser.add_argument(
        "config_file",
        nargs="?",
        default="config.ini",
        help="Config file to save settings (default: %(default)s)",
    )
    init_parser.set_defaults(func=init_config)

    help_parser = subparsers.add_parser(
        "help", help="Show the complete help message for all commands", add_help=False,
    )
    help_parser.set_defaults(
        func=lambda **kwargs: print(
            f"{scrobble_parser.format_help()}\n{'-'*27}\n{init_parser.format_help()}"
        )
    )

    args = parser.parse_args()
    dict_args = vars(args)
    if dict_args:
        args.func(**dict_args)
    else:
        parser.print_help()
