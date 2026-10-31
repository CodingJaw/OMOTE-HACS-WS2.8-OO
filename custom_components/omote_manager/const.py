"""Constants for OMOTE Manager."""

DOMAIN = "omote_manager"
DEFAULT_PORT = 80
DEFAULT_SCAN_INTERVAL = 90
SUPPORTED_API = "omote-config-v1"

# Avoid copying authentication data, network credentials, and other secrets
# into Home Assistant's config backups. Deployment is deliberately disabled.
SENSITIVE_FILES = frozenset(
    {"HaSettings.json", "DeviceSettings.json", "mqtt.json", "ftp.json"}
)
SAFE_PREFIXES = ("Scenes/", "Pages/", "Commands/", "Devices/", "Actions/")
SAFE_ROOT_FILES = frozenset({"Scenes.json"})
MAX_BACKUP_FILE_BYTES = 64 * 1024
