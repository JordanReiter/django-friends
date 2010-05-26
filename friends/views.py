# Rendering & Requests
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render_to_response
from django.template import RequestContext, TemplateDoesNotExist
from django.contrib import messages

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
from friends.models import Contact, Friendship, FriendshipInvitation, JoinInvitation, FriendSuggestion                                            
from friends.forms import MultipleInviteForm, InviteFriendForm, ImportContactForm, ContactForm, FriendshipForm
from friends.exporter import export_vcards
from friends.importer import import_vcards, import_outlook
from friends.signals import invite


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

def view_friends(request, user, template_name="friends/friends.html", redirect_to='/'):
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    user, profile = get_user_profile(user)
    try:
        show = profile.get_access(request.user)
        if show.get('friends',True)==False or show.get('contacts',True)==False:
            messages.add_message(request, messages.ERROR,"You're not allowed to view contacts for %s." % (user.get_full_name() or user.username))
            return HttpResponseRedirect(redirect_to)
    except AttributeError:
        pass
    friends = Friendship.objects.friends_for_user(user)
    return render_to_response(template_name, locals(), RequestContext(request))

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
    return HttpResponse(json.dumps(results), mimetype='application/json')


@csrf_protect
@login_required
def invite_users(request,output_prefix="invite", redirect_to='edit_friends', invite_form=MultipleInviteForm):
    redirect_to = request.REQUEST.get('next',None) or redirect_to
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    if request.method == 'POST':
        invite_users_form = invite_form(data=request.POST, user=request.user)
        if invite_users_form.is_valid():
            total, requests, existing, invitations = invite_users_form.send_invitations()
            messages.add_message(request, messages.SUCCESS,"You have sent invitations to %(invite_count)d email addresses." % {'invite_count':requests+invitations})
            if requests:
                messages.add_message(request, messages.INFO,"%(requests)d email(s) belonged to someone who is already a member of the site, so they received a request to add you as a contact." % {'requests':requests})
            if existing:
                messages.add_message(request, messages.WARNING,"%(existing)d email(s) belonged to someone who is already one of your contacts." % {'existing':existing})
            return HttpResponseRedirect(redirect_to)
    if request.method == 'GET':
        invite_users_form = invite_form()
    return render_to_response('friends/invite.html', locals(), RequestContext(request))


@csrf_protect
@login_required
def add_friend(request, friend, template_name='friends/add.html', add_form=InviteFriendForm, redirect_to="profile"):
    friend, friend_profile = get_user_profile(friend)

    try:
        friendship_allowed = friend_profile.friendship_allowed(request.user)
    except AttributeError:
        friendship_allowed = True

    if not friendship_allowed:
        messages.add_message(request, messages.ERROR,"You're not allowed to add %s as a contact." % (friend.get_full_name() or friend.username))
        return HttpResponseRedirect(reverse(redirect_to,args=[friend]))

    if request.method == 'POST':
        add_friend_form = add_form(request.POST,user=request.user,friend=friend,prefix="friend")
        if add_friend_form.is_valid():
            add_friend_form.save()
            messages.add_message(request, messages.SUCCESS,"You have sent a request for %s to be your contact." % (friend.username))
            return HttpResponseRedirect(reverse(redirect_to,args=[friend]))
    else:
        add_friend_form = add_form(user=request.user, friend=friend, prefix="friend")
    return render_to_response(template_name, locals(), RequestContext(request))


def accept_invitation(request, key, template_name="friends/accept_invitation.html", failure_redirect='/', login_redirect=settings.LOGIN_REDIRECT_URL):
    try:
        joininvitation = JoinInvitation.objects.get(confirmation_key__iexact=key)
        invite.send(sender=JoinInvitation, request=request, instance=joininvitation)
        return render_to_response(template_name, locals(), RequestContext(request))
    except JoinInvitation.DoesNotExist:
        messages.add_message(request, messages.ERROR,"Sorry, it looks like this was not a valid invitation code.")
        if '/' not in failure_redirect:
            failure_redirect = reverse(failure_redirect)
        return HttpResponseRedirect(failure_redirect)


@csrf_protect
@login_required
def accept_friendship(request,friend,template_name='confirm.html'):
    friend, friend_profile = get_user_profile(friend)
    
    # because of the threat of cross-site scripting, this action has to be the result of a form posting
    if request.method == 'GET':
        action_display = "approve %s as a friend." % (friend_profile.user.get_full_name() or friend_profile.user.username) 
        yes_display = "Yes, add as friend"
        no_display = "No, ignore request"
        return render_to_response(template_name, locals(), RequestContext(request))
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return HttpResponseRedirect(
                reverse('profile',args=[friend])
            )
    try:
        invitation = FriendshipInvitation.objects.get(from_user=friend, to_user=request.user)
        invitation.accept()
        notification.send([friend], "friends_accept", {'friend': request.user,})
        notification.send([request.user], "friends_accept", {'friend': friend_profile,})
        messages.add_message(request, messages.SUCCESS,"%s is now your friend." % (friend_profile.user.get_full_name() or friend_profile.user.username))
    except FriendshipInvitation.DoesNotExist:
        messages.add_message(request, messages.ERROR,"Sorry, it looks like %s didn't invite you as a friend." % (friend.get_full_name() or friend.username))
    return HttpResponseRedirect(reverse('profile',args=[friend.username]))

@csrf_protect
@login_required
def remove_contact(request,contact,template_name='confirm.html',redirect_to='edit_contacts'):
    contact = get_object_or_404(Contact, pk=contact)

    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)

    #if the method is GET, show a form to avoid csrf
    if request.method == 'GET':
        action_display = "remove %s from contacts." % (contact.name or contact.email) 
        yes_display = "Yes, remove"
        no_display = "No, keep" % (contact.name or contact.email)
        return render_to_response(template_name, locals(), RequestContext(request))
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return HttpResponseRedirect(redirect_to)

    contact.deleted = datetime.datetime.now()
    contact.save()
    messages.add_message(request, messages.SUCCESS,"You have removed %s from your contacts." % (contact.get_full_name() or contact.username))
    return HttpResponseRedirect(redirect_to)


@csrf_protect
@login_required
def remove_friend(request,friend,template_name='confirm.html',redirect_to='edit_friends'):
    friend, friend_profile = get_user_profile(friend)

    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)

    # confirm that the user can remove this person as a friend
    if not friend_profile.is_friend(request.user.get_profile()):
        messages.add_message(request, messages.ERROR,"%s is not one of your friends" % friend_profile.user.username)
        return HttpResponseRedirect(redirect_to)

    #if the method is GET, show a form to avoid csrf
    if request.method == 'GET':
        action_display = "remove %s as a friend." % friend_profile.user.get_full_name() 
        yes_display = "Yes, remove as friend"
        no_display = "No, keep %s as a friend" % friend_profile.user.get_full_name()
        return render_to_response(template_name, locals(), RequestContext(request))
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return HttpResponseRedirect(redirect_to)

    Friendship.objects.remove(request.user, friend)
    messages.add_message(request, messages.SUCCESS,"You have removed %s from your friends." % (friend_profile.user.get_full_name()))
    return HttpResponseRedirect(redirect_to)


def export_friends(request):
    vcard = export_vcards([ec.friend.user for ec in request.user.get_profile().get_friends()])
    response = HttpResponse(vcard, mimetype='text/x-vcard')
    response['Content-Disposition'] = 'attachment; filename=friends.vcf'
    return response    

    
def import_file_contacts(request, form_class=ImportContactForm, template_name='friends/upload_contacts.html'):
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
                    total, imported = import_vcards(contact_file_content, request.user)
                    messages.add_message(request, messages.SUCCESS,'A total of %d emails imported.' % imported)
                elif format == 'OUTLOOK':
                    imported_type='O'
                    total, imported = import_outlook(contact_file_content, request.user)
                    messages.add_message(request, messages.SUCCESS,'A total of %d emails imported.' % imported)
            imported_contacts = Contact.objects.filter(owner=request.user, type=imported_type)
            return render_to_response('friends/invite_imported.html', {'contacts':imported_contacts }, RequestContext(request))
    else:
        contacts_file_form=form_class()
        return render_to_response(template_name, locals(), RequestContext(request))


def invite_imported(request):
    return HttpResponse("Invite imported")


@csrf_protect
@login_required
def edit_contact(request, contact_id=None, redirect_to='edit_contacts', form_class=ContactForm, template_name="friends/edit_contact.html"):
    contact = get_object_or_404(Contact,pk=contact_id)
    if request.method == 'POST':
        form=form_class(request.POST, instance=contact, user=request.user)
        if form.is_valid():
            saved_contact = form.save()
            messages.add_message(request, messages.SUCCESS,"Contact information for %s saved." % (saved_contact.name or saved_contact.email))
            return HttpResponseRedirect(redirect_to)
    else:
        form=form_class(instance=contact, user=request.user)
    if contact.user:
        try:
            show = contact.user.get_profile().get_access(request.user)
        except:
            pass
    return render_to_response(template_name, locals(), RequestContext(request))

@csrf_protect
@login_required
def edit_friend(request, friend=None, redirect_to='edit_friends', form_class=FriendshipForm, template_name="friends/edit_contact.html"):
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    friend, _ = get_user_profile(friend)
    if not Friendship.objects.are_friends(friend, request.user):
        messages.add_message(request, messages.ERROR,"You are not friends with %s." % (friend.get_full_name() or friend.username))
        return HttpResponseRedirect(redirect_to)
    contact, _ = Contact.objects.get_or_create(owner=request.user, email=friend.email)
    contact.user = friend
    contact.save()
    return edit_contact(request, contact_id=contact.id, redirect_to=redirect_to, template_name=template_name)

@csrf_protect
@login_required
def invite_contact(request,contact_id=None, template_name="confirm.html", redirect_to="edit_contacts"):
    if '/' not in redirect_to:
        redirect_to=reverse(redirect_to)
    contact = get_object_or_404(Contact,pk=contact_id)
    # because of the threat of cross-site scripting, this action has to be the result of a form posting
    if request.method == 'GET':
        action_display = "send invitation to %s." % (contact.name or contact.email) 
        yes_display = "Yes, send invitation"
        no_display = "No, don't send"
        return render_to_response(template_name, locals(), RequestContext(request))
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return HttpResponseRedirect(redirect_to)
    message = request.REQUEST.get('message',None)
    JoinInvitation.objects.send_invitation(request.user, contact.email, message)
    messages.add_message(request, messages.ERROR,"I sent an invitation to %s" % contact.email)
    return HttpResponseRedirect(redirect_to)


@csrf_protect
@login_required
def edit_friends(request, friend=None, redirect_to='edit_friends', form_class=FriendshipForm, template_name="friends/edit_friends.html"):
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    if friend:
        friend, friend_profile = get_user_profile(friend)
        if Friendship.objects.are_friends(friend, request.user):
            friendship, _ = Friendship.objects.get_or_create(from_user=request.user, to_user=friend)
        else:
            messages.add_message(request, messages.ERROR,"You are not friends with %s." % (friend.get_full_name() or friend.username))
            return HttpResponseRedirect(redirect_to)
        if request.method == 'POST':
            friend_form=form_class(request.POST, user=request.user, friend=friend, prefix=request.POST.get('prefix'))
            if friend_form.is_valid():
                friend_form.save()
                messages.add_message(request, messages.SUCCESS,"Contact information for %s saved." % (friend.first_name or friend.username))
                return HttpResponseRedirect(redirect_to)
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
    return render_to_response(template_name, locals(), RequestContext(request))


@login_required
def addressbook(request, template_name="friends/addressbook.html"):
    related_tables = ['user']
    try:
        profile_table = settings.AUTH_PROFILE_MODULE.split('.')[1].lower()
        related_tables.append(profile_table)
    except:
        pass
    import sys
    sys.stderr.write("The related tables are %s" % related_tables)
    contacts = Contact.objects.select_related(*related_tables).filter(owner=request.user)
    return render_to_response(template_name, locals(), RequestContext(request))
