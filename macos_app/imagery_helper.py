"""Entry point for the desktop's isolated optical imagery worker."""
from __future__ import annotations

import json
import sys


def main() -> None:
    if sys.argv[1:] == ["--health"]:
        import httpx
        import numpy
        import PIL
        import pyproj
        import rasterio
        import scipy.ndimage
        import shapely

        # Verify that the two installed PROJ consumers can actually use data.
        pyproj.Transformer.from_crs(4326, 32613, always_xy=True).transform(-105, 40, errcheck=True)
        from rasterio.warp import transform
        transform("EPSG:4326", "EPSG:32613", [-105], [40])
        print(json.dumps({
            "numpy": numpy.__version__, "rasterio": rasterio.__version__,
            "pyproj": pyproj.__version__, "shapely": shapely.__version__,
            "Pillow": PIL.__version__, "httpx": httpx.__version__, "scipy": scipy.__version__,
        }))
        return

    if sys.argv[1:2] == ["--overlay"]:
        from agronomy_agent.imagery_overlay import main as overlay
        del sys.argv[1]
        overlay()
        return

    if sys.argv[1:2] == ["--compare"]:
        from agronomy_agent.imagery_comparison import main as compare
        del sys.argv[1]
        compare()
        return

    import truststore
    truststore.inject_into_ssl()
    from agronomy_agent.imagery_worker import main as analyze
    analyze()


if __name__ == "__main__":
    main()
