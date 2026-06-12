"""
Widget provider per Plugin Template
──────────────────────────────────────────────────────────────────────────────
Integra il plugin con il viewer NIfTI (girder_nifti_viewer).

Questo file è necessario SOLO se vuoi mostrare un pannello nel viewer NIfTI.
Rimuovilo (e le relative importazioni in __init__.py) se non ti integri
con nifti_viewer.
──────────────────────────────────────────────────────────────────────────────
"""

from girder_nifti_viewer.widget_registry import WidgetProviderBase


class PluginTemplateWidgetProvider(WidgetProviderBase):
    """
    Provider del widget nel viewer NIfTI.

    Il registry di nifti_viewer chiama questi metodi per decidere se e come
    mostrare il widget quando l'utente visualizza un item NIfTI.
    """

    @classmethod
    def get_widget_id(cls) -> str:
        """
        Identificatore univoco del widget.
        Deve corrispondere all'id usato nel web client (main.js).
        """
        return "plugin_template_widget"

    @classmethod
    def get_title(cls) -> str:
        """Titolo mostrato nel pannello del viewer."""
        return "Plugin Template"

    @classmethod
    def get_priority(cls) -> int:
        """
        Ordine di visualizzazione nel viewer (numeri bassi = prima).
        Il widget risultati DIADEMA usa priorità bassa; usa un valore più alto
        per apparire dopo.
        """
        return 20

    @classmethod
    def get_rest_endpoint(cls):
        """
        Restituisce l'endpoint REST da cui il widget carica i dati.
        None = i dati vengono dai metadati dell'item (più efficiente,
        nessuna chiamata API extra).
        """
        return None

    def should_display(self, item: dict) -> bool:
        """
        Decide se mostrare il widget per questo item.

        Viene chiamato per ogni item aperto nel viewer.
        Restituisci True solo se hai dati da mostrare.
        """
        return "plugin_template_results" in item

    def get_data(self, item: dict) -> dict:
        """
        Restituisce i dati da passare al componente JavaScript del widget.

        Viene chiamato solo se should_display() restituisce True.
        """
        return {
            "results": item.get("plugin_template_results", {}),
            "status":  item.get("plugin_template_status", "unknown"),
        }
