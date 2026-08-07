# Worker DIADEMA su cluster Kubernetes remoto

Manifest per eseguire il worker MRIQC (pattern replicabile per FreeSurfer/LST-AI) su un
cluster Kubernetes ospitato in un'altra struttura, raggiungendo RabbitMQ e Girder della sede
principale solo attraverso un tunnel WireGuard **punto-punto**: un gateway in-cluster
(`wireguard-gateway.yaml`) e uno speculare lato Girder (`deploy/full/docker-compose.yml`,
servizio `wireguard-gateway`) — nessun servizio di gestione (RabbitMQ/Mongo) esposto
direttamente, solo AMQPS/HTTPS inoltrati esplicitamente attraverso il tunnel.

> Per il log passo-passo di un collegamento reale già testato (comandi eseguiti, bug incontrati
> e risolti, risultati dei test di handshake/canale/isolamento) vedi
> [`CONNECTING-GIRDER-TO-CLUSTER.md`](./CONNECTING-GIRDER-TO-CLUSTER.md).

## 0. Panoramica del percorso dati

```
worker MRIQC (Job) ──▶ Service wireguard-gateway:5671/443 (ClusterIP)
                          └─▶ pod wireguard-gateway ──▶ wg0 (tunnel) ──▶ gateway lato Girder
                                                                            └─▶ rabbitmq:5671 / nginx:443
```

## 1. Generare e scambiare le chiavi WireGuard (una tantum)

```bash
# Lato cluster
wg genkey | tee cluster-priv.key | wg pubkey > cluster-pub.key
# Lato Girder
wg genkey | tee girder-priv.key | wg pubkey > girder-pub.key
```

Scambiare **solo le chiavi pubbliche** (`cluster-pub.key` ↔ `girder-pub.key`); le chiavi
private restano ciascuna sul proprio lato, mai committate né trasferite insieme.

- Lato Girder: valorizzare `WG_PRIVATE_KEY` (privata Girder) e `WG_PEER_PUBLIC_KEY` (pubblica
  cluster) in `deploy/full/.env`.
- Lato cluster: Secret `wireguard-gateway-keys` (vedi comando sotto).

## 2. Prerequisiti sul cluster

1. **Namespace + priorità**: `kubectl apply -f namespace.yaml -f priorityclass.yaml`.
2. **Un NodePort UDP raggiungibile dall'esterno.** `wireguard-gateway.yaml` pubblica
   `wireguard-gateway-external` su NodePort 30820/UDP. Chiedere a chi amministra il perimetro
   davanti all'IP fisso del cluster di inoltrare una porta UDP verso quel NodePort — stesso
   meccanismo già in uso per `ingress-nginx` (80→30999, 443→31773 sul cluster `concord`).
3. **KEDA** (namespace `keda`), scaler RabbitMQ per `ScaledJob`:
   ```bash
   helm repo add kedacore https://kedacore.github.io/charts
   helm install keda kedacore/keda -n keda --create-namespace
   ```
4. **Registry immagini: GitHub Container Registry.** L'immagine `diadema-mriqc-worker` è
   pubblicata (push manuale, non c'è ancora automazione CI) su
   `ghcr.io/marver17/diadema-mriqc-worker:latest` — pacchetto **privato**. Chi ricostruisce il
   worker deve ripetere il push manualmente (`docker build` con lo stesso `Dockerfile` usato da
   `deploy/full/docker-compose.yml`, poi `docker push`) e tenere allineato il tag in
   `scaledjob-mriqc.yaml`. Creare poi l'`imagePullSecret` sul cluster remoto con un PAT proprio
   (scope `read:packages`):
   ```bash
   kubectl -n diadema-remote create secret docker-registry ghcr-pull-secret \
     --docker-server=ghcr.io --docker-username=<user> --docker-password=<PAT con read:packages>
   ```
5. **CA interna DIADEMA con il SAN del Service K8s.** In `deploy/full/.env` impostare
   `DIADEMA_EXTRA_SAN=wireguard-gateway.diadema-remote.svc.cluster.local` **prima** che
   `init-certs` generi il certificato (rigenerare se già esistente: cancellare il volume
   `diadema-full-certs` o valorizzare la var e ricreare lo stack) — altrimenti la verifica TLS
   del worker remoto verso quell'hostname fallisce.

## 3. Applicare

```bash
kubectl -n diadema-remote create secret generic wireguard-gateway-keys \
  --from-literal=WG_PRIVATE_KEY=<privata-cluster> \
  --from-literal=WG_PEER_PUBLIC_KEY=<pubblica-girder>
kubectl apply -f wireguard-gateway.yaml

kubectl -n diadema-remote create secret generic diadema-remote-rabbitmq \
  --from-literal=CELERY_BROKER_URL="amqps://<REMOTE_WORKER_USER>:<REMOTE_WORKER_PASS>@wireguard-gateway.diadema-remote.svc.cluster.local:5671//" \
  --from-literal=CELERY_RESULT_BACKEND="cache+memory://" \
  --from-literal=TLS="enable"
  # NON "rpc://": richiede diritti sull'exchange "amq.default", negati
  # all'utente RabbitMQ ristretto — causava AccessRefused e Job Girder
  # bloccato a RUNNING(2) anche a job completato (vedi secret.example.yaml).
  # TLS="enable" è letto dallo scaler KEDA via TriggerAuthentication
  # (parameter "tls"), NON dal metadata del trigger in scaledjob-mriqc.yaml
  # dove viene ignorato silenziosamente — vedi commenti lì e in
  # secret.example.yaml per il dettaglio del bug KEDA 2.20.2.
kubectl -n diadema-remote create secret generic diadema-remote-ca \
  --from-file=ca.crt=./ca.crt   # estratto da: docker compose -f ../full/docker-compose.yml cp nginx:/etc/nginx/certs/ca.crt ./ca.crt

kubectl apply -f networkpolicy.yaml
kubectl apply -f scaledjob-mriqc.yaml
```

## 4. Verifica

- `kubectl -n diadema-remote logs deploy/wireguard-gateway` — atteso `wg0` up, nessun errore di
  handshake una volta avviato anche il gateway lato Girder (`docker compose -f deploy/full/docker-compose.yml up -d wireguard-gateway`).
- `rabbitmqctl list_consumers` lato broker deve mostrare un consumer sulla coda
  `diadema_mriqc` quando KEDA scala un Job attivo (`kubectl get scaledjob,jobs -n diadema-remote -w`).
- Sottomettere un job MRIQC reale su un dataset piccolo da Girder e verificare che il pod
  remoto scarichi l'input via HTTPS, elabori, e carichi il risultato via REST
  (`kubectl logs -n diadema-remote job/<nome>`).
- Controllo negativo: nessun log/tentativo di connessione a MongoDB dal pod remoto — verificato
  anche dalla `NetworkPolicy` (`networkpolicy.yaml`), che permette egress solo verso il pod
  `wireguard-gateway` e il DNS interno.

Per una prova rapida senza cluster reale (isolamento RabbitMQ/canale REST, senza tunnel/K8s),
vedi `testing/TESTING.md`.
