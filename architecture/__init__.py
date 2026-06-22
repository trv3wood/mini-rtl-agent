__all__ = ["plan_architecture", "write_architecture_outputs"]


def __getattr__(name: str):
    if name in __all__:
        from src.architecture import plan_architecture, write_architecture_outputs

        exports = {
            "plan_architecture": plan_architecture,
            "write_architecture_outputs": write_architecture_outputs,
        }
        return exports[name]
    raise AttributeError(name)
