# OCR

Any number of textual fields can be scanned from the image. By default this happens for `vehicle_direction` as in this
Hikvision example.

[OCR Direction Example](assets/images/ocr-example.png){width=600}

Each field can have optional permitted values (`Unknown` returned if none of them found) and a set of corrections
to handle occasional OCR errors, where corrections are simple strings or regular expressions.

Use the [OCR Tool](debug_tools.md#ocr) for quick tests of configuration with a local image

## OCR Stages

1. Crop the image to a box starting at `x` and `y` position, measured from the bottom left of the image and a given height and width
2. Optionally invert the image colours for better capture accuracy
3. Run OCR over the cropped image
4. Apply optional corrections
5. Optionally restrict to a list of values, forcing case if needed


## Example Configuration

The configuration for this can be in the `anpr2mqtt.yaml` file, or in environment variables or command line arguments.


```yaml
ocr:
  fields:
    vehicle_direction:
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