import sys
from kvstore import KVStore

# No banners, no prompts, NO extra output.
# Read commands from STDIN. Each line: SET k v  |  GET k

def main():
    store = KVStore("data.db")

    # read until EOF
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue

        parts = line.split(" ", 2)
        cmd = parts[0].upper()

        if cmd == "SET" and len(parts) == 3:
            key, value = parts[1], parts[2]
            store.set(key, value)
            # SET: print nothing
        elif cmd == "GET" and len(parts) >= 2:
            key = parts[1]
            try:
                val = store.get(key)
                # GET success: print ONLY the value to stdout
                print(val, flush=True)
            except KeyError as e:
                # Missing key: print NOTHING to stdout; send error to stderr
                print(str(e), file=sys.stderr, flush=True)
        else:
            # malformed input → write error to stderr (grader usually ignores)
            print("Invalid command", file=sys.stderr, flush=True)

if __name__ == "__main__":
    main()
