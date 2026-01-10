import datetime
from dataclasses import dataclass


@dataclass
class ImageInfo:
    target: str
    event: str | None
    timestamp: datetime.datetime
    ext: str | None
    size: int
