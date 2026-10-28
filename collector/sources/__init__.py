# -*- coding: utf-8 -*-
"""Adaptadores de fuentes AIS intercambiables (DISEÑO.md §1)."""
from .aisstream import AisStreamSource
from .openseafeed import OpenSeaFeedSource

SOURCE_CLASSES = {"openseafeed": OpenSeaFeedSource, "aisstream": AisStreamSource}
