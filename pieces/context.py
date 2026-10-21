from django.conf import settings


def site(request):
    return {'readonly': settings.FR_READONLY, 'site_name': 'bibman'}
