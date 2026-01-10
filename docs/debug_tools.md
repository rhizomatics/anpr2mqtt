# Debug Tools

ANPR2MQTT has additional command line options to help debug file system integration or OCR.

## OCR

This will load the image, run the OCR on the (optionally cropped and inverted image) and report the value. It will ignore any yaml config, though will respect environment variables. This can be useful for quick feedback cycle with a local image and bounding boxes.


```bash
 uv run tools ocr_file 20241230152519495_N74DYX_VEHICLE_DETECTION.jpg
```

The default configuration can be overridden from the command line, and a specific OCR field configured

```bash
uv run tools ocr_file fixtures/20250602103045407_B4DM3N_VEHICLE_DETECTION.jpg --ocr.crop.x 850 --ocr.crop.y 0 --ocr.crop.h 200 --ocr.crop.w 400 --ocr.invert False
```

If there are no events defined in the configuration, then the image will be looked for in the current working directory.

## Directory Listing

This will list the images in the current directory that match the ANPR image regular expression

```bash
uv run tools list_dir
```

Like the OCR example, this also allows any of the `event` config to be changed, in this example trying out a regular expression to match the file

```bash
uv run tools list_dir --event.watch_path /ftp/Driveway --event.image_name_re '(?P<dt>[0-9]{17})_(?P<target>[A-Z0-9]+)_(?P<event>VEHICLE_DETECTION)\.(?P<ext>jpg|png|gif|jpeg)'
```
