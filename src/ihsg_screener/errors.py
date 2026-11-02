"""Hierarki exception aplikasi."""


class ScreenerError(Exception):
    """Akar seluruh exception aplikasi."""


class ConfigError(ScreenerError):
    """Konfigurasi hilang atau tidak valid. Fatal: exit 2."""


class InsufficientDataError(ScreenerError):
    """Bar historis tidak cukup untuk menghitung indikator. Per-emiten."""


class StaleDataError(ScreenerError):
    """Bar terbaru terlalu lama; kemungkinan hari libur bursa. Global."""


class QuotaExceededError(ScreenerError):
    """Budget kuota NewsAPI habis. Global terdegradasi."""


class LabelMappingError(ScreenerError):
    """Label model sentimen tidak dapat dipetakan. Fatal: exit 2."""


class NotifierError(ScreenerError):
    """Pengiriman notifikasi gagal. Per-emiten."""
