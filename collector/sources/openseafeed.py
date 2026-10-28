# -*- coding: utf-8 -*-
"""
OpenSeaFeed (https://openseafeed.com) - red AIS abierta, datos CC BY 4.0.
Sin clave se usa el nivel libre (rectángulos de hasta 30.000 grados²).
Al suscribirse reenvía la última posición conocida de cada buque
("InitialState"); el muestreo descarta las que tienen más de 15 minutos.
"""
from .base import WsSource


class OpenSeaFeedSource(WsSource):
    name = "openseafeed"
    url = "wss://stream.openseafeed.com/v1/stream"
    requires_key = False

    def subscription(self):
        sub = super().subscription()
        sub["InitialState"] = True
        return sub
