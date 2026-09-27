# Use the field workspace

The workspace puts a question and its selected field together. **Workspace**, **Fields**, and **Data** are the primary views; **Evidence**, **Benchmarks**, **Privacy**, and **About** are under **More**. The interface is a client of the local API. A page that loads does not establish that the model or optional data providers are ready; check [native setup](native-setup.md) and `/api/health` separately.

![Workspace using synthetic example data](../assets/workspace.jpg)

The image uses synthetic records. It contains no personal field data.

## Ask a question

Open **Workspace** and type a general question. A field is optional: the app must not invent a crop, location, soil test, or measurement to make a general question look field-specific. If the local runtime is unavailable, the text remains a device-local draft; sending it later requires a working API. A saved answer can show source cards, tool use, missing inputs, and a trace through **Sources & checks**. These records show what the system did, not that its answer is correct.

Select a field when its known details matter to the question. Field observations and soil tests are user records; map intersections and provider data are separate contextual inputs. If a field is incomplete, leave unknowns blank and ask a bounded question. A model answer should not turn an unknown into a zero, a pass, or a prescription.

## Add and manage a field

1. In **Fields**, select **Add field**. Enter a field name; crop, region, and province are optional. Reusing the region from a previous field is an explicit action, not an automatic assumption.
2. Place a pin, draw a boundary, enter coordinates, or import one from `.geojson`, `.json`, `.zip`, or `.gpkg`. For files with multiple features, choose the intended field. A pin is enough to start; a full boundary can be edited later. The map checks geometry before save.
3. Review the location and any imported provenance note, then save. A polygon-derived acreage is an estimate. A pin does not establish acreage.

**Fields** has **Overview**, **Records & soil tests**, and **Map context**. Overview holds supplied details; Records & soil tests retains observations, measurements, corrections, and linked answer history; Map context shows regional matches with source and uncertainty. Field-event sync and recovery are available with the records. A browser draft is not a synchronized record until the API confirms it.

Deletion is explicit. The field library can remove the selected field record while historical answer records remain retained by the server; review the confirmation carefully. No map class, graph edge, or regional statistic replaces a representative soil sample or field observation.

## Add a private reference or governed source

The **Data** view can inspect a private PDF, plain-text, Markdown, or JSON reference for the current browser session. The inspect route accepts up to 5 MB for PDF and 1 MB for text formats. It reports low-text PDFs as blocked rather than silently applying OCR. Parsed chunks are unverified context and are not retained by that inspection route or made training-eligible. Clear the browser session when that context is no longer needed.

Boundary import is a separate field-geometry path. An imported field file does not become a retrieval source. Attached images and workspace data sources have their own API/storage and job states; availability depends on the configured backend and authority. The current **Data** view presents private references, Canadian knowledge coverage, and adapter diagnostics. Governed repository ingestion is an operator workflow, not a one-click promotion from this view.

To add material to the shared runtime corpus, start from a publisher/source receipt with exact bytes or URL, date, rights, jurisdiction, and hashes. Use the relevant deterministic ingestion/build script, validate row-level lineage, update the runtime policy and active profile only after review, and run corpus/retrieval and leakage gates. See [knowledge and data governance](../knowledge-and-data.md), [source admission](canada-offline-source-admission.md), and [customizing the harness](../developer/customizing-the-harness.md). Evaluation cases and answers never enter retrieval or training.

## Offline, exports, and limits

The model, admitted corpus, graph, calculations, and local history can run without public-provider access once provisioned. Weather, current product metadata, regulations, and other live adapters depend on network/provider/credential availability and should show an unavailable state when blocked. Optional Prairie Detailed Soil Survey layers require the [separate verified pack](offline-data-setup.md); a missing pack is reported as `not_installed`.

Use **Sources & checks** to inspect or download a reviewer report for a saved answer. Exports preserve source and trace boundaries; a receipt verifies application-level linkage, not independent correctness or current regulatory authority. Confirm current labels and regulations and seek qualified local review before high-consequence decisions.

## Guided setup

![Creating a synthetic field with only a name and optional crop](../assets/field-setup.jpg)

This is an actual local browser capture using synthetic demonstration entries. No personal field record is shown.
