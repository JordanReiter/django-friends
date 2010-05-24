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


class UserForm(forms.Form):
    
    def __init__(self, user=None, *args, **kwargs):
        self.user = user
        super(UserForm, self).__init__(*args, **kwargs)


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


class InviteFriendForm(UserForm):
    
    to_user = forms.CharField(widget=forms.HiddenInput)
    message = forms.CharField(label="Message", required=False, widget=forms.Textarea(attrs = {'cols': '20', 'rows': '5'}))
    
    def clean_to_user(self):
        to_username = self.cleaned_data["to_user"]
        try:
            User.objects.get(username=to_username)
        except User.DoesNotExist:
            raise forms.ValidationError(u"Unknown user.")
            
        return self.cleaned_data["to_user"]
    
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
        invitation = FriendshipInvitation(from_user=self.user, to_user=to_user, message=message, status="2")
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
        value = re.sub(r'[;,\r\n\t]\s*("?[^<>]+"?\s)?<?\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.([A-Z]{2,4}|museum)\b)\b>?',r'\r\2',("\r%s\r" % value))
        return re.split(r'[\s;,]+',value)

    def validate(self, value):
        "Check if value consists only of valid emails."

        # Use the parent's handling of required fields, etc.
        super(MultiEmailField, self).validate(value)
        return True

class MultipleInviteForm(forms.Form):
    invited_emails = MultiEmailField(max_length=1000)
    
    def __init__(self, max_invites=20, *args, **kwargs):
        super(MultipleInviteForm, self).__init__(*args, **kwargs)
        self.max_invites=max_invites
        
    def clean_invited_emails(self):
        data = self.cleaned_data.get('invited_emails')
        bad_emails = []
        raise forms.ValidationError("I got %s, which is %s" % (data,type(data)))
        for email in re.split(r'[\s,;]+',data):
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

    def save(self):
        to_user = User.objects.get(username=self.cleaned_data["to_user"])
        message = self.cleaned_data['message']
        invitation = FriendshipInvitation(from_user=self.user, to_user=to_user, message=message, status="2")
        invitation.save()
        if notification:
            notification.send([to_user], "friends_invite", {"invitation": invitation})
            notification.send([self.user], "friends_invite_sent", {"invitation": invitation})
        self.user.message_set.create(message="Friendship requested with %s" % to_user.username) # @@@ make link like notification
        return invitation


        
RELATED_CHOICES = (
    ('colleague',_('We are colleagues')),
    ('co-worker',_('We we work together')),
    ('friend',_('We are friends')),
    ('co-author',_('We are co-authors (co-wrote a paper)')),
)
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
    dont_know_check = forms.BooleanField(
        label='Don\'t know this person:',
        widget=forms.CheckboxInput,
        required=False
    )

    def __init__(self, *args, **kwargs):
        self.friendship = kwargs.get('instance', None)
        self.user = kwargs.pop('user', None)
        self.friend = kwargs.pop('friend', None)
        form = super(FriendshipForm,self).__init__(*args,**kwargs)
        if self.friendship and self.friendship.how_related:
            hr = self.friendship.how_related.split(' ')
            self.fields['choose_how_related'].initial = list(hr)
            for k, _ in RELATED_CHOICES:
                if k in hr:
                    hr.remove(k)
            if hr and len(hr):
                self.fields['other_related'].initial=' '.join(hr)
                self.fields['other_related_check'].initial = True
                    
        return form
    
    def clean(self):
        if not self.friendship:
            raise forms.ValidationError("Tried to save a friendship record for a friendship that does not exist: %s and %s" % (self.user, self.friend))
        return self.cleaned_data            

    def save(self):
        how_related = "%s %s" % (self.cleaned_data.get('choose_how_related'),self.cleaned_data.get('other_related'))
        if not len(how_related.strip()) and self.cleaned_data.get('how_related_check'):
            how_related = 'other'       
        friendship = Friendship.objects.get(to_user=self.friend, from_user=self.user)
        friendship.how_related=how_related
        friendship.save()
    
    class Meta:
        model=Friendship