"""Мостът към apps/doverie (Z7): ползва се като библиотека, без копиране на код."""
import os
import sys

_DOVERIE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "doverie")
if _DOVERIE not in sys.path:
    sys.path.insert(0, _DOVERIE)

from doverie import osi, pohvati  # noqa: E402,F401
from doverie.config import zaredi as zaredi_doverie  # noqa: E402,F401
from doverie.model import GreshkaModel, GreshkaSadarzhanie, Model, izvadi_json  # noqa: E402,F401
from doverie.ocenka import SISTEMA, chisto, ocenka  # noqa: E402,F401
from doverie.tekst import dumi, izrecheniya, normalizirai, ot_html  # noqa: E402,F401
from doverie.vrata import Vrata, VrataNeBezopasno  # noqa: E402,F401
