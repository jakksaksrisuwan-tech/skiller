class CycleError(Exception):
    pass


class TaskScheduler:
    def __init__(self):
        # TODO: store dependency graph
        pass

    def add(self, name, deps=()):
        # TODO
        pass

    def run_order(self):
        # TODO: topo-sort with alphabetical tie-break, raise CycleError on cycle
        return []
