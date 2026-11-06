"""Display-only Web Mercator reprojection of an integrity-checked native preview.

Runs in the optional raster worker. Numerical indices remain on the original
grid; nearest-neighbour RGBA reprojection never creates new measured support.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from typing import Any


def reproject_preview(png: bytes, grid: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    from PIL import Image
    from affine import Affine
    from rasterio.transform import array_bounds
    from rasterio.warp import calculate_default_transform, reproject, transform_bounds, Resampling

    width, height = grid["width"], grid["height"]
    if type(width) is not int or type(height) is not int or not 0 < width <= 4096 or not 0 < height <= 4096 or width * height > 4_000_000:
        raise ValueError("Preview grid exceeds display limits")
    image = Image.open(io.BytesIO(png))
    if image.size != (width, height) or image.format != "PNG":
        raise ValueError("Preview dimensions do not match the native grid")
    rgba = np.asarray(image.convert("RGBA"))
    transform = Affine(*grid["transform"])
    bounds = array_bounds(height, width, transform)
    target, target_width, target_height = calculate_default_transform(grid["crs"], "EPSG:3857", width, height, *bounds)
    if not 0 < target_width <= 4096 or not 0 < target_height <= 4096 or target_width * target_height > 4_000_000:
        raise ValueError("Projected preview exceeds display limits")
    result = np.zeros((4, target_height, target_width), dtype=np.uint8)
    for band in range(4):
        reproject(rgba[:, :, band], result[band], src_transform=transform, src_crs=grid["crs"],
            dst_transform=target, dst_crs="EPSG:3857", resampling=Resampling.nearest, dst_nodata=0)
    output = io.BytesIO()
    Image.fromarray(result.transpose(1, 2, 0), "RGBA").save(output, format="PNG")
    projected_bounds = array_bounds(target_height, target_width, target)
    west, south, east, north = transform_bounds("EPSG:3857", "EPSG:4326", *projected_bounds)
    return {"png_base64": base64.b64encode(output.getvalue()).decode(), "bounds": [[south, west], [north, east]],
        "display_crs": "EPSG:3857", "display_resampling": "nearest", "width": target_width, "height": target_height,
        "source_preview_sha256": hashlib.sha256(png).hexdigest(), "role": "display_only",
        "boundary": "Display reprojection only. Transparency retains native excluded or undefined support. Read numerical values from the original processing receipt."}


def main() -> None:
    from agronomy_agent.imagery_store import ImageryStore
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--chip-hash", required=True)
    args = parser.parse_args()
    store = ImageryStore(args.cache_root, read_only=True)
    receipt = store.get_by_chip_hash(args.chip_hash)
    image = store.preview_bytes(args.chip_hash)
    if not receipt or image is None:
        raise ValueError("Verified preview not found")
    print(json.dumps({**reproject_preview(image, receipt["grid"]), "chip_hash": args.chip_hash}))


if __name__ == "__main__":
    main()
