import datetime as dt
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import PIL.ImageOps
import pytesseract
import structlog
import tzlocal
from PIL import Image
from watchdog.events import DirCreatedEvent, FileClosedEvent, FileCreatedEvent, RegexMatchingEventHandler

from anpr2mqtt.api_client import DVLA, APIClient
from anpr2mqtt.const import ImageInfo
from anpr2mqtt.hass import HomeAssistantPublisher
from anpr2mqtt.settings import (
    TARGET_TYPE_PLATE,
    DVLASettings,
    EventSettings,
    ImageSettings,
    OCRFieldSettings,
    OCRSettings,
    TargetSettings,
    TrackerSettings,
)

log = structlog.get_logger()


class EventHandler(RegexMatchingEventHandler):
    def __init__(
        self,
        publisher: HomeAssistantPublisher,
        state_topic: str,
        image_topic: str,
        event_config: EventSettings,
        target_config: TargetSettings | None,
        ocr_config: OCRSettings,
        image_config: ImageSettings,
        dvla_config: DVLASettings,
        tracker_config: TrackerSettings,
    ) -> None:
        fqre = f"{event_config.watch_path.resolve() / event_config.image_name_re.pattern}"
        super().__init__(regexes=[fqre], ignore_directories=True, case_sensitive=True)
        log.debug("Listening for images matching %s", fqre)
        self.publisher = publisher
        self.state_topic: str = state_topic
        self.event_config: EventSettings = event_config
        self.tracker_config: TrackerSettings = tracker_config
        self.target_config: TargetSettings | None = target_config
        self.ocr_config: OCRSettings = ocr_config
        self.image_config: ImageSettings = image_config
        self.dvla_config: DVLASettings = dvla_config
        if event_config.image_url_base:
            log.info("Images available from web server with prefix %s", event_config.image_url_base)
        self.image_topic: str | None = image_topic

        if dvla_config.api_key and event_config.target_type == TARGET_TYPE_PLATE:
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
            f"{self.event_config.image_url_base}/{file_path.name!s}" if self.event_config.image_url_base and file_path else None
        )

        try:
            image_info: ImageInfo | None = examine_file(file_path, self.event_config.image_name_re)
            if image_info is not None:
                target: str = image_info.target
                log.info("Examining image for %s at %s", target, file_path.absolute())

                image: Image.Image | None = process_image(
                    file_path.absolute(), image_info, jpeg_opts=self.image_config.jpeg_opts, png_opts=self.image_config.png_opts
                )
                ocr_fields: dict[str, str | None] = scan_ocr_fields(image, self.event_config, self.ocr_config)

                classification: dict[str, Any] = self.classify_target(target)
                if classification["target"] != target:
                    # apply corrected target name if changed
                    target = classification["target"]

                reg_info: list[Any] | dict[str, Any] | None = None
                if (
                    not classification.get("known")
                    and self.api_client
                    and image_info.target
                    and self.event_config.target_type == TARGET_TYPE_PLATE
                ):
                    reg_info = self.api_client.lookup(target)

                visit_count: int
                last_seen: dt.datetime | None
                visit_count, last_seen = self.track_target(target, self.event_config.target_type, image_info.timestamp)

                if classification.get("ignore"):
                    log.info("Skipping MQTT publication for ignored %s", target)
                    return

                self.publisher.post_state_message(
                    self.state_topic,
                    target=target,
                    event_config=self.event_config,
                    image_info=image_info,
                    ocr_fields=ocr_fields,
                    classification=classification,
                    previous_sightings=visit_count,
                    last_sighting=last_seen,
                    url=url,
                    reg_info=reg_info,
                    file_path=file_path,
                )
                if self.image_topic and image:
                    img_format = image_info.ext.upper() if image_info.ext else None
                    img_format = "JPEG" if img_format == "JPG" else img_format
                    if img_format:
                        self.publisher.post_image_message(self.image_topic, image, img_format)
                    else:
                        log.warn("Unknown image format for %s", file_path)
            else:
                ocr_fields = scan_ocr_fields(None, self.event_config, self.ocr_config)

                self.publisher.post_state_message(
                    self.state_topic,
                    event_config=self.event_config,
                    ocr_fields=ocr_fields,
                    target=None,
                    url=url,
                    file_path=file_path,
                )

        except Exception as e:
            log.error("Failed to parse file event %s: %s", event, e, exc_info=1)
            self.publisher.post_state_message(
                self.state_topic,
                event_config=self.event_config,
                target=None,
                error=str(e),
                file_path=file_path,
            )

    def track_target(self, target: str, target_type: str, event_dt: dt.datetime | None) -> tuple[int, dt.datetime | None]:
        target = target or "UNKNOWN"
        target_type_path = self.tracker_config.data_dir / target_type
        target_type_path.mkdir(exist_ok=True)
        target_file = target_type_path / f"{target}.json"
        last_visit: dt.datetime | None = None
        previous_visits: int = 0
        try:
            sightings: list[str] = []
            if target_file.exists():
                with target_file.open("r") as f:
                    sightings = json.load(f)
                    previous_visits = len(sightings)
                    if previous_visits > 0:
                        last_visit = dt.datetime.fromisoformat(sightings[-1])

            sightings.append(event_dt.isoformat() if event_dt else dt.datetime.now(tz=tzlocal.get_localzone()).isoformat())
            with target_file.open("w") as f:
                json.dump(sightings, f)
        except Exception as e:
            log.exception("Failed to track sightings for %s:%s", target, e)
        return previous_visits, last_visit

    def classify_target(self, target: str | None) -> dict[str, Any]:
        results = {
            "orig_target": target,
            "target": target,
            "ignore": False,
            "known": False,
            "dangerous": False,
            "priority": "high",
            "description": "Unknown vehicle",
        }
        if not target or self.target_config is None:
            # empty dict to make home assistant template logic easier
            return results
        for corrected_target, patterns in self.target_config.correction.items():
            if any(re.match(pat, target) for pat in patterns):
                results["target"] = corrected_target
                target = corrected_target
                log.info("Corrected target %s -> %s", results["orig_target"], target)
                break
        for pat in self.target_config.ignore:
            if re.match(pat, target):
                log.info("Ignoring %s matching ignore pattern %s", target, pat)
                results["ignore"] = True
                results["priority"] = "low"
                results["description"] = "Ignored"
                break
        if target in self.target_config.dangerous:
            log.warning("%s known as potential danger", target)
            results["dangerous"] = True
            results["priority"] = "critical"
            results["description"] = self.target_config.dangerous[target] or "Potential threat"
        if target in self.target_config.known:
            log.warning("%s known to household", target)
            results["known"] = True
            results["priority"] = "medium"
            results["description"] = self.target_config.known[target] or "Known"

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
            event: str | None = groups.get("event")
            target: str | None = groups.get("target")
            if target is None:
                log.warning("No target found for match: %s", groups)
                return None
            if file_ext is None:
                file_parts = file_path.name.rsplit(".", 1)
                if file_parts:
                    file_ext = file_parts[0]
            return ImageInfo(target=target, event=event, timestamp=timestamp, ext=file_ext, size=size)
    except Exception as e:
        log.warning("Unable to parse %s: %s", file_path, e)
    return None


def scan_ocr_fields(image: Image.Image | None, event_config: EventSettings, ocr_config: OCRSettings) -> dict[str, str | None]:
    ocr_field_defs: list[OCRFieldSettings] = [
        ocr_config.fields[k] for k in event_config.ocr_field_ids if k in ocr_config.fields
    ]
    results: dict[str, str | None] = {f.label: "Unknown" for f in ocr_field_defs}
    log.debug("OCR default values: %s", results)

    if image is None:
        log.debug("OCR Empty image")
        return results
    if not ocr_field_defs:
        log.debug("OCR No fields to scan")
        return results

    try:
        width, height = image.size
    except Exception as e:
        log.error("OCR fail loading image:%s", e)
        results["IMAGE_ERROR"] = str(e)
        return results

    """
    The Python Imaging Library uses a Cartesian pixel coordinate system, with (0,0) in the upper left corner.
    Note that the coordinates refer to the implied pixel corners; the centre of a pixel addressed as (0, 0)
    actually lies at (0.5, 0.5).

    Coordinates are usually passed to the library as 2-tuples (x, y).
    Rectangles are represented as 4-tuples, (x1, y1, x2, y2), with the upper left corner given first.
    """
    for field_settings in ocr_field_defs:
        try:
            if field_settings.crop:
                x1: int = field_settings.crop.x  # top-left x
                y1: int = height - (field_settings.crop.y + field_settings.crop.h)  # top-left y [ 0 == top of image]
                x2: int = x1 + field_settings.crop.w  # bottom-right x
                y2: int = height - field_settings.crop.y  # bottom-right y [ 0 == top of image]
                log.debug("Cropping %s by %s image using PIL to %s", height, width, (x1, y1, x2, y2))
                # region = im.crop((850, height - 30, 1500, height)) "850,30,650,30"
                region: Image.Image = image.crop((x1, y1, x2, y2))
            else:
                log.debug("No image crop")
                region = image
            if field_settings.invert:
                region = PIL.ImageOps.invert(region)
            txt = pytesseract.image_to_string(region, config=r"")
            if txt:
                log.debug("Tesseract found text %s", txt)
                parsed: list[str] = txt.split(":", 1)
            else:
                log.debug("Tesseract found nothing")
                parsed = []

            if len(parsed) > 1:
                candidate: str = parsed[1].strip()
                if field_settings.correction and candidate not in field_settings.correction:
                    for correct_to, correct_patterns in field_settings.correction.items():
                        if any(re.match(pat, candidate) for pat in correct_patterns):
                            log.debug("Auto-correcting %s from %s to %s", field_settings.label, candidate, correct_to)
                            candidate = correct_to
                if candidate and field_settings.values:
                    for v in field_settings.values:
                        if candidate.upper() == v.upper() and candidate != v:
                            log.debug("OCR case correcting field %s from %s to %s", field_settings.label, candidate, v)
                            candidate = v
                if field_settings.values is None or candidate in field_settings.values:
                    results[field_settings.label] = candidate
                else:
                    log.warning("Unknown value %s for OCR field %s", candidate, field_settings.label)
                    results[field_settings.label] = "Unknown"
            else:
                log.warning("Unparsable field %s: %s", field_settings.label, txt)

        except Exception as e:
            log.error("OCR fail on image:%s", e, exc_info=1)
            results["OCR_ERROR"] = f"field:{field_settings.label}, error:{e}"

    return results
