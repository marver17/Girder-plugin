# Report test end-to-end: worker MRIQC su cluster K8s remoto

Data: 2026-08-06. Cluster reale usato: `concord` (RKE2, kubeconfig locale
`~/.kube/concord-cluster.yml`, fuori repo). Namespace `diadema-remote` e
KEDA già presenti da una sessione precedente; in questa sessione sono stati
completati i pezzi mancanti e fatto un test reale con un job MRIQC vero
sottomesso dall'interfaccia Girder.

**Esito finale: successo end-to-end.** Un job MRIQC reale (file
`sub-D00080948_ses-01_acq-3D-SAG_run-02_T1w.nii.gz`) è stato scaricato dal
worker remoto attraverso il tunnel WireGuard, elaborato con MRIQC, e i
risultati (metriche IQM + report HTML/JSON) sono stati caricati su Girder
via REST. `item.diadema.mriqc.status = "completed"`.

## Cosa è stato fatto in questa sessione

1. **Pubblicazione immagine su GHCR**: `ghcr.io/marver17/diadema-mriqc-worker`
   (pacchetto privato), push manuale da locale. Aggiornati i riferimenti nei
   manifest/doc che avevano il placeholder `<org>` non risolto.
2. **Verifica IP reale nei file committati**: sostituito l'IP pubblico reale
   del cluster di test con `<CLUSTER_PUBLIC_IP>` in `.env.example`,
   `wireguard-gateway.yaml`, `CONNECTING-GIRDER-TO-CLUSTER.md` (resta solo
   in `deploy/full/.env`, gitignored).
3. **Rigenerazione certificato TLS interno**: la CA/cert esistenti non
   includevano ancora il SAN `wireguard-gateway.diadema-remote.svc.cluster.local`
   (`DIADEMA_EXTRA_SAN` era stato aggiunto ma i cert non erano mai stati
   rigenerati). Cancellati i volumi `diadema-full-certs` /
   `diadema-full-rabbitmq-certs` e fatto ripartire `init-certs`.
4. **Creati i secret mancanti sul cluster**: `diadema-remote-rabbitmq`,
   `diadema-remote-ca`, `ghcr-pull-secret` (`kubectl create secret`, non
   committati — vedi `README.md` prerequisito 4).
5. **Applicati `networkpolicy.yaml` e `scaledjob-mriqc.yaml`** sul cluster
   reale.
6. **Trovati e risolti 5 bug reali** (dettaglio sotto) emersi solo
   eseguendo un job vero, non individuabili da una review statica dei
   manifest.
7. **Job Kubernetes manuale di test** (`diadema-mriqc-worker-manual-test`,
   non committato, stesso pod template dello ScaledJob) usato per bypassare
   temporaneamente il bug dello scaler KEDA (punto 4 sotto) e validare la
   pipeline applicativa fino in fondo.

## Bug trovati e risolti

### 1. `args:` incompatibile con `ENTRYPOINT []` (bloccante)
- **File**: `scaledjob-mriqc.yaml`
- **Sintomo**: `exec: "--queues=diadema_mriqc": executable file not found in $PATH`
- **Causa**: il `Dockerfile` del worker ha `ENTRYPOINT []` (vuoto) e l'intero
  comando celery in `CMD`. In Kubernetes, `args:` senza `command:` sostituisce
  il `CMD` invece di completarlo; con `ENTRYPOINT` vuoto, Kubernetes prova a
  eseguire il primo elemento di `args` come binario.
- **Fix**: `command:` esplicito e completo nel manifest (invece di `args:`
  parziale), applicato solo al manifest k8s per non toccare il comportamento
  già testato di `deploy/full/docker-compose.yml`.

### 2. `REQUESTS_CA_BUNDLE` non usata da Celery/kombu per AMQPS (bloccante)
- **File**: `diadema_pipeline/girder_diadema_pipeline/worker_entry.py`
- **Sintomo**: `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
  self-signed certificate in certificate chain`
- **Causa**: `REQUESTS_CA_BUNDLE` è letta solo dalla libreria `requests`
  (chiamate HTTP verso Girder), non da kombu/Celery per la connessione
  AMQPS al broker — serve una config Celery separata (`broker_use_ssl`).
- **Fix**: aggiunto `app.conf.broker_use_ssl = {"ca_certs": ..., "cert_reqs":
  ssl.CERT_REQUIRED}` quando il broker è `amqps://` e `REQUESTS_CA_BUNDLE` è
  presente.

### 3. Config del plugin cancellata da `girder_worker.app` (bloccante, causa del bug #2 persistente)
- **File**: `diadema_pipeline/girder_diadema_pipeline/worker_entry.py`
- **Sintomo**: la fix del punto 2 non aveva alcun effetto anche dopo averla
  applicata — stesso errore TLS identico.
- **Causa**: `girder_worker/app.py` chiama `discover_tasks(app)` (che
  istanzia il plugin, quindi il vecchio `DiademaWorkerPlugin.__init__`
  scriveva su `app.conf` qui) **prima** di
  `app.config_from_object('girder_worker.celeryconfig', force=True)`.
  Accedere a `app.conf` a quel punto forza Celery a congelare la config sui
  soli default correnti; il reload forzato successivo la sovrascrive,
  cancellando ogni modifica fatta nel plugin (non solo `broker_use_ssl`, ma
  anche `broker_heartbeat`, `task_acks_late` ecc. — probabile bug latente
  preesistente, mai emerso prima perché non produce errori visibili
  localmente).
- **Fix**: le assegnazioni a `app.conf` sono state spostate da `__init__`
  (troppo presto) a un handler sul segnale `celery.signals.worker_init`
  (gira dopo il caricamento completo della config).

### 4. `celery.pidbox`/`reply.celery.pidbox` ACCESS_REFUSED (bloccante)
- **File**: `scaledjob-mriqc.yaml`, `worker_entry.py`
- **Sintomo**: `403 ACCESS_REFUSED - configure access to exchange
  'celery.pidbox'/'reply.celery.pidbox' in vhost '/' refused for user
  'remote-worker'`
- **Causa**: l'utente RabbitMQ `remote-worker` ha permessi ristretti via
  regex alla sola coda `diadema_mriqc` (design intenzionale, isolamento).
  Celery però, di default, usa `celery.pidbox`/`reply.celery.pidbox` per il
  proprio protocollo di controllo tra worker (ping/revoke/shutdown, gossip,
  mingle) — a cui l'utente remoto non ha accesso.
- **Fix**: `--without-gossip --without-mingle --without-heartbeat` nel
  comando (copre Gossip/Mingle) **più** `app.conf.worker_enable_remote_control
  = False` in `worker_entry.py` (copre il bootstep "Control", non disattivato
  dai flag CLI) — applicato solo quando il broker è AMQPS con CA (scenario
  worker remoto), non per i worker locali che hanno permessi pieni.

### 5. URL Girder embeddato dal produttore non riscritto per host diversi da localhost (bloccante)
- **File**: `diadema_pipeline/girder_diadema_pipeline/worker_entry.py`
- **Sintomo**: `NameResolutionError("HTTPSConnection(host='nginx', port=443):
  Failed to resolve 'nginx'")` — visto con un **job reale** sottomesso
  dall'utente (non riproducibile con un job di test locale).
- **Causa**: il codice esistente riscriveva l'host del `jobInfoSpec`/
  `girder_api_url` incorporato dal produttore del task solo per i pattern
  `localhost`/`127.0.0.1`. Il Girder server locale (docker-compose) usa
  `GIRDER_API_URL=https://nginx/api/v1` (hostname Docker interno) — non
  intercettato dal filtro precedente, quindi il worker remoto tentava di
  risolvere `nginx`, irraggiungibile fuori dalla rete Docker locale.
- **Fix**: riscrittura **incondizionata** del netloc con quello del
  `GIRDER_API_URL` del worker stesso (via `urlparse`/`urlunparse`), non più
  basata su un elenco di pattern noti.

### 6. Resources troppo basse per MRIQC reale (non bloccante, richiede tuning)
- **File**: `scaledjob-mriqc.yaml`
- **Sintomo**: pod `OOMKilled` a metà elaborazione di un T1w reale con
  `limits.memory: 8Gi`.
- **Fix applicato**: alzato a `requests.memory: 6Gi` / `limits.memory: 16Gi`
  (verificato sufficiente per il file di test usato). Il nodo del cluster ha
  ampio margine (~118Gi allocatable). Questi restano valori empirici da un
  singolo file — vedi problematiche aperte sotto.

## Problematiche ancora aperte (da risolvere)

1. **Bug/limite dello scaler KEDA RabbitMQ con TLS** (non risolto, aggirato).
   Con `tls: enable` + CA passata via `TriggerAuthentication` (parametro
   `ca`, verificato essere il nome corretto analizzando il binario di
   `keda-operator:2.20.2`), lo scaler continua a fallire con `x509:
   certificate signed by unknown authority` — anche con `unsafeSsl: true`,
   che avrebbe dovuto disabilitare la verifica. La CA/catena TLS è stata
   verificata manualmente corretta (`openssl s_client` dallo stesso
   namespace, handshake OK). **Il test end-to-end di questa sessione ha
   bypassato KEDA usando un `Job` Kubernetes manuale** (stesso pod template)
   invece dello `ScaledJob` — quindi lo scaling automatico basato sulla
   profondità di coda **non è ancora verificato funzionante**. Serve capire
   se è un bug noto di KEDA 2.20.2 (verificare changelog/issue tracker) o un
   problema di configurazione più sottile prima di affidarsi allo
   `ScaledJob` in produzione.
2. **`amq.default` ACCESS_REFUSED nei log dopo un task completato con
   successo** (non bloccante, ma da capire). Anche col job riuscito
   correttamente (metriche + upload OK), il worker logga
   `amqp.exceptions.AccessRefused: Basic.publish: (403) ACCESS_REFUSED -
   write access to exchange 'amq.default'`. Sospetto: un meccanismo interno
   di Celery (risposta/stato) che ignora parzialmente `task_ignore_result` o
   `worker_enable_remote_control=False`. Il campo `job.status` in MongoDB
   resta a `2` (RUNNING) anche a job applicativamente concluso
   (`item.diadema.mriqc.status = "completed"`) — probabile conseguenza dello
   stesso problema: l'aggiornamento finale dello stato job Celery/Girder non
   completa. Da investigare prima di fare affidamento sullo stato "job" di
   Girder per i worker remoti (l'endpoint `cleanup_stuck_jobs` menzionato in
   `rest.py` potrebbe già essere pensato per mitigare proprio questo).
3. **Risorse CPU/memoria da ricalibrare su un campione più ampio.** Il
   valore attuale (16Gi limit) è stato validato su **un solo** file reale.
   Andrebbe ripetuto su alcuni dataset rappresentativi (dimensioni/
   risoluzioni diverse) prima di considerarlo definitivo per produzione.
4. **Nessuna automazione CI per l'immagine.** Ogni fix al plugin
   `diadema_pipeline` richiede un rebuild+push manuale di
   `ghcr.io/marver17/diadema-mriqc-worker` (fatto 4 volte in questa sessione
   per iterare sui bug 2-3-4-5) — vedi anche `README.md` prerequisito 4.
   Un workflow GitHub Actions eliminerebbe questo passo manuale e il rischio
   di testare un'immagine non allineata all'ultimo commit.
5. **Bug latente nei worker locali, non solo remoti** (da verificare,
   possibile riflesso del punto 3 dei fix). Se il problema "config
   cancellata da `config_from_object(force=True)`" descritto nel fix #3
   sopra riguardava *tutte* le impostazioni del plugin (non solo
   `broker_use_ssl`, che è l'unica per cui produceva un errore visibile),
   è possibile che anche `broker_heartbeat=0`, `task_acks_late=True`,
   `worker_prefetch_multiplier=1` ecc. non fossero mai realmente applicate
   nemmeno nei worker **locali** prima di questa fix. Non testato
   esplicitamente in questa sessione (il focus era il worker remoto) — da
   verificare con un test mirato locale (es. ispezionare
   `app.conf.task_acks_late` a runtime in un worker locale).
6. **Job Kubernetes manuale di test non pulito.** Il `Job`
   `diadema-mriqc-worker-manual-test` creato per bypassare il bug KEDA (punto
   1) resta sul cluster `diadema-remote` insieme al suo pod — va rimosso
   quando non più necessario per debug (`kubectl -n diadema-remote delete
   job diadema-mriqc-worker-manual-test`), non è stato pensato per restare
   in esecuzione permanentemente.
7. **Secret creati manualmente sul cluster, non versionati** (per design,
   vedi `secret.example.yaml`): `diadema-remote-rabbitmq`,
   `diadema-remote-ca`, `ghcr-pull-secret`, `wireguard-gateway-keys` sul
   cluster `concord` non hanno una fonte di verità versionata — se il
   cluster viene ricreato, vanno rigenerati seguendo `README.md`. Nessuna
   azione necessaria ora, ma da tenere presente per un runbook di
   disaster-recovery.

## File modificati in questa sessione (oltre a questo report)

- `diadema_pipeline/girder_diadema_pipeline/worker_entry.py` — fix #2, #3, #4, #5
- `deploy/k8s-remote-worker/scaledjob-mriqc.yaml` — fix #1, #4, #6, placeholder immagine risolto
- `deploy/k8s-remote-worker/README.md`, `CONNECTING-GIRDER-TO-CLUSTER.md`, `ARCHITECTURE.md` — aggiornati per riflettere la pubblicazione GHCR
- `deploy/full/.env.example`, `deploy/k8s-remote-worker/wireguard-gateway.yaml` — IP reale redatto
</content>
