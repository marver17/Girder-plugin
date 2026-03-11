"""
Test di base per DIADEMA Pipeline
──────────────────────────────────────────────────────────────────────────────
Usa pytest-girder per creare un server Girder in-process.

Esecuzione:
    pytest diadema_pipeline/plugin_tests/ -v
──────────────────────────────────────────────────────────────────────────────
"""

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_user(admin):
    """Utente admin (fixture fornita da pytest-girder)."""
    return admin


@pytest.fixture
def user(user):
    """Utente normale (fixture fornita da pytest-girder)."""
    return user


# ── Test caricamento plugin ───────────────────────────────────────────────────


def test_plugin_loads(server):
    """Verifica che il plugin diadema_pipeline si carichi e risponda sulla route corretta."""
    resp = server.request(path="/api/v1/diadema_pipeline/settings", method="GET")
    # 401 = autenticazione richiesta → plugin caricato (non 404)
    assert resp.status != "404 Not Found", "Il plugin diadema_pipeline non è caricato"


# ── Test REST endpoint /run ───────────────────────────────────────────────────


def test_run_requires_auth(server, fsAssetstore):
    """POST /run senza autenticazione deve restituire 401."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/507f1f77bcf86cd799439011/run/mriqc",
        method="POST",
    )
    assert resp.status == "401 Unauthorized"


def test_run_item_not_found(server, fsAssetstore, admin_user):
    """POST /run con un item ID inesistente deve restituire 400 o 404."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/507f1f77bcf86cd799439011/run/mriqc",
        method="POST",
        user=admin_user,
    )
    assert resp.status in ("400 Bad Request", "404 Not Found")


def test_run_unsupported_tool(server, fsAssetstore, admin_user):
    """POST /run con toolId non valido deve restituire 400."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/507f1f77bcf86cd799439011/run/invalid_tool",
        method="POST",
        user=admin_user,
    )
    assert resp.status in ("400 Bad Request", "404 Not Found")


# ── Test REST endpoint /results ───────────────────────────────────────────────


def test_get_results_item_not_found(server, fsAssetstore, user):
    """GET /results con item ID inesistente deve restituire 400 o 404."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/507f1f77bcf86cd799439011/results",
        method="GET",
        user=user,
    )
    assert resp.status in ("400 Bad Request", "404 Not Found")


# ── Test REST settings ────────────────────────────────────────────────────────


def test_settings_requires_admin(server, fsAssetstore, user):
    """GET /settings non-admin deve restituire 403."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/settings",
        method="GET",
        user=user,
    )
    assert resp.status == "403 Forbidden"


def test_settings_get_defaults(server, fsAssetstore, admin_user):
    """GET /settings admin restituisce i default corretti."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/settings",
        method="GET",
        user=admin_user,
    )
    assert resp.status == "200 OK"
    body = resp.json
    assert "diadema.output_storage" in body
    assert body["diadema.output_storage"] == "item"
    assert "diadema.widget_enabled" in body
    assert body["diadema.widget_enabled"]["mriqc"] is True
    assert body["diadema.widget_enabled"]["lstai"] is False


def test_settings_update_and_read(server, fsAssetstore, admin_user):
    """PUT /settings aggiorna un valore, GET lo ritorna aggiornato."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/settings",
        method="PUT",
        user=admin_user,
        type="application/json",
        body='{"diadema.output_storage": "derivatives"}',
    )
    assert resp.status == "200 OK"
    assert resp.json["updated"]["diadema.output_storage"] == "derivatives"

    resp2 = server.request(
        path="/api/v1/diadema_pipeline/settings",
        method="GET",
        user=admin_user,
    )
    assert resp2.json["diadema.output_storage"] == "derivatives"


def test_settings_invalid_output_storage(server, fsAssetstore, admin_user):
    """PUT /settings con output_storage non valido deve restituire 400."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/settings",
        method="PUT",
        user=admin_user,
        type="application/json",
        body='{"diadema.output_storage": "invalid_value"}',
    )
    assert resp.status == "400 Bad Request"


def test_settings_unknown_key(server, fsAssetstore, admin_user):
    """PUT /settings con chiave non riconosciuta deve restituire 400."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/settings",
        method="PUT",
        user=admin_user,
        type="application/json",
        body='{"diadema.unknown_key": "value"}',
    )
    assert resp.status == "400 Bad Request"


# ── Test REST endpoint cleanup_stuck_jobs ─────────────────────────────────────


def test_cleanup_requires_admin(server, fsAssetstore, user):
    """POST /cleanup_stuck_jobs non-admin deve restituire 403."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/cleanup_stuck_jobs",
        method="POST",
        user=user,
    )
    assert resp.status == "403 Forbidden"


def test_cleanup_dry_run(server, fsAssetstore, admin_user):
    """POST /cleanup_stuck_jobs?dryRun=true deve restituire la lista senza modificare."""
    resp = server.request(
        path="/api/v1/diadema_pipeline/cleanup_stuck_jobs",
        method="POST",
        user=admin_user,
        params={"dryRun": True},
    )
    assert resp.status == "200 OK"
    body = resp.json
    assert body["dry_run"] is True
    assert "jobs_found" in body
    assert "limit" in body


# ── Test task (mock) ──────────────────────────────────────────────────────────


def test_task_mriqc_skips_if_job_terminal(monkeypatch):
    """
    run_mriqc_task deve uscire subito se il job è già in stato terminale.
    Usa monkeypatch per simulare GirderClient senza un server reale.
    """
    from girder_diadema_pipeline.tasks import run_mriqc_task

    class _FakeTask:
        class request:
            girder_client_token = "fake_token"
            girder_api_url = "http://girder:8080/api/v1"

    class _FakeGC:
        def __init__(self, **kwargs):
            pass

        token = None

        def get(self, path):
            # Simula job già in SUCCESS (status=3)
            return {"status": 3}

    import girder_diadema_pipeline.tasks._helpers as helpers_module

    monkeypatch.setattr(helpers_module, "GirderClient", _FakeGC, raising=False)

    result = run_mriqc_task.run(
        _FakeTask(),
        item_id="fake_item",
        file_id="fake_file",
        file_name="test.nii",
        job_id="fake_job",
        job_token_id="fake_token",
    )

    assert result["status"] == "skipped"


def test_task_freesurfer_skips_if_job_terminal(monkeypatch):
    """
    run_freesurfer_task deve uscire subito se il job è già in stato terminale.
    """
    from girder_diadema_pipeline.tasks import run_freesurfer_task

    class _FakeTask:
        class request:
            girder_client_token = "fake_token"
            girder_api_url = "http://girder:8080/api/v1"

    class _FakeGC:
        def __init__(self, **kwargs):
            pass

        token = None

        def get(self, path):
            return {"status": 5}  # CANCELLED

    import girder_diadema_pipeline.tasks._helpers as helpers_module

    monkeypatch.setattr(helpers_module, "GirderClient", _FakeGC, raising=False)

    result = run_freesurfer_task.run(
        _FakeTask(),
        item_id="fake_item",
        file_id="fake_file",
        file_name="test.nii",
        job_id="fake_job",
        job_token_id="fake_token",
    )

    assert result["status"] == "skipped"


def test_lstai_returns_not_implemented(monkeypatch):
    """
    run_lstai_task deve ritornare not_implemented senza lanciare eccezioni non gestite.
    """
    from girder_diadema_pipeline.tasks import run_lstai_task

    class _FakeTask:
        class request:
            girder_client_token = "fake_token"
            girder_api_url = "http://girder:8080/api/v1"

    calls = {}

    class _FakeGC:
        def __init__(self, **kwargs):
            pass

        token = None

        def get(self, path):
            return {"status": 0}  # non terminale

        def put(self, path, **kwargs):
            calls[path] = kwargs

    import girder_diadema_pipeline.tasks._helpers as helpers_module

    monkeypatch.setattr(helpers_module, "GirderClient", _FakeGC, raising=False)
    import girder_diadema_pipeline.tasks.lstai as lstai_module

    monkeypatch.setattr(lstai_module, "GirderClient", _FakeGC, raising=False)

    result = run_lstai_task.run(
        _FakeTask(),
        item_id="fake_item",
        file_id="fake_file",
        file_name="test.nii",
        job_id="fake_job",
        job_token_id="fake_token",
    )

    assert result["status"] == "not_implemented"


# ── Test parser FreeSurfer ────────────────────────────────────────────────────


def test_parse_aseg_stats_basic():
    """Verifica che _parse_aseg_stats legga correttamente volumi subcorticali."""
    import tempfile
    from pathlib import Path

    from girder_diadema_pipeline.tasks.freesurfer import _parse_aseg_stats

    # Formato reale aseg.stats (colonne: Index SegId NVoxels Volume_mm3 StructName ...)
    fake_content = """\
# Header
# Measure BrainSeg, BrainSegVol, Brain Segmentation Volume, 1234567.0, mm^3
  0  2  5000  4200.5  Left-Cerebral-White-Matter  80.0  10.0  5.0  200.0  195.0
  1 17  3500  2900.0  Left-Hippocampus             70.0   9.5  4.5  180.0  175.5
  2 53  3200  2600.0  Right-Hippocampus            68.0   8.5  3.5  170.0  166.5
"""
    with tempfile.NamedTemporaryFile(suffix=".stats", delete=False, mode="w") as f:
        f.write(fake_content)
        path = Path(f.name)
    try:
        result = _parse_aseg_stats(path)
        assert "Left-Hippocampus" in result
        assert abs(result["Left-Hippocampus"] - 2900.0) < 0.01
        assert "Right-Hippocampus" in result
        assert abs(result["Right-Hippocampus"] - 2600.0) < 0.01
    finally:
        path.unlink(missing_ok=True)


def test_parse_global_measures_basic():
    """Verifica che _parse_global_measures estragga le misure globali."""
    import tempfile
    from pathlib import Path

    from girder_diadema_pipeline.tasks.freesurfer import _parse_global_measures

    fake_content = """\
# Measure BrainSeg, BrainSegVol, Brain Segmentation Volume, 1234567.0, mm^3
# Measure eTIV, EstimatedTotalIntraCranialVol, Estimated Total Intracranial Volume, 1500000.0, mm^3
  0  2  5000  4200.5  Left-Cerebral-White-Matter  80.0  10.0  5.0  200.0  195.0
"""
    with tempfile.NamedTemporaryFile(suffix=".stats", delete=False, mode="w") as f:
        f.write(fake_content)
        path = Path(f.name)
    try:
        result = _parse_global_measures(path)
        assert "BrainSeg" in result
        assert abs(result["BrainSeg"] - 1234567.0) < 1.0
        assert "eTIV" in result
    finally:
        path.unlink(missing_ok=True)


def test_parse_aparc_stats_basic():
    """Verifica che _parse_aparc_stats legga la parcellazione corticale."""
    import tempfile
    from pathlib import Path

    from girder_diadema_pipeline.tasks.freesurfer import _parse_aparc_stats

    fake_content = """\
# Header
bankssts  1234  890  2340  2.67  0.45  0.12  0.09  12  2
caudalanteriorcingulate  456  310  890  2.10  0.38  0.11  0.08  8  1
"""
    with tempfile.NamedTemporaryFile(suffix=".stats", delete=False, mode="w") as f:
        f.write(fake_content)
        path = Path(f.name)
    try:
        result = _parse_aparc_stats(path)
        assert "bankssts" in result
        assert result["bankssts"]["GrayVol"] == 2340
        assert abs(result["bankssts"]["ThickAvg"] - 2.67) < 0.001
    finally:
        path.unlink(missing_ok=True)

        path.unlink(missing_ok=True)
