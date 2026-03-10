#!/bin/bash
# Script di avvio per sviluppo locale nel container Girder
# Avvia Girder server e Celery worker con la configurazione corretta

set -e

# Variabili d'ambiente per i servizi Docker
export GIRDER_MONGO_URI=mongodb://mongodb:27017/girder
export GIRDER_REDIS_URL=redis://redis:6379
export GIRDER_NOTIFICATION_REDIS_URL=redis://redis:6379
export CELERY_BROKER_URL=amqp://girder:girder@rabbitmq:5672//
export CELERY_RESULT_BACKEND=mongodb://mongodb:27017/girder
export PYTHONUNBUFFERED=1
# URL del server Girder raggiungibile dai container worker (usato da _patch_gw_task_prerun)
export GIRDER_API_URL="${GIRDER_API_URL:-http://girder:8080/api/v1}"
# ── Heartbeat / connection stability ────────────────────────────────────────
# Con --pool=solo il thread principale è bloccato durante l'esecuzione del task:
# nessun heartbeat AMQP viene inviato → RabbitMQ chiude la connessione dopo 60 s
# → Celery non riesce ad ACK → il messaggio viene ri-consegnato → loop infinito.
export CELERY_BROKER_HEARTBEAT=0
export CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS=true

case "${1:-all}" in
  girder)
    echo "=== Avvio Girder server ==="
    exec girder serve --host 0.0.0.0 --database "$GIRDER_MONGO_URI"
    ;;
  worker)
    echo "=== Avvio Celery worker ==="
    # Ascolta solo la coda 'celery' (default).
    # La coda 'mriqc' è riservata al container dedicato mriqc-worker (nipreps/mriqc).
    # --heartbeat-interval=0: con --pool=solo il thread principale è bloccato durante
    # l'esecuzione dei task → nessun heartbeat AMQP → RabbitMQ chiude la connessione
    # dopo 60 s → ack fallisce → re-delivery. 0 disabilita l'heartbeat lato client.
    exec celery -A girder_worker.app worker -l info --pool=solo --queues=celery --heartbeat-interval=0
    ;;
  all)
    echo "=== Avvio Girder server in background ==="
    girder serve --host 0.0.0.0 --database "$GIRDER_MONGO_URI" &
    GIRDER_PID=$!

    echo "=== Avvio Celery worker in background ==="
    # Ascolta solo la coda 'celery'. La coda 'mriqc' è del container mriqc-worker.
    celery -A girder_worker.app worker -l info --pool=solo --queues=celery --heartbeat-interval=0 &
    WORKER_PID=$!

    echo ""
    echo "Girder PID: $GIRDER_PID"
    echo "Worker PID: $WORKER_PID"
    echo ""
    echo "Per fermare: kill $GIRDER_PID $WORKER_PID"
    echo "Log Girder: tail -f /tmp/girder.log"

    # Gestione pulita di Ctrl+C: termina i figli senza propagare SIGINT ai loro
    # sottoprocessi Python (evita il Traceback di multiprocessing/spawn.py).
    _shutdown() {
        echo ""
        echo "=== Shutdown in corso... ==="
        kill "$GIRDER_PID" "$WORKER_PID" 2>/dev/null || true
        wait "$GIRDER_PID" 2>/dev/null || true
        wait "$WORKER_PID" 2>/dev/null || true
        echo "=== Shutdown completato ==="
    }
    trap _shutdown INT TERM

    # Aspetta uno dei processi
    wait
    ;;
  *)
    echo "Usage: $0 [girder|worker|all]"
    echo "  girder  - avvia solo Girder server"
    echo "  worker  - avvia solo Celery worker"
    echo "  all     - avvia entrambi (default)"
    exit 1
    ;;
esac
