"""
ResultsPanel: display pipeline results stored in item.diadema.{tool}.results.

Result payload shapes (written by the workers, see tasks/*.py):
  - mriqc:      {metrics, modality, mriqc_version, reports_uploaded,
                 derivative_item_ids, ...}
  - freesurfer: {stats, files_uploaded, derivative_item_ids, ...}
  - lstai:      {lesion_count, total_volume_ml, threshold, flair_used,
                 lstai_version, files_uploaded, derivative_item_ids, ...}

Derivative links point to the Girder download endpoint so HTML reports open
inline in a new tab.
"""

from __future__ import annotations

import asyncio

from trame.widgets import html
from trame.widgets import vuetify3 as v3

from diadema.core.girder_client import DiademaGirderClient

# Key MRIQC image-quality metrics worth surfacing in the summary table
MRIQC_KEY_METRICS = [
    "snr", "snr_total", "cnr", "efc", "fber", "cjv", "fwhm_avg", "qi_1", "qi_2",
]


class ResultsPanel:
    def __init__(self, server, gc: DiademaGirderClient):
        self.state = server.state
        self.ctrl = server.controller
        self._gc = gc

        self.state.setdefault("pipeline_results", {})

        server.state.change("current_item")(self._on_item_change)

    # ── Result extraction ──────────────────────────────────────────────────

    def _on_item_change(self, current_item, **_):
        if not current_item:
            self.state.pipeline_results = {}
            return
        asyncio.create_task(self._build_results(current_item))

    async def _build_results(self, item: dict):
        diadema = item.get("diadema") or {}
        out = {}
        for tool_id, info in diadema.items():
            if not isinstance(info, dict) or info.get("status") != "completed":
                continue
            results = info.get("results") or {}
            entry = {
                "timestamp": results.get("timestamp"),
                "links": await self._derivative_links(
                    results.get("derivative_item_ids") or []
                ),
            }
            if tool_id == "mriqc":
                metrics = results.get("metrics") or {}
                entry["metrics"] = [
                    {"name": k, "value": round(metrics[k], 4)}
                    for k in MRIQC_KEY_METRICS
                    if isinstance(metrics.get(k), (int, float))
                ]
                entry["version"] = results.get("mriqc_version")
                entry["modality"] = results.get("modality")
            elif tool_id == "freesurfer":
                stats = results.get("stats") or {}
                entry["metrics"] = [
                    {"name": k, "value": v}
                    for k, v in list(stats.items())[:12]
                    if isinstance(v, (int, float, str))
                ]
            elif tool_id == "lstai":
                entry["metrics"] = [
                    {"name": "Lesion count", "value": results.get("lesion_count")},
                    {"name": "Total volume (ml)", "value": results.get("total_volume_ml")},
                    {"name": "Threshold", "value": results.get("threshold")},
                    {"name": "FLAIR used", "value": results.get("flair_used")},
                ]
                entry["version"] = results.get("lstai_version")
            out[tool_id] = entry

        with self.state:
            self.state.pipeline_results = out

    async def _derivative_links(self, item_ids: list[str]) -> list[dict]:
        links = []
        for iid in item_ids[:20]:
            try:
                doc = await self._gc.aget(f"item/{iid}")
            except Exception:
                continue
            name = doc.get("name", iid)
            links.append({
                "id": iid,
                "name": name,
                "is_nifti": name.endswith((".nii", ".nii.gz")),
            })
        return links

    # ── UI ─────────────────────────────────────────────────────────────────

    def build(self):
        with v3.VCard(
            flat=True,
            classes="ma-2",
            v_if=("Object.keys(pipeline_results).length",),
        ):
            with v3.VCardTitle(classes="d-flex align-center text-subtitle-1"):
                v3.VIcon("mdi-chart-box-outline", classes="mr-2", color="primary")
                html.Span("Results")

            with v3.VExpansionPanels(variant="accordion", multiple=True):
                with v3.VExpansionPanel(
                    v_for="(result, tool) in pipeline_results", key="tool"
                ):
                    with v3.VExpansionPanelTitle():
                        html.Span("{{ tool }}", classes="text-uppercase font-weight-medium mr-2")
                        v3.VChip(
                            "{{ result.timestamp }}",
                            v_if=("result.timestamp",),
                            size="x-small",
                            variant="tonal",
                        )
                    with v3.VExpansionPanelText():
                        # Metrics table
                        with v3.VTable(
                            density="compact",
                            v_if=("result.metrics && result.metrics.length",),
                        ):
                            with html.Tbody():
                                with html.Tr(v_for="m in result.metrics", key="m.name"):
                                    html.Td("{{ m.name }}", classes="text-medium-emphasis")
                                    html.Td("{{ m.value }}")

                        # Derivative file links
                        with v3.VList(
                            density="compact",
                            v_if=("result.links && result.links.length",),
                        ):
                            with v3.VListItem(
                                v_for="link in result.links",
                                key="link.id",
                                href=(
                                    "girder_api_root + '/item/' + link.id +"
                                    " '/download?contentDisposition=inline'",
                                ),
                                target="_blank",
                            ):
                                with html.Template(v_slot_prepend=True):
                                    v3.VIcon(
                                        ("link.is_nifti ? 'mdi-cube-scan' : 'mdi-file-document-outline'",),
                                        size="small",
                                    )
                                v3.VListItemTitle("{{ link.name }}", classes="text-body-2")
