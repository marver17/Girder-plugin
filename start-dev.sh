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

case "${1:-all}" in
  girder)
    echo "=== Avvio Girder server ==="
    exec girder serve --host 0.0.0.0 --database "$GIRDER_MONGO_URI"
    ;;
  worker)
    echo "=== Avvio Celery worker ==="
    exec celery -A girder_worker.app worker -l info --pool=solo
    ;;
  all)
    echo "=== Avvio Girder server in background ==="
    girder serve --host 0.0.0.0 --database "$GIRDER_MONGO_URI" &
    GIRDER_PID=$!

    echo "=== Avvio Celery worker in background ==="
    celery -A girder_worker.app worker -l info --pool=solo &
    WORKER_PID=$!

    echo ""
    echo "Girder PID: $GIRDER_PID"
    echo "Worker PID: $WORKER_PID"
    echo ""
    echo "Per fermare: kill $GIRDER_PID $WORKER_PID"
    echo "Log Girder: tail -f /tmp/girder.log"

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
