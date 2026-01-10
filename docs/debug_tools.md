# Debug Tools

ANPR2MQTT has additional command line options to help debug file system integration or OCR.

## OCR

This will load the image, run the OCR on the (optionally cropped and inverted image) and report the value.

In this example, the directory of the image comes from an existing config file or env var.

```bash
 uv run tools ocr_file 20241230152519495_N74DYX_VEHICLE_DETECTION.jpg
```

If there's no config at all, the command can be configured entirely from the command line, and this allows any other defaults to be changed, such as the OCR box

```bash
 uv run tools ocr_file --file_system.watch_path /ftp/Driveway --ocr.direction_box 0,100,200,400 20241230152519495_Z374TST_VEHICLE_DETECTION.jpg
 ```


## Directory Listing

This will list the images in the given directory that match the ANPR image regular expression

```bash
uv run anpr2mqtt list_dir /ftp/driveway
```

Like the OCR example, this also allows any of the `file_system` config to be changed, in this example trying out a regular expression to match the file

```bash
uv run tools list_dir --file_system.watch_path /ftp/Driveway --file_system.image_name_re '(?P<dt>[0-9]{17})_(?P<plate>[A-Z0-9]+)_VEHICLE_DETECTION\.(?P<ext>jpg|png|gif|jpeg)'
```
