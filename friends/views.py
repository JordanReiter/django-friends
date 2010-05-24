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

# Locals (used only in Friends)
from friends.models import Contact, Friendship, FriendshipInvitation, JoinInvitation, FriendSuggestion                                            
from friends.forms import *
from friends.exporter import export_vcards
from friends.importer import import_vcards

# Utils
import re, datetime
try:
    import json #Works with Python 2.6
except ImportError:
    from django.utils import simplejson as json

def get_user_profile(user):
    try:
        profile = user.get_profile()
    except AttributeError:
        user = User.objects.get(code=user)
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

def view_friends(request, user, template_name="friends/friends.html"):
    user, profile = get_user_profile(user)
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
        invite_users_form = invite_form(data=request.POST)
        if invite_users_form.is_valid():
            me = request.user.get_profile()
            invited_emails = [email for email in invite_users_form.cleaned_data.get('invited_emails')]
            invited_count = len(invited_emails)
            existing_users = User.objects.filter(email__in=invited_emails)
            if existing_users:
                for user in existing_users:
                    invitation = FriendshipInvitation(from_user=request.user, to_user=user, message=None, status="2")
                    invitation.save()
                    if notification:
                        notification.send([user], "friends_invite", {"invitation": invitation})
                        notification.send([request.user], "friends_invite_sent", {"invitation": invitation})
                for user in existing_users:
                    invited_emails.remove(user.email)
            for email in invited_emails:
                JoinInvitation.objects.send_invitation(request.user, email, None)
    if request.method == 'GET':
        invite_users_form = invite_form()
    return render_to_response('friends/invite.html', locals(), RequestContext(request))


@csrf_protect
@login_required
def add_friend(request,friend,template_name='confirm.html',add_form=InviteFriendForm, redirect_to="profile"):
    friend, friend_profile = get_user_profile()

    if request.method == 'POST':
        add_friend_form = add_form(request.POST,user=request.user,friend=friend,prefix="friend")
        if add_friend_form.is_valid():
            add_friend_form.save()
            messages.add_message(request, messages.SUCCESS,"You have sent a request for %s to be your friend." % (friend.username))
            return HttpResponseRedirect(reverse(redirect_to,args=[friend]))
    else:
        add_friend_form = add_form(expert=request.user,friend=friend,prefix="friend")
    return render_to_response('friends/add.html', locals(), RequestContext(request))


@csrf_protect
@login_required
def accept_friendship(request,friend,template_name='confirm.html'):
    friend, friend_profile = get_user_profile()
    
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
    friend, friend_profile = get_user_profile()

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
    
def get_file_friends(request):
    display_import = False
    if request.method == 'POST':
        friend_file_form=ImportContactForm(request.POST,request.FILES)
        if friend_file_form.is_valid():
            friends_file=request.FILES['friends_file']
            if friends_file.multiple_chunks():
                messages.add_message(request, messages.ERROR,"The file you uploaded is too large.")
            else:
                start = True
                format = None
                friend_file_content = ""
                for chunk in friends_file.chunks():
                    if start == True:
                        if 'VCARD' in chunk:
                            format = 'VCARD'
                    friend_file_content += chunk
                if format == 'VCARD':
                    display_import = True
                    my_friends = import_vcards(friend_file_content)
            if display_import:
                already_friends_ids = [ec.friend.user.id for ec in Expert_Contact.objects.filter(expert_profile=request.user.get_profile())]
                existing_users = User.objects.filter(email__in=[k['email'] for k in my_friends]).order_by('last_name','first_name')
                existing_lookup = {}
                for user in existing_users:
                    existing_lookup[user.email] = user
                filtered_friends = []
                for friend in my_friends:
                    if existing_lookup.has_key(friend['email']):
                        user = existing_lookup.get(friend['email'])
                        if user.id not in already_friends_ids:
                            friend.user = user
                        else:
                            continue
                    filtered_friends.append(friend)

                return render_to_response('friends/invite.html', {'my_friends':filtered_friends }, RequestContext(request))
    else:
        friend_file_form=ImportContactForm()
        return render_to_response('friends/upload_friends.html', locals(), RequestContext(request))
        
def email_imported_friends(request, output_prefix="invite", redirect_to='edit_friends'): 
    redirect_to = request.REQUEST.get('next',None) or redirect_to
    me = request.user.get_profile()
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    if request.method == 'POST':
        invited_emails = [email for email in request.POST.getlist("add_as_friend") if re.match(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,6}$',email.strip(),re.IGNORECASE)]
        existing_profiles = Expert_Profile.objects.filter(user__email__in=invited_emails)
        all_profiles = Expert_Profile.objects.all()
        if existing_profiles.exists():
            request.user.get_profile().add_friends(existing_profiles)
            for profile in existing_profiles:
                invited_emails.remove(profile.user.email)
        invited_count = len(invited_emails)
        subj_template = "%s%s_subj.txt" % (settings.MAILINGS_DIR,output_prefix) 
        body_template = "%s%s_body.txt" % (settings.MAILINGS_DIR,output_prefix)
        subject_output = render_to_string(subj_template,locals()) 
        body_output = render_to_string(body_template,locals())
        messages_to_send = []
        from_address = "\"%s at AcademicExperts.org\" <%s>" % (request.user.get_full_name(),settings.SERVER_EMAIL)
        for email in invited_emails:
            messages_to_send.append(
                (subject_output,body_output,from_address,[email])
            )
        add_desired_friends(request.user.get_profile(),invited_emails)
        send_mass_mail(tuple(messages_to_send), fail_silently=False)
        messages.add_message(request, messages.SUCCESS,'You have sent invitations to a total of %s emails.' % invited_count)
        return HttpResponseRedirect(redirect_to)
    if request.method == 'GET':
        messages.add_message(request, messages.ERROR,'Please try importing your friends again.')
        return HttpResponseRedirect(redirect_to)
    return render_to_response('friends/invite_users.html', locals(), RequestContext(request))
        
def get_google_friends(request):
    cache_code = "GOOG_%s" % hashlib.md5(request.user.email).hexdigest()
    my_friends = cache.get(cache_code,None)
    if my_friends == None:
        import gdata.friends.service
        import gdata.auth
        from django_authopenid.utils import get_url_host
        import datetime
        from dateutil.relativedelta import relativedelta
        AUTH_SCOPE = "http://www.google.com/m8/feeds"
        friends_service = gdata.friends.service.ContactsService()
        if request.GET.has_key('token'):
            rsa_key = open(settings.PRIVATE_KEY,'r').read()
            token = gdata.auth.extract_auth_sub_token_from_url(request.get_full_path(),rsa_key=rsa_key)
            friends_service.SetAuthSubToken(token)
            friends_service.UpgradeToSessionToken()
            query = gdata.friends.service.ContactsQuery()
            d = datetime.datetime.now() + relativedelta(years=-1)
            query.updated_min = d.strftime('%Y-%m-%dT%H:%M:%S%z')
            friends = []
            feed = friends_service.GetContactsFeed(query.ToUri())
            friends.extend(sum([[email.address for email in entry.email] for entry in feed.entry], []))
            next_link = feed.GetNextLink()
            link_counter = 0
            while next_link and link_counter < 20:
                link_counter += 1
                feed = friends_service.GetContactsFeed(uri=next_link.href)
                friends.extend(sum([[email.address for email in entry.email] for entry in feed.entry], []))
                next_link = feed.GetNextLink()
            my_friends = [{ 'name':None, 'email':email} for email in friends ]
            cache.set(cache_code,my_friends,3000)
        else:
            next = "http://%s%s" % (
                    Site.objects.get_current(),
                    reverse('google_friends') 
            )
            url = friends_service.GenerateAuthSubURL(next, AUTH_SCOPE, False, 1)
            return HttpResponseRedirect(url)
        counter = 0
        my_friends_lookup = {}
        for k in my_friends:
            my_friends_lookup[k['email']] = counter
            counter += 1
        already_friends_ids = [ec.friend.user.id for ec in Expert_Contact.objects.filter(expert_profile=request.user.get_profile())]
        existing_users = User.objects.filter(email__in=[k['email'] for k in my_friends]).order_by('last_name','first_name')
        for u in existing_users:
            if my_friends_lookup.has_key(u.email):
                if u.id in already_friends_ids:
                    del my_friends[my_friends_lookup[u.email]]
                    continue
                my_friends[my_friends_lookup[u.email]]['user']=u
        return render_to_response('friends/invite_friends.html', {'my_friends':my_friends }, RequestContext(request))

    

@csrf_protect
@login_required
def edit_relationship(request,friend=None,redirect_to='edit_friends',form_class=FriendshipForm):
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    try:
        friend_profile=Expert_Profile.objects.get(code=friend)
    except Expert_Profile.DoesNotExist:
        messages.add_message(request, messages.ERROR,"I couldn't find a friend for %s" % friend)
        return HttpResponseRedirect(redirect_to)
    try:
        ec = Expert_Contact.objects.get(expert_profile=friend_profile,friend=request.user.get_profile(),approved=True)
    except:
        messages.add_message(request, messages.ERROR,"%s is not one of your friends, or you're not one of their friends." % friend)
        return HttpResponseRedirect(redirect_to)
    if request.method == 'POST':
        friend_form=form_class(request.POST,expert=request.user.get_profile(),friend=friend_profile,prefix="friend")
        if request.POST.get('update_approval'):
            approve_related = request.POST.getlist('approve_related')
            for rel in approve_related:
                if rel not in ec.how_related:
                    messages.add_message(request, messages.INFO,"I removed %s." % rel)
                    approve_related.remove(rel)
            ec.how_related = ' '.join(approve_related)
            ec.how_related_approved = True
            ec.save()
        if friend_form.is_valid():
            friend_form.save()
            messages.add_message(request, messages.SUCCESS,"Your relationship details with %s have been saved." % friend)
            return HttpResponseRedirect(redirect_to)
    else:
        friend_form=form_class(expert=request.user.get_profile(),friend=friend_profile,prefix="friend")
    return render_to_response('friends/edit_relationship.html', locals(), RequestContext(request))

@csrf_protect
@login_required
def edit_friend(request, friend=None, redirect_to='edit_friends', form_class=None):
    return HttpResponse("Editing friendship")

@csrf_protect
@login_required
def edit_friends(request, friend=None, redirect_to='edit_friends', form_class=None):
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    if request.method == 'POST':
        friend, friend_profile = get_user_profile(friend)
        friend_form=friend_form(request.POST,expert=request.user.get_profile(),friend=friend_profile,prefix=request.POST.get('prefix'))
        if friend_form.is_valid():
            friend_form.save()
            messages.add_message(request, messages.SUCCESS,"Contact information for %s saved." % friend)
            return HttpResponseRedirect(redirect_to)
    else:
        if friend:
            try:
                friend_profile=Expert_Profile.objects.get(code=friend)
            except Expert_Profile.DoesNotExist:
                messages.add_message(request, messages.ERROR,"I couldn't find a friend for %s" % friend)
                return HttpResponseRedirect(redirect_to)
            friend_form=form_class(expert=request.user.get_profile(),friend=friend_profile,prefix="friend")
        else:
            profile_friends = []
            friendship_list = request.user.get_profile().get_friends()
            counter = 0
            for f in friendship_list:
                counter += 1
                friend_forms.append(form_class(friendship=f.friendship, user=request.user, friend=f.friend, prefix='friend_%s' % counter))
    return render_to_response('friends/edit.html', locals(), RequestContext(request))

