"""
Test script for interacting with the nodes.
Regular use:
  - Send internal events to a node (which increments Lamport and can send messages)
  - Request a node to initiate an election
  - Send a Lamport message with a "virtual" ID to a node (useful for testing)
  - Print instructions to simulate a failure (docker stop)

Examples:
  python client/test_runner.py --trigger-internal --target 127.0.0.1:50051 --count 10 --delay 0.2
  python client/test_runner.py --start-election --target 127.0.0.1:50051
  python client/test_runner.py --send-lamport --target 127.0.0.1:50051 --from-id 9 --count 5 --delay 0.3
"""
import argparse
import time
import random
import grpc

import sys
sys.path.append(".")

import distributed_pb2
import distributed_pb2_grpc

def call_trigger_internal(target, count=1, delay=0.1):
    for i in range(count):
        with grpc.insecure_channel(target) as ch:
            stub = distributed_pb2_grpc.NodeStub(ch)
            try:
                stub.TriggerInternal(distributed_pb2.Empty(), timeout=3.0)
                print(f"[ok] TriggerInternal -> {target}")
            except Exception as e:
                print(f"[err] TriggerInternal -> {target}: {e}")
        time.sleep(delay)

def call_start_election(target):
    with grpc.insecure_channel(target) as ch:
        stub = distributed_pb2_grpc.NodeStub(ch)
        try:
            stub.StartElection(distributed_pb2.Empty(), timeout=5.0)
            print(f"[ok] StartElection -> {target}")
        except Exception as e:
            print(f"[err] StartElection -> {target}: {e}")

def send_lamport(target, from_id=999, count=1, delay=0.1):
    # We simulate a remote sender that attaches a clock. We set a random clock
    for i in range(count):
        with grpc.insecure_channel(target) as ch:
            stub = distributed_pb2_grpc.NodeStub(ch)
            # choosing a fake clock value (test only)
            clk = random.randint(1, 50)
            msg = distributed_pb2.LamportMsg(clock=clk, from_id=from_id, payload=f"test {i}")
            try:
                stub.SendLamport(msg, timeout=2.0)
                print(f"[ok] SendLamport -> {target} from {from_id} clk={clk}")
            except Exception as e:
                print(f"[err] SendLamport -> {target}: {e}")
        time.sleep(delay)

def print_failure_hint(container_name_or_node):
    print("\n--- Simulate failure ---")
    print("To simulate a node crash if you are using docker-compose:")
    print(f"  docker-compose stop {container_name_or_node}")
    print("ou (docker run):")
    print(f"  docker stop <container_id>")
    print("---------------------\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", "-t", help="target host:port", required=True)
    parser.add_argument("--trigger-internal", action="store_true")
    parser.add_argument("--start-election", action="store_true")
    parser.add_argument("--send-lamport", action="store_true")
    parser.add_argument("--from-id", type=int, default=999, help="from id for send-lamport")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()

    if args.trigger_internal:
        call_trigger_internal(args.target, count=args.count, delay=args.delay)
    if args.start_election:
        call_start_election(args.target)
    if args.send_lamport:
        send_lamport(args.target, from_id=args.from_id, count=args.count, delay=args.delay)

    if not (args.trigger_internal or args.start_election or args.send_lamport):
        print("No action selected. Use --trigger-internal, --start-election or --send-lamport")
        sys.exit(1)

    # print hint for simulating failure
    print_failure_hint("nodeX")

if __name__ == "__main__":
    main()
