import os
import importlib.util
import sys
from typing import List
from .base import AnalyzerPlugin

class PluginLoader:
    """
    Loads custom analyzers from the local filesystem.
    """
    def __init__(self, plugin_dir: str = None):
        self.plugin_dir = plugin_dir or os.path.expanduser("~/.dx/plugins")
        os.makedirs(self.plugin_dir, exist_ok=True)

    def load_plugins(self) -> List[AnalyzerPlugin]:
        plugins = []
        if not os.path.exists(self.plugin_dir):
            return []

        for filename in os.listdir(self.plugin_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                file_path = os.path.join(self.plugin_dir, filename)
                module_name = filename[:-3]
                
                try:
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[module_name] = module
                        spec.loader.exec_module(module)
                        
                        # Look for classes that inherit from AnalyzerPlugin
                        for attribute_name in dir(module):
                            attribute = getattr(module, attribute_name)
                            if (isinstance(attribute, type) and 
                                issubclass(attribute, AnalyzerPlugin) and 
                                attribute is not AnalyzerPlugin):
                                plugins.append(attribute())
                except Exception as e:
                    print(f"Error loading plugin {filename}: {e}")
                    
        return plugins
