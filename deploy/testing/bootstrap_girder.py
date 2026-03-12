#!/usr/bin/env python3
"""Bootstrap Girder settings and users on container start."""

from __future__ import annotations

import importlib
import logging
import os
import sys
from typing import Optional

try:  # pragma: no cover - guard for local tooling
    ValidationException = importlib.import_module("girder.exceptions").ValidationException
    Assetstore = importlib.import_module("girder.models.assetstore").Assetstore
    Setting = importlib.import_module("girder.models.setting").Setting
    User = importlib.import_module("girder.models.user").User
    SettingKey = importlib.import_module("girder.settings").SettingKey
except ImportError as import_exc:  # pragma: no cover - guard for local tooling
    raise RuntimeError(
        "Girder is not installed. Run inside the container image where girder is available."
    ) from import_exc

LOG_LEVEL = os.environ.get("BOOTSTRAP_LOGLEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="[bootstrap] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _read_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read a configuration value, supporting *_FILE secrets."""
    file_var = os.environ.get(f"{name}_FILE")
    if file_var:
        try:
            with open(file_var, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except FileNotFoundError:
            logger.warning("Secret file %s referenced by %s not found", file_var, name)
        except OSError as exc:
            logger.error("Failed to read secret file %s for %s: %s", file_var, name, exc)
            raise
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


def _env_bool(name: str) -> Optional[bool]:
    value = _read_secret(name)
    if value is None:
        return None
    return value.lower() in {"1", "true", "yes", "on"}


def ensure_assetstore() -> None:
    path = _read_secret("GIRDER_ASSETSTORE_PATH", "/data/assetstore")
    name = _read_secret("GIRDER_ASSETSTORE_NAME", "Primary Assetstore")
    if not path:
        logger.info("GIRDER_ASSETSTORE_PATH unset; skipping assetstore bootstrap")
        return

    os.makedirs(path, exist_ok=True)
    assetstore_model = Assetstore()

    existing = assetstore_model.findOne({"root": path})
    if existing:
        if not existing.get("current", False):
            existing["current"] = True
            assetstore_model.save(existing)
            logger.info("Marked assetstore '%s' at %s as current", existing["name"], path)
        else:
            logger.debug("Assetstore '%s' already configured", existing["name"])
        return

    assetstore_model.createFilesystemAssetstore(name=name or "Primary", root=path)
    logger.info("Created filesystem assetstore '%s' at %s", name or "Primary", path)


def ensure_admin_user() -> None:
    login = _read_secret("GIRDER_ADMIN_LOGIN")
    password = _read_secret("GIRDER_ADMIN_PASSWORD")
    email = _read_secret("GIRDER_ADMIN_EMAIL")

    if not all([login, password, email]):
        logger.info("Admin bootstrap skipped (login/password/email incomplete)")
        return

    first = _read_secret("GIRDER_ADMIN_FIRST_NAME", "Admin")
    last = _read_secret("GIRDER_ADMIN_LAST_NAME", "User")
    reset_password = _env_bool("GIRDER_ADMIN_RESET_PASSWORD")

    user_model = User()
    login = login.lower()
    user = user_model.findOne({"login": login})

    if user:
        changed = False
        if reset_password:
            user_model.setPassword(user, password)
            logger.info("Reset password for admin user '%s'", login)
        if email and user.get("email") != email:
            user["email"] = email
            changed = True
        if first and user.get("firstName") != first:
            user["firstName"] = first
            changed = True
        if last and user.get("lastName") != last:
            user["lastName"] = last
            changed = True
        if not user.get("admin"):
            user["admin"] = True
            changed = True
        if changed:
            user_model.save(user)
            logger.info("Updated admin profile for '%s'", login)
        else:
            logger.debug("Admin user '%s' already up-to-date", login)
        return

    try:
        user_model.createUser(
            login=login,
            password=password,
            firstName=first or "Admin",
            lastName=last or "User",
            email=email,
            admin=True,
        )
    except ValidationException as exc:
        logger.error("Failed to create admin user '%s': %s", login, exc)
        raise
    logger.info("Created admin user '%s'", login)


def apply_settings() -> None:
    settings_model = Setting()

    string_settings = {
        "GIRDER_BRAND_NAME": SettingKey.BRAND_NAME,
        "GIRDER_CONTACT_EMAIL": SettingKey.CONTACT_EMAIL_ADDRESS,
        "GIRDER_REGISTRATION_POLICY": SettingKey.REGISTRATION_POLICY,
        "GIRDER_EMAIL_VERIFICATION": SettingKey.EMAIL_VERIFICATION,
    }

    for env_name, key in string_settings.items():
        value = _read_secret(env_name)
        if value:
            if key in {SettingKey.REGISTRATION_POLICY, SettingKey.EMAIL_VERIFICATION}:
                value = value.lower()
            try:
                settings_model.set(key, value)
                logger.info("Set setting '%s'", key)
            except ValidationException as exc:
                logger.error("Invalid value for %s: %s", key, exc)
                raise

    bool_settings = {
        "GIRDER_ENABLE_PASSWORD_LOGIN": SettingKey.ENABLE_PASSWORD_LOGIN,
    }

    for env_name, key in bool_settings.items():
        value = _env_bool(env_name)
        if value is None:
            continue
        try:
            settings_model.set(key, value)
            logger.info("Set setting '%s' to %s", key, value)
        except ValidationException as exc:
            logger.error("Invalid value for %s: %s", key, exc)
            raise


def _setup_girder_context() -> None:
    """Inizializza la connessione a MongoDB per l'esecuzione standalone.

    Viene chiamata solo quando lo script è eseguito direttamente (non importato),
    in modo da configurare il contesto Girder prima di usare i modelli.
    """
    mongo_uri = os.environ.get("GIRDER_MONGO_URI", "mongodb://mongodb:27017/girder")
    try:
        from girder.utility import config as cfg_util  # type: ignore[import-untyped]
        from girder.utility.server import ServerMode, create_app  # type: ignore[import-untyped]

        cfg = cfg_util.getConfig()
        # Config è dict-like (cherrypy style)
        if "database" not in cfg:
            cfg["database"] = {}
        cfg["database"]["uri"] = mongo_uri

        create_app(ServerMode.PRODUCTION)
        logger.debug("Girder context initialized (mongo: %s)", mongo_uri)
    except Exception as exc:
        logger.error("Failed to initialize Girder context: %s", exc)
        raise


def main() -> int:
    try:
        ensure_assetstore()
        apply_settings()
        ensure_admin_user()
    except Exception:
        logger.exception("Girder bootstrap failed")
        return 1
    return 0


if __name__ == "__main__":
    _setup_girder_context()
    sys.exit(main())
