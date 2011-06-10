from django.contrib.auth.models import User
from models import *

from django.conf import settings
if "notification" in settings.INSTALLED_APPS:
    from notification import models as notification
else:
    notification = None


def build_friend_suggestions(user, *args, **kwargs):
    profile = user.get_profile()
    friend_suggestions_users = [fs.suggested_user for fs in FriendSuggestion.objects.select_related('suggested_user__id').filter(user=user)]
    try:
        coworkers = profile.get_coworkers().exclude(user__in=friend_suggestions_users)
        for coworker in coworkers:
            try:
                FriendSuggestion.objects.get(user=user, suggested_user=coworker.user)
            except FriendSuggestion.DoesNotExist:
                FriendSuggestion(user=user, suggested_user=coworker.user, why=SUGGEST_BECAUSE_COWORKER).save()
    except AttributeError, inst:
        print inst
        pass
    for fof in friends_of_friends(user).exclude(id__in=[u.id for u in friend_suggestions_users]):
            try:
                FriendSuggestion.objects.get(user=user, suggested_user=fof)
            except FriendSuggestion.DoesNotExist:
                FriendSuggestion(user=user, suggested_user=fof, why=SUGGEST_BECAUSE_FRIENDOFFRIEND).save()
    try:
        neighbors = profile.get_neighbors().exclude(user__in=friend_suggestions_users)
        MAX_NEIGHBORS = 100 # Don't add them as suggestions if you're in an area with a ton of people.
        if neighbors.count() < MAX_NEIGHBORS:
            for neighbor in neighbors:
                try:
                    FriendSuggestion.objects.get(user=user, suggested_user=neighbor.user)
                except FriendSuggestion.DoesNotExist:
                    FriendSuggestion(user=user, suggested_user=neighbor.user, why=SUGGEST_BECAUSE_NEIGHBOR).save()
    except AttributeError, inst:
        print inst
        pass        

def shared_friends(me, them):
    my_friends = User.objects.filter(friends__to_user=me)
    their_friends = User.objects.filter(friends__to_user=them)
    shared_friends = my_friends & their_friends
    return shared_friends.exclude(id__in=[me.id, them.id])

def friends_of_friends(user):
    return User.objects.filter(friends__to_user__friends__to_user=user).exclude(id=user.id).exclude(friends__to_user=user)

def send_invitations(me, invited_emails=[], message=None):
        processed_emails = []
        existing_users = User.objects.filter(email__in=invited_emails)
        requests = 0
        invitations = 0
        existing = 0
        total = len(invited_emails)
        friend_users = [f['friend'] for f in Friendship.objects.friends_for_user(me)]
        if existing_users:
            for user in existing_users:
                if user in friend_users:
                    existing += 1
                else:
                    requests += 1
                    invitation = FriendshipInvitation(from_user=me, to_user=user, message=message, status="2")
                    invitation.save()
                    if notification:
                        notification.send([user], "friends_invite", {"invitation": invitation})
                        notification.send([me], "friends_invite_sent", {"invitation": invitation})
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
                JoinInvitation.objects.send_invitation(me, email, None)
        return total, requests, existing, invitations

def get_friends(user=None):
    if not hasattr(user, '_friends'):
        friend_list = Friendship.objects.friends_for_user(user)
        friend_users = {}
        for u in User.objects.filter(pk__in=[f['friend'].pk for f in friend_list]):
            friend_users[u.id]=u
        already = []
        user._friends = []
        for f in friend_list:
            if f['friend'] not in already:
                user._friends.append(f)
                already.append(f['friend'])
    return user._friends
