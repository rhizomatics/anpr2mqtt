import datetime
from dataclasses import dataclass


@dataclass
class ImageInfo:
    plate: str
    timestamp: datetime.datetime
    ext: str | None
    size: int
