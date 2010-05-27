from django.contrib.auth.models import User
from models import *

def build_friend_suggestions(user, *args, **kwargs):
    profile = user.get_profile()
    friend_suggestions_users = [fs.suggested_user for fs in FriendSuggestion.objects.filter(user=user)]
    try:
        coworkers = profile.get_neighbors().exclude(user__in=friend_suggestions_users)
        for coworker in coworkers:
            try:
                FriendSuggestion.objects.get(user=user, suggested_user=coworker.user)
            except FriendSuggestion.DoesNotExist:
                FriendSuggestion(user=user, suggested_user=coworker.user, why=SUGGEST_BECAUSE_COWORKER).save()
    except AttributeError:
        pass
    for fof in friends_of_friends(user).exclude(id__in=friend_suggestions_users):
            try:
                FriendSuggestion.objects.get(user=user, suggested_user=coworker.user)
            except FriendSuggestion.DoesNotExist:
                FriendSuggestion(user=user, suggested_user=fof, why=SUGGEST_BECAUSE_FRIENDOFFRIEND)
    try:
        neighbors = profile.get_neighbors().exclude(user__in=friend_suggestions_users)
        MAX_NEIGHBORS = 100 # Don't add them as suggestions if you're in an area with a ton of people.
        if neighbors.count() < MAX_NEIGHBORS:
            for neighbor in neighbors:
                try:
                    FriendSuggestion.objects.get(user=user, suggested_user=neighbor.user)
                except FriendSuggestion.DoesNotExist:
                    FriendSuggestion(user=user, suggested_user=neighbor.user, why=SUGGEST_BECAUSE_NEIGHBOR).save()
    except AttributeError:
        pass        

def shared_friends(me, them):
    my_friends = User.objects.filter(friends__from_user=me)
    their_friends = User.objects.filter(friends__from_user=them)
    shared_friends = my_friends & their_friends
    return shared_friends.exclude(id__in=[me.id, them.id])

def friends_of_friends(user):
    return User.objects.filter(friends__from_user__friends__from_user=user).exclude(id=user.id).exclude(friends__from_user=user)
