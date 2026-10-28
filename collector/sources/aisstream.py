# -*- coding: utf-8 -*-
"""
aisstream.io (https://aisstream.io) - WebSocket gratuito con clave obligatoria.
Límites publicados: 3 conexiones por cuenta, suscripción en < 3 s y, desde
09/2026, límite de ancho de banda para conexiones sin compresión (por eso se
activa permessage-deflate en la clase base).
"""
from .base import WsSource


class AisStreamSource(WsSource):
    name = "aisstream"
    url = "wss://stream.aisstream.io/v0/stream"
    requires_key = True
