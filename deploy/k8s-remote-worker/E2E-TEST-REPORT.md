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

1. **RISOLTO il 2026-08-07.** Bug dello scaler KEDA RabbitMQ con TLS, causa
   isolata leggendo il sorgente di KEDA v2.20.2
   (`pkg/scalers/rabbitmq_scaler.go`): il campo `EnableTLS` ha tag
   `keda:"name=tls, order=authParams"` — letto **solo** da
   `TriggerAuthentication`, mai dal `metadata:` del trigger nello
   `ScaledJob`, dove l'avevamo messo (`tls: enable`) senza alcun effetto
   (nessun errore di validazione, silenziosamente ignorato). Con
   `EnableTLS` sempre `"disable"` lato KEDA, `buildAMQPConfig` non costruiva
   mai un `tls.Config` con la CA interna — ma la libreria AMQP tentava
   comunque TLS per via dello schema `amqps://` nell'URL, usando il pool di
   CA di sistema (che non conosce la CA interna DIADEMA): da qui `x509:
   certificate signed by unknown authority` anche con la CA giusta
   configurata altrove. Fix: valore `TLS: "enable"` spostato dentro il
   secret `diadema-remote-rabbitmq`, referenziato da un nuovo
   `secretTargetRef` (`parameter: tls`) in `TriggerAuthentication` — vedi
   `scaledjob-mriqc.yaml`, `secret.example.yaml`, `README.md`. Verificato
   live sul cluster `concord`: dopo il fix `READY: True` sullo `ScaledJob` e
   un Job MRIQC reale sottomesso da Girder ha fatto scattare KEDA da solo
   (nessun `Job` k8s manuale), creando il pod, elaborando ed arrivando a
   `job.status = 3` (SUCCESS) in Girder senza intervento manuale — lo
   scaling automatico è ora verificato funzionante end-to-end. Nota a
   parte: lo `ScaledJob` applicato sul cluster era rimasto alla versione con
   il bug `args:`/`ENTRYPOINT []` (punto già "risolto" nel repo ma mai
   ri-applicato al cluster con `kubectl apply` dopo il fix) — vale la pena
   ricontrollare periodicamente che i manifest live non siano andati alla
   deriva rispetto al repo.
2. **RISOLTO il 2026-08-07.** `job.status` in MongoDB bloccato a `2`
   (RUNNING) anche a job applicativamente concluso. Causa isolata leggendo
   il sorgente `girder_worker` installato nel worker: il signal handler
   `gw_task_success` (in `girder_worker.app`) chiama `is_revoked(sender)`
   per distinguere un completamento normale da una cancellazione, PRIMA di
   impostare lo stato SUCCESS del Job. `is_revoked` usa
   `app.control.inspect()` di Celery, che richiede l'exchange
   `reply.celery.pidbox` — non concesso all'utente RabbitMQ remoto
   (permessi ristretti alla sola coda offloadata, per design). L'eccezione
   `AccessRefused` risultante non è né `AttributeError` né
   `StateTransitionException`: `gw_task_success` non la cattura, quindi la
   PUT che chiude il Job non partiva mai. `gw_task_failure` non ha questo
   problema (non chiama `is_revoked`), infatti i job falliti transitavano
   correttamente a ERROR — solo il percorso di successo era bloccato. Il
   sintomo `amq.default ACCESS_REFUSED` osservato in questa sessione era un
   problema **distinto e concorrente** (risolto anch'esso: result backend
   `rpc://` → `cache+memory://`, vedi commit `52b0551`/`4a0965a` su
   `diadema-plugin-hardening`), non la causa dello stato bloccato. Fix in
   `worker_entry.py`: sovrascritto l'attributo `is_revoked` sul modulo
   `girder_worker.app` con una versione che tratta un fallimento del
   controllo remoto come "non revocato" invece di propagare l'eccezione.
   Verificato con un job MRIQC reale: `job.status` arriva a `3` (SUCCESS).
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
