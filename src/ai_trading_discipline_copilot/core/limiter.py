"""Shared rate limiter instance.

A single Limiter is created here and imported by both main.py (to attach to
app.state and register the exception handler) and any router that needs to
apply per-route limits.  Using one shared instance ensures all route counters
live in the same in-memory store.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
