"""
Test di base per Plugin Template
──────────────────────────────────────────────────────────────────────────────
Usa pytest-girder per creare un server Girder in-process.

Esecuzione:
    pytest plugin_tests/ -v

COME ADATTARE:
  - Aggiungi fixture specifiche del tuo dominio
  - Aggiungi test per ogni endpoint REST
  - Aggiungi test per la logica dei task (mock del GirderClient)
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
    """Verifica che il plugin si carichi senza errori."""
    resp = server.request(path="/api/v1/plugin_template", method="GET")
    # 400 o 405 significa che il path esiste (il plugin è caricato)
    # 404 significa che il plugin NON è caricato
    assert resp.status != "404 Not Found", "Il plugin non è caricato"


# ── Test REST endpoint /run ───────────────────────────────────────────────────

def test_run_requires_auth(server, fsAssetstore):
    """POST /run senza autenticazione deve restituire 401."""
    resp = server.request(
        path="/api/v1/plugin_template/507f1f77bcf86cd799439011/run",
        method="POST",
    )
    assert resp.status == "401 Unauthorized"


def test_run_item_not_found(server, fsAssetstore, admin_user):
    """POST /run con un item ID inesistente deve restituire 400 o 404."""
    resp = server.request(
        path="/api/v1/plugin_template/507f1f77bcf86cd799439011/run",
        method="POST",
        user=admin_user,
    )
    assert resp.status in ("400 Bad Request", "404 Not Found")


# ── Test REST endpoint /results ───────────────────────────────────────────────

def test_get_results_item_not_found(server, fsAssetstore, user):
    """GET /results con item ID inesistente deve restituire 400 o 404."""
    resp = server.request(
        path="/api/v1/plugin_template/507f1f77bcf86cd799439011/results",
        method="GET",
        user=user,
    )
    assert resp.status in ("400 Bad Request", "404 Not Found")


# ── Test REST endpoint cleanup_stuck_jobs ─────────────────────────────────────

def test_cleanup_requires_admin(server, fsAssetstore, user):
    """POST /cleanup_stuck_jobs non-admin deve restituire 403."""
    resp = server.request(
        path="/api/v1/plugin_template/cleanup_stuck_jobs",
        method="POST",
        user=user,
    )
    assert resp.status == "403 Forbidden"


def test_cleanup_dry_run(server, fsAssetstore, admin_user):
    """POST /cleanup_stuck_jobs?dryRun=true deve restituire la lista senza modificare."""
    resp = server.request(
        path="/api/v1/plugin_template/cleanup_stuck_jobs",
        method="POST",
        user=admin_user,
        params={"dryRun": True},
    )
    assert resp.status == "200 OK"
    body = resp.json
    assert body["dry_run"] is True
    assert "jobs_found" in body


# ── Test task (mock) ──────────────────────────────────────────────────────────

def test_task_skips_if_job_terminal(monkeypatch):
    """
    Il task deve uscire subito se il job è già in stato terminale.
    Usa monkeypatch per simulare GirderClient senza un server reale.
    """
    from girder_plugin_template.tasks import plugin_template_task

    class _FakeTask:
        class request:
            girder_client_token = "fake_token"
            girder_api_url = "http://girder:8080/api/v1"

    class _FakeGC:
        def __init__(self, **kwargs): pass
        def get(self, path):
            # Simula un job già in SUCCESS (status=3)
            return {"status": 3}

    import girder_plugin_template.tasks as tasks_module
    monkeypatch.setattr(tasks_module, "GirderClient", _FakeGC, raising=False)

    # Chiama la funzione originale (non il task Celery decorato)
    result = plugin_template_task.run(
        _FakeTask(),
        item_id="fake_item",
        file_id="fake_file",
        file_name="test.nii",
        job_id="fake_job",
        job_token_id="fake_token",
    )

    assert result["status"] == "skipped"
    assert result["job_status"] == 3
