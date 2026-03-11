"""
Migrazione dati DIADEMA: item.meta → item.diadema

Sposta i campi di elaborazione DIADEMA dal campo generico `item.meta`
al campo dedicato `item.diadema`:

  Prima (vecchio):
    item.meta.diadema_mriqc_status   → item.diadema.mriqc.status
    item.meta.diadema_mriqc_results  → item.diadema.mriqc.results
    item.meta.diadema_mriqc_job_id   → item.diadema.mriqc.job_id
    item.meta.diadema_mriqc_error    → item.diadema.mriqc.error
    (stessa logica per freesurfer e lstai)

Uso:
    python migrate_diadema_fields.py [--dry-run] [--mongo-uri URI] [--db DBNAME]
"""

import argparse
import sys

from pymongo import MongoClient

TOOLS = ["mriqc", "freesurfer", "lstai"]
FIELDS = ["status", "results", "job_id", "error"]

# Mappatura vecchio campo meta → (tool, field)
META_MAP = {}
for _tool in TOOLS:
    for _field in FIELDS:
        # es. diadema_mriqc_status → (mriqc, status)
        META_MAP[f"diadema_{_tool}_{_field}"] = (_tool, _field)


def migrate(db, dry_run=False):
    items = db["item"]

    # Trova tutti gli item che hanno almeno un campo diadema_* in meta
    meta_keys = [f"meta.{k}" for k in META_MAP]
    query = {"$or": [{k: {"$exists": True}} for k in meta_keys]}

    cursor = items.find(query, {"_id": 1, "meta": 1, "name": 1})
    count = 0
    migrated = 0

    for doc in cursor:
        count += 1
        meta = doc.get("meta") or {}

        # Costruisce il dict diadema da impostare
        set_ops = {}
        unset_ops = {}

        for meta_key, (tool, field) in META_MAP.items():
            if meta_key in meta:
                set_ops[f"diadema.{tool}.{field}"] = meta[meta_key]
                unset_ops[f"meta.{meta_key}"] = ""

        if not set_ops:
            continue

        print(f"  Item {doc['_id']} ({doc.get('name', '?')}): {list(set_ops.keys())}")

        if not dry_run:
            items.update_one(
                {"_id": doc["_id"]},
                {"$set": set_ops, "$unset": unset_ops},
            )
        migrated += 1

    return count, migrated


def main():
    parser = argparse.ArgumentParser(
        description="Migra dati DIADEMA da item.meta a item.diadema"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra cosa farebbe senza modificare nulla",
    )
    parser.add_argument(
        "--mongo-uri", default="mongodb://localhost:27017", help="URI MongoDB"
    )
    parser.add_argument("--db", default="girder", help="Nome database")
    args = parser.parse_args()

    print(f"Connessione a {args.mongo_uri}, database '{args.db}'...")
    client = MongoClient(args.mongo_uri)
    db = client[args.db]

    mode = "[DRY RUN]" if args.dry_run else "[LIVE]"
    print(f"\n{mode} Cerco item con campi diadema_* in meta...\n")

    found, migrated = migrate(db, dry_run=args.dry_run)

    print(
        f"\nRisultato: trovati {found} item candidati, {'sarebbero migrati' if args.dry_run else 'migrati'} {migrated}."
    )
    if args.dry_run:
        print("Esegui senza --dry-run per applicare le modifiche.")
    else:
        print("Migrazione completata. Riavvia Girder per applicare i cambiamenti.")

    client.close()


if __name__ == "__main__":
    main()
    main()
