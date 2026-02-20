"""
REST API endpoints for widget data retrieval
"""

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, loadmodel
from girder.constants import AccessType

from .widget_registry import get_widget_providers


class WidgetResource(Resource):
    """REST endpoints for NIfTI viewer widget data"""

    def __init__(self):
        super(WidgetResource, self).__init__()
        self.resourceName = "item"

    @access.public
    @loadmodel(model="item", level=AccessType.READ)
    @autoDescribeRoute(
        Description("Get widget data for NIfTI item")
        .modelParam("id", model="item", level=AccessType.READ)
        .param(
            "widget_id",
            "Optional widget ID to fetch specific widget data",
            required=False,
        )
        .errorResponse("Item not found", 404)
        .errorResponse("Read access denied", 403)
    )
    def getWidgetData(self, item, widget_id=None):
        """
        Get data from all applicable widgets for this item.

        Returns array of widget data objects:
        [
            {
                'widget_id': 'qc_metrics',
                'config': { 'id', 'title', 'priority', 'rest_endpoint' },
                'data': { ... widget-specific data ... }
            },
            ...
        ]
        """
        providers = get_widget_providers()

        # Filter to specific widget if requested
        if widget_id:
            if widget_id not in providers:
                return {"error": f"Widget {widget_id} not found"}
            providers = {widget_id: providers[widget_id]}

        result = []
        for wid, provider_class in providers.items():
            provider = provider_class()
            if provider.should_display(item):
                try:
                    widget_data = {
                        "widget_id": wid,
                        "config": provider_class.get_widget_config(),
                        "data": provider.get_data(item),
                    }
                    result.append(widget_data)
                except Exception as e:
                    # Log error but don't fail entire request
                    result.append(
                        {
                            "widget_id": wid,
                            "config": provider_class.get_widget_config(),
                            "error": str(e),
                        }
                    )

        # Sort by priority
        result.sort(key=lambda w: w["config"].get("priority", 50))

        return result
