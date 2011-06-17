import datetime, re
from django.utils.translation import ugettext as _

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


__all__ = [
    "GoogleToken", 
    "IMPORTED_TYPES", "CONTACT_TYPES", "Contact", 
    "SUGGEST_BECAUSE_INVITE", "SUGGEST_BECAUSE_COWORKER", 
    "SUGGEST_BECAUSE_COAUTHOR", "SUGGEST_BECAUSE_FRIENDOFFRIEND", 
    "SUGGEST_BECAUSE_NEIGHBOR", "SUGGEST_WHY_CHOICES",
    "FriendSuggestion", "Friendship", "INVITE_STATUS", "JoinInvitation",
    "FriendshipInvitation", "FriendshipInvitationHistory", "delete_friendship", "friendship_invitation"
]
    
try:
    from django_countries import CountryField
except ImportError:
    class CountryField(models.CharField): 
        def __init__(self, *args, **kwargs): 
            kwargs.setdefault('max_length', 50) 
            super(models.CharField, self).__init__(*args, **kwargs) 

class GoogleToken(models.Model):
    user = models.ForeignKey(User, related_name='googletokens')
    token = models.TextField()
    token_secret = models.CharField(max_length=100)
    
    def get_token(self):
        import pickle
        return pickle.loads(str(self.token))

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
    
    def create_from_user(self, owner, user, *args, **kwargs):
        contact, created = self.get_or_create(owner=owner, email=user.email)
        contact.user = user
        contact.first_name = user.first_name
        contact.last_name = user.last_name
        contact.name = user.get_full_name()
        contact.save()
        return contact, created


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
    owner = models.ForeignKey(User, related_name="contacts", editable=False, null=True, blank=True, on_delete=models.SET_NULL)
    
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
    
    def save(self, *args, **kwargs):
        if self.email and not self.name and not (self.first_name or self.last_name):
            name = ""
            for w in re.split(r'\W+',self.email.split('@')[0]):
                if not re.search(r'[A-Z][a-z]', w):
                    w = w.title()
                name += " " + w
                print "Now name is %s" % name
            self.name = name.strip()
        if not self.name and (self.first_name or self.last_name):
            self.name = ("%s %s" % (self.first_name, self.last_name)).strip()
        super(Contact,self).save(*args, **kwargs)
        return self
    
    def get_label(self):
        if self.user and self.user.get_full_name():
            return self.user.get_full_name()
        elif self.name:
            return self.name
        elif self.first_name or self.last_name:
            return ("%s %s" % (self.first_name, self.last_name)).strip()
        else:
            return self.email
    
    def __unicode__(self):
        if self.name:
            label = "%s <%s>" % (self.name, self.email)
        elif self.first_name or self.last_name:
            label = "%s %s <%s>" % (self.first_name, self.last_name, self.email)
        else:
            label = self.email
        return "%s (%s's contact)" % (label.strip(), self.owner)
    
    class Meta:
        unique_together = (('owner','email'))

def contact_update_user(sender, instance, created, *args, **kwargs):
    if created:
        Contact.objects.filter(email=instance.email).update(user=instance)

def contact_create_for_friendship(sender, instance, created, *args, **kwargs):
    if created:
        contact1, _ = Contact.objects.create_from_user(instance.to_user, user=instance.from_user)
        contact1.type = 'F'
        contact1.save()
        contact2, _ = Contact.objects.create_from_user(owner=instance.from_user, user=instance.to_user)
        contact2.type = 'F'
        contact2.save()

SUGGEST_BECAUSE_INVITE=0
SUGGEST_BECAUSE_COWORKER=1
SUGGEST_BECAUSE_COAUTHOR=2
SUGGEST_BECAUSE_FRIENDOFFRIEND=3
SUGGEST_BECAUSE_NEIGHBOR=4
SUGGEST_WHY_CHOICES = (
    (SUGGEST_BECAUSE_INVITE, "They sent you an invitation to the site."),
    (SUGGEST_BECAUSE_COWORKER, "They work at the same organization/company."),
    (SUGGEST_BECAUSE_COAUTHOR, "They co-authored one or more papers with you."),
    (SUGGEST_BECAUSE_FRIENDOFFRIEND, "They're connected to you through another member on the site."),
    (SUGGEST_BECAUSE_NEIGHBOR,"They live in the same town or city."),
)

class FriendSuggestionQuerySet(models.query.QuerySet):
    def filter(self, *args, **kwargs):
        self.ex

class FriendSuggestionManager(models.Manager):
    def get_query_set(self, *args, **kwargs):
        return FriendSuggestionQuerySet(self.model, using=self._db)

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
    
    def __unicode__(self):
        if self.user:
            return "%s should become friends with %s" % ((self.user.get_full_name() or self.user.username), (self.suggested_user.get_full_name() or self.suggested_user.username))
        else:
            return "%s should become friends with %s" % ((self.email), (self.suggested_user.get_full_name() or self.suggested_user.username))

def suggest_friend_from_invite(sender, instance, created, *args, **kwargs):
    if created:
        FriendSuggestion.objects.get_or_create(suggested_user=instance.from_user, email=instance.contact.email, why=SUGGEST_BECAUSE_INVITE)

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
        me_friends = self.filter(from_user=user).select_related("to_user__pk","to_user__profile__pk","from_user__pk","from_user__profile__pk").order_by('to_user__last_name','to_user__first_name')
        them_friends = self.filter(to_user=user).select_related("to_user__pk","to_user__profile__pk","from_user__pk","from_user__profile__pk").order_by('from_user__last_name','from_user__first_name')
        all_friends = me_friends | them_friends
        # give priority to "from" records. This is done by looping through them twice and only adding "to" records
        # if absolutely necessary.
        for friendship in all_friends:
            if friendship.from_user_id == user.id:
                friend = friendship.to_user
                if friend.pk not in already:
                    already.append(friend.pk)
                    friends.append({"friend": friend, "how_related": None })
        for friendship in all_friends:
            if friendship.to_user_id == user.id:
                friend = friendship.from_user
                if friend.pk not in already:
                    already.append(friend.pk)
                    friends.append({"friend": friend, "how_related": None })
        return sorted(friends, key=lambda k: "%s%s" % (k['friend'].last_name, k['friend'].first_name) )
    
    def are_friends(self, user1, user2):
        if self.filter(from_user=user1, to_user=user2).count() > 0:
            return True
        if self.filter(from_user=user2, to_user=user1).count() > 0:
            return True
        return False
    
    def remove(self, user1, user2):
        self.filter(from_user=user1, to_user=user2).delete()
        self.filter(from_user=user2, to_user=user1).delete()


HOW_RELATED_LABELS = {
    'colleague':[_('are colleagues'),_('are colleagues')],
    'met':[_('have met'),_('have met')],
    'co-worker':[_('work together'),_('work together')],
    'friend': [_('are friends'),_('are friends')],
    'co-author': [_('are co-authors (co-wrote a paper)'),_('are co-authors (co-wrote a paper)')],
    'unknown': None,
}
class Friendship(models.Model):
    """
    A friendship is a bi-directional association between two users who
    have both agreed to the association.
    """
    
    to_user = models.ForeignKey(User, related_name="_unused_", editable=False)
    from_user = models.ForeignKey(User, related_name="friends", editable=False)
    how_related = models.CharField(max_length=100, null=True, blank=True)
    added = models.DateField(default=datetime.date.today, editable=False)
    
    objects = FriendshipManager()
    
    class Meta:
        unique_together = (('to_user', 'from_user'),)

    def render_related_you(self):
        return self.render_related(you=True)

    def save(self, *args, **kwargs):
        matching_fs = FriendSuggestion.objects.filter(suggested_user=self.to_user, user=self.from_user) | FriendSuggestion.objects.filter(suggested_user=self.from_user, user=self.to_user)
        matching_fs.delete()
        matching_fis = FriendshipInvitation.objects.filter(from_user=self.from_user, to_user=self.to_user) | FriendshipInvitation.objects.filter(from_user=self.to_user, to_user=self.from_user)
        matching_fis.update(status='5')
        super(Friendship, self).save(*args, **kwargs)

    def render_related(self, you=False):
        result = ""
        if not (self.how_related and len(self.how_related)):
            return None
        reason_list = []
        how_related_tokens = self.how_related.split(' ')
        how_related_codes = HOW_RELATED_LABELS.keys()
        if you:
            reason_index = 0
        else:
            reason_index = 1
        reasons_shown = []
        while len(how_related_tokens):
            # next two lines simulate shift function
            hr=how_related_tokens[0].lower().strip()
            if hr not in how_related_codes:
                break
            del(how_related_tokens[:1])
            if hr in reasons_shown:
                continue 
            else:
                reasons_shown.append(hr)
                try:
                    reason_list.append(HOW_RELATED_LABELS[hr][reason_index])
                except IndexError, inst:
                    pass
        other = ' '.join(how_related_tokens)
        if len(reason_list) > 2:
            reason_list[-1]=_('and %(last)s' % {'last': reason_list[-1]})
            reason_string = ', '.join(reason_list)
        else:
            reason_string = ' and '.join(reason_list)
        if len(reason_string):
            if not you:
                subject = _("%(onefriend)s and %(twofriend)s" % {
                    'onefriend': (self.from_user.first_name or self.from_user.username),
                    'twofriend': (self.to_user.first_name or self.to_user.username),
                })
            else:
                subject = _("You")
            result += _("%(subject)s %(reasons)s." % {'subject': subject, 'reasons': reason_string})
        if other:
            result += _(" %(other)s" % {'other': other})
        return result
        
        
    def __unicode__(self):
        result = "%s is friend of %s" % (self.from_user, self.to_user)
        if self.how_related:
            result+= " (%s)" % self.how_related
        return result

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
    
    def send_invitation(self, from_user, to_email, message=None):
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
    
    def accept(self, new_user, notify_friends=False):
        # mark invitation accepted
        self.status = "5"
        self.save()
        # auto-create friendship
        friendship = Friendship(to_user=new_user, from_user=self.from_user)
        friendship.save()
        # notify
        if notification:
            notification.send([self.from_user], "join_accept", {"invitation": self, "new_user": new_user, "current_site": Site.objects.get_current()})
            friends = []
            for user in friend_set_for(new_user) | friend_set_for(self.from_user):
                if user != new_user and user != self.from_user:
                    friends.append(user)
            if notify_friends:
                notification.send(friends, "friends_otherconnect", {"invitation": self, "to_user": new_user, "curent_site": Site.objects.get_current()})
    
    class Meta:
        ordering=['-sent']


class FriendshipInvitationManager(models.Manager):

    def active(self, *args, **kwargs):
        self.filter(*args, **kwargs).filter(status__in=["1","2","7"])
    
    def invitations(self, *args, **kwargs):
        return self.filter(*args, **kwargs).exclude(status__in=["6", "8"])


class FriendshipInvitation(models.Model):
    """
    A frienship invite is an invitation from one user to another to be
    associated as friends.
    """
    
    from_user = models.ForeignKey(User, related_name="invitations_from")
    to_user = models.ForeignKey(User, related_name="invitations_to")
    how_related = models.CharField(max_length=100, null=True, blank=True)
    message = models.CharField(max_length=2000, null=True, blank=True)
    sent = models.DateField(default=datetime.date.today)
    status = models.CharField(max_length=1, choices=INVITE_STATUS)
    
    objects = FriendshipInvitationManager()
    
    def accept(self, notify_friends=False):
        if not Friendship.objects.are_friends(self.to_user, self.from_user):
            friendship = Friendship(to_user=self.to_user, from_user=self.from_user, how_related=self.how_related)
            friendship.save()
            self.status = "5"
            self.save()
            if notification:
                notification.send([self.from_user], "friends_accept", {"invitation": self, "curent_site": Site.objects.get_current()})
                notification.send([self.to_user], "friends_accept_sent", {"invitation": self, "curent_site": Site.objects.get_current()})
                if notify_friends:
                    for user in friend_set_for(self.to_user) | friend_set_for(self.from_user):
                        if user != self.to_user and user != self.from_user:
                            notification.send([user], "friends_otherconnect", {"invitation": self, "to_user": self.to_user, "curent_site": Site.objects.get_current()})
    
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
