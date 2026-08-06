# Collegare un Girder locale a un cluster Kubernetes remoto

Guida pratica + log dei test eseguiti per collegare uno stack `deploy/full` (anche in esecuzione
su una macchina di sviluppo, non necessariamente in produzione) a un cluster Kubernetes reale
tramite il gateway WireGuard punto-punto descritto in `ARCHITECTURE.md` §13. Il cluster usato nei
test è `concord` (RKE2, IP fisso `<CLUSTER_PUBLIC_IP>`), ma la procedura è generica.

## Architettura in breve

```
worker MRIQC (Job/ScaledJob) ──▶ Service wireguard-gateway:5671/443 (ClusterIP, namespace diadema-remote)
                                    └─▶ pod wireguard-gateway ──▶ wg0 (tunnel WireGuard) ──▶ gateway lato Girder (docker compose)
                                                                                                └─▶ rabbitmq:5671 (AMQPS) / nginx:443 (HTTPS)
```

- **Il cluster K8s è il lato "server"** del tunnel (ha un IP fisso, ascolta su un `Service`
  NodePort UDP). **Girder è il client**: si connette in uscita, nessuna porta da aprire sulla
  rete dove gira Girder.
- Tunnel punto-punto: ogni gateway inoltra (via `socat`) solo le porte 5671/443 verso il tunnel,
  nessun routing L3 generico — vedi `deploy/full/wireguard/entrypoint.sh` e
  `wireguard-gateway.yaml`.
- Isolamento applicativo: l'utente RabbitMQ dedicato ai worker remoti (`REMOTE_WORKER_USER`) ha
  permessi ristretti via regex alla sola coda offloadata (default `diadema_mriqc`) — vedi
  `deploy/full/docker-compose.yml`, servizio `init-rabbitmq-remote`.

## Procedura eseguita

### 1. Generazione e scambio chiavi WireGuard
```bash
docker run --rm alpine:3 sh -c "apk add --no-cache wireguard-tools >/dev/null 2>&1 && \
  wg genkey | tee /tmp/cluster.key | wg pubkey > /tmp/cluster.pub && \
  wg genkey | tee /tmp/girder.key | wg pubkey > /tmp/girder.pub && \
  echo CLUSTER_PRIV=\$(cat /tmp/cluster.key) && echo CLUSTER_PUB=\$(cat /tmp/cluster.pub) && \
  echo GIRDER_PRIV=\$(cat /tmp/girder.key) && echo GIRDER_PUB=\$(cat /tmp/girder.pub)"
```
Container Alpine effimero, nessuna modifica all'host. Le chiavi private restano ciascuna sul
proprio lato (mai scambiate né committate); solo le pubbliche si scambiano.

### 2. Lato Girder (`deploy/full/.env`, mai committato)
```ini
DIADEMA_EXTRA_SAN=wireguard-gateway.diadema-remote.svc.cluster.local
RABBITMQ_AMQPS_PORT=5671
REMOTE_WORKER_USER=remote-worker
REMOTE_WORKER_PASS=changeme_remote_worker
REMOTE_WORKER_QUEUES_REGEX=^diadema_mriqc$
WG_PRIVATE_KEY=<privata generata al passo 1>
WG_PEER_PUBLIC_KEY=<pubblica cluster>
WG_PEER_ENDPOINT=<CLUSTER_PUBLIC_IP>:30820   # IP fisso cluster + NodePort UDP
WG_ADDRESS=10.90.0.1/24
WG_PEER_ALLOWED_IPS=10.90.0.2/32
WG_LISTEN_PORT=51820
```
`DIADEMA_EXTRA_SAN` è necessario **prima** che `init-certs` generi il certificato (altrimenti
va rigenerato — vedi §5) perché la verifica TLS del worker remoto contro l'hostname del
`Service` K8s funzioni.

### 3. Lato cluster (`kubectl`, contesto `concord`)
```bash
kubectl apply -f namespace.yaml -f priorityclass.yaml

kubectl -n diadema-remote create secret generic wireguard-gateway-keys \
  --from-literal=WG_PRIVATE_KEY=<privata-cluster> \
  --from-literal=WG_PEER_PUBLIC_KEY=<pubblica-girder>

# wireguard-gateway.yaml contiene anche un Secret placeholder (template) da NON applicare:
# escluderlo per non sovrascrivere quello reale appena creato.
python3 -c "
import yaml
docs = [d for d in yaml.safe_load_all(open('wireguard-gateway.yaml')) if d['kind'] != 'Secret']
print(yaml.dump_all(docs))
" | kubectl apply -f -

helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda -n keda --create-namespace

kubectl apply -f networkpolicy.yaml
```

### 4. Apertura della porta UDP verso l'IP fisso del cluster
Azione fuori da `kubectl`, a livello di security group/firewall del provider cloud (nel caso
`concord`: OpenStack-like, security group applicato all'istanza con l'IP floating):
- Ingress, UDP, porta **30820**, remote `0.0.0.0/0` (Girder è client dietro NAT/IP potenzialmente
  dinamico, non c'è una sorgente fissa da cui restringere), applicata allo stesso security group
  già usato per le porte 6443/80/443.
- Nessuna regola egress separata necessaria (security group stateful).

### 5. Avvio dello stack Girder e verifica
```bash
docker compose -f deploy/full/docker-compose.yml up -d mongodb redis rabbitmq \
  init-permissions init-certs init-rabbitmq-certs init-rabbitmq-remote girder nginx wireguard-gateway
```

## Bug incontrati e risolti durante il test

1. **uid/gid errato per l'utente RabbitMQ** (`deploy/full/docker-compose.yml`,
   `init-rabbitmq-certs`): il codice presumeva uid/gid `999:999` (corretto per l'immagine
   Debian-based `rabbitmq`), ma `rabbitmq:3-management-alpine` usa **`100:101`**
   (verificabile con `docker run --rm rabbitmq:3-management-alpine sh -c "id rabbitmq"`). Senza
   la correzione RabbitMQ falliva il boot con `ssl_options.keyfile invalid, file does not exist
   or cannot be read by the node`, pur avendo i file presenti e con permessi apparentemente
   corretti (`640`) — l'owner semplicemente non corrispondeva all'utente reale del processo.
   **Fix**: `chown -R 100:101` invece di `999:999`.
2. **Volume dati RabbitMQ corrotto dopo i tentativi falliti**: una volta corretto l'uid, il
   container continuava comunque a fallire con lo stesso identico errore, perché il volume
   `diadema-full-rabbitmq` (dati Mnesia/Khepri) conteneva stato scritto durante i boot falliti
   precedenti. **Fix**: `docker volume rm diadema-full-rabbitmq` (sicuro solo su stack di
   test/nuovi, senza dati reali da preservare) e riavvio pulito.

## Test eseguiti (tutti superati)

**Stage 1 — Handshake del tunnel**
```bash
docker compose -f deploy/full/docker-compose.yml exec wireguard-gateway wg show   # lato Girder
kubectl -n diadema-remote exec deploy/wireguard-gateway -- wg show                # lato cluster
```
Atteso e ottenuto su entrambi i lati: `latest handshake: N seconds ago`, `transfer` con byte
scambiati in entrambe le direzioni.

**Stage 2 — Canale applicativo attraverso il tunnel** (pod di debug effimero nel namespace
`diadema-remote`, eliminato subito dopo):
```bash
kubectl -n diadema-remote run debug --rm -i --image=alpine:3 --restart=Never --command -- sh -c "
  apk add --no-cache curl openssl >/dev/null 2>&1
  curl -sk https://wireguard-gateway.diadema-remote.svc.cluster.local/api/v1/system/version
  echo | openssl s_client -connect wireguard-gateway.diadema-remote.svc.cluster.local:5671 -brief
"
```
Risultato: risposta REST reale di Girder (`{"release": "...", "serverStartDate": "..."}`) e
handshake TLS 1.3 riuscito su AMQPS — percorso completo pod → Service → gateway K8s → wg0 →
gateway Girder → nginx/rabbitmq confermato funzionante.

**Stage 3 — Isolamento permessi RabbitMQ** (pod di debug con `pika`, credenziali
`REMOTE_WORKER_USER`):
```python
# dichiarazione attiva (non passive=True: serve per far scattare davvero il controllo permessi)
ch.queue_declare(queue='diadema_mriqc', durable=False, auto_delete=True)  # atteso: OK
ch.queue_declare(queue='freesurfer', durable=False, auto_delete=True)     # atteso: negato
```
Risultato:
- `diadema_mriqc`: **consentito**
- `freesurfer`: **`403 ACCESS_REFUSED - configure access to queue 'freesurfer' ... refused for user 'remote-worker'`**

Isolamento confermato: il worker remoto può operare solo sulla coda offloadata, non su quelle
degli altri worker né su exchange/management.

## Cosa manca per un job MRIQC reale end-to-end
1. ~~Pubblicare l'immagine `diadema-mriqc-worker` su un registry raggiungibile dal cluster~~ —
   fatto: `ghcr.io/marver17/diadema-mriqc-worker:latest` (push manuale, vedi `README.md`
   prerequisito 4). Resta da creare l'`imagePullSecret` sul cluster remoto.
2. Applicare `scaledjob-mriqc.yaml`.
3. Sottomettere un job reale da Girder e osservare `kubectl -n diadema-remote get jobs -w`.

## Pulizia dopo un test
```bash
docker compose -f deploy/full/docker-compose.yml down          # lato Girder, se era solo per test
# lato cluster: lasciare wireguard-gateway/KEDA se si continua a lavorarci, altrimenti:
kubectl delete namespace diadema-remote
helm uninstall keda -n keda
```
