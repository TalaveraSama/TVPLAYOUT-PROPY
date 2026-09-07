#!/usr/bin/env python3
"""mpv falso para pruebas: implementa el subconjunto IPC JSON que usa TVPlayout (socket UNIX / pipe).
Reproduce cada archivo durante N segundos (según nombre 'dur=X' o 2 s) emitiendo time-pos y end-file eof."""
import json, os, socket, sys, threading, time

ipc = next((a.split("=",1)[1] for a in sys.argv if a.startswith("--input-ipc-server=")), None)
if not ipc:
    sys.exit(2)
try: os.unlink(ipc)
except OSError: pass
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); srv.bind(ipc); srv.listen(1)
conn, _ = srv.accept()
lock = threading.Lock()
state = {"file": None, "pause": False, "start": 0.0, "dur": 0.0, "observed": {}}

def send(obj):
    with lock:
        try: conn.sendall((json.dumps(obj)+"\n").encode())
        except OSError: pass

def player():
    while True:
        time.sleep(0.25)
        f = state["file"]
        if f is None or state["pause"]:
            continue
        pos = time.time() - state["start"]
        send({"event":"property-change","id":1,"name":"time-pos","data":round(pos,2)})
        if pos >= state["dur"]:
            state["file"] = None
            send({"event":"end-file","reason":"eof"})
            send({"event":"property-change","id":4,"name":"idle-active","data":True})

threading.Thread(target=player, daemon=True).start()
buf = b""
while True:
    data = conn.recv(65536)
    if not data: break
    buf += data
    while b"\n" in buf:
        line, buf = buf.split(b"\n",1)
        if not line.strip(): continue
        msg = json.loads(line); cmd = msg.get("command", []); rid = msg.get("request_id")
        name = cmd[0] if cmd else ""
        err = "success"; dat = None
        if name == "loadfile":
            path = cmd[1]
            if not os.path.exists(path):
                send({"event":"end-file","reason":"error","file_error":"no such file"})
            else:
                dur = 2.0
                base = os.path.basename(path)
                if "dur=" in base:
                    try: dur = float(base.split("dur=")[1].split("_")[0].split(".")[0])
                    except ValueError: pass
                state.update(file=path, start=time.time(), dur=dur, pause=False)
                send({"event":"start-file"})
                send({"event":"file-loaded"})
                send({"event":"property-change","id":2,"name":"duration","data":dur})
                send({"event":"property-change","id":4,"name":"idle-active","data":False})
        elif name == "stop":
            if state["file"]: 
                state["file"] = None; send({"event":"end-file","reason":"stop"})
        elif name == "set_property":
            if cmd[1] == "pause":
                if cmd[2] and not state["pause"]:
                    state["pause"] = True; state["_pt"] = time.time()
                elif not cmd[2] and state["pause"]:
                    state["pause"] = False; state["start"] += time.time() - state.get("_pt", time.time())
        elif name == "get_property":
            if cmd[1] == "af-metadata/vu":
                dat = {"lavfi.astats.1.Peak_level": "-12.5", "lavfi.astats.2.Peak_level": "-14.0"}
            else:
                err = "property unavailable"
        elif name == "quit":
            send({"request_id": rid, "error": "success"}); sys.exit(0)
        if rid is not None:
            send({"request_id": rid, "error": err, "data": dat})
