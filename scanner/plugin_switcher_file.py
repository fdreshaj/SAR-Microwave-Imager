from scanner.scan_file_controller import ScanFileControllerPlugin
from scanner.plugin_setting import PluginSettingString, PluginSettingInteger, PluginSettingFloat
from scanner.plugin_setting import PluginSetting
from tkinter import filedialog as fd
import os


class PluginSwitcherFile(ScanFileControllerPlugin):

    plugin_name: str = ""
    basename: str = ""

    def __init__(self):
        super().__init__()

        self.pluginMode = PluginSettingString(
            "Plugin Selection",
            "No Plugin Selected" if PluginSwitcherFile.plugin_name == "" else PluginSwitcherFile.plugin_name,
            select_options=["No Plugin Selected" if PluginSwitcherFile.plugin_name == "" else PluginSwitcherFile.plugin_name],
            restrict_selections=True
        )
        self.add_setting_pre_connect(self.pluginMode)

    @staticmethod
    def select_plugin() -> bool:
        """Open file dialog to select a scan file plugin. Returns True if selected, False if cancelled."""
        filename = fd.askopenfilename(
            title="Select Scan File Plugin",
            filetypes=[("Python files", "*.py")]
        )

        if not filename:
            return False

        basename = os.path.basename(filename)
        print(f"Selected plugin file: {basename}")

        import importlib.util
        import inspect

        spec = importlib.util.spec_from_file_location("plugin_mod", filename)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        plugin_cls = None
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if (obj.__module__ == mod.__name__
                    and issubclass(obj, ScanFileControllerPlugin)
                    and obj is not ScanFileControllerPlugin):
                plugin_cls = obj
                break

        if plugin_cls is None:
            print("Error: No ScanFileControllerPlugin class found in selected file")
            return False

        s = str(plugin_cls)                         # "<class 'plugin_mod.ScanFile'>"
        PluginName = s.split('.')[-1].rstrip("'>")
        PluginSwitcherFile.plugin_name = PluginName
        PluginSwitcherFile.basename = basename

        print(f"Plugin selected: {PluginName}")
        return True

    @staticmethod
    def _load_selected():
        """
        Instantiate and return the last plugin selected via select_plugin().
        Called by the GUI after select_plugin() returns True.
        """
        import importlib.util
        import inspect
        from scanner.plugin_switcher_file import PluginSwitcherFile

        plugins_dir = os.path.join(os.path.dirname(__file__))
        filename = os.path.join(plugins_dir, PluginSwitcherFile.basename)

        spec = importlib.util.spec_from_file_location("plugin_mod", filename)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if (obj.__module__ == mod.__name__
                    and issubclass(obj, ScanFileControllerPlugin)
                    and obj is not ScanFileControllerPlugin):
                return obj()

        raise RuntimeError(f"Could not reload plugin from {filename}")

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return False
