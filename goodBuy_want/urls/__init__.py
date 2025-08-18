from .want import urlpatterns as want_urlpatterns
from .want_reply import urlpatterns as action_urlpatterns

urlpatterns = want_urlpatterns + action_urlpatterns

