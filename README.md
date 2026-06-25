# SharpFrame → Extract the Sharpest Frames from Any Video

> A small, reusable command-line tool that pulls the
> **sharpest individual frames out of a video, such as a 4K/HEVC clip, as
> full-resolution JPEGs.** It scores every frame for sharpness, removes
> near-duplicates, and exports only the best.

SharpFrame turns a video recording into a curated set of still photos. Pick the
crisp, distinct frames automatically instead of scrubbing through footage by
hand for hours.

[![Python][python-badge]][python]
[![License][license-badge]][license]
[![Dependencies][dependencies-badge]][requirements]

![Logo][project-logo]

---

## Table of Contents

- [SharpFrame → Extract the Sharpest Frames from Any Video](#sharpframe--extract-the-sharpest-frames-from-any-video)
  - [Table of Contents](#table-of-contents)
  - [1. Goal](#1-goal)
  - [2. Requirements](#2-requirements)
    - [You need](#you-need)
    - [You do not need](#you-do-not-need)
  - [3. Usage](#3-usage)
  - [4. How It Works](#4-how-it-works)
    - [The Two-Pass Pipeline](#the-two-pass-pipeline)
      - [Pass 1 Scan](#pass-1-scan)
      - [Selection](#selection)
      - [Pass 2 Export](#pass-2-export)
    - [Cache and Re-Tuning](#cache-and-re-tuning)
  - [5. Parameters](#5-parameters)
  - [6. Handling Different Video Properties](#6-handling-different-video-properties)
    - [Resolution and Orientation](#resolution-and-orientation)
    - [Framerate](#framerate)
    - [Video Length and Runtime](#video-length-and-runtime)
    - [Codec](#codec)
    - [Variable Frame Rate](#variable-frame-rate)
    - [Disk Space](#disk-space)
  - [7. Output Files](#7-output-files)
  - [8. Verifying the Result](#8-verifying-the-result)
  - [9. Limitations and Error Handling](#9-limitations-and-error-handling)

---

## 1. Goal

The aim is to recover **as many genuinely sharp, mutually distinct frames as
possible** from a video, each saved as a standalone JPEG at **native
resolution**. For example, use it to harvest the best still photos from a video
take without spending hours searching manually.

Guiding principle: **quality over quantity.** The target count, by default
`300`, is an *upper bound*, not a quota. It is better to end up with 120
razor-sharp, distinct images than 300 full of mediocrity or duplicates.

---

## 2. Requirements

### You need

| Requirement     | Note                                                 |
| --------------- | ---------------------------------------------------- |
| Python 3.8+     | Tested with Python 3.14.5.                           |
| `opencv-python` | Decodes the video, measures sharpness, writes JPEGs. |
| `numpy`         | Provides statistics, percentiles, and variance.      |

Install them with:

```bash
pip install opencv-python numpy
```

### You do not need

- **No separate ffmpeg.** The FFmpeg build bundled with `opencv-python`
  reliably decodes **HEVC/H.265** on its own. The tool assumes this keeps
  working. If a codec ever fails, it emits a clear error message including a
  transcode hint. See
  [Limitations and Error Handling](#9-limitations-and-error-handling).
- **No GPU driver, no internet, no admin rights.** Everything runs locally and
  on the CPU.

---

## 3. Usage

```bash
python SharpFrame.py <video> [options]
```

Standard case, recommended:

```bash
python SharpFrame.py "C:\Videos\vacation.mp4"
```

This creates `C:\Videos\vacation_sharp\` containing the JPEGs, a cache file,
and a report.

More examples:

```bash
python SharpFrame.py vacation.mp4 --window 0.2 --max 500
python SharpFrame.py vacation.mp4 --floor 250
python SharpFrame.py vacation.mp4 --floor-pct 30
python SharpFrame.py vacation.mp4 --stride 3
python SharpFrame.py vacation.mp4 --scan-only
python SharpFrame.py vacation.mp4 --out D:\Result\set1
```

---

## 4. How It Works

Image sharpness is measured via the **variance of the Laplacian operator**. The
Laplacian filter is a high-pass filter that detects edges.

- **Sharp image** means hard edges and high contrast at transitions, which
  yields **high variance**.
- **Blurry image** means soft, washed-out transitions, which yields **low
  variance**.

In code: grayscale → `cv2.Laplacian(gray, CV_64F).var()`.

> Note: keyframes, or I-frames, tell you nothing about photographic sharpness.
> That is why the sharpness score is computed for *every* evaluated frame,
> regardless of frame type.

### The Two-Pass Pipeline

#### Pass 1 Scan

- Decode every frame at native resolution and compute its sharpness score.
- Keep only the values: index, timestamp, and sharpness. This is easy on RAM,
  even for many frames.
- Store the result in the cache `<stem>_sharpness.json`, including statistics:
  min, p10, p25, p50, p75, p90, and max.

#### Selection

1. **Floor, or quality gate:** all frames below a threshold are discarded.
   Default is the **40th percentile** of sharpness *for this video*. This
   adapts automatically: soft video means a lower floor, and sharp video means
   a higher floor.
2. **Temporal non-maximum suppression, or dedup:** the remaining frames are
   sorted by sharpness descending. A frame is kept only if no already-kept
   frame lies within ±`window` of it. This yields exactly one image, the
   sharpest, per hold or movement burst.
3. **Cap:** export at most `--max` images. The default is `300`.

#### Pass 2 Export

- Decode again, but write only the selected frames as JPEGs.
- Use quality 95, native resolution, and BGR-correct output.

### Cache and Re-Tuning

A one-time scan is cached per video as `<stem>_sharpness.json`. If you later
change only `--floor`, `--window`, or `--max`, **Pass 1 is skipped**, saving
time. The cache is bound to the video path **and** `--stride`; any other value
triggers an automatic rescan.

---

## 5. Parameters

| Option               | Default                     | Meaning                                   |
| -------------------- | --------------------------- | ----------------------------------------- |
| `video` *(required)* | -                           | Path to the video file.                   |
| `--out`              | `<videodir>/<stem>_sharp`   | Output folder.                            |
| `--window`           | `0.13`                      | Dedup window in **seconds**.              |
| `--floor`            | *auto*                      | Absolute sharpness floor.                 |
| `--floor-pct`        | `40`                        | Auto-floor as a percentile, from 0-100.   |
| `--max`              | `300`                       | Upper bound on exported images.           |
| `--stride`           | `1`                         | Analyze only every Nth frame.             |
| `--quality`          | `95`                        | JPEG quality, from 1-100.                 |
| `--scan-only`        | *off*                       | Run Pass 1 only, with no export.          |

Additional notes:

- A larger `--window` is stricter and produces fewer images.
- A smaller `--window` produces more images.
- `--floor` overrides `--floor-pct`.
- Sharpness values appear in filenames as `_s…` and in the report.
- `--stride > 1` speeds up long videos.

Typical result adjustments:

- **Too many duplicates or too many soft images:** increase `--window` or set
  an absolute `--floor`.
- **Too few images, want more:** use a smaller `--window`, set `--floor 0`, or
  raise `--max`.
- **Only the absolutely sharpest:** set `--floor` high. Use the report values
  as a guide, for example above p90.

---

## 6. Handling Different Video Properties

### Resolution and Orientation

- Works at **any resolution**, such as 720p, 1080p, 4K, or 8K, and **any
  orientation**, such as portrait or landscape. The script reads the decoded
  frame directly and writes it at **native pixel dimensions**.
- **Rotation** from phone metadata is applied automatically by the FFmpeg inside
  OpenCV, so images come out upright. For example, a 4K sensor clip encoded as
  3840×2160 with 90° rotation is exported as an upright 2160×3840 image.

### Framerate

The dedup window is specified in **seconds** and converted to frames using the
actual fps: `round(window · fps)`. That is why `--window` behaves consistently
across 24, 30, 60, and 120 fps.

### Video Length and Runtime

The **double full decode**, Pass 1 plus Pass 2, scales linearly with length.

- **Short videos, up to 1-2 minutes:** no problem, usually seconds to a few
  minutes.
- **Medium videos, up to about 10 minutes:** noticeable. Consider
  `--stride 2-3`.
- **Very long videos, over 10 minutes or hours:** set `--stride` or split the
  video into segments beforehand.

> Note: Pass 2 still fully decodes the video because HEVC seeking via OpenCV is
> unreliable. For multi-hour clips, consider breaking them into segments.

### Codec

- **H.264/H.265:** work fine. HEVC was successfully tested here.
- **AV1 or exotic codecs:** may fail depending on your OpenCV build. In that
  case, the tool aborts with a clear message and a transcode hint. See
  [Limitations and Error Handling](#9-limitations-and-error-handling).

### Variable Frame Rate

Some phones produce variable frame rate, or VFR, video. The *timestamps* in the
filenames may drift slightly, but selection runs frame-index-based and stays
correct.

### Disk Space

Expect about **1-2 MB** per 4K JPEG at q95, and up to about 5 MB for highly
detailed subjects. Plan roughly **0.5-1.5 GB** for 300 images.

---

## 7. Output Files

Each run produces the following in `<out>/`:

| File                                  | Contents                         |
| ------------------------------------- | -------------------------------- |
| `frame_<idx>_t<sec>_s<sharpness>.jpg` | Exported images.                 |
| `<stem>_sharpness.json`               | Cache with sharpness statistics. |
| `report.txt`                          | Statistics, settings, file list. |

Filename fields:

- `idx` is the frame index.
- `t` is time in seconds.
- `s` is the sharpness value.

Filenames are sortable and self-explanatory, for example:

```text
frame_000913_t030.390_s205.jpg
```

---

## 8. Verifying the Result

1. **Read the report:** `report.txt` shows the sharpness statistics, the
   applied floor and window, and the number of saved images.
2. **Check the count:** how many JPEGs are in the folder? Does it match the
   report?
3. **Check the resolution, which must be native:**

   ```bash
   python -c "import cv2,glob; fs=sorted(glob.glob('vacation_sharp/*.jpg')); print(cv2.imread(fs[0]).shape)"
   ```

4. **Check the time distribution:** the `t…` values in the filenames should
   spread fairly evenly across the video duration, with no large cluster in one
   spot. If there is a large cluster, increase `--window`.
5. **Visual spot check:** open a few of the highest `_s…` values. They should
   be genuinely sharp and distinct.

---

## 9. Limitations and Error Handling

- **Non-video files**, such as `.txt` files, are detected during pre-flight via
  magic bytes and rejected instead of producing garbage data.
- **Unsupported codec or corrupt file:** the tool aborts with an informative
  message and suggests transcoding the video:

  ```bash
  ffmpeg -i "input.mp4" -c:v libx264 -crf 18 "input_h264.mp4"
  ```

  Then use the converted file.
- **Very long videos:** see
  [Handling Different Video Properties](#6-handling-different-video-properties)
  for notes about double decoding, `--stride`, and splitting videos.
- **The sharpness metric is a heuristic:** Laplacian variance captures focus
  and motion blur together. In extreme edge cases, such as lots of texture
  producing high variance despite mediocre focus, the metric can diverge from
  human perception. In that case, manually readjust `--floor`.

[project-logo]: logo.webp
[python-badge]: https://img.shields.io/badge/python-3.8+-blue.svg
[python]: https://www.python.org/
[license-badge]: https://img.shields.io/badge/License-MPL--2.0-green
[license]: https://www.mozilla.org/en-US/MPL/2.0/
[dependencies-badge]: https://img.shields.io/badge/dependencies-opencv%20%7C%20numpy-lightgrey.svg
[requirements]: #2-requirements
