from datetime import datetime
from zoneinfo import ZoneInfo

from kiri import config


def zone():
    return ZoneInfo(config.TIMEZONE)


def now():
    return datetime.now(zone())


def today():
    return now().strftime("%A %Y-%m-%d")


def stamp(epoch):
    return datetime.fromtimestamp(epoch, zone()).strftime("%Y-%m-%d %H:%M %Z")
