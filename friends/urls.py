from django.conf.urls.defaults import *
from django.conf import settings
from views import * 

urlpatterns = patterns('',
   url(r'^(?P<user>[-\w\.]+)/?$', edit_friend, name="edit_friend"),
   url(r'^?$', edit_friends, name="edit_friends"),
)
