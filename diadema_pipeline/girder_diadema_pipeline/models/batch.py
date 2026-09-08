"""Modello DiademaBatch — registro di un lancio multi-soggetto.

Un batch NON è un task: è il verbale di un fan-out. Una POST su
`batch/run/:toolId` crea N run di sessione indipendenti (N Girder Job + N task
Celery, uno per messaggio in coda) e questo documento registra *cosa* è stato
lanciato, su quali sessioni e con quali parametri.

Deliberatamente non conserva lo stato di avanzamento: l'unica fonte di verità
resta `folder.diadema.<tool>.status`, scritto dal dispatch e poi dai worker via
`update_diadema_tool_on_folder`. Duplicarlo qui significherebbe un terzo stato
da tenere sincronizzato con Item e Folder — lo stesso tipo di drift che la
propagazione item↔sessione esiste per evitare.
"""

import datetime

from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.models.model_base import AccessControlledModel

# Esito del *dispatch* di un singolo target (non il suo avanzamento):
#   queued  → messaggio effettivamente messo in coda
#   skipped → non lanciato di proposito (job già attivo, già completato,
#             permessi insufficienti)
#   failed  → tentato ma il dispatch ha sollevato
DISPATCH_QUEUED = "queued"
DISPATCH_SKIPPED = "skipped"
DISPATCH_FAILED = "failed"

_VALID_DISPATCH = (DISPATCH_QUEUED, DISPATCH_SKIPPED, DISPATCH_FAILED)


class DiademaBatch(AccessControlledModel):
    def initialize(self):
        self.name = "diadema_batch"
        self.ensureIndices(["creatorId", "rootFolderId", "created"])
        self.exposeFields(
            level=AccessType.READ,
            fields={
                "_id",
                "created",
                "updated",
                "creatorId",
                "toolId",
                "rootFolderId",
                "rootFolderName",
                "params",
                "targets",
            },
        )

    def validate(self, doc):
        if not doc.get("toolId"):
            raise ValidationException("toolId mancante", "toolId")
        if not isinstance(doc.get("targets"), list) or not doc["targets"]:
            raise ValidationException("targets deve essere una lista non vuota", "targets")
        for target in doc["targets"]:
            if target.get("dispatch") not in _VALID_DISPATCH:
                raise ValidationException(
                    f"dispatch non valido: {target.get('dispatch')!r}", "targets"
                )
        return doc

    def createBatch(self, creator, tool_id, root_folder, params, targets):
        """Persiste un batch appena dispatchato.

        `targets` è la lista già risolta dal REST, un dict per sessione con
        folderId/subjectLabel/sessionLabel/path/jobId/celeryTaskId/dispatch/message.
        """
        now = datetime.datetime.utcnow()
        doc = {
            "created": now,
            "updated": now,
            "creatorId": creator["_id"],
            "toolId": tool_id,
            "rootFolderId": root_folder["_id"],
            "rootFolderName": root_folder.get("name", ""),
            "params": params,
            "targets": targets,
        }
        # Il batch è visibile a chi l'ha lanciato; gli admin passano da force=True.
        self.setUserAccess(doc, user=creator, level=AccessType.ADMIN, save=False)
        return self.save(doc)
