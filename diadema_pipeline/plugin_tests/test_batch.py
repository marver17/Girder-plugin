"""
Test del lancio batch multi-soggetto DIADEMA
──────────────────────────────────────────────────────────────────────────────
Copre l'enumerazione dei target BIDS, il fan-out (una richiesta → N task) e lo
stato aggregato.

Esecuzione:
    pytest diadema_pipeline/plugin_tests/test_batch.py -v
──────────────────────────────────────────────────────────────────────────────
"""

import json

import pytest
from girder.models.folder import Folder
from girder.models.item import Item


@pytest.fixture
def admin_user(admin):
    return admin


@pytest.fixture
def user(user):
    return user


# ── Helper: alberatura BIDS di prova ─────────────────────────────────────────


def _make_dataset(owner, subjects=("sub-001", "sub-002"), sessions=("ses-01",),
                  with_nifti=True):
    """Crea dataset_root/sub-XXX/ses-YY/<file>.nii.gz e ritorna la radice.

    `with_nifti=False` produce sessioni vuote, che non devono comparire fra i
    target: una ses-XX senza dati non ha nulla su cui far girare una pipeline.
    """
    root = Folder().createFolder(
        owner, "BIDSDataset", parentType="user", creator=owner, reuseExisting=True
    )
    Item().createItem("dataset_description.json", owner, root)

    for sub in subjects:
        sub_folder = Folder().createFolder(
            root, sub, parentType="folder", creator=owner, reuseExisting=True
        )
        for ses in sessions:
            ses_folder = Folder().createFolder(
                sub_folder, ses, parentType="folder", creator=owner, reuseExisting=True
            )
            if with_nifti:
                anat = Folder().createFolder(
                    ses_folder, "anat", parentType="folder",
                    creator=owner, reuseExisting=True,
                )
                Item().createItem(f"{sub}_{ses}_T1w.nii.gz", owner, anat)
    return root


def _set_status(folder_id, tool_id, status):
    Folder().update(
        {"_id": folder_id},
        {"$set": {f"diadema.{tool_id}.status": status}},
        multi=False,
    )


@pytest.fixture
def no_dispatch(monkeypatch):
    """Intercetta apply_async: i test non hanno un broker Celery.

    Registra le chiamate così si può asserire il fan-out (N target → N task,
    ciascuno sulla coda del proprio tool).
    """
    calls = []

    class _FakeAsyncResult:
        def __init__(self, index):
            self.id = f"fake-celery-{index}"

    def _fake_apply_async(*args, **kwargs):
        calls.append(kwargs)
        return _FakeAsyncResult(len(calls))

    # Si patcha l'istanza di ogni task, non celery.Task: girder_worker
    # sovrascrive apply_async con una propria implementazione, quindi un patch
    # sulla classe base non verrebbe mai raggiunto.
    from girder_diadema_pipeline import tasks

    for name in ("run_mriqc_task", "run_freesurfer_task", "run_lstai_task"):
        monkeypatch.setattr(getattr(tasks, name), "apply_async", _fake_apply_async)
    return calls


# ── batch/targets ─────────────────────────────────────────────────────────────


def test_batch_targets_lists_sessions(server, fsAssetstore, admin_user):
    """Elenca una riga per sessione, con soggetto e conteggio file."""
    root = _make_dataset(admin_user, subjects=("sub-001", "sub-002"),
                         sessions=("ses-01", "ses-02"))
    resp = server.request(
        path="/api/v1/diadema_pipeline/batch/targets",
        method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    )
    assert resp.status == "200 OK"
    targets = resp.json["targets"]
    assert len(targets) == 4
    assert resp.json["root"]["is_dataset_root"] is True
    # Ordinamento per (soggetto, sessione)
    assert [t["path"] for t in targets] == [
        "sub-001/ses-01", "sub-001/ses-02",
        "sub-002/ses-01", "sub-002/ses-02",
    ]
    assert all(t["nifti_count"] == 1 for t in targets)


def test_batch_targets_skips_empty_sessions(server, fsAssetstore, admin_user):
    """Una ses-XX senza item NIfTI non è un target valido."""
    root = _make_dataset(admin_user, subjects=("sub-001",), with_nifti=False)
    resp = server.request(
        path="/api/v1/diadema_pipeline/batch/targets",
        method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    )
    assert resp.status == "200 OK"
    assert resp.json["targets"] == []


def test_batch_targets_hides_other_users_data(server, fsAssetstore, admin_user, user):
    """Un utente senza permessi di scrittura non vede i target altrui."""
    root = _make_dataset(admin_user, subjects=("sub-001",))
    resp = server.request(
        path="/api/v1/diadema_pipeline/batch/targets",
        method="GET",
        user=user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    )
    # O 403 sulla radice, o lista vuota: in nessun caso i target altrui.
    if resp.status == "200 OK":
        assert resp.json["targets"] == []
    else:
        assert resp.status.startswith("403")


def test_batch_targets_unknown_tool(server, fsAssetstore, admin_user):
    root = _make_dataset(admin_user, subjects=("sub-001",))
    resp = server.request(
        path="/api/v1/diadema_pipeline/batch/targets",
        method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "nope"},
    )
    assert resp.status == "400 Bad Request"


# ── batch/run ─────────────────────────────────────────────────────────────────


def _run_batch(server, user, tool, root, targets, **extra):
    body = {"rootFolderId": str(root["_id"]), "targets": targets, "params": {}}
    body.update(extra)
    return server.request(
        path=f"/api/v1/diadema_pipeline/batch/run/{tool}",
        method="POST",
        user=user,
        type="application/json",
        body=json.dumps(body),
    )


def test_batch_run_requires_auth(server, fsAssetstore):
    resp = server.request(
        path="/api/v1/diadema_pipeline/batch/run/mriqc",
        method="POST",
        type="application/json",
        body=json.dumps({"rootFolderId": "x", "targets": [{"folderId": "y"}]}),
    )
    assert resp.status == "401 Unauthorized"


def test_batch_run_unsupported_tool(server, fsAssetstore, admin_user):
    root = _make_dataset(admin_user, subjects=("sub-001",))
    resp = _run_batch(server, admin_user, "nope", root, [{"folderId": "x"}])
    assert resp.status == "400 Bad Request"


def test_batch_run_empty_targets(server, fsAssetstore, admin_user):
    root = _make_dataset(admin_user, subjects=("sub-001",))
    resp = _run_batch(server, admin_user, "mriqc", root, [])
    assert resp.status == "400 Bad Request"


def test_batch_run_too_many_targets(server, fsAssetstore, admin_user):
    """Oltre il tetto per richiesta si rifiuta prima di accodare qualsiasi cosa."""
    from girder_diadema_pipeline.rest import _MAX_BATCH_TARGETS

    root = _make_dataset(admin_user, subjects=("sub-001",))
    targets = [{"folderId": "507f1f77bcf86cd799439011"}] * (_MAX_BATCH_TARGETS + 1)
    resp = _run_batch(server, admin_user, "mriqc", root, targets)
    assert resp.status == "400 Bad Request"


def test_batch_run_fans_out(server, fsAssetstore, admin_user, no_dispatch):
    """Una richiesta → N task sulla coda del tool, N folder in 'queued'."""
    root = _make_dataset(admin_user, subjects=("sub-001", "sub-002"))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    ).json["targets"]
    targets = [{"folderId": t["folder_id"]} for t in listing]

    resp = _run_batch(server, admin_user, "mriqc", root, targets)
    assert resp.status == "200 OK"
    assert resp.json["queued"] == 2
    assert resp.json["skipped"] == 0
    assert resp.json["failed"] == 0

    # Un task Celery per target, tutti sulla coda del tool
    assert len(no_dispatch) == 2
    assert {c["queue"] for c in no_dispatch} == {"diadema_mriqc"}

    for t in listing:
        folder = Folder().load(t["folder_id"], force=True)
        assert folder["diadema"]["mriqc"]["status"] == "queued"
        assert folder["diadema"]["mriqc"]["job_id"]


def test_batch_run_routes_freesurfer_to_its_queue(
    server, fsAssetstore, admin_user, no_dispatch
):
    root = _make_dataset(admin_user, subjects=("sub-001",))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "freesurfer"},
    ).json["targets"]

    resp = _run_batch(
        server, admin_user, "freesurfer", root,
        [{"folderId": t["folder_id"]} for t in listing],
    )
    assert resp.status == "200 OK"
    assert {c["queue"] for c in no_dispatch} == {"freesurfer"}


def test_batch_run_skips_active_and_continues(
    server, fsAssetstore, admin_user, no_dispatch
):
    """Un target già in corso viene saltato senza abortire gli altri."""
    root = _make_dataset(admin_user, subjects=("sub-001", "sub-002"))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    ).json["targets"]

    busy = listing[0]
    _set_status(Folder().load(busy["folder_id"], force=True)["_id"], "mriqc", "running")

    resp = _run_batch(
        server, admin_user, "mriqc", root,
        [{"folderId": t["folder_id"]} for t in listing],
    )
    assert resp.status == "200 OK"
    assert resp.json["queued"] == 1
    assert resp.json["skipped"] == 1
    assert len(no_dispatch) == 1

    skipped = [t for t in resp.json["targets"] if t["dispatch"] == "skipped"][0]
    assert skipped["folderId"] == busy["folder_id"]
    assert "già in corso" in skipped["message"]
    # Lo stato del target attivo non è stato toccato
    assert Folder().load(busy["folder_id"], force=True)["diadema"]["mriqc"]["status"] == "running"


def test_batch_run_skip_completed(server, fsAssetstore, admin_user, no_dispatch):
    """skipCompleted salta i completati; force li rilancia comunque."""
    root = _make_dataset(admin_user, subjects=("sub-001",))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    ).json["targets"]
    targets = [{"folderId": t["folder_id"]} for t in listing]
    _set_status(Folder().load(listing[0]["folder_id"], force=True)["_id"], "mriqc", "completed")

    resp = _run_batch(server, admin_user, "mriqc", root, targets, skipCompleted=True)
    assert resp.json["skipped"] == 1
    assert resp.json["queued"] == 0
    assert len(no_dispatch) == 0

    resp = _run_batch(server, admin_user, "mriqc", root, targets,
                      skipCompleted=True, force=True)
    assert resp.json["queued"] == 1
    assert len(no_dispatch) == 1


def test_batch_run_skips_unauthorized_target(
    server, fsAssetstore, admin_user, user, no_dispatch
):
    """Un folderId fuori dal proprio perimetro viene saltato, non fa 403."""
    admin_root = _make_dataset(admin_user, subjects=("sub-001",))
    admin_targets = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(admin_root["_id"]), "toolId": "mriqc"},
    ).json["targets"]

    user_root = _make_dataset(user, subjects=("sub-009",))
    user_targets = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=user,
        params={"folderId": str(user_root["_id"]), "toolId": "mriqc"},
    ).json["targets"]

    resp = _run_batch(
        server, user, "mriqc", user_root,
        [{"folderId": user_targets[0]["folder_id"]},
         {"folderId": admin_targets[0]["folder_id"]}],
    )
    assert resp.status == "200 OK"
    assert resp.json["queued"] == 1
    assert resp.json["skipped"] == 1
    assert len(no_dispatch) == 1


def test_batch_run_validates_params_before_queueing(
    server, fsAssetstore, admin_user, no_dispatch
):
    """Un parametro non valido rifiuta tutto: nessun batch parzialmente lanciato."""
    root = _make_dataset(admin_user, subjects=("sub-001",))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "freesurfer"},
    ).json["targets"]

    resp = _run_batch(
        server, admin_user, "freesurfer", root,
        [{"folderId": t["folder_id"]} for t in listing],
        params={"directive": "; rm -rf /"},
    )
    assert resp.status == "400 Bad Request"
    assert len(no_dispatch) == 0


def test_batch_run_coerces_string_params(
    server, fsAssetstore, admin_user, no_dispatch
):
    """I valori JSON arrivano come stringhe dagli <input>: vanno coerciti.

    Senza coercizione _validate_threshold confronterebbe un float con una
    stringa (TypeError) e i task riceverebbero un timeout non numerico.
    """
    root = _make_dataset(admin_user, subjects=("sub-001",))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "lstai"},
    ).json["targets"]

    resp = _run_batch(
        server, admin_user, "lstai", root,
        [{"folderId": t["folder_id"]} for t in listing],
        params={"threshold": "0.4", "useGpu": "false"},
    )
    assert resp.status == "200 OK"
    assert resp.json["queued"] == 1
    kwargs = no_dispatch[0]["kwargs"]
    assert kwargs["threshold"] == 0.4
    assert kwargs["use_gpu"] is False


def test_batch_run_rejects_non_numeric_param(
    server, fsAssetstore, admin_user, no_dispatch
):
    root = _make_dataset(admin_user, subjects=("sub-001",))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    ).json["targets"]

    resp = _run_batch(
        server, admin_user, "mriqc", root,
        [{"folderId": t["folder_id"]} for t in listing],
        params={"timeout": "molto"},
    )
    assert resp.status == "400 Bad Request"
    assert len(no_dispatch) == 0


# ── batch/:id/status ──────────────────────────────────────────────────────────


def test_batch_status_aggregates(server, fsAssetstore, admin_user, no_dispatch):
    """Il summary rispecchia gli stati correnti delle folder; done solo a fine corsa."""
    root = _make_dataset(admin_user, subjects=("sub-001", "sub-002"))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    ).json["targets"]

    launched = _run_batch(
        server, admin_user, "mriqc", root,
        [{"folderId": t["folder_id"]} for t in listing],
    ).json
    batch_id = launched["batch_id"]

    def _status():
        resp = server.request(
            path=f"/api/v1/diadema_pipeline/batch/{batch_id}/status",
            method="GET", user=admin_user,
        )
        assert resp.status == "200 OK"
        return resp.json

    body = _status()
    assert body["summary"]["total"] == 2
    assert body["summary"]["queued"] == 2
    assert body["done"] is False

    _set_status(Folder().load(listing[0]["folder_id"], force=True)["_id"], "mriqc", "completed")
    body = _status()
    assert body["summary"]["completed"] == 1
    assert body["done"] is False

    _set_status(Folder().load(listing[1]["folder_id"], force=True)["_id"], "mriqc", "error")
    body = _status()
    assert body["summary"]["error"] == 1
    assert body["done"] is True


def test_batch_status_denied_to_other_user(
    server, fsAssetstore, admin_user, user, no_dispatch
):
    root = _make_dataset(admin_user, subjects=("sub-001",))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    ).json["targets"]
    batch_id = _run_batch(
        server, admin_user, "mriqc", root,
        [{"folderId": t["folder_id"]} for t in listing],
    ).json["batch_id"]

    resp = server.request(
        path=f"/api/v1/diadema_pipeline/batch/{batch_id}/status",
        method="GET", user=user,
    )
    assert resp.status.startswith("403")


# ── Non-regressione: la run di sessione singola resta invariata ──────────────


def test_session_run_still_returns_409_on_active_job(
    server, fsAssetstore, admin_user, no_dispatch
):
    """Il refactor degli helper non deve aver cambiato il claim della run singola."""
    root = _make_dataset(admin_user, subjects=("sub-001",))
    listing = server.request(
        path="/api/v1/diadema_pipeline/batch/targets", method="GET",
        user=admin_user,
        params={"folderId": str(root["_id"]), "toolId": "mriqc"},
    ).json["targets"]
    folder_id = listing[0]["folder_id"]
    _set_status(Folder().load(folder_id, force=True)["_id"], "mriqc", "running")

    resp = server.request(
        path=f"/api/v1/diadema_pipeline/session/{folder_id}/run/mriqc",
        method="POST", user=admin_user,
    )
    assert resp.status.startswith("409")
