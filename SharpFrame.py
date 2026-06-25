#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract the sharpest frames from a video as JPGs (CLI tool).
Usage, pipeline, and parameters are documented in README.md.
"""

import os
import sys
import json
import argparse

import numpy as np
import cv2

FLOOR_PCT_DEFAULT = 40
WINDOW_SEC_DEFAULT = 0.13
MAX_KEEP_DEFAULT = 300
STRIDE_DEFAULT = 1
JPG_Q_DEFAULT = 95


# ----------------------------------------------------------------------------- errors
def die(msg):
    sys.stderr.write("\n" + msg + "\n")
    sys.exit(1)


def validate_video(path):
    if not os.path.isfile(path):
        die(
            "FEHLER: Videodatei nicht gefunden.\n"
            f"  Pfad: {path}\n"
            "  Bitte den vollstaendigen, korrekten Dateipfad angeben."
        )
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError as e:
        die(f"FEHLER: Datei nicht lesbar: {path}\n  {e}")
    sigs = {
        "MP4/MOV/M4V/HEIF": lambda h: h[4:8] == b"ftyp",
        "AVI":              lambda h: h[0:4] == b"RIFF",
        "MKV/WebM":         lambda h: h[0:4] == b"\x1a\x45\xdf\xa3",
        "FLV":              lambda h: h[0:3] == b"FLV",
        "MPEG-TS":          lambda h: len(h) > 0 and h[0] == 0x47,
        "MPEG-PS":          lambda h: h[0:3] == b"\x00\x00\x01",
        "WMV/ASF":          lambda h: h[0:4] == b"\x30\x26\xb2\x75",
    }
    if not any(f(head) for f in sigs.values()):
        die(
            "FEHLER: Datei scheint kein unterstuetztes Video zu sein.\n"
            f"  Pfad: {path}\n"
            f"  Erkannte Anfangsbytes: {head[:8]!r}\n"
            "Unterstuetzt: MP4/MOV/M4V, AVI, MKV/WebM, FLV, MPEG-TS/PS, WMV/ASF.\n"
            "Falls es doch ein Video ist, evtl. ein ungewoehnlicher Container."
        )


def open_video(path):
    """Opens the video (existence/format already checked by validate_video())."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        die(
            "FEHLER: Video konnte von OpenCV nicht geoeffnet/decodiert werden.\n"
            f"  Pfad: {path}\n"
            "Moegliche Ursachen:\n"
            "  - Codec (z.B. AV1/H.265) wird von diesem OpenCV-Build nicht unterstuetzt\n"
            "  - Datei ist beschaedigt oder keine Videodatei\n"
            "Abhilfe: ffmpeg installieren und in ein kompatibles Format transcodieren, z.B.:\n"
            f'  ffmpeg -i "{path}" -c:v libx264 -crf 18 "convertiert.mp4"\n'
            '  Danach das konvertierte File verwenden.'
        )
    # some codecs report isOpened() but never return a frame
    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        die(
            "FEHLER: Video wird geoeffnet, aber kein Frame dekodiert (vermutlich\n"
            "nicht unterstuetzter Codec in diesem OpenCV-Build).\n"
            f"  Pfad: {path}\n"
            "Abhilfe: mit ffmpeg transcodieren (s.o.) oder OpenCV mit weiteren Codecs bauen."
        )
    # seek back to the first frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return cap


# ----------------------------------------------------------------------------- frame iterator
def frame_iter(path, stride=1):
    """Yields (idx, frame_bgr). stride>1 uses grab() to cheaply skip frames."""
    cap = open_video(path)
    idx = 0
    while True:
        if stride <= 1:
            ok, frame = cap.read()
        else:
            ok = True
            for _ in range(stride - 1):
                if not cap.grab():
                    ok = False
                    break
            frame = None
            if ok:
                ok, frame = cap.read()
        if not ok or frame is None:
            break
        yield idx, frame
        idx += stride
    cap.release()


def sharpness_of(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# ----------------------------------------------------------------------------- Pass 1
def pass1_scan(args, cache_path):
    print(f"[Pass 1] Scanne {args.video}  (stride={args.stride}) ...")
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_est = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()

    rows = []
    for idx, frame in frame_iter(args.video, args.stride):
        s = sharpness_of(frame)
        rows.append({"idx": idx, "t": round(idx / fps, 3), "sharpness": s})
        if idx % (100 * args.stride) < args.stride:
            print(f"  Frame {idx:6d} / ~{int(n_est)}  (sharp={s:9.1f})")

    if not rows:
        die("FEHLER: Es konnten keine Frames analysiert werden (siehe Meldung oben).")

    vals = np.array([r["sharpness"] for r in rows], dtype=float)
    stats = {
        "frames": len(rows), "fps": fps, "stride": args.stride,
        "video": os.path.abspath(args.video),
        "min": float(vals.min()),
        "p10": float(np.percentile(vals, 10)),
        "p25": float(np.percentile(vals, 25)),
        "p50": float(np.percentile(vals, 50)),
        "p75": float(np.percentile(vals, 75)),
        "p90": float(np.percentile(vals, 90)),
        "max": float(vals.max()),
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"stats": stats, "frames": rows}, f)
    print(f"[Pass 1] {len(rows)} Frames, Schaerfe min={stats['min']:.1f} "
          f"p50={stats['p50']:.1f} p90={stats['p90']:.1f} max={stats['max']:.1f}")
    print(f"[Pass 1] -> {cache_path}")
    return stats, rows


def load_cache(cache_path, args):
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    st = data.get("stats", {})
    if (st.get("video") == os.path.abspath(args.video)
            and st.get("stride") == args.stride):
        return data["stats"], data["frames"]
    print("[Cache] Vorhandener Scan passt nicht zu Video/stride -> neu scannen.")
    return None


# ----------------------------------------------------------------------------- Selection
def select(rows, stats, args):
    vals = np.array([r["sharpness"] for r in rows], dtype=float)
    if args.floor is not None:
        floor = float(args.floor)
        floor_src = f"manuell (--floor)"
    else:
        floor = float(np.percentile(vals, args.floor_pct))
        floor_src = f"auto p{args.floor_pct}"

    window_frames = max(1, int(round(args.window * stats["fps"])))

    cand = sorted((r for r in rows if r["sharpness"] >= floor),
                  key=lambda r: r["sharpness"], reverse=True)

    accepted = []
    for r in cand:
        if any(abs(r["idx"] - a["idx"]) <= window_frames for a in accepted):
            continue
        accepted.append(r)
        if len(accepted) >= args.max:
            break

    accepted.sort(key=lambda r: r["idx"])
    print(f"[Auswahl] FLOOR={floor:.1f} ({floor_src})  "
          f"WINDOW=±{window_frames} Frames (~{args.window:.3f}s)  "
          f"nach Floor={len(cand)}  ->  ausgewaehlt={len(accepted)} (cap {args.max})")
    return floor, window_frames, accepted


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description="Scharfe Bilder aus einem Video als JPG extrahieren.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("video", help="Pfad zur Videodatei (z.B. clip.mp4)")
    ap.add_argument("--out", default=None,
                    help="Output-Ordner (default: <videodir>/<stem>_sharp)")
    ap.add_argument("--window", type=float, default=WINDOW_SEC_DEFAULT,
                    help="Dedup-Fenster in Sekunden (moderat ~0.13)")
    ap.add_argument("--floor", type=float, default=None,
                    help="absoluter Schaerfe-FLOOR (sonst auto-Perzentil)")
    ap.add_argument("--floor-pct", type=int, default=FLOOR_PCT_DEFAULT,
                    help="auto-FLOOR als Perzentil (0-100)")
    ap.add_argument("--max", type=int, default=MAX_KEEP_DEFAULT,
                    help="maximale Anzahl Bilder")
    ap.add_argument("--stride", type=int, default=STRIDE_DEFAULT,
                    help="nur jedes N. Frame analysieren (>1 fuer lange Videos)")
    ap.add_argument("--quality", type=int, default=JPG_Q_DEFAULT,
                    help="JPEG-Qualitaet (1-100)")
    ap.add_argument("--scan-only", action="store_true",
                    help="nur Pass 1 ausfuehren (Statistik)")
    args = ap.parse_args()

    if not (0 <= args.floor_pct <= 100):
        die("FEHLER: --floor-pct muss zwischen 0 und 100 liegen.")
    if not (1 <= args.quality <= 100):
        die("FEHLER: --quality muss zwischen 1 und 100 liegen.")
    if args.stride < 1:
        die("FEHLER: --stride muss >= 1 sein.")

    validate_video(args.video)

    stem = os.path.splitext(os.path.basename(args.video))[0]
    vdir = os.path.dirname(os.path.abspath(args.video))
    out_dir = args.out or os.path.join(vdir, f"{stem}_sharp")
    os.makedirs(out_dir, exist_ok=True)
    cache_path = os.path.join(out_dir, f"{stem}_sharpness.json")
    report_path = os.path.join(out_dir, "report.txt")

    cached = None if args.scan_only else load_cache(cache_path, args)
    if cached:
        stats, rows = cached
        print(f"[Cache] Verwende vorhandenen Scan: {cache_path}")
    else:
        stats, rows = pass1_scan(args, cache_path)
        if args.scan_only:
            print("[--scan-only] Nur Scan ausgefuehrt. Beende.")
            return

    floor, window_frames, accepted = select(rows, stats, args)
    sel = {a["idx"]: a for a in accepted}

    print(f"[Pass 2] Exportiere {len(accepted)} JPGs (q{args.quality}) nach {out_dir} ...")
    out_records = []
    for idx, frame in frame_iter(args.video, args.stride):
        a = sel.get(idx)
        if a is None:
            continue
        name = f"frame_{idx:06d}_t{a['t']:07.3f}_s{int(a['sharpness'])}.jpg"
        path = os.path.join(out_dir, name)
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
        out_records.append({"file": name, "idx": idx, "t": a["t"],
                            "sharpness": a["sharpness"]})
        if len(out_records) % 25 == 0:
            print(f"  geschrieben {len(out_records)}/{len(accepted)}")

    write_report(report_path, stats, floor, window_frames, args, out_records)
    print(f"\nFERTIG: {len(out_records)} Bilder in {out_dir}")
    print(f"Report: {report_path}")
    if len(out_records) < args.max:
        print(f"Hinweis: <{args.max} (Qualitaet vor Menge; ggf. --window kleiner "
              f"oder --floor 0 fuer mehr Bilder).")


def write_report(report_path, stats, floor, window_frames, args, out_records):
    lines = []
    lines.append("=== Schaerfe-Extraktion ===")
    lines.append(f"Video:   {stats.get('video', args.video)}")
    lines.append(f"Frames:  {stats['frames']} (stride {stats.get('stride',1)})  "
                 f"| fps: {stats['fps']:.3f}  | JPEG-Qualitaet: {args.quality}")
    lines.append("")
    lines.append("Schaerfe-Statistik (Varianz Laplace):")
    for k in ("min", "p10", "p25", "p50", "p75", "p90", "max"):
        lines.append(f"  {k:>4} = {stats[k]:9.1f}")
    lines.append("")
    src = f"manuell --floor" if args.floor is not None else f"auto p{args.floor_pct}"
    lines.append(f"FLOOR (Qualitaetsgate): {floor:.1f}  ({src})")
    lines.append(f"NMS-Fenster (Dedup):    ±{window_frames} Frames (~{args.window:.3f}s)")
    lines.append(f"Cap / Ziel:            {args.max}")
    lines.append(f"Gespeicherte Bilder:   {len(out_records)}")
    lines.append("")
    lines.append("Dateien (Index, Zeit s, Schaerfe):")
    for r in sorted(out_records, key=lambda x: x["idx"]):
        lines.append(f"  {r['file']}   idx={r['idx']:6d}  t={r['t']:7.3f}s  sharp={r['sharpness']:.1f}")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
