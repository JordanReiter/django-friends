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
from friends.models import *                                            


# Utils
import re, datetime
try:
    import json #Works with Python 2.6
except ImportError:
    from django.utils import simplejson as json

@login_required
def my_contacts(request):
    return view_contacts(request,request.user)

def contact_lookup(request):
    query_tokens = re.split(r'\W+',request.GET.get('q',''))
    matching_contacts = Contact.objects.all()
    if query_tokens:
        for token in query_tokens:
            matching_contacts = (
                matching_contacts.filter(name__icontains=token) |
                matching_contacts.filter(first_name__icontains=token) |
                matching_contacts.filter(last_name__icontains=token)
            )
    else:
        matching_contacts = []
    results = []
    for contact in matching_contacts:
        results.append({
            'id':str(contact.id),
            'name':str(contact.name),
            'first_name':str(contact.first_name),
            'last_name':str(contact.last_name),
            'email':str(contact.email),
            'user':str(contact.user.id),
        })
    return HttpResponse(json.dumps(results), mimetype='application/json')

@csrf_protect
@login_required
def invite_users(request,output_prefix="invite", redirect_to='edit_contacts'):
    redirect_to = request.REQUEST.get('next',None) or redirect_to
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    if request.method == 'POST':
        invite_users_form = InviteForm(data=request.POST)
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
                        notification.send([to_user], "friends_invite", {"invitation": invitation})
                        notification.send([self.user], "friends_invite_sent", {"invitation": invitation})
                for user in existing_users:
                    invited_emails.remove(user.email)
            for email in invited_emails:
                JoinInvitation.objects.send_invitation(request.user, email, None)
    if request.method == 'GET':
        invite_users_form = InviteForm()
    return render_to_response('friends/invite.html', locals(), RequestContext(request))


@csrf_protect
@login_required
@has_profile
def add_contact(request,user,template_name='confirm.html',add_form=AddFriendForm, redirect_to="profile"):
    try:
        contact_profile = user.get_profile()
    except AttributeError:
        contact = User.objects.get(code=user)
        try:
            contact_profile = user.get_profile()
        except:
            pass

    if not contact or not user.is_active:
        return Http404()

    if request.method == 'POST':
        add_contact_form = add_form(request.POST,user=request.user,contact=contact,prefix="contact")
        if add_contact_form.is_valid():
            add_contact_form.save()
            messages.add_message(request, messages.SUCCESS,"You have sent a request for %s to be your contact." % (contact.username))
            return HttpResponseRedirect(reverse(redirect_to,args=[contact]))
    else:
        add_contact_form = add_form(expert=request.user,contact=contact,prefix="contact")
    return render_to_response('contacts/add.html', locals(), RequestContext(request))


@csrf_protect
@login_required
def accept_friendship(request,contact,template_name='confirm.html'):
    me = request.user.get_profile()
    try:
        contact_profile=get_active_profile(contact)
    except:
        return render_to_response('contacts/noprofile.html',{}, RequestContext(request))
    
    # because of the threat of cross-site scripting, this action has to be the result of a form posting
    if request.method == 'GET':
        action_display = "approve %s as a contact." % (contact_profile.user.get_full_name() or contact_profile.user.username) 
        yes_display = "Yes, add as contact"
        no_display = "No, ignore request"
        return render_to_response(template_name, locals(), RequestContext(request))
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return HttpResponseRedirect(
                reverse('profile',args=[contact])
            )
        
    try:
        me.approve_contact(contact_profile)
        notification.send([contact_profile.user], "contacts_accept", {'contact': me,})
        notification.send([request.user], "contacts_accept", {'contact': contact_profile,})
        messages.add_message(request, messages.SUCCESS,"%s is now your contact." % (contact_profile.user.get_full_name() or contact_profile.user.username))
    except Expert_Profile.NoContact, inst:
        messages.add_message(request, messages.ERROR,"%s has definitely not (%s) added you as a contact yet." % (inst, contact_profile.user.username))
    return HttpResponseRedirect(reverse('profile',args=[contact]))


@csrf_protect
@login_required
def remove_contact(request,contact,template_name='confirm.html',redirect_to='edit_contacts'):
    try:
        contact_profile=get_active_profile(contact)
    except:
        messages.add_message(request, messages.ERROR,"I couldn't find a contact for %s" % contact)
        return HttpResponseRedirect(redirect_to)
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    # confirm that the user can remove this person as a contact
    if not contact_profile.is_contact(request.user.get_profile()):
        messages.add_message(request, messages.ERROR,"%s is not one of your contacts" % contact_profile.user.username)
        return HttpResponseRedirect(redirect_to)
    #if the method is GET, show a form to avoid csrf
    if request.method == 'GET':
        action_display = "remove %s as a contact." % contact_profile.user.get_full_name() 
        yes_display = "Yes, remove as contact"
        no_display = "No, keep %s as a contact" % contact_profile.user.get_full_name()
        return render_to_response(template_name, locals(), RequestContext(request))
    elif request.POST.get('confirm_action')=='no':
        messages.add_message(request, messages.INFO,"You canceled the action.")
        return HttpResponseRedirect(redirect_to)
    try:
        ec = Expert_Contact.objects.get(expert_profile=request.user.get_profile(),contact=contact_profile)
        ec.delete()
        messages.add_message(request, messages.SUCCESS,"You have removed %s from your contacts." % (contact_profile.user.get_full_name()))
    except:
        messages.add_message(request, messages.SUCCESS,"%s is no longer on your contacts list." % (contact_profile.user.get_full_name()))
    return HttpResponseRedirect(redirect_to)

def export_contacts(request):
    vcard = export_vcards([ec.contact.user for ec in request.user.get_profile().get_contacts()])
    response = HttpResponse(vcard, mimetype='text/x-vcard')
    response['Content-Disposition'] = 'attachment; filename=contacts.vcf'
    return response
    
    
def get_file_contacts(request):
    display_import = False
    if request.method == 'POST':
        contact_file_form=ImportContactForm(request.POST,request.FILES)
        if contact_file_form.is_valid():
            contacts_file=request.FILES['contacts_file']
            if contacts_file.multiple_chunks():
                messages.add_message(request, messages.ERROR,"The file you uploaded is too large.")
            else:
                start = True
                format = None
                contact_file_content = ""
                for chunk in contacts_file.chunks():
                    if start == True:
                        if 'VCARD' in chunk:
                            format = 'VCARD'
                    contact_file_content += chunk
                if format == 'VCARD':
                    display_import = True
                    my_contacts = import_vcards(contact_file_content)
            if display_import:
                already_contacts_ids = [ec.contact.user.id for ec in Expert_Contact.objects.filter(expert_profile=request.user.get_profile())]
                existing_users = User.objects.filter(email__in=[k['email'] for k in my_contacts]).order_by('last_name','first_name')
                existing_lookup = {}
                for user in existing_users:
                    existing_lookup[user.email] = user
                filtered_contacts = []
                for contact in my_contacts:
                    if existing_lookup.has_key(contact['email']):
                        user = existing_lookup.get(contact['email'])
                        if user.id not in already_contacts_ids:
                            contact.user = user
                        else:
                            continue
                    filtered_contacts.append(contact)

                return render_to_response('contacts/invite.html', {'my_contacts':filtered_contacts }, RequestContext(request))
    else:
        contact_file_form=ImportContactForm()
        return render_to_response('contacts/upload_contacts.html', locals(), RequestContext(request))
        
def email_imported_contacts(request, output_prefix="invite", redirect_to='edit_contacts'): 
    redirect_to = request.REQUEST.get('next',None) or redirect_to
    me = request.user.get_profile()
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    if request.method == 'POST':
        invited_emails = [email for email in request.POST.getlist("add_as_contact") if re.match(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,6}$',email.strip(),re.IGNORECASE)]
        existing_profiles = Expert_Profile.objects.filter(user__email__in=invited_emails)
        all_profiles = Expert_Profile.objects.all()
        if existing_profiles.exists():
            request.user.get_profile().add_contacts(existing_profiles)
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
        add_desired_contacts(request.user.get_profile(),invited_emails)
        send_mass_mail(tuple(messages_to_send), fail_silently=False)
        messages.add_message(request, messages.SUCCESS,'You have sent invitations to a total of %s emails.' % invited_count)
        return HttpResponseRedirect(redirect_to)
    if request.method == 'GET':
        messages.add_message(request, messages.ERROR,'Please try importing your contacts again.')
        return HttpResponseRedirect(redirect_to)
    return render_to_response('contacts/invite_users.html', locals(), RequestContext(request))
        
def get_google_contacts(request):
    cache_code = "GOOG_%s" % hashlib.md5(request.user.email).hexdigest()
    my_contacts = cache.get(cache_code,None)
    if my_contacts == None:
        import gdata.contacts.service
        import gdata.auth
        from django_authopenid.utils import get_url_host
        import datetime
        from dateutil.relativedelta import relativedelta
        AUTH_SCOPE = "http://www.google.com/m8/feeds"
        contacts_service = gdata.contacts.service.ContactsService()
        if request.GET.has_key('token'):
            rsa_key = open(settings.PRIVATE_KEY,'r').read()
            token = gdata.auth.extract_auth_sub_token_from_url(request.get_full_path(),rsa_key=rsa_key)
            contacts_service.SetAuthSubToken(token)
            contacts_service.UpgradeToSessionToken()
            query = gdata.contacts.service.ContactsQuery()
            d = datetime.datetime.now() + relativedelta(years=-1)
            query.updated_min = d.strftime('%Y-%m-%dT%H:%M:%S%z')
            contacts = []
            feed = contacts_service.GetContactsFeed(query.ToUri())
            contacts.extend(sum([[email.address for email in entry.email] for entry in feed.entry], []))
            next_link = feed.GetNextLink()
            link_counter = 0
            while next_link and link_counter < 20:
                link_counter += 1
                feed = contacts_service.GetContactsFeed(uri=next_link.href)
                contacts.extend(sum([[email.address for email in entry.email] for entry in feed.entry], []))
                next_link = feed.GetNextLink()
            my_contacts = [{ 'name':None, 'email':email} for email in contacts ]
            cache.set(cache_code,my_contacts,3000)
        else:
            next = "http://%s%s" % (
                    Site.objects.get_current(),
                    reverse('google_contacts') 
            )
            url = contacts_service.GenerateAuthSubURL(next, AUTH_SCOPE, False, 1)
            return HttpResponseRedirect(url)
        counter = 0
        my_contacts_lookup = {}
        for k in my_contacts:
            my_contacts_lookup[k['email']] = counter
            counter += 1
        already_contacts_ids = [ec.contact.user.id for ec in Expert_Contact.objects.filter(expert_profile=request.user.get_profile())]
        existing_users = User.objects.filter(email__in=[k['email'] for k in my_contacts]).order_by('last_name','first_name')
        for u in existing_users:
            if my_contacts_lookup.has_key(u.email):
                if u.id in already_contacts_ids:
                    del my_contacts[my_contacts_lookup[u.email]]
                    continue
                my_contacts[my_contacts_lookup[u.email]]['user']=u
        return render_to_response('contacts/invite_contacts.html', {'my_contacts':my_contacts }, RequestContext(request))

    

@csrf_protect
@login_required
def edit_relationship(request,contact=None,redirect_to='edit_contacts'):
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    try:
        contact_profile=Expert_Profile.objects.get(code=contact)
    except Expert_Profile.DoesNotExist:
        messages.add_message(request, messages.ERROR,"I couldn't find a contact for %s" % contact)
        return HttpResponseRedirect(redirect_to)
    try:
        ec = Expert_Contact.objects.get(expert_profile=contact_profile,contact=request.user.get_profile(),approved=True)
    except:
        messages.add_message(request, messages.ERROR,"%s is not one of your contacts, or you're not one of their contacts." % contact)
        return HttpResponseRedirect(redirect_to)
    if request.method == 'POST':
        contact_form=XFNContactForm(request.POST,expert=request.user.get_profile(),contact=contact_profile,prefix="contact")
        if request.POST.get('update_approval'):
            approve_related = request.POST.getlist('approve_related')
            for rel in approve_related:
                if rel not in ec.how_related:
                    messages.add_message(request, messages.INFO,"I removed %s." % rel)
                    approve_related.remove(rel)
            ec.how_related = ' '.join(approve_related)
            ec.how_related_approved = True
            ec.save()
        if contact_form.is_valid():
            contact_form.save()
            messages.add_message(request, messages.SUCCESS,"Your relationship details with %s have been saved." % contact)
            return HttpResponseRedirect(redirect_to)
    else:
        contact_form=XFNContactForm(expert=request.user.get_profile(),contact=contact_profile,prefix="contact")
    return render_to_response('contacts/edit_relationship.html', locals(), RequestContext(request))


@csrf_protect
@login_required
def edit_contacts(request,contact=None,redirect_to='edit_contacts'):
    if '/' not in redirect_to:
        redirect_to = reverse(redirect_to)
    if request.method == 'POST':
        try:
            contact_profile=Expert_Profile.objects.get(code=contact)
        except Expert_Profile.DoesNotExist:
            messages.add_message(request, messages.ERROR,"I couldn't find a contact for %s" % contact)
            return HttpResponseRedirect(redirect_to)
        contact_form=XFNContactForm(request.POST,expert=request.user.get_profile(),contact=contact_profile,prefix=request.POST.get('prefix'))
        if contact_form.is_valid():
            contact_form.save()
            messages.add_message(request, messages.SUCCESS,"Contact information for %s saved." % contact)
            return HttpResponseRedirect(redirect_to)
    else:
        if contact:
            try:
                contact_profile=Expert_Profile.objects.get(code=contact)
            except Expert_Profile.DoesNotExist:
                messages.add_message(request, messages.ERROR,"I couldn't find a contact for %s" % contact)
                return HttpResponseRedirect(redirect_to)
            contact_form=XFNContactForm(expert=request.user.get_profile(),contact=contact_profile,prefix="contact")
        else:
            profile_contacts = []
            expert_contacts = request.user.get_profile().get_contacts()
            counter = 0
            for expert_contact in expert_contacts:
                counter += 1
                profile_contacts.append(XFNContactForm(expert=request.user.get_profile(),contact=expert_contact.contact,prefix='contact_%s' % counter))
    return render_to_response('contacts/edit.html', locals(), RequestContext(request))

