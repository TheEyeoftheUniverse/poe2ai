"""AstrBot API stub:仅用于插件冒烟测试。"""
import tempfile


class Context:
    pass


class Star:
    def __init__(self, context):
        self.context = context


def register(*a, **k):
    def deco(cls):
        cls._registered = a
        return cls
    return deco


class StarTools:
    _dir = tempfile.mkdtemp(prefix="poe2ai_test_")

    @staticmethod
    def get_data_dir(name):
        import os
        d = os.path.join(StarTools._dir, name)
        os.makedirs(d, exist_ok=True)
        return d
