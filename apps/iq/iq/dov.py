"""Мостът към apps/doverie (Z7): имената на осите и закръгляването — без копиране на код."""
import os
import sys

_DOVERIE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "doverie")
if _DOVERIE not in sys.path:
    sys.path.insert(0, _DOVERIE)

from doverie.config import OSI_KLUCHOVE  # noqa: E402,F401
from doverie.osi import IMENA as IMENA_OSI, okragli  # noqa: E402,F401
