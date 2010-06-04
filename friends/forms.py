import re
from django import forms
from django.conf import settings
from django.utils.translation import ugettext as _

from django.contrib.auth.models import User

from friends.models import *

if "notification" in settings.INSTALLED_APPS:
    from notification import models as notification
else:
    notification = None

if "emailconfirmation" in settings.INSTALLED_APPS:
    from emailconfirmation.models import EmailAddress
else:
    EmailAddress = None


RELATED_CHOICES = (
    ('colleague',_('We are colleagues')),
    ('co-worker',_('We we work together')),
    ('friend',_('We are friends')),
    ('co-author',_('We are co-authors (co-wrote a paper)')),
    ('unknown',_('I don\'t know them')),
)

def format_how_related(form):
    how_related = "%s %s" % (' '.join(form.cleaned_data.get('choose_how_related')), form.cleaned_data.get('other_related'))
    if not len(how_related.strip()) and form.cleaned_data.get('other_related_check'):
        how_related = 'other'
    return how_related

def parse_related(form, how_related):
    if how_related != None:
        hr = how_related.strip().split(' ')
        form.fields['choose_how_related'].initial = list(hr)
        for k, _ in RELATED_CHOICES:
            if k in hr:
                hr.remove(k)
        if hr and len(hr):
            form.fields['other_related'].initial=' '.join(hr)
            form.fields['other_related_check'].initial = True




if EmailAddress:
    class JoinRequestForm(forms.Form):
        
        email = forms.EmailField(label="Email", required=True, widget=forms.TextInput(attrs={'size':'30'}))
        message = forms.CharField(label="Message", required=False, widget=forms.Textarea(attrs = {'cols': '30', 'rows': '5'}))
        
        def clean_email(self):
            # @@@ this assumes email-confirmation is being used
            self.existing_users = EmailAddress.objects.get_users_for(self.cleaned_data["email"])
            if self.existing_users:
                raise forms.ValidationError(u"Someone with that email address is already here.")
            return self.cleaned_data["email"]
        
        def save(self, user):
            join_request = JoinInvitation.objects.send_invitation(user, self.cleaned_data["email"], self.cleaned_data["message"])
            user.message_set.create(message="Invitation to join sent to %s" % join_request.contact.email)
            return join_request


class InviteFriendForm(forms.Form):
    to_user = forms.CharField(widget=forms.HiddenInput)
    message = forms.CharField(label="Message", required=False, widget=forms.Textarea(attrs = {'cols': '20', 'rows': '5'}))
    choose_how_related = forms.MultipleChoiceField(
       choices=RELATED_CHOICES,
       widget=forms.CheckboxSelectMultiple(),
       required=False
    )
    other_related = forms.CharField(required=False, max_length=50)
    other_related_check = forms.BooleanField(
        label='Other:',
        widget=forms.CheckboxInput,
        required=False
    )
    
    def clean_to_user(self):
        raise Exception("%s" % self.cleaned_data.items())
        to_username = self.cleaned_data["to_user"]
        try:
            User.objects.get(username=to_username)
        except User.DoesNotExist:
            raise forms.ValidationError(u"Unknown user.")
            
        return self.cleaned_data["to_user"]
    
    def __init__(self, *args, **kwargs):
        self.friend = kwargs.pop('friend', None)
        self.user = kwargs.pop('user', None)
        super(InviteFriendForm, self).__init__(*args, **kwargs)
        self.fields['to_user'].initial = self.friend.username
    
    def clean(self):
        to_user = User.objects.get(username=self.cleaned_data["to_user"])
        previous_invitations_to = FriendshipInvitation.objects.invitations(to_user=to_user, from_user=self.user)
        if previous_invitations_to.count() > 0:
            raise forms.ValidationError(u"Already requested friendship with %s" % to_user.username)
        # check inverse
        previous_invitations_from = FriendshipInvitation.objects.invitations(to_user=self.user, from_user=to_user)
        if previous_invitations_from.count() > 0:
            raise forms.ValidationError(u"%s has already requested friendship with you" % to_user.username)
        return self.cleaned_data
    
    def save(self):
        to_user = User.objects.get(username=self.cleaned_data["to_user"])
        message = self.cleaned_data["message"]
        how_related=format_how_related(self)
        invitation = FriendshipInvitation(from_user=self.user, to_user=to_user, message=message, how_related=how_related, status="2")
        invitation.save()
        if notification:
            notification.send([to_user], "friends_invite", {"invitation": invitation})
            notification.send([self.user], "friends_invite_sent", {"invitation": invitation})
        self.user.message_set.create(message="Friendship requested with %s" % to_user.username) # @@@ make link like notification
        return invitation

class MultiEmailField(forms.CharField):
    widget = forms.Textarea(attrs={ 'rows':5, 'cols':50})
    
    def to_python(self, value):
        "Normalize data to a list of strings."
        # Return an empty list if no input was given.
        if not value:
            return []
        value = re.sub(r'[;,\r\n\t]+?\s*("?[^<@>]+?"?\s)?<?([A-Za-z0-9._%+-]+?@[A-Za-z0-9.-]+?\.([A-Za-z]{2,4}|museum))>?',r'\t\2\t',"\t%s\t" % value,re.IGNORECASE)
        return re.split(r'[\s,;]+',value.strip())

    def validate(self, value):
        "Check if value consists only of valid emails."

        # Use the parent's handling of required fields, etc.
        super(MultiEmailField, self).validate(value)
        return True

class MultipleInviteForm(forms.Form):
    invited_emails = MultiEmailField(max_length=1000)
    message = forms.CharField(max_length=300, required=False)
    
    def __init__(self, max_invites=20, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(MultipleInviteForm, self).__init__(*args, **kwargs)
        self.max_invites=max_invites
        
    def clean_invited_emails(self):
        data = self.cleaned_data.get('invited_emails')
        bad_emails = []
        for email in data:
            if not len(email.strip()):
                data.remove(email)
                continue
            if not (re.match(r'(?u)^[-\w.+]+@[-A-Za-z0-9.]+\.([A-Za-z]{2,4}|museum)$',email) >= 0):
                bad_emails.append(email)
        if len(bad_emails):
            raise forms.ValidationError('The following email addresses had errors: %s' % ','.join(bad_emails))
        if not data:
            raise forms.ValidationError('You must enter at least one valid e-mail address.')
        if self.max_invites and len(data) > self.max_invites:
            raise forms.ValidationError('You can\'t send out more than %s invitations; you tried to send out to %s emails:' % (self.max_invites,len(data)))
        return data

    def send_invitations(self):
        message = self.cleaned_data.get('message',None)
        invited_emails = [email for email in self.cleaned_data.get('invited_emails')]
        processed_emails = []
        existing_users = User.objects.filter(email__in=invited_emails)
        requests = 0
        invitations = 0
        existing = 0
        total = len(invited_emails)
        friend_users = [f['friend'] for f in Friendship.objects.friends_for_user(self.user)]
        if existing_users:
            for user in existing_users:
                if user in friend_users:
                    existing += 1
                else:
                    requests += 1
                    invitation = FriendshipInvitation(from_user=self.user, to_user=user, message=message, status="2")
                    invitation.save()
                    if notification:
                        notification.send([user], "friends_invite", {"invitation": invitation})
                        notification.send([self.user], "friends_invite_sent", {"invitation": invitation})
            for user in existing_users:
                processed_emails.append(user.email)
                try:
                    invited_emails.remove(user.email)
                except:
                    pass #guess it was already gone?
        for email in invited_emails:
            if email not in processed_emails:
                processed_emails.append(email)
                invitations += 1
                JoinInvitation.objects.send_invitation(self.user, email, None)
        return total, requests, existing, invitations

        
class FriendshipForm(forms.ModelForm):
    choose_how_related = forms.MultipleChoiceField(
       choices=RELATED_CHOICES,
       widget=forms.CheckboxSelectMultiple(),
       required=False
    )
    other_related = forms.CharField(required=False, max_length=50)
    other_related_check = forms.BooleanField(
        label='Other:',
        widget=forms.CheckboxInput,
        required=False
    )

    def __init__(self, *args, **kwargs):
        self.friendship = kwargs.get('instance', None)
        self.user = kwargs.pop('user', None)
        self.friend = kwargs.pop('friend', None)
        super(FriendshipForm,self).__init__(*args,**kwargs)
        if self.friendship and self.friendship.how_related:
            parse_related(self, self.friendship.how_related)
    
    def clean(self):
        if not self.friendship:
            raise forms.ValidationError("Tried to save a friendship record for a friendship that does not exist: %s and %s" % (self.user, self.friend))
        return self.cleaned_data            

    def save(self):
        friendship = Friendship.objects.get(to_user=self.friend, from_user=self.user)
        friendship.how_related=format_how_related(self)
        friendship.save()
        return friendship
    
    class Meta:
        model=Friendship
        

class ContactForm(forms.ModelForm):
    name = forms.CharField(max_length=100)
    address = forms.CharField(max_length=300, required=False, widget=forms.Textarea(attrs={'rows':5, 'cols':50}))
    website = forms.URLField(required=False, widget=forms.TextInput(attrs={'size':50}))
    choose_how_related = forms.MultipleChoiceField(
       choices=RELATED_CHOICES,
       widget=forms.CheckboxSelectMultiple(),
       required=False
    )
    other_related = forms.CharField(required=False, max_length=50)
    other_related_check = forms.BooleanField(
        label='Other:',
        widget=forms.CheckboxInput,
        required=False
    )

    def __init__(self, *args, **kwargs):
        self.contact=kwargs.get('instance',None)
        self.user=kwargs.pop('user',None)
        super(ContactForm, self).__init__(*args, **kwargs)
        if self.contact and self.contact.user:
            try:
                self.is_friend = Friendship.objects.are_friends(self.contact.user, self.user)
                if self.is_friend:
                    try:
                        friendship = Friendship.objects.get(from_user=self.user, to_user=self.contact.user)
                        parse_related(self, friendship.how_related)
                    except Friendship.DoesNotExist:
                        pass
                    except Exception, inst:
                        raise Exception("%s" % inst)
            except AttributeError:
                self.is_friend = False
            show = self.contact.user.get_profile().get_access(self.user)
            for f, v  in self.fields.items():
                if show.get(f,True) != False:
                    d = getattr(self.contact.user,f, getattr(self.contact.user.get_profile(), f, None))
                else:
                    d = None
                if not v.initial:
                    self.fields[f].initial = getattr(self.contact,f,None) or d
                
        
    def save(self, *args, **kwargs):
        contact=super(ContactForm, self).save(*args, **kwargs)
        if self.is_friend:
            friendship, _ = Friendship.objects.get_or_create(from_user=self.user, to_user=contact.user)
            friendship.how_related = format_how_related(self)
            friendship.save()
        return contact

    class Meta:
        model = Contact
        

class ImportContactForm(forms.Form):
      contacts_file = forms.FileField(help_text="Upload a contacts file here. Current supported formats are vCard and Outlook.")