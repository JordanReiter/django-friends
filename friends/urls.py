from django.conf.urls.defaults import *
from django.conf import settings
from views import * 

urlpatterns = patterns('',
   url(r'^invite/(?P<contact_id>[0-9]+)/$', invite_contact, name="invite_contact"),
   url(r'^edit/(?P<contact_id>[0-9]+)/$', edit_contact, name="edit_contact"),
   url(r'^edit/(?P<friend>[-\w\.]+)/$', edit_friend, name="edit_friend"),
   url(r'^add/(?P<friend>[-\w\.]+)/$', add_friend, name="add_friend"),
   url(r'^remove/(?P<contact_id>[0-9]+)/$', remove_contact, name="remove_contact"),
   url(r'^remove/(?P<friend>[-\w\.]+)/$', remove_friend, name="remove_friend"),
   url(r'^invite/$', invite_users, name="invite_friends"),
   url(r'^invite/imports/$', invite_imported, name="invite_imported"),
   url(r'^recommended/$', recommended_friends, name="recommended_friends"),
   url(r'^invitations/$', invitations_sent, name="invitations_sent"),
   url(r'^requests/$', requests_received, name="requests_received"),
   url(r'^accept/(?P<friend>[\w\.]+)/$', accept_friendship, name="accept_friend"),
   url(r'^decline/(?P<friend>[\w\.]+)/$', reject_friendship, name="reject_friendship"),
   url(r'^join/(?P<key>[a-z0-9]+)/?$', accept_invitation, name="friends_accept_join"),
   url(r'^addressbook/$', addressbook, name="edit_contacts"),
   url(r'^import/file/$', import_file_contacts, name="import_file_contacts"),
   url(r'^import/google/$', import_google_contacts, name="import_google_contacts"),
   url(r'^(?P<user>[-\w\.]+)/$', view_friends, name="view_friends"),
   url(r'^$', edit_friends, name="edit_friends"),
)
