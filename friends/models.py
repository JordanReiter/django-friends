import datetime

from random import random

from django.conf import settings
from django.core.urlresolvers import reverse
from django.db import models
from django.db.models import signals
from django.template.loader import render_to_string
from django.utils.hashcompat import sha_constructor

from django.contrib.sites.models import Site
from django.contrib.auth.models import User

# favour django-mailer but fall back to django.core.mail
if "mailer" in settings.INSTALLED_APPS:
    from mailer import send_mail
else:
    from django.core.mail import send_mail

if "notification" in settings.INSTALLED_APPS:
    from notification import models as notification
else:
    notification = None

if "emailconfirmation" in settings.INSTALLED_APPS:
    from emailconfirmation.models import EmailAddress
else:
    EmailAddress = None
    
try:
    from django_countries import CountryField
except ImportError:
    class CountryField(models.CharField): 
        def __init__(self, *args, **kwargs): 
            kwargs.setdefault('max_length', 50) 
            super(models.CharField, self).__init__(*args, **kwargs) 

class ContactManager(models.Manager):
    """
    Deleted records are now hidden most of the time
    Stolen from django-logicaldelete by paltman http://github.com/paltman/django-logicaldelete
    """
    def filter(self, *args, **kwargs):
        if 'pk' in kwargs or 'deleted' in kwargs:
            return super(ContactManager, self).filter(*args, **kwargs)
        else:
            kwargs.update({'deleted__isnull':True})
            return super(ContactManager, self).filter(*args, **kwargs)
    
    def all(self, *args, **kwargs):
        kwargs.update({'deleted__isnull':True})
        return super(ContactManager, self).filter(*args, **kwargs)


IMPORTED_TYPES = (
    ("V", "VCard Import"),
    ("G", "Google Import"),
    ("O", "Outlook Import"),
)
CONTACT_TYPES = (
    ("F", "Friendship"),
    ("I", "Invited"),
    ("A", "Manually added"),
)
class Contact(models.Model):
    """
    A contact is a person known by a user who may or may not themselves
    be a user.
    """
    
    # the user who created the contact; switched to owner so I can use 'user' for the actual user this corresponds to
    owner = models.ForeignKey(User, related_name="contacts", editable=False)
    
    name = models.CharField(max_length=100, null=True, blank=True)
    first_name = models.CharField(max_length=50, null=True, blank=True)
    last_name = models.CharField(max_length=50, null=True, blank=True)
    address = models.CharField(max_length=500, null=True, blank=True)
    country = CountryField(null=True, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=50, null=True, blank=True)
    fax = models.CharField(max_length=50, null=True, blank=True)
    mobile = models.CharField(max_length=50, null=True, blank=True)
    website = models.URLField(max_length=250, verify_exists=False, null=True, blank=True)
    birthday = models.DateField(null=True, blank=True)

    added = models.DateField(default=datetime.date.today, editable=False)
    edited = models.DateField(null=True, blank=True, editable=False)
    deleted = models.DateField(null=True, blank=True, editable=False)
    type = models.CharField(max_length=1, choices=(CONTACT_TYPES+IMPORTED_TYPES), editable=False)
    
    # the user this contact corresponds to -- I'm not allowing more than one user/email
    user = models.ForeignKey(User, null=True, blank=True, editable=False)
    
    objects = ContactManager()
    
    def __unicode__(self):
        return "%s (%s's contact)" % (self.email, self.owner)
    
    class Meta:
        unique_together = (('owner','email'))

def contact_update_user(sender, instance, created, *args, **kwargs):
    if created:
        Contact.objects.filter(email=instance.email).update(user=instance)

def contact_create_for_friendship(sender, instance, created, *args, **kwargs):
    if created:
        contact1, _ = Contact.objects.get_or_create(owner=instance.to_user, email=instance.from_user.email, name=instance.from_user.get_full_name(), first_name=instance.from_user.first_name, last_name=instance.from_user.last_name)
        contact1.type = 'F'
        contact1.save()
        contact2, _ = Contact.objects.get_or_create(owner=instance.from_user, email=instance.to_user.email, name=instance.to_user.get_full_name(), first_name=instance.to_user.first_name, last_name=instance.to_user.last_name)
        contact2.type = 'F'
        contact2.save()

SUGGEST_BECAUSE_INVITE=0
SUGGEST_BECAUSE_COWORKER=1
SUGGEST_BECAUSE_FRIENDOFFRIEND=2
SUGGEST_BECAUSE_NEIGHBOR=3
SUGGEST_WHY_CHOICES = (
    (SUGGEST_BECAUSE_INVITE, "They sent you an invitation to the site."),
    (SUGGEST_BECAUSE_COWORKER, "They work at the same organization/company."),
    (SUGGEST_BECAUSE_FRIENDOFFRIEND, "They're connected to you through another member on the site."),
    (SUGGEST_BECAUSE_NEIGHBOR,"They live in the same town or city."),
)
class FriendSuggestion(models.Model):
    email = models.EmailField(null=True, blank=True)
    user = models.ForeignKey(User, null=True, blank=True, related_name="suggested_friends")
    suggested_user = models.ForeignKey(User, related_name="__unused__")
    why = models.IntegerField(null=True, blank=True, choices=SUGGEST_WHY_CHOICES)
    active = models.BooleanField(default=True)
    
    def show_why(self):
        for r in SUGGEST_WHY_CHOICES:
            if r[0]==self.why:
                return r[1]
        else:
            return "%d not in %s" % (self.why, [r[0] for r in SUGGEST_WHY_CHOICES])

def suggest_friend_from_invite(sender, instance, created, *args, **kwargs):
    if created:
        FriendSuggestion.objects.get_or_create(suggested_user=instance.from_user, email=instance.contact.email, why='INVITE')

def friendsuggestion_update_user(sender, instance, created, *args, **kwargs):
    if created:
        FriendSuggestion.objects.filter(email__iexact=instance.email,user__isnull=True).update(user=instance)
        
def friendship_destroys_suggestions(sender, instance, created, *args, **kwargs):
    if created:
        suggestions = FriendSuggestion.objects.filter(user=instance.to_user,suggested_user=instance.from_user)
        suggestions |=  FriendSuggestion.objects.filter(user=instance.from_user,suggested_user=instance.to_user)
        suggestions.update(active=False)

class FriendshipManager(models.Manager):
    
    def friends_for_user(self, user):
        friends = []
        already = []
        for friendship in self.filter(from_user=user).select_related(depth=1):
            if friendship.to_user not in already:
                already.append(friendship.to_user)
                friends.append({"friend": friendship.to_user, "friendship": friendship})
        for friendship in self.filter(to_user=user).select_related(depth=1):
            if friendship.from_user not in already:
                already.append(friendship.from_user)
                friends.append({"friend": friendship.from_user, "friendship": friendship})
        return friends
    
    def are_friends(self, user1, user2):
        if self.filter(from_user=user1, to_user=user2).count() > 0:
            return True
        if self.filter(from_user=user2, to_user=user1).count() > 0:
            return True
        return False
    
    def remove(self, user1, user2):
        if self.filter(from_user=user1, to_user=user2):
            friendship = self.filter(from_user=user1, to_user=user2)
        elif self.filter(from_user=user2, to_user=user1):
            friendship = self.filter(from_user=user2, to_user=user1)
        friendship.delete()


class Friendship(models.Model):
    """
    A friendship is a bi-directional association between two users who
    have both agreed to the association.
    """
    
    to_user = models.ForeignKey(User, related_name="friends", editable=False)
    from_user = models.ForeignKey(User, related_name="_unused_", editable=False)
    how_related = models.CharField(max_length=100, null=True, blank=True)
    added = models.DateField(default=datetime.date.today, editable=False)
    
    objects = FriendshipManager()
    
    class Meta:
        unique_together = (('to_user', 'from_user'),)

def friendship_symmetrical(sender, instance, created, *args, **kwargs):
    if created:
        try:
            Friendship.objects.get(to_user=instance.from_user, from_user=instance.to_user)
        except Friendship.DoesNotExist:
            symmetrical_friendship = Friendship(to_user=instance.from_user, from_user=instance.to_user)
            symmetrical_friendship.how_related=instance.how_related
            symmetrical_friendship.added=instance.added
            symmetrical_friendship.save()
signals.post_save.connect(friendship_symmetrical, sender=Friendship)

def friend_set_for(user):
    return set([obj["friend"] for obj in Friendship.objects.friends_for_user(user)])


INVITE_STATUS = (
    ("1", "Created"),
    ("2", "Sent"),
    ("3", "Failed"),
    ("4", "Expired"),
    ("5", "Accepted"),
    ("6", "Declined"),
    ("7", "Joined Independently"),
    ("8", "Deleted")
)


class JoinInvitationManager(models.Manager):
    
    def send_invitation(self, from_user, to_email, message):
        contact, _ = Contact.objects.get_or_create(email=to_email, owner=from_user)
        contact.type = 'I'
        contact.save()
        salt = sha_constructor(str(random())).hexdigest()[:5]
        confirmation_key = sha_constructor(salt + to_email).hexdigest()
        
        accept_url = u"http://%s%s" % (
            unicode(Site.objects.get_current()),
            reverse("friends_accept_join", args=(confirmation_key,)),
        )
        
        ctx = {
            "SITE_NAME": unicode(Site.objects.get_current()),
            "CONTACT_EMAIL": settings.CONTACT_EMAIL,
            "contact": contact,
            "user": from_user,
            "message": message,
            "accept_url": accept_url,
        }
        
        subject = render_to_string("friends/join_invite_subject.txt", ctx)
        email_message = render_to_string("friends/join_invite_message.txt", ctx)
        
        send_mail(subject, email_message, settings.DEFAULT_FROM_EMAIL, [to_email])        
        return self.create(from_user=from_user, contact=contact, message=message, status="2", confirmation_key=confirmation_key)


class JoinInvitation(models.Model):
    """
    A join invite is an invitation to join the site from a user to a
    contact who is not known to be a user.
    """
    
    from_user = models.ForeignKey(User, related_name="join_from")
    contact = models.ForeignKey(Contact)
    message = models.CharField(max_length=2000, null=True, blank=True)
    sent = models.DateField(default=datetime.date.today)
    status = models.CharField(max_length=1, choices=INVITE_STATUS)
    confirmation_key = models.CharField(max_length=40)
    
    objects = JoinInvitationManager()
    
    def accept(self, new_user):
        # mark invitation accepted
        self.status = "5"
        self.save()
        # auto-create friendship
        friendship = Friendship(to_user=new_user, from_user=self.from_user)
        friendship.save()
        # notify
        if notification:
            notification.send([self.from_user], "join_accept", {"invitation": self, "new_user": new_user})
            friends = []
            for user in friend_set_for(new_user) | friend_set_for(self.from_user):
                if user != new_user and user != self.from_user:
                    friends.append(user)
            notification.send(friends, "friends_otherconnect", {"invitation": self, "to_user": new_user})


class FriendshipInvitationManager(models.Manager):
    
    def invitations(self, *args, **kwargs):
        return self.filter(*args, **kwargs).exclude(status__in=["6", "8"])


class FriendshipInvitation(models.Model):
    """
    A frienship invite is an invitation from one user to another to be
    associated as friends.
    """
    
    from_user = models.ForeignKey(User, related_name="invitations_from")
    to_user = models.ForeignKey(User, related_name="invitations_to")
    message = models.CharField(max_length=2000, null=True, blank=True)
    sent = models.DateField(default=datetime.date.today)
    status = models.CharField(max_length=1, choices=INVITE_STATUS)
    
    objects = FriendshipInvitationManager()
    
    def accept(self):
        if not Friendship.objects.are_friends(self.to_user, self.from_user):
            friendship = Friendship(to_user=self.to_user, from_user=self.from_user)
            friendship.save()
            self.status = "5"
            self.save()
            if notification:
                notification.send([self.from_user], "friends_accept", {"invitation": self})
                notification.send([self.to_user], "friends_accept_sent", {"invitation": self})
                for user in friend_set_for(self.to_user) | friend_set_for(self.from_user):
                    if user != self.to_user and user != self.from_user:
                        notification.send([user], "friends_otherconnect", {"invitation": self, "to_user": self.to_user})
    
    def decline(self):
        if not Friendship.objects.are_friends(self.to_user, self.from_user):
            self.status = "6"
            self.save()


class FriendshipInvitationHistory(models.Model):
    """
    History for friendship invitations
    """
    
    from_user = models.ForeignKey(User, related_name="invitations_from_history")
    to_user = models.ForeignKey(User, related_name="invitations_to_history")
    message = models.CharField(max_length=2000, null=True, blank=True)
    sent = models.DateField(default=datetime.date.today)
    status = models.CharField(max_length=1, choices=INVITE_STATUS)


if EmailAddress:
    def new_user(sender, instance, **kwargs):
        if instance.verified:
            for join_invitation in JoinInvitation.objects.filter(contact__email=instance.email):
                if join_invitation.status not in ["5", "7"]: # if not accepted or already marked as joined independently
                    join_invitation.status = "7"
                    join_invitation.save()
                    # notification will be covered below
            for contact in Contact.objects.filter(email=instance.email):
                contact.users.add(instance.user)
                # @@@ send notification
    
    # only if django-email-notification is installed
    signals.post_save.connect(new_user, sender=EmailAddress)

def delete_friendship(sender, instance, **kwargs):
    friendship_invitations = FriendshipInvitation.objects.filter(to_user=instance.to_user, from_user=instance.from_user)
    for friendship_invitation in friendship_invitations:
        if friendship_invitation.status != "8":
            friendship_invitation.status = "8"
            friendship_invitation.save()


# moves existing friendship invitation from user to user to FriendshipInvitationHistory before saving new invitation
def friendship_invitation(sender, instance, **kwargs):
    friendship_invitations = FriendshipInvitation.objects.filter(to_user=instance.to_user, from_user=instance.from_user)
    for friendship_invitation in friendship_invitations:
        FriendshipInvitationHistory.objects.create(
                from_user=friendship_invitation.from_user,
                to_user=friendship_invitation.to_user,
                message=friendship_invitation.message,
                sent=friendship_invitation.sent,
                status=friendship_invitation.status
                )
        friendship_invitation.delete()




# SIGNALS
signals.pre_save.connect(friendship_invitation, sender=FriendshipInvitation)
signals.post_save.connect(contact_update_user, sender=User)
signals.post_save.connect(friendsuggestion_update_user, sender=User)
signals.post_save.connect(contact_create_for_friendship, sender=Friendship)
signals.post_save.connect(friendship_destroys_suggestions, sender=Friendship)
signals.pre_delete.connect(delete_friendship, sender=Friendship)
signals.post_save.connect(suggest_friend_from_invite, sender=JoinInvitation)