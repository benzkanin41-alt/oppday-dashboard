import importlib

for name in ["pandas", "requests", "json"]:
    try:
        mod = importlib.import_module(name)
        print(name, getattr(mod, "__version__", "stdlib"))
    except Exception as exc:
        print(name, "ERROR", repr(exc))
