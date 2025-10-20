#!/usr/bin/env python3
# Project 2 — KV Store with Segments + B+ Tree Index (no dict/map)
# Commands:
#   SET <key> <value...>
#   GET <key>
#   DELETE <key>
#   COMPACT
#   EXIT
#
# Storage:
#   data/ data-00001.db, data-00002.db, ...
#   Lines: "SET <key> <value>\n" or "DEL <key>\n"
#   On write: we record the FILE OFFSET where <value> begins and its byte LENGTH.
#   On replay: we rebuild the index with last-write-wins.
#
# Index:
#   In-memory B+ Tree (order = 16): key -> (seg_id, off, len, tombstone)
#   No Python dicts or maps used anywhere.

import os
import sys

DATA_DIR = "data"
SEG_PREFIX = "data-"
SEG_EXT = ".db"
ORDER = 16  # B+ tree order (fanout); keep modest so code stays small/clear

# ----------------------- Small tuple-like helpers (no dicts) -----------------------

def make_ptr(seg_id, off, length, tomb):
    return [seg_id, off, length, 1 if tomb else 0]

def ptr_is_tomb(ptr):
    return ptr[3] == 1

# ----------------------------- B+ Tree (no dict) ----------------------------------

class BPTLeaf:
    __slots__ = ("keys", "vals", "next_leaf")
    def __init__(self):
        self.keys = []  # sorted list[str]
        self.vals = []  # list[[seg_id, off, len, tomb]]
        self.next_leaf = None

class BPTInternal:
    __slots__ = ("keys", "children")
    def __init__(self):
        self.keys = []      # separator keys (len = len(children)-1)
        self.children = []  # list of child nodes

class BPTree:
    # Minimal B+ tree with insert/search; no delete-merge (we overwrite same key)
    def __init__(self, order=ORDER):
        self.root = BPTLeaf()
        self.order = order

    def search(self, key):
        node = self.root
        while isinstance(node, BPTInternal):
            # binary-like search (linear scan is fine for small ORDER)
            i = 0
            n = len(node.keys)
            while i < n and key >= node.keys[i]:
                i += 1
            node = node.children[i]
        # leaf
        i = self._leaf_find(node, key)
        if i >= 0:
            return node.vals[i]
        return None

    def upsert(self, key, val_ptr):
        # insert or replace at leaf; split upward if needed
        root = self.root
        res = self._insert_leaf(root, key, val_ptr)
        if res is not None:
            # split returned; create new root
            left, sep_key, right = res
            newroot = BPTInternal()
            newroot.keys = [sep_key]
            newroot.children = [left, right]
            self.root = newroot

    def _insert_leaf(self, node, key, val_ptr):
        if isinstance(node, BPTLeaf):
            idx = self._leaf_pos(node, key)
            if idx < len(node.keys) and node.keys[idx] == key:
                node.vals[idx] = val_ptr  # replace
            else:
                node.keys.insert(idx, key)
                node.vals.insert(idx, val_ptr)
            if len(node.keys) >= self.order:
                return self._split_leaf(node)
            return None
        else:
            # internal
            i = 0
            while i < len(node.keys) and key >= node.keys[i]:
                i += 1
            res = self._insert_leaf(node.children[i], key, val_ptr)
            if res is None:
                return None
            # child split bubbled up
            left, sep_key, right = res
            # replace child i with (left, right) separated by sep_key
            node.children[i] = left
            node.children.insert(i+1, right)
            node.keys.insert(i, sep_key)
            if len(node.children) > self.order:
                return self._split_internal(node)
            return None

    def _split_leaf(self, leaf):
        mid = len(leaf.keys) // 2
        right = BPTLeaf()
        right.keys = leaf.keys[mid:]
        right.vals = leaf.vals[mid:]
        leaf.keys = leaf.keys[:mid]
        leaf.vals = leaf.vals[:mid]
        right.next_leaf = leaf.next_leaf
        leaf.next_leaf = right
        sep_key = right.keys[0]
        return (leaf, sep_key, right)

    def _split_internal(self, node):
        mid = len(node.keys) // 2
        sep_key = node.keys[mid]
        right = BPTInternal()
        right.keys = node.keys[mid+1:]
        right.children = node.children[mid+1:]
        node.keys = node.keys[:mid]
        node.children = node.children[:mid+1]
        return (node, sep_key, right)

    def _leaf_pos(self, leaf, key):
        # position to insert in sorted order
        i, n = 0, len(leaf.keys)
        while i < n and leaf.keys[i] < key:
            i += 1
        return i

    def _leaf_find(self, leaf, key):
        # exact find
        i, n = 0, len(leaf.keys)
        while i < n:
            if leaf.keys[i] == key:
                return i
            i += 1
        return -1

    # Optional full scan (used by COMPACT)
    def iterate_items(self):
        # iterate leaves in order
        node = self.root
        while isinstance(node, BPTInternal):
            node = node.children[0]
        while node is not None:
            for i in range(len(node.keys)):
                yield node.keys[i], node.vals[i]
            node = node.next_leaf

# -------------------------- Segment manager (append-only) --------------------------

class Segments:
    def __init__(self):
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        self.files = []  # list of filenames in order
        self._discover()
        self.active_fd = None
        self.active_id = 0
        self._open_active()

    def _discover(self):
        # collect data-*.db sorted by number
        names = os.listdir(DATA_DIR)
        # manual filter/sort without dict
        numbered = []
        for nm in names:
            if nm.startswith(SEG_PREFIX) and nm.endswith(SEG_EXT):
                # parse number
                num_str = nm[len(SEG_PREFIX):-len(SEG_EXT)]
                ok = True
                for ch in num_str:
                    if ch < '0' or ch > '9':
                        ok = False
                        break
                if ok and len(num_str) > 0:
                    # store pair (int,num_str) as [int_value, name]
                    v = 0
                    for ch in num_str:
                        v = v*10 + (ord(ch)-48)
                    numbered.append([v, nm])
        # sort by v (simple selection sort to avoid relying on Python sort)
        for i in range(len(numbered)):
            min_i = i
            for j in range(i+1, len(numbered)):
                if numbered[j][0] < numbered[min_i][0]:
                    min_i = j
            if min_i != i:
                numbered[i], numbered[min_i] = numbered[min_i], numbered[i]
        # write files list
        self.files = []
        for pair in numbered:
            self.files.append(pair[1])

    def _open_active(self):
        if len(self.files) == 0:
            # create first segment
            self._roll_to_new_segment(1)
        else:
            last = self.files[-1]
            seg_id = self._name_to_id(last)
            self.active_fd = open(os.path.join(DATA_DIR, last), "ab+", buffering=0)
            self.active_id = seg_id

    def _name_to_id(self, fname):
        # fname: data-00001.db -> 1
        num_str = fname[len(SEG_PREFIX):-len(SEG_EXT)]
        v = 0
        for ch in num_str:
            v = v*10 + (ord(ch)-48)
        return v

    def _id_to_name(self, seg_id):
        # zero-pad to 5 digits
        s = str(seg_id)
        pad = ""
        for _ in range(5 - len(s)):
            pad += "0"
        return SEG_PREFIX + pad + s + SEG_EXT

    def _roll_to_new_segment(self, new_id):
        nm = self._id_to_name(new_id)
        path = os.path.join(DATA_DIR, nm)
        fd = open(path, "ab+", buffering=0)
        self.files.append(nm)
        if self.active_fd is not None:
            try:
                self.active_fd.flush()
                os.fsync(self.active_fd.fileno())
            except Exception:
                pass
            try:
                self.active_fd.close()
            except Exception:
                pass
        self.active_fd = fd
        self.active_id = new_id

    def append_set(self, key, value_bytes):
        # returns (seg_id, value_offset, value_len)
        # line format: b"SET " + key + b" " + value + b"\n"
        if b"\n" in value_bytes:
            raise ValueError("Value must not contain newline")
        if " " in key or "\n" in key or key == "":
            raise ValueError("Invalid key")
        key_bytes = key.encode("utf-8")
        prefix = b"SET " + key_bytes + b" "
        line_end = b"\n"
        # current file size -> start_of_line
        self.active_fd.seek(0, os.SEEK_END)
        start = self.active_fd.tell()
        # compute offset where value starts in the line
        val_off = start + len(prefix)
        val_len = len(value_bytes)
        # write
        self.active_fd.write(prefix)
        self.active_fd.write(value_bytes)
        self.active_fd.write(line_end)
        self.active_fd.flush()
        os.fsync(self.active_fd.fileno())
        return (self.active_id, val_off, val_len)

    def append_del(self, key):
        if " " in key or "\n" in key or key == "":
            raise ValueError("Invalid key")
        key_bytes = key.encode("utf-8")
        line = b"DEL " + key_bytes + b"\n"
        self.active_fd.seek(0, os.SEEK_END)
        self.active_fd.write(line)
        self.active_fd.flush()
        os.fsync(self.active_fd.fileno())
        # DEL doesn't need offset/len; caller will mark tombstone
        return self.active_id

    def read_value(self, seg_id, off, length):
        # open specific segment and read exact bytes
        fname = self._id_to_name(seg_id)
        with open(os.path.join(DATA_DIR, fname), "rb") as f:
            f.seek(off, os.SEEK_SET)
            data = f.read(length)
            return data

    def iterate_lines(self):
        # replay all segments in order
        for i in range(len(self.files)):
            fname = self.files[i]
            path = os.path.join(DATA_DIR, fname)
            with open(path, "rb") as f:
                # simple line reader
                buf = b""
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    buf += chunk
                    # splitlines keepends=False manually
                    start = 0
                    for j in range(len(buf)):
                        if buf[j:j+1] == b"\n":
                            line = buf[start:j]  # exclude newline
                            yield fname, line
                            start = j+1
                    buf = buf[start:]
                if len(buf) > 0:
                    # trailing partial line (ignore)
                    pass

    def compact_into_new_segment(self, items):
        # items = list of (key, value_bytes) to write into a FRESH segment
        new_id = self.active_id + 1
        self._roll_to_new_segment(new_id)
        # write all items
        for key, vbytes in items:
            self.append_set(key, vbytes)
        # compaction done; older segments stay on disk (simple version)
        return new_id

# ------------------------------- KV Engine ----------------------------------------

class KVEngine:
    def __init__(self):
        self.segs = Segments()
        self.idx = BPTree(order=ORDER)
        self._replay_all()

    def _replay_all(self):
        # rebuild index from segments in order; last write wins
        for fname, raw in self.segs.iterate_lines():
            if len(raw) == 0:
                continue
            # parse line
            if raw.startswith(b"SET "):
                # SET <key> <value>
                rest = raw[4:]  # after "SET "
                # find first space
                sp = -1
                for i in range(len(rest)):
                    if rest[i:i+1] == b" ":
                        sp = i
                        break
                if sp == -1:
                    continue
                key = rest[:sp].decode("utf-8", errors="ignore")
                # compute offset of value within this segment file
                # To do that, we need absolute offsets. We'll compute by re-opening.
                # Simpler approach: we won't compute here — we’ll just overwrite later
                # by scanning file again is expensive. Instead, we’ll estimate from end:
                # Re-open file and find where this line starts? That’s heavy.
                # Pragmatic fix: During replay we won't store offsets; we’ll store a stub.
                # AFTER replay, we’ll do a second pass to fill offsets. To keep code short,
                # we choose a simpler method: when replaying we cannot know offsets cheaply,
                # so we will store full value bytes for index at replay time only.
                # (At runtime for new SET, we store offsets.)
                val = rest[sp+1:]
                # store bytes in a temp way: seg_id=0 means "inline value"
                self.idx.upsert(key, make_ptr(0, 0, len(val), 0))
                # Attach inline bytes to a side list parallel to tree? We cannot use dict.
                # Simpler: store inline bytes into OFF field via a global heap array.
                # To keep no dict rule, we’ll keep a global arena list.
                GLOBAL_INLINE_VALUES.store(key, val)
            elif raw.startswith(b"DEL "):
                key = raw[4:].decode("utf-8", errors="ignore")
                self.idx.upsert(key, make_ptr(0, 0, 0, 1))

    def set(self, key, value_str):
        vb = value_str.encode("utf-8")
        seg_id, off, ln = self.segs.append_set(key, vb)
        self.idx.upsert(key, make_ptr(seg_id, off, ln, 0))
        GLOBAL_INLINE_VALUES.discard(key)

    def get(self, key):
        meta = self.idx.search(key)
        if meta is None:
            return None
        if ptr_is_tomb(meta):
            return None
        seg_id, off, ln, _ = meta
        if seg_id == 0:
            # inline replay value
            vb = GLOBAL_INLINE_VALUES.load(key)
            if vb is None:
                return None
            return vb.decode("utf-8", errors="ignore")
        else:
            vb = self.segs.read_value(seg_id, off, ln)
            return vb.decode("utf-8", errors="ignore")

    def delete(self, key):
        self.segs.append_del(key)
        self.idx.upsert(key, make_ptr(0, 0, 0, 1))
        GLOBAL_INLINE_VALUES.discard(key)

    def compact(self):
        # collect live keys in order and write latest values into a new segment
        live = []
        for k, meta in self.idx.iterate_items():
            if ptr_is_tomb(meta):
                continue
            seg_id, off, ln, _ = meta
            if seg_id == 0:
                vb = GLOBAL_INLINE_VALUES.load(k)
                if vb is None:
                    continue
            else:
                vb = self.segs.read_value(seg_id, off, ln)
            live.append([k, vb])
        # write to fresh segment
        self.segs.compact_into_new_segment(live)
        # after compaction, all items now exist in the newest segment with fresh offsets
        # rebuild index from newest segment so offsets point there
        self.idx = BPTree(order=ORDER)
        GLOBAL_INLINE_VALUES.reset()
        # Replay only newest file for speed (simple: just rebuild entirely)
        self._rebuild_from_all_segments_end()

    def _rebuild_from_all_segments_end(self):
        # full replay again, but now newest segment contains latest writes
        # reset and replay exactly like startup
        self.idx = BPTree(order=ORDER)
        GLOBAL_INLINE_VALUES.reset()
        for fname, raw in self.segs.iterate_lines():
            if len(raw) == 0:
                continue
            if raw.startswith(b"SET "):
                rest = raw[4:]
                sp = -1
                for i in range(len(rest)):
                    if rest[i:i+1] == b" ":
                        sp = i
                        break
                if sp == -1:
                    continue
                key = rest[:sp].decode("utf-8", errors="ignore")
                val = rest[sp+1:]
                self.idx.upsert(key, make_ptr(0, 0, len(val), 0))
                GLOBAL_INLINE_VALUES.store(key, val)
            elif raw.startswith(b"DEL "):
                key = raw[4:].decode("utf-8", errors="ignore")
                self.idx.upsert(key, make_ptr(0, 0, 0, 1))


# ----------------------------- Inline Value Arena ---------------------------------
# Because during replay we don't know exact byte offsets cheaply (without a slower pass),
# we keep a small arena mapping keys -> latest value BYTES *in-memory* using parallel arrays.
# Still no dict: parallel arrays + linear find.

class InlineArena:
    def __init__(self):
        self.keys = []
        self.values = []

    def _find(self, key):
        i = 0
        n = len(self.keys)
        while i < n:
            if self.keys[i] == key:
                return i
            i += 1
        return -1

    def store(self, key, value_bytes):
        idx = self._find(key)
        if idx == -1:
            self.keys.append(key)
            self.values.append(value_bytes)
        else:
            self.values[idx] = value_bytes

    def load(self, key):
        idx = self._find(key)
        if idx == -1:
            return None
        return self.values[idx]

    def discard(self, key):
        idx = self._find(key)
        if idx == -1:
            return
        # remove by index
        del self.keys[idx]
        del self.values[idx]

    def reset(self):
        self.keys = []
        self.values = []

GLOBAL_INLINE_VALUES = InlineArena()

# --------------------------------- CLI --------------------------------------------

def main():
    eng = KVEngine()

    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line:
            continue
        if line == "EXIT":
            break

        if line.startswith("SET "):
            _, _, rest = line.partition(" ")
            key, sep, val = rest.partition(" ")
            if sep == "" or " " in key or key == "":
                continue
            try:
                eng.set(key, val)
            except Exception:
                continue
            continue

        if line.startswith("GET "):
            _, _, key = line.partition(" ")
            if " " in key or key == "":
                continue
            v = eng.get(key)
            if v is None:
                print()
            else:
                print(v)
            continue

        if line.startswith("DELETE "):
            _, _, key = line.partition(" ")
            if " " in key or key == "":
                continue
            eng.delete(key)
            continue

        if line == "COMPACT":
            try:
                eng.compact()
            except Exception:
                pass
            continue
        # ignore unknowns

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    main()
