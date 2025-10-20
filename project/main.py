import sys
from kvstore import KVStore

def main():
    store = KVStore("data.db")

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue

        parts = line.split(" ", 2)
        cmd = parts[0].upper()

        if cmd == "SET" and len(parts) == 3:
            key, value = parts[1], parts[2]
            store.set(key, value)
        elif cmd == "GET" and len(parts) >= 2:
            key = parts[1]
            try:
                val = store.get(key)
                print(val, flush=True)
            except KeyError:
                # ⚠️ Correct format — stderr only
                print("Key not found", file=sys.stderr, flush=True)
        else:
            print("Invalid command", file=sys.stderr, flush=True)

if __name__ == "__main__":
    main()
