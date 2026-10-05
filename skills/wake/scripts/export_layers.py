#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = ["pillow", "numpy"]
# ///
"""Export the parts already taken out of the picture as a layer pack: PNG layers + layers.json.

  export_layers.py <srcDir> --out <dir> [--no-crop] [files...]

Reads <srcDir>/assets/ (what segment.py, inpaint.py and depth.py left there) and writes:
  <dir>/layers/NN-name.png    one file per part, bottom layer first
  <dir>/layers.json           canvas size, and for every layer: file, kind, x, y, w, h, z (stacking order), visible,
                              depth (0 far .. 1 near, median under the cut-out; null when there is no depth map)
Import into After Effects / Figma / a game engine, or read layers.json to place them yourself.

Kinds (guessed the same way sheet.py --parts does):
  plate    RGB image, not the source (inpaint.py output)  -> bottom of the stack
  cutout   RGBA with transparency (segment.py --cutout)   -> above the plate, far to near by depth
  mask     8-bit grey, not depth (segment.py --out)       -> hidden, on top
  depth    16-bit / grey file named like *depth*           -> hidden, on top (copied as it is)
  source   assets/source.*                                -> reference only, hidden, listed first (z = 0)

  files      export only these parts (paths, or names inside assets/); the source is always listed
  --no-crop  keep every cut-out at full canvas size (x = y = 0) instead of cropping it to its visible bounding box

Text is lifted by colour key plus inpainting, so it is a picture layer, not an editable text layer.
"""
import argparse, glob, json, os, shutil, sys
import numpy as np
from PIL import Image

IMG = (".png", ".jpg", ".jpeg", ".webp")
ORDER = {"source": 0, "plate": 1, "cutout": 2, "mask": 3, "depth": 4}


def kind_of(path, im):
    name = os.path.basename(path).lower()
    if name.startswith("source."): return "source"
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info): return "cutout"
    if "depth" in name: return "depth"
    if im.mode in ("L", "1"): return "mask"
    if im.mode in ("I", "I;16"): return "depth"
    return "plate"


def median_depth(alpha, depth):
    """Median of the depth map (0 far .. 1 near) under the opaque part of a cut-out."""
    d = depth.convert("I") if depth.mode not in ("I", "I;16", "L") else depth
    d = np.asarray(d.resize(alpha.size), np.float64)
    lo, hi = d.min(), d.max()
    on = np.asarray(alpha) > 127
    if not on.any() or hi <= lo: return None
    return round(float((np.median(d[on]) - lo) / (hi - lo)), 4)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("files", nargs="*")
    ap.add_argument("--out", required=True); ap.add_argument("--no-crop", action="store_true")
    a = ap.parse_intermixed_args()

    assets = os.path.join(a.src, "assets")
    if a.files:
        paths = [f if os.path.isfile(f) else os.path.join(assets, f) for f in a.files]
        for p in paths:
            if not os.path.isfile(p): sys.exit(f"not found: {p}")
    else:
        paths = [f for f in sorted(glob.glob(os.path.join(assets, "*"))) if f.lower().endswith(IMG)]
    srcs = sorted(glob.glob(os.path.join(assets, "source.*")))
    if srcs and srcs[0] not in paths: paths.insert(0, srcs[0])
    if not paths: sys.exit(f"no parts in {assets}/ yet (cut-outs, masks, plates, depth)")

    parts = []
    for p in paths:
        im = Image.open(p); parts.append((kind_of(p, im), p, im))
    canvas = next((im.size for k, _, im in parts if k == "source"), parts[0][2].size)
    depth = next((im for k, _, im in parts if k == "depth"), None)

    parts.sort(key=lambda t: (ORDER[t[0]], t[1]))
    # cut-outs: far to near, so the nearest ends up on top
    keyed = {id(t): (median_depth(t[2].convert("RGBA").getchannel("A"), depth) if t[0] == "cutout" and depth else None) for t in parts}
    parts.sort(key=lambda t: (ORDER[t[0]], keyed[id(t)] if keyed[id(t)] is not None else 0, t[1]))

    out_dir = os.path.join(a.out, "layers"); os.makedirs(out_dir, exist_ok=True)
    layers = []
    for z, (kind, path, im) in enumerate(parts):
        stem = os.path.splitext(os.path.basename(path))[0]
        fn = f"{z:02d}-{stem}.png"
        x = y = 0; w, h = im.size
        if kind == "cutout":
            rgba = im.convert("RGBA")
            box = None if a.no_crop else rgba.getchannel("A").point(lambda v: 255 if v > 0 else 0).getbbox()
            if box: rgba = rgba.crop(box); x, y = box[0], box[1]; w, h = rgba.size
            rgba.save(os.path.join(out_dir, fn))
        elif kind in ("depth", "mask"):
            shutil.copyfile(path, os.path.join(out_dir, fn)) if path.lower().endswith(".png") else im.save(os.path.join(out_dir, fn))
        else:
            im.convert("RGB").save(os.path.join(out_dir, fn))
        layers.append({"file": f"layers/{fn}", "name": stem, "kind": kind, "x": x, "y": y, "w": w, "h": h, "z": z,
                       "visible": kind in ("plate", "cutout"), "depth": keyed[id(parts[z])]})
    meta = {"canvas": {"w": canvas[0], "h": canvas[1]}, "layers": layers}
    with open(os.path.join(a.out, "layers.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    for l in layers:
        print(f"{l['z']:>2}  {l['kind']:<6}  {l['x']},{l['y']} {l['w']}x{l['h']}  {l['file']}", file=sys.stderr)
    print(os.path.join(a.out, "layers.json"))


main()
