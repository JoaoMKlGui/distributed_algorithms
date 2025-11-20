# Introduction
This project aims to implement the Bully-Election and the Lamport Clock algorithms in distributed nodes and verify their functionality.

The program was developed to run on Google Cloud with three Virtual Machines located on three different regions (us-central1-a, europe-west1-b, southamerica-east1-b).

# How to configure the cloud

## Access Google Cloud

Initially, one need to access the Google Cloud with their respective credentials. In order to do so, execute the command in your local terminal:
```bash
gcloud auth login
```
Then, set a project and enable further useful services:
```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable compute.googleapis.com cloudbuild.googleapis.com
```
From now on, we'll provide examples considering the project name `neural-service-478119-k0`, but in your machine you should adapt the name to your project.

## Build the image
Execute the command
```bash
gcloud builds submit --tag gcr.io/neural-service-478119-k0/ds-node:latest --project=neural-service-478119-k0 .
```
Here, the Cloud Build will utilize the `Dockerfile` to build an image and upload it to the Container Registry (gcr.io) with the name `gcr.io/neural-service-478119-k0/ds-node:latest`.

## Create static external IPs (NAT / public IP) for each region
As our project require nodes to communicate between themselves, establishing a static External IPs for each VM is essential. In order to so, run the commands below:
```bash
gcloud compute addresses create node-us-static-ip --region=us-central1 --project=neural-service-478119-k0

gcloud compute addresses create node-eu-static-ip --region=europe-west1 --project=neural-service-478119-k0

gcloud compute addresses create node-br-static-ip --region=southamerica-east1 --project=neural-service-478119-k0
```

Obs.: An alternative to defining these static External IPs is to utilize the VM's Internal IPs to establish communication.

## Create each VM with the container and the static IP
Now we'll run the commands to create three VMs, one for each region, and already establish a container running within them to execute the image previously uploaded to the registry. Additionally, each will have its own static IP and all of them will be set with the tag `ds-node`. To avoid unnecessary expenses, the machines will run on a `e2-standard-4`. Environment variables will be set with a `NODE_ID` and a `PORT`, which will be by default `50051` - the standard port for the gRPC protocol. However, afterwards the `PEERS` environment variable will also need to be set, so it will be further updated.

```bash
gcloud compute instances create-with-container node-us \
  --zone=us-central1-a \
  --machine-type=e2-standard-4 \
  --address=node-us-static-ip \
  --container-image=gcr.io/neural-service-478119-k0/ds-node:latest \
  --container-env=NODE_ID=1,PORT=50051 \
  --tags=ds-node \
  --project=neural-service-478119-k0

gcloud compute instances create-with-container node-eu \
  --zone=europe-west1-b \
  --machine-type=e2-standard-4 \
  --address=node-eu-static-ip \
  --container-image=gcr.io/neural-service-478119-k0/ds-node:latest \
  --container-env=NODE_ID=2,PORT=50051 \
  --tags=ds-node \
  --project=neural-service-478119-k0

gcloud compute instances create-with-container node-br \
  --zone=southamerica-east1-b \
  --machine-type=e2-standard-4 \
  --address=node-br-static-ip \
  --container-image=gcr.io/neural-service-478119-k0/ds-node:latest \
  --container-env=NODE_ID=3,PORT=50051 \
  --tags=ds-node \
  --project=neural-service-478119-k0
```

## Establish Firewall rule
To ensure nodes can communicate between themselves, we'll set the following firewall rule:
```bash
gcloud compute firewall-rules create allow-ds-nodes-external \
  --allow tcp:50051 \
  --target-tags ds-node \
  --source-ranges=IP_US/32,IP_EU/32,IP_BR/32 \
  --project=neural-service-478119-k0 \
  --description="Allow gRPC traffic between the 3 specific ds-nodes"
```
You need to change the `IP_US`, `IP_EU` and `IP_BR` with their specific External IP's, which can be accessed by the command:
```bash
gcloud compute instances list --project=neural-service-478119-k0
```
If you would like to run tests from your local machine, you should also allow for your IP to send messages:
```bash
gcloud compute firewall-rules create allow-from-my-ip \
  --allow tcp:50051 \
  --source-ranges=MY_IP/32 \
  --target-tags=ds-node \
  --project=neural-service-478119-k0
```
You can visualize your IP by running `curl ifconfig.me` (tested in WSL).

## Update internal environment vairables
In order to inform each node about the other existent peers, we recommend you to create a `.txt` file specifying each information:
```txt
NODE_ID=2
PORT=50051
PEERS=1@10.128.0.4:50051,3@10.158.0.3:50051
```
You must create one file for each node, and the `PEERS` env var must be adapted for each of them following the pattern `ID@IP:PORT, ID@IP:PORT`. Here, the following command will expect files with the names `node-us-env.txt`, `node-eu-env.txt` and `node-br-env.txt`.

**Important note:** In the example being shown, the IP utilized here can be either the External IP or the Internal IP of the VM, as we are working with only one container per VM and we have specified static external IP and a correct Firewall rule. However, to expand this project and include more nodes in the same VM, one must utilize the Internal IPs instead, which means that the messages will move within your VPC (Virtual Private Cloud).

Then, you can update each container with the new defined variables by running the commands below:
```bash
# update node-us (NODE_ID=1)
gcloud compute instances update-container node-us \
  --zone=us-central1-a \
  --container-env-file=node-us-env.txt \
  --project=neural-service-478119-k0


# update node-eu (NODE_ID=2)
gcloud compute instances update-container node-eu \
  --zone=europe-west1-b \
  --container-env-file=node-eu-env.txt \
  --project=neural-service-478119-k0

# update node-br (NODE_ID=3)
gcloud compute instances update-container node-br \
  --zone=southamerica-east1-b \
  --container-env-file=node-br-env.txt \
  --project=neural-service-478119-k0
```

## How to access the VM and visualize logs

To get into the VM, you can utilize SSH:
```bash
gcloud compute ssh node-us \
  --zone=us-central1-a \
  --project=neural-service-478119-k0
```
From within the machine, run the following command to see the containers that are running:
```bash
docker ps
```
As response, you should visualize a container running the image we set preivously. Then, you can run
```bash
docker logs <container-id>
```
to see the logs of the container. Here, you should be able to visualize the logs of the `node_server.py` script and verify if the actions being printed are coehrent with the tests you have run.

## [Extra] How to delete a VM
If you did something wrong, or just want to retry from the beggining you can easily delted a VM using the following command:
```bash
gcloud compute instances delete node-us \
  --zone=us-central1-a \
  --project=neural-service-478119-k0
```
Obviously, you need to change the command to use the name and zone of the machine you want to delete.

# How to run

Initially, from the root of the repository, run the following command to generate the scripts `distributed_pb2.py` and `distributed_pb2_grpc.py`:
```bash
python -m grpc_tools.protoc -I./proto --python_out=. --grpc_python_out=. proto/distributed.proto
```

Afterwards, you must configure the cloud following the steps specified above. Now, to visualize our project working in practice, we recommend you to open four different terminals:
- one for each VM, in which you would access the machine through SSH (as shown above) and see its logs;
- another to trigger tests from your machine (in case of utilizing External IPs)

## Testing the nodes utilizng the `test_runner.py`
In order to send messages to the nodes and visualize their behavior when making an election or updating the Lamport Clock, one can run the following commands:
```bash
python client/test_runner.py --target IP_US:50051 --trigger-internal --count 10 --delay 0.2

python client/test_runner.py --target IP_EU:50051 --start-election

python client/test_runner.py --target IP_BR:50051 --send-lamport --from-id 99 --count 5 --delay 0.2
```

The first simulates `--count` internal events on the machine specified by `--target`. Each event increases the local clock and sends a message to a randomly selected peer. The `--delay` specifies how many seconds should pass between one event and another. The second test triggers the election process on the `--target` node. The last one simulates the delivery of `--count` messages comming from a node with ID specified by `--from-id`. In this case, the `delay` is the simulated elapsed time between the delivery of a message and another. Moreover, the messages are delivered with a clock defined as a randomly selected integer between 1 and 50.

### Important note
If you chose to run the project with the External IPs, you can run these commands from your local machine (and put the External IPs in place of `IP_US`, `IP_EU` and `IP_BR`). However, if you decided to proceed utilizng Internal IPs, you first need to create a SSH tunnel to the VM from your local, and then send the command. In order to do it, you have firstly to open the tunnel:
```bash
gcloud compute ssh node-us --zone=us-central1-a --project=neural-service-478119-k0 -- \
  -L 50051:INTERNAL_US_IP:50051
```
Then, you have to open another terminal and execute:
```bash
python client/test_runner.py --target localhost:50051 --trigger-internal --count 10 --delay 0.2
```