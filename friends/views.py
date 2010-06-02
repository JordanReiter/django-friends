# Rendering & Requests
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render_to_response
from django.template import RequestContext, TemplateDoesNotExist
from django.contrib import messages
from django_rendering.decorators import render_to

# Authentication & Linking Modules
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
import multi_oauth.oauth as oauth
import multi_oauth.utils as oauth_utils

# Queries, Results & Searching
from django.core.paginator import InvalidPage, Paginator
from django.db.models import Avg, Count, Max, Min, Q
from haystack.query import EmptySearchQuerySet, SearchQuerySet

# Forms
from django.views.decorators.csrf import csrf_protect
from django.forms.formsets import formset_factory
from django.forms.models import modelformset_factory

# Settings
from django.conf import settings
from django.contrib.sites.models import Site

# Utils
import re, datetime
try:
    import json #Works with Python 2.6
except ImportError:
    from django.utils import simplejson as json

# Messaging
if "notification" in settings.INSTALLED_APPS:
    from notification import models as notification
else:
    notification = None

# Locals (used only in Friends)
from friends.models import Contact, Friendship, FriendshipInvitation, JoinInvitation, FriendSuggestion, IMPORTED_TYPES                                            
from friends.forms import MultipleInviteForm, InviteFriendForm, ImportContactForm, ContactForm, FriendshipForm
from friends.exporter import export_vcards
from friends.importer import import_vcards, import_outlook, import_google
from friends.signals import invite
from friends.utils import shared_friends, friends_of_friends


def get_user_profile(user):
    try:
        profile = user.get_profile()
    except AttributeError:
        user = User.objects.get(username=user)
        try:
            profile = user.get_profile()
        except:
            profile = None
    
    if not profile:
        raise Http404("No active profile for %s" % user)
    else:
        return user, profile

@login_required
def my_friends(request):
    return view_friends(request,request.user)

@render_to()
def view_friends(request, user, template_name="friends/friends.html", redirect_to='/'):
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)
    user, profile = get_user_profile(user)
    try:
        show = profile.get_access(request.user)
        if show.get('friends',True)==False or show.get('contacts',True)==False:
            messages.add_message(request, messages.ERROR, "You're not allowed to view contacts for %s." % (user.get_full_name() or user.username))
            return {'success':False}, {'url': redirect_to}
    except AttributeError:
        pass
    friends = Friendship.objects.friends_for_user(user)
    return locals(), template_name

@render_to()
def friend_lookup(request):
    query_tokens = re.split(r'\W+',request.GET.get('q',''))
    matching_friends = Contact.objects.all()
    if query_tokens:
        for token in query_tokens:
            matching_friends = (
                matching_friends.filter(name__icontains=token) |
                matching_friends.filter(first_name__icontains=token) |
                matching_friends.filter(last_name__icontains=token)
            )
    else:
        matching_friends = []
    results = []
    for friend in matching_friends:
        results.append({
            'id':str(friend.id),
            'name':str(friend.name),
            'first_name':str(friend.first_name),
            'last_name':str(friend.last_name),
            'email':str(friend.email),
            'user':str(friend.user.id),
        })
    return results

@render_to()
@csrf_protect
@login_required
def invite_users(request,output_prefix="invite", redirect_to='edit_friends', form_class=MultipleInviteForm, template_name='friends/invite.html'):
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)
    if request.method == 'POST':
        invite_users_form = form_class(data=request.POST, user=request.user)
        if invite_users_form.is_valid():
            total, requests, existing, invitations = invite_users_form.send_invitations()
            messages.add_message(request, messages.SUCCESS,"You have sent invitations to %(invite_count)d email addresses." % {'invite_count':requests+invitations})
            if requests:
                messages.add_message(request, messages.INFO,"%(requests)d email(s) belonged to someone who is already a member of the site, so they received a request to add you as a contact." % {'requests':requests})
            if existing:
                messages.add_message(request, messages.WARNING,"%(existing)d email(s) belonged to someone who is already one of your contacts." % {'existing':existing})
            return {'success':True}, {'url':redirect_to }
    if request.method == 'GET':
        invite_users_form = form_class()
    return locals(), template_name

@render_to()
@csrf_protect
@login_required
def invite_imports(request,output_prefix="invite", redirect_to='edit_friends', form_class=MultipleInviteForm, template_name='friends/invite.html'):
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)
    if request.method == 'POST':
        invite_users_form = form_class(data=request.POST, user=request.user)
        if invite_users_form.is_valid():
            total, requests, existing, invitations = invite_users_form.send_invitations()
            messages.add_message(request, messages.SUCCESS,"You have sent invitations to %(invite_count)d email addresses." % {'invite_count':requests+invitations})
            if requests:
                messages.add_message(request, messages.INFO,"%(requests)d email(s) belonged to someone who is already a member of the site, so they received a request to add you as a contact." % {'requests':requests})
            if existing:
                messages.add_message(request, messages.WARNING,"%(existing)d email(s) belonged to someone who is already one of your contacts." % {'existing':existing})
            return {'success':True}, {'url':redirect_to }
    if request.method == 'GET':
        invite_users_form = form_class()
    return locals(), template_name


@render_to()
@csrf_protect
@login_required
def add_friend(request, friend, template_name='friends/add_friend.html', add_form=InviteFriendForm, redirect_to=None):
    friend, friend_profile = get_user_profile(friend)
    connections = shared_friends(request.user, friend)
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)

    try:
        friendship_allowed = friend_profile.friendship_allowed(request.user)
    except AttributeError:
        friendship_allowed = True

    if not friendship_allowed:
        messages.add_message(request, messages.ERROR,"You're not allowed to add %s as a contact." % (friend.get_full_name() or friend.username))
        if not redirect_to:
            redirect_to = reverse(settings.PROFILE_URL,args=[friend.username])
        return {'success':False}, {'url': redirect}

    if request.method == 'POST':
        add_friend_form = add_form(request.POST,user=request.user,friend=friend,prefix="friend")
        if add_friend_form.is_valid():
            add_friend_form.save()
            messages.add_message(request, messages.SUCCESS,"You have sent a request for %s to be your contact." % (friend.username))
            if not redirect_to:
                redirect_to = reverse(settings.PROFILE_URL,args=[friend.username])
            return {'success':True}, {'url':redirect_to }
    else:
        add_friend_form = add_form(user=request.user, friend=friend, prefix="friend", initial={'to_user':friend})
    return locals(), template_name


@render_to()
def accept_invitation(request, key, template_name="friends/accept_invitation.html", failure_redirect='/', login_redirect=settings.LOGIN_REDIRECT_URL):
    try:
        joininvitation = JoinInvitation.objects.get(confirmation_key__iexact=key)
        invite.send(sender=JoinInvitation, request=request, instance=joininvitation)
        return locals(), template_name
    except JoinInvitation.DoesNotExist:
        messages.add_message(request, messages.ERROR,"Sorry, it looks like this was not a valid invitation code.")
        if '/' not in failure_redirect:
            failure_redirect = reverse(failure_redirect)
        return {'success': False}, {'url':failure_redirect }


@render_to()
@csrf_protect
@login_required
def accept_friendship(request, friend, template_name='confirm.html', redirect_to=None):
    friend, friend_profile = get_user_profile(friend)
    
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)
    
    # because of the threat of cross-site scripting, this action has to be the result of a form posting
    if request.method == 'GET':
        action_display = "approve %s as a friend." % (friend_profile.user.get_full_name() or friend_profile.user.username) 
        yes_display = "Yes, accept request"
        no_display = "No, cancel"
        return locals(), template_name
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return {}, 'base.html'
    try:
        invitation = FriendshipInvitation.objects.get(from_user=friend, to_user=request.user)
        invitation.accept()
        messages.add_message(request, messages.SUCCESS,"%s is now your friend." % (friend_profile.user.get_full_name() or friend_profile.user.username))
        success=True
    except FriendshipInvitation.DoesNotExist:
        messages.add_message(request, messages.ERROR,"It appears you did not receive an invitation from %s" % (friend.first_name or friend.username))
        success=False
    if not redirect_to:
        redirect_to=reverse(settings.PROFILE_URL,args=[friend.username])
    return {'success': success}, {'url':redirect_to }

@render_to()
@csrf_protect
@login_required
def reject_friendship(request, friend, template_name='confirm.html', redirect_to='edit_friends'):
    friend, friend_profile = get_user_profile(friend)
    
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)
    # because of the threat of cross-site scripting, this action has to be the result of a form posting
    if request.method == 'GET':
        action_display = "decline invitation from %s." % (friend_profile.user.get_full_name() or friend_profile.user.username) 
        yes_display = "Yes, decline request"
        no_display = "No, keep request"
        return locals(), template_name
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return {}, 'base.html'
    try:
        invitation = FriendshipInvitation.objects.get(from_user=friend, to_user=request.user)
        invitation.decline()
        success=True
    except FriendshipInvitation.DoesNotExist:
        messages.add_message(request, messages.ERROR,"It appears you did not receive an invitation from %s" % (friend.first_name or friend.username))
        success=False
    return {'success': success}, {'url':redirect_to }

@render_to()
@csrf_protect
@login_required
def remove_contact(request,contact_id,template_name='confirm.html',redirect_to='edit_contacts'):
    try:
        contact = Contact.objects.get(pk=contact_id)
    except:
        messages.add_message(request, messages.ERROR,"No contact record found.")
        

    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)

    #if the method is GET, show a form to avoid csrf
    if request.method == 'GET':
        action_display = "remove %s from contacts." % (contact.name or contact.email) 
        yes_display = "Yes, remove"
        no_display = "No, keep %s" % (contact.name or contact.email)
        return locals(), template_name
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return {'success':False}, {'url':redirect_to }

    contact.deleted = datetime.datetime.now()
    contact.save()
    messages.add_message(request, messages.SUCCESS,"You have removed %s from your contacts." % (contact.get_label()))
    return {'success':True, 'contact_id':contact_id }, {'url':redirect_to }


@render_to()
@csrf_protect
@login_required
def remove_friend(request,friend,template_name='confirm.html',redirect_to='edit_friends'):
    friend, friend_profile = get_user_profile(friend)

    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)

    # confirm that the user can remove this person as a friend
    if not friend_profile.is_friend(request.user.get_profile()):
        messages.add_message(request, messages.ERROR,"%s is not one of your friends" % friend_profile.user.username)
        return {'success':False}, {'url':redirect_to }

    #if the method is GET, show a form to avoid csrf
    if request.method == 'GET':
        action_display = "remove %s as a friend." % friend_profile.user.get_full_name() 
        yes_display = "Yes, remove as friend"
        no_display = "No, keep %s as a friend" % friend_profile.user.get_full_name()
        return locals(), template_name
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return {'success':True}, {'url':redirect_to }

    Friendship.objects.remove(request.user, friend)
    messages.add_message(request, messages.SUCCESS,"You have removed %s from your friends." % (friend_profile.user.get_full_name()))
    return {}, {'url':redirect_to }


def export_friends(request):
    vcard = export_vcards([ec.friend.user for ec in request.user.get_profile().get_friends()])
    response = HttpResponse(vcard, mimetype='text/x-vcard')
    response['Content-Disposition'] = 'attachment; filename=friends.vcf'
    return response    

    
@render_to()
def import_file_contacts(request, form_class=ImportContactForm, template_name='friends/upload_contacts.html', redirect_to="invite_imported"):
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)

    if request.method == 'POST':
        contacts_file_form=form_class(request.POST,request.FILES)
        if contacts_file_form.is_valid():
            friends_file=request.FILES['contacts_file']
            if friends_file.multiple_chunks():
                messages.add_message(request, messages.ERROR,"The file you uploaded is too large.")
            else:
                start = True
                format = None
                contact_file_content = ""
                for chunk in friends_file.chunks():
                    if start == True:
                        if 'VCARD' in chunk:
                            format = 'VCARD'
                        else:
                            ARBITRARY_FIELD_MINIMUM=5
                            first_line = chunk.split('\n')[0]
                            if len(first_line.split(',')) > ARBITRARY_FIELD_MINIMUM or len(first_line.split('\t')) > ARBITRARY_FIELD_MINIMUM:
                                format = 'OUTLOOK' 
                    contact_file_content += chunk
                    start = False
                if format == 'VCARD':
                    imported_type='V'
                    imported, total = import_vcards(contact_file_content, request.user)
                    messages.add_message(request, messages.SUCCESS,'A total of %d emails imported.' % imported)
                    return {'imported':imported, 'total':total}, {'url': redirect_to} 
                elif format == 'OUTLOOK':
                    imported_type='O'
                    imported, total = import_outlook(contact_file_content, request.user)
                    messages.add_message(request, messages.SUCCESS,'A total of %d emails imported.' % imported)
                    return {'imported':imported, 'total':total}, {'url': redirect_to}
                else:
                    messages.add_message(request, messages.ERROR,'The file format you uploaded wasn\'t valid.')
        contacts_file_form=form_class()
        return locals(), template_name

@render_to()
def import_google_contacts(request, redirect_to="invite_imported"):
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)

    import gdata.contacts.service
    import gdata.auth
    AUTH_SCOPE = "http://www.google.com/m8/feeds"
    contacts_service = gdata.contacts.service.ContactsService()
    if request.GET.has_key('token'):
        rsa_key = open(settings.PRIVATE_KEY,'r').read()
        token = gdata.auth.extract_auth_sub_token_from_url(request.get_full_path(),rsa_key=rsa_key)
        imported, total = import_google(token, request.user)
        messages.add_message(request, messages.SUCCESS,'A total of %d emails imported.' % imported)
        return {'imported':imported, 'total':total}, {'url': redirect_to} 
    else:
        next = "http://%s%s" % (
                Site.objects.get_current(),
                reverse('import_google_contacts') 
        )
        url = contacts_service.GenerateAuthSubURL(next, AUTH_SCOPE, False, 1)
        return HttpResponseRedirect(url)


@render_to()
def invite_imported(request, type=None):
    type = request.REQUEST.get('type', type)
    imported_contacts = Contact.objects.filter(owner=request.user).select_related("user__username","user__expert_profile__code")
    if type:
        imported_contacts = imported_contacts.filter(type__iexact=type)
    else:
        imported_contacts = imported_contacts.filter(type__in=[t[0] for t in IMPORTED_TYPES])
    return {'contacts':imported_contacts }, 'friends/invite_imported.html'


@render_to()
@csrf_protect
@login_required
def edit_contact(request, contact_id=None, redirect_to='edit_contacts', form_class=ContactForm, template_name="friends/edit_contact.html"):
    contact = get_object_or_404(Contact,pk=contact_id)
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)

    if request.method == 'POST':
        form=form_class(request.POST, instance=contact, user=request.user)
        if form.is_valid():
            saved_contact = form.save()
            messages.add_message(request, messages.SUCCESS,"Contact information for %s saved." % (saved_contact.name or saved_contact.email))
            return {}, {'url':redirect_to }
    else:
        form=form_class(instance=contact, user=request.user)
    if contact.user:
        try:
            show = contact.user.get_profile().get_access(request.user)
        except:
            pass
    return locals(), template_name

@render_to()
@csrf_protect
@login_required
def edit_friend(request, friend=None, redirect_to='edit_friends', form_class=FriendshipForm, template_name="friends/edit_contact.html"):
    friend, _ = get_user_profile(friend)
    if not Friendship.objects.are_friends(friend, request.user):
        messages.add_message(request, messages.ERROR,"You are not friends with %s." % (friend.get_full_name() or friend.username))
        return {}, {'url':redirect_to }
    contact, _ = Contact.objects.get_or_create(owner=request.user, email=friend.email)
    contact.user = friend
    contact.save()
    return edit_contact(request, contact_id=contact.id, redirect_to=redirect_to, template_name=template_name)

@render_to()
@csrf_protect
@login_required
def invite_contact(request,contact_id=None, template_name="confirm.html", redirect_to="edit_friends"):
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)
    contact = get_object_or_404(Contact,pk=contact_id)
    # because of the threat of cross-site scripting, this action has to be the result of a form posting
    if request.method == 'GET':
        action_display = "send invitation to %s." % (contact.name or contact.email) 
        yes_display = "Yes, send invitation"
        no_display = "No, don't send"
        return locals(), template_name
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return {}, {'url':redirect_to }
    message = request.REQUEST.get('message',None)
    JoinInvitation.objects.send_invitation(request.user, contact.email, message)
    messages.add_message(request, messages.SUCCESS,"Your invitation to %s <%s> has been sent" % (contact.name or contact.email, contact.email))
    return {}, {'url':redirect_to }

@render_to()
@csrf_protect
@login_required
def edit_friends(request, friend=None, redirect_to='edit_friends', form_class=FriendshipForm, template_name="friends/edit_friends.html"):
    redirect_to=request.REQUEST.get(REDIRECT_FIELD_NAME, redirect_to)
    if redirect_to and '/' not in redirect_to:
        redirect_to=reverse(redirect_to)
    if friend:
        friend, friend_profile = get_user_profile(friend)
        if Friendship.objects.are_friends(friend, request.user):
            friendship, _ = Friendship.objects.get_or_create(from_user=request.user, to_user=friend)
        else:
            messages.add_message(request, messages.ERROR,"You are not friends with %s." % (friend.get_full_name() or friend.username))
            return {}, {'url':redirect_to }
        if request.method == 'POST':
            friend_form=form_class(request.POST, user=request.user, friend=friend, prefix=request.POST.get('prefix'))
            if friend_form.is_valid():
                friend_form.save()
                messages.add_message(request, messages.SUCCESS,"Contact information for %s saved." % (friend.first_name or friend.username))
                return {}, {'url':redirect_to }
        else:
            friend_form=form_class(instance=friendship, user=request.user, friend=friend, prefix='friend')
    else:
        friend_forms = []
        friendship_list = request.user.get_profile().get_friends()
        counter = 0
        for f in friendship_list:
            counter += 1
            friendship, _ = Friendship.objects.get_or_create(from_user=request.user, to_user=f['friend'])
            friend_forms.append(form_class(instance=friendship, user=request.user, friend=f['friend'], prefix='friend_%s' % counter))
    return locals(), template_name

@render_to()
@login_required
def recommended_friends(request, template_name="friends/recommended_friends.html"):
    recommended_friends = FriendSuggestion.objects.filter(user=request.user)
    return locals(), template_name

@render_to()
@login_required
def addressbook(request, template_name="friends/addressbook.html"):
    friends = [f['friend'] for f in Friendship.objects.friends_for_user(request.user)]
    contact_list = Contact.objects.select_related("user").filter(owner=request.user)
    contacts = []
    for contact in contact_list:
        c = {}
        c['info']=contact
        c['id']=contact.id
        try:
            c['user'] = contact.user
            c['is_friend'] = contact.user in friends
        except:
            pass
        contacts.append(c)
    return {'contacts':contacts}, template_name

@render_to()
@login_required
def invitations_sent(request, template_name="friends/invitations_sent.html"):
    friend_invitations = FriendshipInvitation.objects.invitations(from_user=request.user)
    join_invitations = JoinInvitation.objects.filter(from_user=request.user,status='2')
    return locals(), template_name

@render_to()
@login_required
def requests_received(request, template_name="friends/requests_received.html"):
    requests_received = FriendshipInvitation.objects.invitations(to_user=request.user)
    return locals(), template_name
