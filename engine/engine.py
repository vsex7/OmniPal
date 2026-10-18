#!/usr/bin/env python3
"""Backward-compatibility shim for the historical ``engine.engine`` module.

The implementation now lives in the :mod:`engine.omnipal` package, split by
responsibility (paths / util / hypr_ipc / profiles / core / daemon).
Attribute access is delegated live (PEP 562) so rebinding performed by
:func:`engine.omnipal.paths._resolve_run_dir` stays visible here, exactly as
when everything lived in this single file.
"""
import atexit
import datetime
import json
import contextlib
import fcntl
import io
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from engine import omnipal as _omnipal


def __getattr__(name):
    return getattr(_omnipal, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_omnipal)))


if __name__ == "__main__":
    from engine.omnipal import OmniPalEngine, run_daemon
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        run_daemon()
    else:
        eng = OmniPalEngine()
        print(json.dumps(eng.get_state(), indent=2, ensure_ascii=False))
