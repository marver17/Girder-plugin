#!/bin/sh
# ═══════════════════════════════════════════════════════════════════
# Gateway WireGuard generico, guidato da env var — usato identico sia
# lato Girder (deploy/full/docker-compose.yml) sia lato cluster K8s
# remoto (deploy/k8s-remote-worker/wireguard-gateway.yaml), con env
# diverse per i due lati (v. commenti in fondo a questo file).
#
# Instaura il tunnel wg0 punto-punto, poi inoltra (socat) le porte
# applicative locali verso il target giusto: verso i servizi Docker
# interni lato Girder, verso l'IP del peer nel tunnel lato K8s.
# ═══════════════════════════════════════════════════════════════════
set -e

apk add --no-cache wireguard-tools socat >/dev/null

mkdir -p /etc/wireguard
umask 077
{
  echo "[Interface]"
  echo "PrivateKey = ${WG_PRIVATE_KEY:?WG_PRIVATE_KEY mancante}"
  echo "Address = ${WG_ADDRESS:?WG_ADDRESS mancante}"
  echo "ListenPort = ${WG_LISTEN_PORT:-51820}"
  echo ""
  echo "[Peer]"
  echo "PublicKey = ${WG_PEER_PUBLIC_KEY:?WG_PEER_PUBLIC_KEY mancante}"
  echo "AllowedIPs = ${WG_PEER_ALLOWED_IPS:?WG_PEER_ALLOWED_IPS mancante}"
  [ -n "${WG_PEER_ENDPOINT:-}" ] && echo "Endpoint = ${WG_PEER_ENDPOINT}"
  echo "PersistentKeepalive = 25"
} > /etc/wireguard/wg0.conf

wg-quick up wg0

cleanup() {
  wg-quick down wg0 || true
  exit 0
}
trap cleanup TERM INT

# Inoltro applicativo: solo le porte esplicitamente richieste, nessun
# routing L3 generico verso il resto della rete del peer.
[ -n "${FORWARD_5671_TARGET:-}" ] && socat TCP-LISTEN:5671,fork,reuseaddr "TCP:${FORWARD_5671_TARGET}" &
[ -n "${FORWARD_443_TARGET:-}" ] && socat TCP-LISTEN:443,fork,reuseaddr "TCP:${FORWARD_443_TARGET}" &

wait
