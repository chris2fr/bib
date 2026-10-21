"""Date, heure et fuseau : formats, contrôles et calcul de xdatetime.

date      AAAA-MM-JJ, MM et JJ pouvant valoir 00 (inconnus)
xtime     HH:MM (00:00 à 23:59)
xtimezone nom IANA (Europe/Paris...), facultatif
xdatetime calculé : date et xtime (date complète) -> AAAA-MM-JJTHH:MM, avec le fuseau -> AAAA-MM-JJTHH:MM+02:00"""
import calendar
import re
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
TIME_RE = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


def check_date(value):
    """Message d'erreur si value n'est pas une date ISO AAAA-MM-JJ (MM ou JJ éventuellement 00), sinon None."""
    m = DATE_RE.match(value)
    if not m:
        return 'Format attendu : AAAA-MM-JJ (MM et JJ peuvent valoir 00).'
    y, mo, d = map(int, m.groups())
    if y < 1:
        return 'Année invalide.'
    if mo > 12:
        return 'Mois invalide (00 à 12).'
    if mo == 0 and d:
        return 'Un mois 00 impose un jour 00.'
    if d and d > calendar.monthrange(y, mo)[1]:
        return f'Jour invalide : {y:04d}-{mo:02d} n\'a pas {d} jours.'
    return None


def is_full_date(value):
    """Vrai pour une date réelle, sans 00 (seule une telle date se combine avec une heure)."""
    m = DATE_RE.match(value or '')
    return bool(m) and check_date(value) is None and m[2] != '00' and m[3] != '00'


def check_time(value):
    return None if TIME_RE.match(value) else 'Format attendu : HH:MM (00:00 à 23:59).'


@lru_cache(maxsize=1)
def timezones():
    return sorted(z for z in available_timezones() if not z.startswith(('posix/', 'right/')))


def check_timezone(value):
    return None if value in timezones() else 'Fuseau horaire inconnu (nom IANA attendu, ex. Europe/Paris).'


def make_datetime(date, xtime, tz=None):
    """xdatetime à partir de la date, de l'heure et du fuseau ; None si date complète et heure ne sont pas toutes deux connues."""
    if not (xtime and is_full_date(date) and check_time(xtime) is None):
        return None
    y, mo, d = map(int, date.split('-'))
    h, mi = map(int, xtime.split(':'))
    if tz and check_timezone(tz) is None:
        return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).isoformat(timespec='minutes')
    return f'{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}'
