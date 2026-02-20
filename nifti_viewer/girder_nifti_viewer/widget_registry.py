"""
Widget Registry System for NIfTI Viewer Plugin Extensions

This module provides a registry pattern for plugins to register metadata
widgets that will be displayed in the NIfTI viewer interface.

Example usage in a plugin:

    from girder_nifti_viewer.widget_registry import WidgetProviderBase, register_widget_provider
    from girder.plugin import GirderPlugin
    from girder import events

    class MyWidgetProvider(WidgetProviderBase):
        @classmethod
        def get_widget_id(cls):
            return 'my_custom_widget'

        @classmethod
        def get_title(cls):
            return 'My Custom Data'

        def should_display(self, item):
            return 'my_custom_data' in item

        def get_data(self, item):
            return item.get('my_custom_data', {})

    class MyPlugin(GirderPlugin):
        def load(self, info):
            events.bind('nifti_viewer.register_widgets', 'my_plugin',
                       lambda event: event.info['register_function'](MyWidgetProvider))
"""

import collections


class WidgetProviderBase:
    """
    Base class for widget providers.

    Plugins should subclass this and implement the required methods to
    provide custom metadata widgets in the NIfTI viewer.
    """

    @classmethod
    def get_widget_id(cls):
        """
        Return unique identifier for this widget.

        Returns:
            str: Unique widget ID (e.g., 'qc_metrics', 'freesurfer_volumes')
        """
        raise NotImplementedError("get_widget_id() must be implemented")

    @classmethod
    def get_title(cls):
        """
        Return human-readable title for this widget.

        Returns:
            str: Widget title displayed in UI
        """
        return cls.get_widget_id().replace("_", " ").title()

    @classmethod
    def get_priority(cls):
        """
        Return display priority (lower numbers appear first).

        Returns:
            int: Priority value (default: 50)
        """
        return 50

    @classmethod
    def get_rest_endpoint(cls):
        """
        Return REST API endpoint pattern for fetching widget data.

        Returns:
            str: Endpoint pattern (e.g., '/nifti_qc/{id}/results')
                 or None if data is retrieved from item metadata
        """
        return None

    @classmethod
    def get_widget_config(cls):
        """
        Return complete widget configuration for frontend.

        Returns:
            dict: Configuration with keys: id, title, priority, rest_endpoint
        """
        return {
            "id": cls.get_widget_id(),
            "title": cls.get_title(),
            "priority": cls.get_priority(),
            "rest_endpoint": cls.get_rest_endpoint(),
        }

    def should_display(self, item):
        """
        Determine if widget should be displayed for given item.

        Args:
            item (dict): Girder item document

        Returns:
            bool: True if widget should be displayed
        """
        raise NotImplementedError("should_display() must be implemented")

    def get_data(self, item):
        """
        Retrieve data to display in widget.

        Args:
            item (dict): Girder item document

        Returns:
            dict: Data to be serialized and sent to frontend
        """
        raise NotImplementedError("get_data() must be implemented")


# Global registry of widget providers
_widget_providers = collections.OrderedDict()


def register_widget_provider(provider_class):
    """
    Register a widget provider.

    Args:
        provider_class: Class inheriting from WidgetProviderBase
    """
    if not issubclass(provider_class, WidgetProviderBase):
        raise TypeError("Provider must inherit from WidgetProviderBase")

    widget_id = provider_class.get_widget_id()
    _widget_providers[widget_id] = provider_class


def get_widget_providers():
    """
    Get all registered widget providers.

    Returns:
        OrderedDict: Mapping of widget_id -> provider_class
    """
    return _widget_providers


def unregister_widget_provider(widget_id):
    """
    Unregister a widget provider.

    Args:
        widget_id (str): ID of widget to unregister
    """
    _widget_providers.pop(widget_id, None)
