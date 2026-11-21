"""Minimal in-process stand-in for google.cloud.firestore.AsyncClient (only what the session service uses)."""
import copy


class _Snap:
    def __init__(self, ref, data):
        self.reference, self.id = ref, ref.id
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)


class _Doc:
    def __init__(self, store, path):
        self._store, self.path = store, path
        self.id = path[-1]

    async def get(self):
        return _Snap(self, self._store.docs.get(self.path))

    async def set(self, data, merge=False):
        if merge and self.path in self._store.docs:
            self._store.docs[self.path].update(copy.deepcopy(data))
        else:
            self._store.docs[self.path] = copy.deepcopy(data)

    async def delete(self):
        self._store.docs.pop(self.path, None)

    def collection(self, name):
        return _Col(self._store, self.path + (name,))


class _Col:
    def __init__(self, store, path, order=None):
        self._store, self.path, self._order = store, path, order

    def document(self, doc_id):
        return _Doc(self._store, self.path + (doc_id,))

    def order_by(self, field):
        return _Col(self._store, self.path, order=field)

    async def stream(self):
        n = len(self.path)
        snaps = [_Snap(_Doc(self._store, p), d) for p, d in list(self._store.docs.items())
                 if len(p) == n + 1 and p[:n] == self.path]
        # parent docs of sub-collections may exist only implicitly
        implicit = {p[:n + 1] for p in self._store.docs if len(p) > n + 1 and p[:n] == self.path}
        snaps += [_Snap(_Doc(self._store, p), {}) for p in implicit if p not in self._store.docs]
        if self._order:
            snaps.sort(key=lambda s: (s.to_dict() or {}).get(self._order, 0))
        for s in snaps:
            yield s


class FakeFirestore:
    def __init__(self):
        self.docs = {}

    def collection(self, name):
        return _Col(self, (name,))
