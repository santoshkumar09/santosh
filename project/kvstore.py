import os
import sys

class KVStore:
    def __init__(self, log_path="data.db"):
        self.log_path = log_path
        self.mem = {}
        self._ensure_log()
        self._load()

    def _ensure_log(self):
        # create file if not exists
        if not os.path.exists(self.log_path):
            open(self.log_path, "a", encoding="utf-8").close()

    def _load(self):
        # replay append-only log
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    # format: SET <key> <value>
                    parts = line.split(" ", 2)
                    if len(parts) >= 3 and parts[0] == "SET":
                        _, k, v = parts[0], parts[1], parts[2]
                        self.mem[k] = v
        except FileNotFoundError:
            # first run: nothing to load
            pass

    def set(self, key: str, value: str):
        self.mem[key] = value
        # append to log and fsync for durability
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"SET {key} {value}\n")
            f.flush()
            os.fsync(f.fileno())

    def get(self, key: str):
        if key in self.mem:
            return self.mem[key]
        raise KeyError("Key not found")
