# Debug Tools

ANPR2MQTT has additional command line options to help debug file system integration or OCR.

## OCR

This will load the image, run the OCR on the (optionally cropped and inverted image) and report the value. It can run either with a configured `anpr2mqtt` setup, or entirely stand-alone. The latter can be useful for quick feedback cycle with a local image and bounding boxes.


```bash
 uv run tools ocr_file 20241230152519495_N74DYX_VEHICLE_DETECTION.jpg
```

If there's no config at all, the command can be configured entirely from the command line, and a specific OCR field configured

```bash
 uv run tools ocr_file  20241230152519495_Z374TST_VEHICLE_DETECTION.jpg --ocr.crop.x 0 --ocr.crop.y 100 --ocr.crop.h 200 --ocr.crop.w 400 --ocr.invert False
```

If `file_system.watch_path` can't be resolved from the configuration, then the image will be looked for in the current working directory.

## Directory Listing

This will list the images in the given directory that match the ANPR image regular expression

```bash
uv run anpr2mqtt list_dir /ftp/driveway
```

Like the OCR example, this also allows any of the `file_system` config to be changed, in this example trying out a regular expression to match the file

```bash
uv run tools list_dir --file_system.watch_path /ftp/Driveway --file_system.image_name_re '(?P<dt>[0-9]{17})_(?P<plate>[A-Z0-9]+)_VEHICLE_DETECTION\.(?P<ext>jpg|png|gif|jpeg)'
```
