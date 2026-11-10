# OCR

Any number of textual fields can be scanned from the image. By default this happens for `vehicle_direction` as in this Hikvision example.

Each field can have optional permitted values (`Unknown` returned if none of them found) and a set of corrections to handle occasional OCR errors, where corrections are simple strings or regular expressions.

Use the [OCR Tool](https://anpr2mqtt.rhizomatics.org.uk/debug_tools/#ocr-ocr_file) for quick tests of configuration with a local image

## OCR Stages

1. Crop the image to a box starting at `x` and `y` position, measured from the bottom left of the image and a given height and width
1. Optionally invert the image colours for better capture accuracy
1. Run OCR over the cropped image
1. Apply optional corrections
1. Optionally restrict to a list of values, forcing case if needed

## Startup Check

When any event uses OCR fields, ANPR2MQTT reads a small bundled sample image at startup, the caption bar from the Hikvision example above, and expects `vehicle_direction` to be `Forward`. This checks the [Tesseract](https://github.com/tesseract-ocr/tesseract) OCR engine is installed and working, independently of your own field settings, and logs either `Verified OCR` or an error. The app keeps running either way, but OCR fields will read as `Unknown` until a failure is fixed.

Outside Docker, a failure usually means the `tesseract` binary isn't installed or isn't on the `PATH`. Every event reads the `hik_direction` field unless told otherwise, so if your images have no text worth reading, turn OCR off for each event with `ocr_field_ids: []`. That also skips this check. To skip only the check:

```yaml
ocr:
  verify_on_startup: false
```

## Example Configuration

The configuration for this can be in the `anpr2mqtt.yaml` file, or in environment variables or command line arguments.

In this example `hik_direction` is the `ocr_field_id` value that can be referenced in an event, and `label` is the name of the attribute that will appear in the Home Asssitant entity attributes.

```yaml
ocr:
  hik_direction:
    label: vehicle_direction
    values: Reverse, Forward
    invert: true
    crop: 
      x: 0
      y: 850
      h: 30
      w: 650
    correction:
      Forward:
      - F.*wd
      Reverse:
      - R.*v.*se
      - Back.*
```

Use the [debug tools](https://anpr2mqtt.rhizomatics.org.uk/debug_tools/index.md) to quickly iterate over an image, for example:

```bash
uvx --from anpr2mqtt anprtools ocr_file 20260130174327627_K39ZTB_VEHICLE_DETECTION.jpg
```

or to test cropping values:

```bash
uvx --from anpr2mqtt anprtools ocr_file example_image.jpg \
  --ocr.crop.x 850 --ocr.crop.y 0 --ocr.crop.h 200 --ocr.crop.w 400
```
