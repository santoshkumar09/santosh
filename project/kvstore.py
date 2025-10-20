import threading

class Node:
    def __init__(self, key, value, next_node=None):
        self.key = key
        self.value = value
        self.next = next_node

class KVStore:
    def __init__(self, filename):
        self.filename = filename
        self.head = None
        self.lock = threading.Lock()

    def load_from_file(self):
        try:
            with open(self.filename, "r") as f:
                for line in f:
                    parts = line.strip().split(' ', 2)
                    if len(parts) == 3 and parts[0] == "SET":
                        self._index_insert(parts[1], parts[2])
        except FileNotFoundError:
            pass

    def set(self, key, value):
        with self.lock:
            with open(self.filename, "a") as f:
                f.write(f"SET {key} {value}\n")
                f.flush()
            self._index_insert(key, value)

    def get(self, key):
        with self.lock:
            node = self.head
            while node:
                if node.key == key:
                    return node.value
                node = node.next
        return None

    def _index_insert(self, key, value):
        node = self.head
        while node:
            if node.key == key:
                node.value = value
                return
            node = node.next
        self.head = Node(key, value, self.head)
