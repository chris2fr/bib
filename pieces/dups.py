"""Doublons déclarés : le champ xdup d'une entrée donne la clé d'une autre entrée de la table pieces dont elle est le doublon.

Un doublon est parfois nécessaire (d'anciens documents le citent) : on le garde, mais en le rattachant à l'entrée de référence.
Une seule couche : la cible n'est pas elle-même un doublon, et une entrée citée comme cible ne peut pas devenir doublon."""
from .models import Piece


def xdup_error(own_key, target_key, current_key=None):
    """Message d'erreur si own_key ne peut pas être déclarée doublon de target_key, sinon None.
    current_key : clé enregistrée de l'entrée (différente de own_key si elle est renommée dans le même formulaire)."""
    if target_key in (own_key, current_key):
        return 'Une entrée ne peut pas être son propre doublon.'
    target = Piece.objects.filter(key=target_key).values('xdup').first()
    if target is None:
        return f'Aucune entrée n\'a la clé « {target_key} ».'
    if target['xdup']:
        return f'« {target_key} » est elle-même un doublon de « {target["xdup"]} » : indiquez plutôt « {target["xdup"]} ».'
    refs = list(Piece.objects.filter(xdup=current_key or own_key).values_list('key', flat=True)[:3])
    if refs:
        return f'Cette entrée est déjà la cible de doublons ({", ".join(refs)}) : elle ne peut pas être elle-même un doublon.'
    return None


def referrers(key):
    """[(clé, titre)] des entrées déclarées doublons de key."""
    return list(Piece.objects.filter(xdup=key).order_by('key').values_list('key', 'title'))
