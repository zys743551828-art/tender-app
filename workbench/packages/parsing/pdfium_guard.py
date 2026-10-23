"""The text parser and technical renderer share a lock, not process isolation."""

from threading import Lock

LOCK = Lock()
