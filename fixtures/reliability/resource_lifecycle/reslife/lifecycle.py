"""A small synchronous acquire/use/release lease."""


class LifecycleError(RuntimeError):
    """The lease is no longer usable."""


class Lease:
    def __init__(self, resource):
        self._resource = resource
        self._closed = False

    def use(self, value):
        return self._resource.use(value)

    def close(self):
        self._resource.release()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def open_lease(provider):
    return Lease(provider.acquire())
