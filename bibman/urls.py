from django.urls import path

from pieces import views

urlpatterns = [
    path('', views.list_view, name='list'),
    path('nouvelle/', views.create, name='create'),
    path('p/<str:key>/', views.detail, name='detail'),
    path('p/<str:key>/modifier/', views.edit, name='edit'),
    path('p/<str:key>/supprimer/', views.delete, name='delete'),
    path('p/<str:key>/bib/', views.piece_bib, name='piece_bib'),
    path('audit/', views.audit_view, name='audit'),
    path('doublons/', views.duplicates_view, name='duplicates'),
    path('export/fr.json', views.export_json, name='export_json'),
    path('export/fr.bib', views.export_bib, name='export_bib'),
]
