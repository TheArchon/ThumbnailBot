#
# Copyright (C) 2025-present by TheAloneTeam@Github, < https://github.com/TheAloneTeam >.
#
# This file is part of < https://github.com/TheAloneTeam/KartikMusic > project,
# and is released under the "MIT License".
# Please see < https://github.com/TheAloneTeam/KartikMusic/blob/master/LICENSE >
#
# All rights reserved.
#

from dataclasses import dataclass


@dataclass
class Media:
    id: str
    duration: str = "00:00"
    duration_sec: int = 0
    file_path: str = None
    message_id: int = 0
    title: str = None
    url: str = None
    time: int = 0
    played_at: float = None
    user: str = None
    video: bool = False


@dataclass
class Track:
    id: str
    channel_name: str = None
    duration: str = "00:00"
    duration_sec: int = 0
    title: str = None
    url: str = None
    file_path: str = None
    message_id: int = 0
    time: int = 0
    played_at: float = None
    thumbnail: str = None
    user: str = None
    view_count: str = None
    video: bool = False
