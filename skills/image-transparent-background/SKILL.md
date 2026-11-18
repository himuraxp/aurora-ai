---
name: image-transparent-background
description: Use when the user sends an image and asks to remove the white background, make it transparent, replace the background with transparency, or process an image with ImageMagick for background removal. Trigger on keywords like "fond transparent", "remove white background", "background transparent", "transparence", "ImageMagick fond blanc".
---

# Image Transparent Background

Remove white backgrounds from images and replace them with transparency using ImageMagick.

## Important Limitation

Images attached to the chat are **not local files** and cannot be accessed directly by tools. The user **must** provide the absolute file path of the saved image.

## Process

### Step 1: Request file path

If the user only sent an image without a file path, ask immediately:

> "Pour que je puisse traiter l'image, peux-tu me donner le chemin absolu du fichier sur ton disque ? (ex: `~/Desktop/mon-image.png`)"

### Step 2: Verify file exists

Check that the file exists before processing.

### Step 3: Remove white background

Execute ImageMagick with these exact parameters:

```bash
magick <input> -fuzz 10% -transparent white -trim <output>
```

Where:
- `<input>`: the user's file path
- `<output>`: same directory, suffixed with `-transparent.png` (or user-specified)

**Adjust fuzz if needed:**
- `-fuzz 5%` : stricter, keeps more white/cream details
- `-fuzz 15%` : more aggressive for anti-aliased edges
- `-fuzz 20%` : maximum, may remove white clothing/armor details

### Step 4: Verify output

Confirm the output file exists and has an alpha channel (RGBA):

```bash
magick identify -verbose <output> | grep -i alpha
file <output>
```

Expected: `8-bit/color RGBA` or `TrueColorAlpha`

### Step 5: Report result

Report:
- Input and output file paths
- Image dimensions
- Confirmation that alpha channel is present

If the user is not satisfied with the result, adjust the `-fuzz` value and retry.
