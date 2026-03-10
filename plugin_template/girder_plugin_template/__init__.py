"""
Plugin Template per Girder v5
──────────────────────────────────────────────────────────────────────────────
COME USARE:
  Sostituisci globalmente:
    "plugin_template"  →  "nome_mio_plugin"
    "PluginTemplate"   →  "NomeMioPlugin"
    "Plugin Template"  →  "Nome Mio Plugin"
──────────────────────────────────────────────────────────────────────────────
"""

from pathlib import Path

from girder import events
from girder.constants import AccessType
from girder.models.item import Item
from girder.plugin import GirderPlugin, registerPluginStaticContent


class PluginTemplatePlugin(GirderPlugin):
    """
    Classe principale del plugin.

    DISPLAY_NAME:      nome mostrato nell'interfaccia admin di Girder.
    CLIENT_SOURCE_PATH: path relativo alla directory del web client,
                        partendo dalla directory di questo __init__.py.
    """

    DISPLAY_NAME = "Plugin Template"
    CLIENT_SOURCE_PATH = "web_client"

    def load(self, info):
        """
        Chiamata da Girder all'avvio, dopo che tutti i plugin sono stati
        scoperti ma prima che il server HTTP inizi ad accettare richieste.

        info["apiRoot"]    → oggetto cherrypy con le route REST montate
        info["serverRoot"] → root del server (usato da registerPluginStaticContent)
        """
        # ── Import lazy ──────────────────────────────────────────────────────
        # Gli import interni vanno dentro load() per evitare circular import
        # durante la fase di discovery dei plugin da parte di stevedore.
        from .rest import PluginTemplateResource
        from .widget_provider import PluginTemplateWidgetProvider

        # ── Campi custom sull'Item ────────────────────────────────────────────
        # Rende i campi leggibili via REST agli utenti con accesso READ.
        # Senza exposeFields, i campi extra vengono filtrati da Girder.
        Item().exposeFields(
            level=AccessType.READ,
            fields={"plugin_template_results", "plugin_template_status"},
        )

        # ── REST API ──────────────────────────────────────────────────────────
        # Monta il Resource sotto /api/v1/plugin_template
        info["apiRoot"].plugin_template = PluginTemplateResource()

        # ── Web client ────────────────────────────────────────────────────────
        # Serve il bundle Vite compilato come contenuto statico del plugin.
        # Il file JS verrà caricato automaticamente da Girder nell'app SPA.
        registerPluginStaticContent(
            plugin="plugin_template",
            css=[],
            js=["/plugin-template.umd.cjs"],   # nome del bundle generato da Vite
            staticDir=Path(__file__).parent / "web_client" / "dist",
            tree=info["serverRoot"],
        )

        # ── Integrazione con nifti_viewer (widget) ────────────────────────────
        # Strategia doppia: registrazione immediata se nifti_viewer è già caricato,
        # oppure via evento se viene caricato dopo questo plugin.
        # RIMUOVI questo blocco se non ti integri con nifti_viewer.
        widget_registered = False

        if "nifti_widget_registry" in info:
            try:
                info["nifti_widget_registry"]["register_function"](
                    PluginTemplateWidgetProvider
                )
                widget_registered = True
                print("[plugin_template] Widget provider: registered (immediate)")
            except Exception as e:
                print(f"[plugin_template] Widget provider: immediate registration failed: {e}")

        def _register_widget(event):
            register_func = event.info.get("register_function")
            if register_func:
                try:
                    register_func(PluginTemplateWidgetProvider)
                    print("[plugin_template] Widget provider: registered (via event)")
                except Exception as e:
                    print(f"[plugin_template] Widget provider: event registration failed: {e}")

        events.bind("nifti_viewer.register_widgets", "plugin_template", _register_widget)

        print("[plugin_template] Plugin caricato correttamente!")
        print("  - REST API: /api/v1/plugin_template")
        print("  - Web UI: enabled")
        print("  - Worker tasks: registered")
