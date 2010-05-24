from django.conf.urls.defaults import *
from django.conf import settings
from views import * 

urlpatterns = patterns('',
   url(r'^edit/(?P<user>[-\w\.]+)/$', edit_friend, name="edit_friend"),
   url(r'^add/(?P<user>[-\w\.]+)/$', add_friend, name="edit_friend"),
   url(r'^remove/(?P<user>[-\w\.]+)/$', remove_friend, name="remove_friend"),
   url(r'^invite/$', invite_users, name="invite_friends"),
   url(r'^$', edit_friends, name="edit_friends"),
)
