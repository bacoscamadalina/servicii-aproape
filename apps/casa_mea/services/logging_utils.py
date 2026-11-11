"""Privacy-bounded structured logging for production operational events."""

from datetime import datetime, timezone
import json
import logging


class OperationalJsonFormatter(logging.Formatter):
    """Serialize only an explicit allowlist; arbitrary record fields never leak."""

    optional_fields = ("event", "scope", "exception_type")

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            (field, getattr(record, field))
            for field in self.optional_fields
            if hasattr(record, field)
        )
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
