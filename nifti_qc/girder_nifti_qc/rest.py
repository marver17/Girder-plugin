"""
REST API endpoints for NIfTI Quality Control
"""

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel, getApiUrl
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.models.file import File
from girder.models.item import Item
from girder.models.token import Token


class NiftiQC(Resource):
    """REST resource for NIfTI quality control operations"""

    def __init__(self):
        super().__init__()
        self.resourceName = "nifti_qc"

        # Register routes
        self.route("POST", (":id", "run_mriqc"), self.runMRIQC)
        self.route("POST", (":id", "quick_check"), self.quickCheck)
        self.route("GET", (":id", "results"), self.getResults)
        self.route("DELETE", (":id", "results"), self.deleteResults)

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Run MRIQC quality control on NIfTI file")
        .notes(
            "This will launch a Girder Worker job that executes MRIQC in a Docker container. "
            "Processing time varies but typically takes 5-30 minutes depending on file size and complexity."
        )
        .modelParam(
            "id",
            model=Item,
            level=AccessType.WRITE,
            destName="item",
            description="The item containing the NIfTI file",
        )
        .param(
            "fileId",
            "ID of the specific NIfTI file to process (optional, will use first .nii/.nii.gz)",
            required=False,
        )
        .param(
            "participantLabel",
            "BIDS participant label (default: 001)",
            required=False,
            default="001",
        )
        .param(
            "modality",
            "MRI modality (T1w, T2w, bold, etc.)",
            required=False,
            default="T1w",
        )
        .param(
            "timeout",
            "Maximum execution time in seconds",
            required=False,
            dataType="integer",
            default=1800,
        )
        .errorResponse("Item not found", 404)
        .errorResponse("Write access denied", 403)
    )
    def runMRIQC(self, item, fileId, participantLabel, modality, timeout):
        """Launch MRIQC quality control job"""
        from .tasks import run_mriqc_task

        # Find NIfTI file
        if not fileId:
            files = list(File().find({"itemId": item["_id"]}))
            nifti_files = [f for f in files if f["name"].endswith((".nii", ".nii.gz"))]

            if not nifti_files:
                raise RestException("No NIfTI file found in this item")

            file_obj = nifti_files[0]
            fileId = str(file_obj["_id"])

        # Create token for worker
        token = Token().createToken(
            user=self.getCurrentUser(),
            days=1,
            scope=[TokenScope.DATA_READ, TokenScope.DATA_WRITE],
        )

        # Get file name for context
        file_obj = File().load(fileId, force=True)
        file_name = file_obj.get("name", "unknown") if file_obj else "unknown"

        # VERSION CHECK
        REST_VERSION = "2026-02-20 runMRIQC"
        print(f"========================================")
        print(f"REST VERSION: {REST_VERSION}")
        print(f"========================================")
        print(f"DEBUG REST runMRIQC: item_id={str(item['_id'])}")
        print(f"DEBUG REST runMRIQC: file_id={fileId}")
        print(f"DEBUG REST runMRIQC: file_name={file_name}")
        print(f"DEBUG REST runMRIQC: modality={modality}")
        print(f"DEBUG REST runMRIQC: participantLabel={participantLabel}")
        print(f"DEBUG REST runMRIQC: timeout={timeout}")
        print(f"DEBUG REST runMRIQC: token={str(token['_id'])}")
        print(f"DEBUG REST runMRIQC: api_url={getApiUrl()}")
        print(f"DEBUG REST runMRIQC: About to call apply_async")

        # Mark item as processing
        Item().setMetadata(
            item,
            {
                "nifti_qc_status": "processing",
                "nifti_qc_started": str(self.getCurrentUser()["_id"]),
            },
        )

        # Launch Celery task - pass all parameters including token
        try:
            celery_job = run_mriqc_task.apply_async(
                kwargs={
                    "item_id": str(item["_id"]),
                    "file_id": fileId,
                    "participant_label": participantLabel,
                    "modality": modality,
                    "timeout": timeout,
                    "file_name": file_name,
                    "girder_client_token": str(token["_id"]),
                    "girder_api_url": getApiUrl(),
                },
                # Job title as girder_worker option
                girder_job_title=f"MRIQC: {file_name} ({modality}, sub-{participantLabel})",
            )
            print(f"DEBUG REST runMRIQC: apply_async success, celery_id={celery_job.id}")
        except Exception as e:
            print(f"DEBUG REST runMRIQC: apply_async FAILED: {e}")
            import traceback
            print(traceback.format_exc())
            raise RestException(f"Failed to submit MRIQC job: {e}", code=500)

        return {
            "celery_id": celery_job.id,
            "item_id": str(item["_id"]),
            "file_id": fileId,
            "status": "queued",
            "message": "MRIQC job submitted to worker. This may take 5-30 minutes.",
            "participant_label": participantLabel,
            "modality": modality,
        }

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Quick NIfTI structure check (no MRIQC)")
        .notes(
            "Fast validation that only checks NIfTI header and basic statistics. "
            "Use this for testing or quick validation."
        )
        .modelParam("id", model=Item, level=AccessType.WRITE, destName="item")
        .param("fileId", "ID of the NIfTI file", required=False)
    )
    def quickCheck(self, item, fileId):
        """Quick NIfTI validation without full MRIQC"""
        from .tasks import quick_nifti_check

        if not fileId:
            files = list(File().find({"itemId": item["_id"]}))
            nifti_files = [f for f in files if f["name"].endswith((".nii", ".nii.gz"))]

            if not nifti_files:
                raise RestException("No NIfTI file found")

            file_obj = nifti_files[0]
            fileId = str(file_obj["_id"])

        token = Token().createToken(
            user=self.getCurrentUser(),
            days=1,
            scope=[TokenScope.DATA_READ, TokenScope.DATA_WRITE],
        )

        # Get file name for context
        file_obj = File().load(fileId, force=True)
        file_name = file_obj.get("name", "unknown") if file_obj else "unknown"

        # VERSION CHECK
        REST_VERSION = "2026-02-17 12:30:00"
        print(f"========================================")
        print(f"REST VERSION: {REST_VERSION}")
        print(f"========================================")

        # DEBUG REST
        print(f"DEBUG REST: item_id={str(item['_id'])}")
        print(f"DEBUG REST: file_id={fileId}")
        print(f"DEBUG REST: file_name={file_name}")
        print(f"DEBUG REST: token={str(token['_id'])}")
        print(f"DEBUG REST: api_url={getApiUrl()}")
        print(f"DEBUG REST: About to call apply_async with kwargs and options")

        # Launch Celery task - pass all parameters including token
        celery_job = quick_nifti_check.apply_async(
            kwargs={
                "item_id": str(item["_id"]),
                "file_id": fileId,
                "file_name": file_name,
                "girder_client_token": str(token["_id"]),
                "girder_api_url": getApiUrl(),
            },
            # Job title as girder_worker option
            girder_job_title=f"Quick NIfTI Check: {file_name}",
        )

        return {
            "celery_id": celery_job.id,
            "item_id": str(item["_id"]),
            "status": "queued",
            "message": "Quick check job submitted (fast, ~30 seconds)",
        }

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description("Get QC results for an item").modelParam(
            "id", model=Item, level=AccessType.READ, destName="item"
        )
    )
    @filtermodel(model=Item)
    def getResults(self, item):
        """Retrieve QC results stored in item"""
        return item

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Delete QC results from item").modelParam(
            "id", model=Item, level=AccessType.WRITE, destName="item"
        )
    )
    def deleteResults(self, item):
        """Remove QC results from item metadata"""

        Item().setMetadata(
            item,
            {"nifti_qc_results": None, "nifti_qc_status": None, "nifti_qc_error": None},
        )

        return {"message": "QC results deleted"}
