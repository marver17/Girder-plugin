"""
BIDS scope detection and NIfTI item discovery.

When the user selects a resource in the file browser, this module determines
the pipeline execution scope:

  - "item"    → single NIfTI file selected
  - "session" → a BIDS session folder (name starts with "ses-"); pipelines run
                through the dedicated /session REST endpoints
  - "subject" → a BIDS subject folder (name starts with "sub-")
  - "dataset" → a BIDS dataset root (contains dataset_description.json or sub-* folders)

For subject/dataset scopes, all NIfTI items within the folder tree are collected
to build the batch job list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from diadema.core.girder_client import DiademaGirderClient


async def detect_scope(
    gc: "DiademaGirderClient",
    *,
    item_id: str | None = None,
    folder_id: str | None = None,
    resource_type: str,
    folder: dict | None = None,
) -> tuple[str, list[str], str]:
    """
    Detect pipeline scope for the selected resource.

    Returns:
        (scope, target_item_ids, scope_label)
        - scope: "item" | "session" | "subject" | "dataset"
        - target_item_ids: item _id strings to process ("session" → [folder_id])
        - scope_label: human-readable string for the UI (e.g. "sub-001 (4 files)")
    """
    if resource_type == "item" and item_id:
        return "item", [item_id], "Single item"

    if resource_type == "folder" and folder_id:
        folder_name = (folder or {}).get("name", "")

        # Session folder: handled by the dedicated /session endpoints
        if folder_name.startswith("ses-"):
            items = await _collect_nifti_items_recursive(gc, folder_id)
            label = f"{folder_name} ({len(items)} files)"
            return "session", [folder_id], label

        # Subject folder: name starts with "sub-"
        if folder_name.startswith("sub-"):
            items = await _collect_nifti_items(gc, folder_id)
            label = f"{folder_name} ({len(items)} files)"
            return "subject", [i["_id"] for i in items], label

        # Check if it's a BIDS dataset root
        if await _is_bids_root(gc, folder_id):
            items = await _collect_nifti_items_recursive(gc, folder_id)
            label = f"Dataset ({len(items)} files)"
            return "dataset", [i["_id"] for i in items], label

        # Generic folder — treat as dataset scope if it has NIfTI files
        items = await _collect_nifti_items_recursive(gc, folder_id)
        if items:
            label = f"{folder_name} ({len(items)} files)"
            return "dataset", [i["_id"] for i in items], label

    return "item", [], "No NIfTI items"


async def _collect_nifti_items(gc: "DiademaGirderClient", folder_id: str) -> list[dict]:
    """Collect NIfTI items directly inside a folder (non-recursive)."""
    try:
        items = await gc.aget("item", parameters={"folderId": folder_id, "limit": 500})
        return [i for i in items if _is_nifti_item(i)]
    except Exception as e:
        print(f"[bids_explorer] Error collecting items from folder {folder_id}: {e}")
        return []


async def _collect_nifti_items_recursive(
    gc: "DiademaGirderClient", folder_id: str, _depth: int = 0
) -> list[dict]:
    """Recursively collect NIfTI items from a folder tree (max depth 5)."""
    if _depth > 5:
        return []

    items = await _collect_nifti_items(gc, folder_id)

    # Recurse into subfolders
    try:
        subfolders = await gc.aget(
            "folder",
            parameters={"parentId": folder_id, "parentType": "folder", "limit": 200},
        )
        for subfolder in subfolders:
            items.extend(
                await _collect_nifti_items_recursive(gc, subfolder["_id"], _depth + 1)
            )
    except Exception as e:
        print(f"[bids_explorer] Error listing subfolders of {folder_id}: {e}")

    return items


def _is_nifti_item(item: dict) -> bool:
    """Return True if the item is a parsed NIfTI file."""
    return (
        item.get("nifti") is not None
        or item.get("name", "").endswith((".nii", ".nii.gz"))
    )


async def _is_bids_root(gc: "DiademaGirderClient", folder_id: str) -> bool:
    """
    Heuristic: a folder is a BIDS root if it contains dataset_description.json
    or has at least one direct subfolder starting with "sub-".
    """
    try:
        # Check for dataset_description.json
        items = await gc.aget(
            "item", parameters={"folderId": folder_id, "name": "dataset_description.json"}
        )
        if items:
            return True

        # Check for sub-* subfolders
        subfolders = await gc.aget(
            "folder",
            parameters={"parentId": folder_id, "parentType": "folder", "limit": 50},
        )
        return any(f["name"].startswith("sub-") for f in subfolders)
    except Exception:
        return False
