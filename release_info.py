"""Single release version shared by the UI, installer and archive builder."""

import configparser
from pathlib import Path

configuration = configparser.ConfigParser()
configuration.read(Path(__file__).with_name("release.ini"), encoding="utf-8")
VERSION = configuration["app"]["version"]
