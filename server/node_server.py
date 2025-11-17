"""
gRPC server that implements:
- Lamport clocks
- Bully protocol (simplified)

Expected ENV vars:
- NODE_ID: int (e.g., 1)
- PORT: int (e.g., 50051)
- PEERS: comma-separated list of peers in the format id@host:port (e.g., "2@127.0.0.1:50052, 3@127.0.0.1:50053")

Notes:
- We expect PEERS to include the peer ID (id@host:port) so Bully has ID information.
- The server exposes the RPCs: SendLamport, SendElection, SendOk, SendCoordinator, Health and also: StartElection (starts election locally),
TriggerInternal (generates an internal event and sends a message to a random peer).
"""
import os
import time
import threading
import json
import random
from concurrent import futures

import grpc
import sys
sys.path.append(".")
# generated from proto; assumes you ran grpc_tools.protoc to create them
import distributed_pb2
import distributed_pb2_grpc

# configuration
NODE_ID = int(os.environ.get("NODE_ID", "1"))
PORT = int(os.environ.get("PORT", "50051"))
PEERS_RAW = os.environ.get("PEERS", "")  # format: "2@host:port,3@host:port"
BULLY_OK_TIMEOUT = float(os.environ.get("BULLY_OK_TIMEOUT", "1.5"))  # seconds
BULLY_COORD_WAIT = float(os.environ.get("BULLY_COORD_WAIT", "2.5"))  # seconds

# parse peers
PEERS = []  # list of dicts {'id': int, 'addr': 'host:port'}
if PEERS_RAW.strip():
    for token in PEERS_RAW.split(","):
        token = token.strip()
        if not token:
            continue
        if "@" in token:
            id_part, addr = token.split("@", 1)
            try:
                peer_id = int(id_part)
            except:
                print(f"Invalid peer id in token: {token} (must be integer)")
                continue
            PEERS.append({"id": peer_id, "addr": addr})
        else:
            # fallback: no id supplied -> ignore (we require id@host:port)
            print(f"Peer token '{token}' ignored: expected format id@host:port")

# helper: logging JSON lines
def log(event: str, **kwargs):
    payload = {"ts": time.time(), "node": NODE_ID, "event": event}
    payload.update(kwargs)
    print(json.dumps(payload), flush=True)

class NodeServicer(distributed_pb2_grpc.NodeServicer):
    def __init__(self):
        # Lamport clock
        self.lock = threading.Lock()
        self.local_clock = 0

        # Bully state
        self.leader = None  # leader id
        self.is_leader = False
        self.election_in_progress = False
        self._ok_received_event = threading.Event()

        # For graceful stopping of waiting loops
        self._stop = False

        # Start a background thread to periodically announce status (for debug)
        t = threading.Thread(target=self._status_printer, daemon=True)
        t.start()

    # ========== Lamport RPCs ==========
    def SendLamport(self, request, context):
        """
        request: LamportMsg { clock, from_id, payload }
        """
        with self.lock:
            old = self.local_clock
            self.local_clock = max(self.local_clock, request.clock) + 1
            lc = self.local_clock
        log("receive_lamport", from_id=request.from_id, recv_clock=request.clock, local_clock=lc, payload=request.payload)
        return distributed_pb2.Empty()

    # ========== Bully RPCs ==========
    def SendElection(self, request, context):
        """
        Another node asked us to participate in an election.
        Behavior: send OK back to sender, and if not already in election, start one.
        """
        sender = request.from_id
        log("recv_election", from_id=sender)
        # send OK back
        try:
            self._send_ok_to(sender)
            log("sent_ok", to=sender)
        except Exception as e:
            log("send_ok_failed", to=sender, error=str(e))
        # If we're not already running an election, start one
        if not self.election_in_progress:
            # start in a separate thread to avoid blocking RPC
            threading.Thread(target=self.start_election, daemon=True).start()
        return distributed_pb2.Empty()

    def SendOk(self, request, context):
        sender = request.from_id
        log("recv_ok", from_id=sender)
        # Mark that we got at least one OK
        self._ok_received_event.set()
        return distributed_pb2.Empty()

    def SendCoordinator(self, request, context):
        leader_id = request.leader_id
        log("recv_coordinator", leader=leader_id)
        self.leader = leader_id
        self.is_leader = (self.leader == NODE_ID)
        # stop any election state
        self.election_in_progress = False
        self._ok_received_event.clear()
        return distributed_pb2.Empty()

    def Health(self, request, context):
        # simple health response; keep signature as Empty -> Empty per spec
        log("health_check")
        return distributed_pb2.Empty()

    # Extra RPCs to help tests:
    def StartElection(self, request, context):
        log("start_election_rpc")
        threading.Thread(target=self.start_election, daemon=True).start()
        return distributed_pb2.Empty()

    def TriggerInternal(self, request, context):
        """
        Simulates an internal event: increments local_clock.
        Sends a Lamport message to a peer to create activity.
        """
        with self.lock:
            self.local_clock += 1
            lc = self.local_clock
        log("internal_event", local_clock=lc)
        # Randomly send a Lamport message to a random peer to create communication
        if PEERS:
            peer = random.choice(PEERS)
            try:
                self._send_lamport_to_peer(peer, payload=f"auto from {NODE_ID}")
                log("trigger_sent_lamport", to=peer["id"], to_addr=peer["addr"], local_clock=lc)
            except Exception as e:
                log("trigger_send_failed", to=peer["id"], error=str(e))
        return distributed_pb2.Empty()

    # ========== Implementation helpers ==========
    def _status_printer(self):
        while not self._stop:
            try:
                log("status", local_clock=self.local_clock, leader=self.leader, is_leader=self.is_leader, peers=[p["id"] for p in PEERS])
            except Exception:
                pass
            time.sleep(10)

    def start_election(self):
        """
        Bully algorithm (simplified):
         - send ELECTION to all nodes with id > my id
         - wait for ANY OK for BULLY_OK_TIMEOUT seconds
         - if no OK -> declare self leader and broadcast COORDINATOR
         - if OK -> wait for coordinator announcement for BULLY_COORD_WAIT seconds, otherwise restart election
        """
        log("election_starting")
        self.election_in_progress = True
        self._ok_received_event.clear()
        higher_peers = [p for p in PEERS if p["id"] > NODE_ID]
        if not higher_peers:
            log("no_higher_peers", action="declare_self_leader")
            self._declare_self_leader()
            return

        # Send Election messages to higher peers
        for p in higher_peers:
            try:
                self._send_election_to_peer(p)
                log("sent_election", to=p["id"])
            except Exception as e:
                log("sent_election_failed", to=p["id"], error=str(e))

        # wait for OK
        got_ok = self._ok_received_event.wait(BULLY_OK_TIMEOUT)
        if not got_ok:
            # no OKs -> become leader
            log("no_ok_received", action="declare_self_leader")
            self._declare_self_leader()
            return
        else:
            log("ok_received", action="waiting_for_coordinator")
            # wait for coordinator announcement
            coord_waited = 0.0
            poll_interval = 0.2
            while coord_waited < BULLY_COORD_WAIT:
                if self.leader is not None:
                    log("detected_coordinator", leader=self.leader)
                    self.election_in_progress = False
                    self._ok_received_event.clear()
                    return
                time.sleep(poll_interval)
                coord_waited += poll_interval
            # if we got here, no coordinator arrived -> restart election
            log("no_coordinator_after_ok", action="restart_election")
            self._ok_received_event.clear()
            # simple backoff
            time.sleep(0.5)
            self.start_election()

    def _declare_self_leader(self):
        self.leader = NODE_ID
        self.is_leader = True
        self.election_in_progress = False
        self._ok_received_event.clear()
        # broadcast coordinator
        for p in PEERS:
            try:
                self._send_coordinator_to_peer(p, leader_id=NODE_ID)
                log("sent_coordinator", to=p["id"])
            except Exception as e:
                log("sent_coordinator_failed", to=p["id"], error=str(e))
        log("declared_leader", leader=NODE_ID)

    # ========== RPC client helpers (synchronous, short-lived channels) ==========
    def _send_lamport_to_peer(self, peer, payload=""):
        """
        peer: dict with id, addr
        """
        addr = peer["addr"]
        with grpc.insecure_channel(addr) as ch:
            stub = distributed_pb2_grpc.NodeStub(ch)
            # increment own clock when sending
            with self.lock:
                self.local_clock += 1
                send_clock = self.local_clock
            msg = distributed_pb2.LamportMsg(clock=send_clock, from_id=NODE_ID, payload=payload)
            # use short timeout
            stub.SendLamport(msg, timeout=2.0)

    def _send_election_to_peer(self, peer):
        addr = peer["addr"]
        with grpc.insecure_channel(addr) as ch:
            stub = distributed_pb2_grpc.NodeStub(ch)
            msg = distributed_pb2.ElectionMsg(from_id=NODE_ID)
            stub.SendElection(msg, timeout=2.0)

    def _send_ok_to(self, peer_id):
        """
        peer_id is integer; find its addr
        """
        found = next((p for p in PEERS if p["id"] == peer_id), None)
        if not found:
            raise RuntimeError(f"peer {peer_id} unknown")
        addr = found["addr"]
        with grpc.insecure_channel(addr) as ch:
            stub = distributed_pb2_grpc.NodeStub(ch)
            msg = distributed_pb2.OkMsg(from_id=NODE_ID)
            stub.SendOk(msg, timeout=2.0)

    def _send_coordinator_to_peer(self, peer, leader_id):
        addr = peer["addr"]
        with grpc.insecure_channel(addr) as ch:
            stub = distributed_pb2_grpc.NodeStub(ch)
            msg = distributed_pb2.CoordinatorMsg(leader_id=leader_id)
            stub.SendCoordinator(msg, timeout=10)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
    servicer = NodeServicer()
    distributed_pb2_grpc.add_NodeServicer_to_server(servicer, server)
    bind_addr = f"[::]:{PORT}"
    server.add_insecure_port(bind_addr)
    server.start()
    log("server_started", port=PORT, node_id=NODE_ID, peers=[p["id"] for p in PEERS])
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log("shutting_down")
        server.stop(0)


if __name__ == "__main__":
    serve()
