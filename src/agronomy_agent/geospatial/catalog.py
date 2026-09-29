"""One public-source inventory for imagery and terrain discovery.

Access, processing support and rights are independent. Catalogue presence is
not runtime admission, installed coverage, pixel access or training permission.
"""
from __future__ import annotations
import copy
from typing import Any

SCHEMA_VERSION = "geospatial.source_catalog.v1"

_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "sentinel2-c1-earth-search",
        "name": "Sentinel-2 Collection 1 L2A COGs (Earth Search)",
        "source": "ESA/Copernicus Sentinel-2; Element 84 Earth Search COG hosting",
        "collection": "sentinel-2-c1-l2a",
        "catalog_url": "https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a",
        "access": "anonymous_metadata_and_cog",
        "account_required": False,
        "payment_required": False,
        "rights": "Copernicus Sentinel Data Terms and Conditions; attribution required. STAC collection declares license=proprietary; inspect source terms before redistribution.",
        "rights_url": "https://sentinels.copernicus.eu/web/sentinel/data-access-and-products/legal-notices",
        "capabilities": ["scene_discovery", "anonymous_cog_range_read"],
        "limitations": "Scene cloud cover is scene-wide, not clear field coverage; C1 historical gaps exist. No pixel analysis in this module.",
    },
    {
        "id": "hls-s30-planetary-computer",
        "name": "NASA HLS S30 v2 (Planetary Computer mirror)",
        "source": "NASA LP DAAC HLS S30; Microsoft Planetary Computer mirror",
        "collection": "hls2-s30",
        "catalog_url": "https://planetarycomputer.microsoft.com/api/stac/v1/collections/hls2-s30",
        "access": "anonymous_metadata_public_short_lived_sas_for_cog",
        "account_required": False,
        "payment_required": False,
        "rights": "HLS source data CC BY 4.0 per NASA AWS Registry; Planetary Computer STAC collection declares license=proprietary and links LP DAAC policies. Preserve attribution and verify redistribution terms.",
        "rights_url": "https://lpdaac.usgs.gov/data/data-citation-and-policies/",
        "capabilities": ["scene_discovery", "public_sas_cog_range_read"],
        "limitations": "Public SAS expires; scene metadata is not field coverage or validated reflectance.",
    },
    {
        "id": "hls-l30-planetary-computer",
        "name": "NASA HLS L30 v2 (Planetary Computer mirror)",
        "source": "NASA LP DAAC HLS L30; Microsoft Planetary Computer mirror",
        "collection": "hls2-l30",
        "catalog_url": "https://planetarycomputer.microsoft.com/api/stac/v1/collections/hls2-l30",
        "access": "anonymous_metadata_public_short_lived_sas_for_cog",
        "account_required": False,
        "payment_required": False,
        "rights": "HLS source data CC BY 4.0 per NASA AWS Registry; Planetary Computer STAC collection declares license=proprietary and links LP DAAC policies. Preserve attribution and verify redistribution terms.",
        "rights_url": "https://lpdaac.usgs.gov/data/data-citation-and-policies/",
        "capabilities": ["scene_discovery", "public_sas_cog_range_read"],
        "limitations": "Public SAS expires; scene metadata is not field coverage or validated reflectance.",
    },
    {
        "id": "hls-earth-engine",
        "name": "NASA HLS v2 (Google Earth Engine)",
        "source": "NASA HLS via Google Earth Engine",
        "collection": None,
        "catalog_url": "https://developers.google.com/earth-engine/datasets/tags/hls",
        "access": "account_and_project_required_not_configured",
        "account_required": True,
        "project_required": True,
        "payment_required": "depends_on_Earth_Engine_eligibility_and_quota",
        "rights": "NASA HLS source terms and Google Earth Engine platform terms apply separately.",
        "rights_url": "https://developers.google.com/earth-engine/guides/access",
        "capabilities": [],
        "limitations": "Optional provider declaration only; no Earth Engine credentials are read or configured.",
    },
)


_NRCAN = "https://datacube.services.geo.ca/stac/api/search"
_TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
_EARTH = "https://earth-search.aws.element84.com/v1/search"
_PC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"


def imagery_provider_catalog() -> list[dict[str, Any]]:
    return copy.deepcopy(list(_PROVIDERS))


def _terrain(source_id: str, name: str, collection: str | None, resolution: float | None,
             *, endpoint: str = _NRCAN, dataset: str | None = None) -> dict[str, Any]:
    canada = endpoint == _NRCAN
    return {
        "id": source_id, "name": name, "domain": "terrain", "collection": collection,
        "discovery_endpoint": endpoint, "discovery_protocol": "stac" if canada else "tnm",
        "dataset": dataset, "metadata_access": "anonymous", "asset_access": "anonymous_https",
        "api_key_required": False, "account_required": False, "payment_required": False,
        "preferred_asset": "dtm" if canada else "downloadURL", "surface_type": "DTM",
        "resolution_m": resolution, "vertical_units": "m",
        "vertical_datum": "CGVD2013 (verify asset)" if canada else "asset-specific; verify metadata",
        "jurisdiction": "Canada" if canada else "United States",
        "processing": "operator_local_dem_terrain_screening",
        "rights_url": "https://open.canada.ca/en/open-government-licence-canada" if canada else "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
        "documentation_url": "https://open.canada.ca/data/en/dataset/957782bf-847c-4644-a757-e383c0057995" if canada else "https://www.usgs.gov/3d-elevation-program/about-3dep-products-services",
        "asset_hosts": ["canelevation-dem.s3.ca-central-1.amazonaws.com"] if canada else ["prd-tnm.s3.amazonaws.com", "rockyweb.usgs.gov"],
        "limitations": "Coverage and acquisition age vary. Inspect native header, vertical datum, nodata and provenance; a field buffer does not prove complete upstream catchment. DTM is required; DSM is not substituted. Metadata lookup does not fetch or certify pixels.",
    }


_EXTRA = (
    _terrain("ca-hrdem-mosaic-1m", "Canada HRDEM mosaic · 1 m DTM", "hrdem-mosaic-1m", 1),
    _terrain("ca-hrdem-mosaic-2m", "Canada HRDEM mosaic · 2 m DTM", "hrdem-mosaic-2m", 2),
    _terrain("ca-hrdem-lidar", "Canada HRDEM acquisition projects · DTM", "hrdem-lidar", None),
    _terrain("us-3dep-1m", "USGS 3DEP project DEM · 1 m", None, 1, endpoint=_TNM, dataset="Digital Elevation Model (DEM) 1 meter"),
    _terrain("us-3dep-seamless-1m", "USGS 3DEP seamless DEM · 1 m", None, 1, endpoint=_TNM, dataset="Seamless 1-m DEM (S1M)"),
    {
        "id": "cop-dem-glo-30-earth-search", "name": "Copernicus GLO-30 · surface model",
        "domain": "terrain", "collection": "cop-dem-glo-30", "discovery_endpoint": _EARTH,
        "discovery_protocol": "stac", "metadata_access": "anonymous", "asset_access": "anonymous_https_or_s3",
        "api_key_required": False, "account_required": False, "payment_required": False,
        "surface_type": "DSM", "resolution_m": 30, "vertical_units": "m", "vertical_datum": "EGM2008 (verify asset)",
        "preferred_asset": "data", "jurisdiction": "global", "processing": "discovery_only_not_fine_field_drainage",
        "rights_url": "https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model",
        "documentation_url": "https://element84.com/geospatial/introducing-earth-search-v1-new-datasets-now-available/",
        "asset_hosts": ["copernicus-dem-30m.s3.amazonaws.com", "copernicus-dem-30m.s3.eu-central-1.amazonaws.com"],
        "limitations": "Global 30 m DSM includes vegetation/buildings. Not a substitute for high-resolution bare-earth DTM or field drainage assessment.",
    },
    {
        "id": "naip-earth-search", "name": "US NAIP aerial imagery · catalog only",
        "domain": "imagery", "collection": "naip", "discovery_endpoint": _EARTH,
        "discovery_protocol": "stac", "metadata_access": "anonymous", "asset_access": "requester_pays",
        "api_key_required": False, "account_required": True, "payment_required": True,
        "preferred_asset": "image", "surface_type": None, "resolution_m": None,
        "jurisdiction": "United States", "processing": "discovery_only",
        "rights_url": "https://www.fsa.usda.gov/resources/programs/aerial-photography",
        "documentation_url": "https://element84.com/geospatial/introducing-earth-search-v1-new-datasets-now-available/",
        "asset_hosts": [], "limitations": "Public metadata is keyless; inspected analytical assets declare requester-pays. No account configured and no automatic pixel acquisition. Resolution/year vary by source.",
    },
)


def source_catalog() -> dict[str, Any]:
    sources = []
    for p in imagery_provider_catalog():
        p.update({"domain": "imagery", "metadata_access": "anonymous" if p["capabilities"] else "not_configured",
                  "asset_access": p["access"], "api_key_required": p["account_required"],
                  "discovery_protocol": "stac" if p["collection"] else None,
                  "discovery_endpoint": _EARTH if p["id"] == "sentinel2-c1-earth-search" else _PC if p["collection"] else None,
                  "processing": "hls_spectral_indices" if p["id"].startswith(("hls-s30", "hls-l30")) else "discovery_only",
                  "documentation_url": p["catalog_url"], "surface_type": None})
        sources.append(p)
    sources.extend(copy.deepcopy(list(_EXTRA)))
    return {"schema_version": SCHEMA_VERSION, "sources": sources,
            "boundary": "Discovery, pixel access, processing, rights and scientific validity are separate. No source is automatically admitted to chat or training."}


def source_definition(source_id: str) -> dict[str, Any]:
    for source in source_catalog()["sources"]:
        if source["id"] == source_id:
            return source
    raise ValueError("unknown geospatial source")
