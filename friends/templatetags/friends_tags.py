from friends.utils import shared_friends as get_shared_friends
from django import template
from django.core.urlresolvers import NoReverseMatch

register = template.Library()

def shared_friends(context):
    friend = context['user']
    request = context['request']
    return {
        'request': context['request'],
        'friend': friend,
        'shared_friends': get_shared_friends(request.user, friend)
    }
register.inclusion_tag('friends/shared_friends.inc', takes_context=True)(shared_friends)
