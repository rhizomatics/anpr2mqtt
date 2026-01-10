import datetime as dt
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import PIL.ImageOps
import pytesseract
import structlog
import tzlocal
from PIL import Image
from watchdog.events import DirCreatedEvent, FileClosedEvent, FileCreatedEvent, RegexMatchingEventHandler

from anpr2mqtt.api_client import DVLA, APIClient
from anpr2mqtt.const import ImageInfo
from anpr2mqtt.hass import post_image_message, post_state_message
from anpr2mqtt.settings import DVLASettings, FileSystemSettings, ImageSettings, OCRSettings, PlateSettings, TrackerSettings

log = structlog.get_logger()


class EventHandler(RegexMatchingEventHandler):
    def __init__(
        self,
        client: mqtt.Client,
        camera: str,
        state_topic: str,
        image_topic: str,
        file_system_config: FileSystemSettings,
        plate_config: PlateSettings,
        ocr_config: OCRSettings,
        image_config: ImageSettings,
        dvla_config: DVLASettings,
        tracker_config: TrackerSettings,
    ) -> None:
        fqre = f"{file_system_config.watch_path.resolve() / file_system_config.image_name_re.pattern}"
        super().__init__(regexes=[fqre], ignore_directories=True, case_sensitive=True)
        log.debug("Listening for images matching %s", fqre)
        self.client: mqtt.Client = client
        self.state_topic: str = state_topic
        self.camera = camera
        self.file_system_config: FileSystemSettings = file_system_config
        self.tracker_config: TrackerSettings = tracker_config
        self.plate_config: PlateSettings = plate_config
        self.ocr_config: OCRSettings = ocr_config
        self.image_config: ImageSettings = image_config
        self.dvla_config: DVLASettings = dvla_config
        if file_system_config.image_url_base:
            log.info("Images available from web server with prefix %s", file_system_config.image_url_base)
        self.image_topic: str | None = image_topic
        self.coordinates: list[int] | None = (
            [int(v) for v in ocr_config.direction_box.split(",")] if ocr_config.direction_box else None
        )
        if self.coordinates:
            log.debug(
                "Configured to crop image to (x,y)=%s,%s with width %s and height %s",
                self.coordinates[0],
                self.coordinates[1],
                self.coordinates[2],
                self.coordinates[3],
            )
        else:
            log.debug("Image uncropped for direction checking")
        if dvla_config.api_key:
            log.info("Configured gov API lookup")
            self.api_client: APIClient | None = DVLA(dvla_config.api_key, cache_ttl=dvla_config.cache_ttl)
        else:
            log.info("No gov API lookup configured")
            self.api_client = None

    @property
    def ignore_directories(self) -> bool:
        return True

    def on_created(self, event: DirCreatedEvent | FileCreatedEvent) -> None:
        if event.event_type != "created" or event.is_directory:
            log.debug("on_created: skipping irrelevant event: %s", event)
            return
        log.info("New file detected: %s", event.src_path)

    def on_closed(self, event: FileClosedEvent) -> None:
        if event.event_type != "closed" or event.is_directory:
            log.debug("on_closed: skipping irrelevant event: %s", event)
            return
        log.info("New complete file detected: %s", event.src_path)

        file_path = Path(str(event.src_path))
        if not file_path.stat() or file_path.stat().st_size == 0:
            log.warning("Empty image file, ignoring, at %s", file_path)
            return
        url: str | None = (
            f"{self.file_system_config.image_url_base}/{file_path.name!s}"
            if self.file_system_config.image_url_base and file_path
            else None
        )
        try:
            image_info: ImageInfo | None = examine_file(file_path, self.file_system_config.image_name_re)
            if image_info is not None:
                plate: str = image_info.plate
                log.info("Examining image for %s at %s", plate, file_path.absolute())

                image: Image.Image | None = process_image(
                    file_path.absolute(), image_info, jpeg_opts=self.image_config.jpeg_opts, png_opts=self.image_config.png_opts
                )

                if image and self.coordinates:
                    direction: str | None = determine_anpr_direction(image, self.coordinates, self.ocr_config.invert)
                else:
                    direction = None

                classification: dict[str, Any] = self.classify_plate(plate)
                if classification["plate"] != plate:
                    plate = classification["plate"]

                reg_info: list[Any] | dict[str, Any] | None = None
                if not classification.get("known") and self.api_client and image_info.plate:
                    reg_info = self.api_client.lookup(plate)

                visit_count: int
                last_seen: dt.datetime | None
                visit_count, last_seen = self.track_plate(plate, image_info.timestamp)

                if classification.get("ignore"):
                    log.info("Skipping MQTT publication for ignored %s", plate)
                    return

                post_state_message(
                    self.client,
                    self.state_topic,
                    plate=plate,
                    image_info=image_info,
                    direction=direction,
                    classification=classification,
                    previous_sightings=visit_count,
                    last_sighting=last_seen,
                    url=url,
                    reg_info=reg_info,
                    camera=self.camera,
                    file_path=file_path,
                )
                if self.image_topic and image:
                    img_format = image_info.ext.upper() if image_info.ext else None
                    img_format = "JPEG" if img_format == "JPG" else img_format
                    if img_format:
                        post_image_message(self.client, self.image_topic, image, img_format)
                    else:
                        log.warn("Unknown image format for %s", file_path)
            else:
                post_state_message(
                    self.client,
                    self.state_topic,
                    plate=None,
                    url=url,
                    camera=self.camera,
                    file_path=file_path,
                )

        except Exception as e:
            log.error("Failed to parse file event %s: %s", event, e, exc_info=1)
            post_state_message(self.client, self.state_topic, plate=None, camera=self.camera, error=str(e), file_path=file_path)

    def track_plate(self, plate: str, event_dt: dt.datetime | None) -> tuple[int, dt.datetime | None]:
        plate = plate or "UNKNOWN"
        plate_file = self.tracker_config.data_dir / f"{plate}.json"
        last_visit: dt.datetime | None = None
        previous_visits: int = 0
        try:
            sightings: list[str] = []
            if plate_file.exists():
                with plate_file.open("r") as f:
                    sightings = json.load(f)
                    previous_visits = len(sightings)
                    if previous_visits > 0:
                        last_visit = dt.datetime.fromisoformat(sightings[-1])

            sightings.append(event_dt.isoformat() if event_dt else dt.datetime.now(tz=tzlocal.get_localzone()).isoformat())
            with plate_file.open("w") as f:
                json.dump(sightings, f)
        except Exception as e:
            log.exception("Failed to track sightings for %s:%s", plate, e)
        return previous_visits, last_visit

    def classify_plate(self, plate: str | None) -> dict[str, Any]:
        results = {
            "orig_plate": plate,
            "plate": plate,
            "ignore": False,
            "known": False,
            "dangerous": False,
            "priority": "high",
            "description": "Unknown vehicle",
        }
        if not plate:
            # empty dict to make home assistant template logic easier
            return results
        for corrected_plate, patterns in self.plate_config.correction.items():
            if any(re.match(pat, plate) for pat in patterns):
                results["plate"] = corrected_plate
                plate = corrected_plate
                log.info("Corrected plate %s -> %s", results["orig_plate"], plate)
                break
        for pat in self.plate_config.ignore:
            if re.match(pat, plate):
                log.info("Ignoring plate %s matching ignore pattern %s", plate, pat)
                results["ignore"] = True
                results["priority"] = "low"
                results["description"] = "Ignored Plate"
                break
        if plate in self.plate_config.dangerous:
            log.warning("Plate %s known as potential danger", plate)
            results["dangerous"] = True
            results["priority"] = "critical"
            results["description"] = self.plate_config.dangerous[plate] or "Potential threat vehicle"
        if plate in self.plate_config.known:
            log.warning("Plate %s known to household", plate)
            results["known"] = True
            results["priority"] = "medium"
            results["description"] = self.plate_config.known[plate] or "Known vehicle"

        return results


def process_image(
    file_path: Path, image_info: ImageInfo, jpeg_opts: dict[str, Any], png_opts: dict[str, Any]
) -> Image.Image | None:
    try:
        image: Image.Image | None = Image.open(file_path.absolute())
        if image is None:
            log.error("Unable to open image at %s", file_path.absolute())
            return None
        image_format: str | None = image.format.lower() if image.format else image_info.ext
        img_args: dict[str, Any] | None = None

        if image_format in ("jpg", "jpeg") and jpeg_opts:
            img_args = jpeg_opts
        elif image_format == "png" and png_opts:
            img_args = png_opts
        if img_args:
            log.debug("Rewriting image to process %s", img_args)
            buffer = BytesIO()
            image.save(buffer, image_format, **img_args)
            size = buffer.getbuffer().nbytes
            if size != image_info.size:
                log.info("Image size %s -> %s", image_info.size, size)
                image_info.size = size
            image = Image.open(buffer)
            log.info("Resaved image with %s", img_args)
        return image
    except Exception as e:
        log.warn("Unable to load image at %s: %s", file_path, e)
        return None


def examine_file(file_path: Path, image_name_re: re.Pattern) -> ImageInfo | None:
    try:
        match = re.match(image_name_re, file_path.name)
        if match:
            groups = match.groupdict()
            size: int = file_path.stat().st_size
            raw_date = match.group("dt")
            year, month, day = map(int, (raw_date[:4], raw_date[4:6], raw_date[6:8]))
            hours, minutes, seconds, microseconds = map(
                int, (raw_date[8:10], raw_date[10:12], raw_date[12:14], raw_date[14:17])
            )
            timestamp = dt.datetime(year, month, day, hours, minutes, seconds, microseconds, tzinfo=tzlocal.get_localzone())
            file_ext: str | None = groups.get("ext")
            if file_ext is None:
                file_parts = file_path.name.rsplit(".", 1)
                if file_parts:
                    file_ext = file_parts[0]
            return ImageInfo(match.group("plate"), timestamp, file_ext, size=size)
    except Exception as e:
        log.warning("Unable to parse %s: %s", file_path, e)
    return None


def determine_anpr_direction(image: Image.Image, coordinates: list[int] | None, invert: bool = True) -> str:
    try:
        width, height = image.size

        """
        The Python Imaging Library uses a Cartesian pixel coordinate system, with (0,0) in the upper left corner.
        Note that the coordinates refer to the implied pixel corners; the centre of a pixel addressed as (0, 0)
        actually lies at (0.5, 0.5).

        Coordinates are usually passed to the library as 2-tuples (x, y).
        Rectangles are represented as 4-tuples, (x1, y1, x2, y2), with the upper left corner given first.
        """
        if coordinates:
            x1: int = coordinates[0]  # top-left x
            y1: int = height - coordinates[3]  # top-left y [ 0 == top of image]
            x2: int = x1 + coordinates[2]  # bottom-right x
            y2: int = height - coordinates[1]  # bottom-right y [ 0 == top of image]
            log.debug("Cropping %s by %s image using PIL to %s", height, width, (x1, y1, x2, y2))
            # region = im.crop((850, height - 30, 1500, height)) "850,30,650,30"
            region: Image.Image = image.crop((x1, y1, x2, y2))
        else:
            log.debug("No image crop")
            region = image
        if invert:
            region = PIL.ImageOps.invert(region)
        txt = pytesseract.image_to_string(region, config=r"")
        log.debug("Tesseract found text %s", txt)
        parsed = txt.split(":", 1)
        if len(parsed) > 1:
            candidate: str = parsed[1].strip()
            if candidate in ("Forward", "Reverse"):
                return candidate
            if re.match(r"Fo.*rd", candidate, flags=re.IGNORECASE):  # codespell:ignore
                log.debug("Auto-correcting %s", candidate)
                return "Forward"
            if re.match(r"Bac.*rd", candidate, flags=re.IGNORECASE) or re.match(r"Revers.*", candidate, flags=re.IGNORECASE):
                log.debug("Auto-correcting %s", candidate)
                return "Reverse"
            log.warning("Unmatched direction: %s", candidate)
        else:
            log.warning("Unparsable direction: %s", txt)
        return "Unknown"
    except Exception as e:
        log.error("OCR fail on image:%s", e, exc_info=1)
        return "Error"
