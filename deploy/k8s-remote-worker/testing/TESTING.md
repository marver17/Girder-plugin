# Test end-to-end del worker remoto (senza cluster K8s reale)

Verifica in locale l'intera catena descritta in `ARCHITECTURE.md` §13 prima di
spendere tempo su tunnel WireGuard e cluster K8s reali: un container "esterno"
che raggiunge lo stack DIADEMA **solo** attraverso le porte pubblicate
sull'host (AMQPS 5671, HTTPS 443), esattamente come farebbe un worker remoto
attraverso il tunnel — senza risoluzione dei nomi Docker interni (`rabbitmq`,
`mongodb`, `girder`) e senza accesso alla rete `diadema-full-network`.

Non sostituisce il test sul cluster reale (non replica NetworkPolicy, latenza
del tunnel, o la pubblicazione dell'immagine su un registry esterno — vedi
`../README.md`), ma verifica la parte che conta di più: **isolamento
RabbitMQ/Mongo e corretto funzionamento del canale REST**, con feedback in
pochi minuti invece che dopo aver instaurato l'infrastruttura remota.

## 0. Prerequisiti

- Stack `deploy/full` già avviato e sano: `docker compose -f ../../full/docker-compose.yml ps` mostra tutti i servizi `healthy`.
- `.env` in `deploy/full/` con `REMOTE_WORKER_USER`/`REMOTE_WORKER_PASS` valorizzati e il servizio `init-rabbitmq-remote` eseguito con successo almeno una volta:
  ```bash
  docker compose -f ../../full/docker-compose.yml logs init-rabbitmq-remote
  # atteso: "Utente 'remote-worker' pronto su vhost '/' (permessi limitati a: ^diadema_mriqc$)"
  ```
- Immagine `diadema-diadema-mriqc-worker:latest` già buildata (`docker compose -f ../../full/docker-compose.yml build diadema-mriqc-worker`).

## 1. Estrarre la CA interna

```bash
cd deploy/k8s-remote-worker/testing
docker compose -f ../../full/docker-compose.yml cp nginx:/etc/nginx/certs/ca.crt ./ca.crt
```

## 2. Verificare l'isolamento RabbitMQ *prima* di avviare il worker

L'utente `remote-worker` deve poter leggere/scrivere **solo** sulla coda
`diadema_mriqc`, mai su quelle degli altri worker né sull'API di management.

```bash
# Deve fallire (ACCESS_REFUSED): l'utente remoto non ha permessi su "freesurfer"
docker compose -f ../../full/docker-compose.yml exec rabbitmq \
  rabbitmqctl list_permissions -p / | grep remote-worker
# atteso: configure/write/read = ^diadema_mriqc$ per la riga "remote-worker"

# Verifica diretta con amqps: un tentativo di dichiarare/leggere "freesurfer"
# con le credenziali remote-worker deve essere rifiutato dal broker.
```

Se il pattern non è `^diadema_mriqc$` (o quello impostato in
`REMOTE_WORKER_QUEUES_REGEX`), fermarsi qui: un errore di permessi va
corretto prima di avviare qualunque worker, non dopo.

## 3. Avviare il worker "esterno"

```bash
docker compose -f docker-compose.external-worker.yml \
  --env-file ../../full/.env up --abort-on-container-exit
```

Log attesi:
- connessione AMQPS a `127.0.0.1:5671` riuscita (nessun errore TLS: la CA
  copiata al passo 1 verifica il certificato server via `REQUESTS_CA_BUNDLE`);
- `celery@... ready`, in ascolto sulla coda `diadema_mriqc`.

Se la connessione TLS fallisce con un errore di hostname/certificato,
controllare che `127.0.0.1` sia nel SAN del certificato (`init-certs` lo
include di default) — non è un problema di questo worker ma della CA
generata dallo stack `deploy/full`.

## 4. Sottomettere un job reale

1. Accedere a Girder (`https://127.0.0.1` o la porta configurata), caricare un
   NIfTI di test in un item.
2. Lanciare il job MRIQC su quell'item dall'interfaccia (o via API
   `POST /diadema_pipeline/mriqc/run` — vedere la route REST del plugin).
3. Osservare i log di `external-mriqc-worker`: deve scaricare l'input via
   `GET /api/v1/file/{id}/download` su `https://127.0.0.1/...`, eseguire
   MRIQC, e caricare i risultati via REST.
4. Verificare in Girder che l'item riceva i derivati/il campo di stato
   aggiornato — è la prova che il canale REST worker→Girder funziona
   identico a quello dei worker locali, senza alcun cambio applicativo.

## 5. Controlli negativi (l'assenza è il risultato positivo)

- Il container `external-mriqc-worker` **non** deve avere `mongodb` né
  `rabbitmq` risolvibili come hostname (non è su `diadema-full-network`):
  ```bash
  docker compose -f docker-compose.external-worker.yml exec external-mriqc-worker \
    getent hosts mongodb   # atteso: nessun output / errore di risoluzione
  ```
- Nessuna variabile d'ambiente del container deve puntare a MongoDB
  (`CELERY_RESULT_BACKEND=rpc://` nel compose, non `mongodb://...`).

## 6. Pulizia

```bash
docker compose -f docker-compose.external-worker.yml down -v
rm -f ca.crt
```

## Differenze rispetto al cluster K8s reale

Questo test locale copre l'isolamento applicativo (permessi RabbitMQ,
assenza di Mongo, canale REST) ma **non** replica:
- l'isolamento di rete reale (qui è `network_mode: host` sullo stesso
  Docker host; sul cluster remoto lo fornisce la combinazione tunnel
  WireGuard + `NetworkPolicy`, vedi `../networkpolicy.yaml`);
- la pubblicazione dell'immagine su un registry esterno (qui si usa
  l'immagine buildata localmente);
- lo scaling KEDA basato sulla profondità di coda (qui il worker è singolo
  e sempre acceso, non un `ScaledJob`).

Una volta superato questo test, i passi di verifica end-to-end sul cluster
reale sono quelli descritti nel piano architetturale e in `../README.md`.
