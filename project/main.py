from kvstore import KVStore

def main():
    db = KVStore("data.db")
    db.load_from_file()

    while True:
        try:
            cmd = input("> ").strip()
        except EOFError:
            break

        if not cmd:
            continue

        if cmd == "EXIT":
            break

        parts = cmd.split(' ', 2)
        if parts[0] == "SET" and len(parts) == 3:
            db.set(parts[1], parts[2])
        elif parts[0] == "GET" and len(parts) == 2:
            val = db.get(parts[1])
            print(val if val is not None else "Key not found")
        else:
            print("Invalid command. Use SET <key> <value>, GET <key>, EXIT")

if __name__ == "__main__":
    main()
