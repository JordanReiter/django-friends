from friends.utils import shared_friends
from django import template
from django.core.urlresolvers import NoReverseMatch

register = template.Library()

def shared_friends(context, friend):
    return {
        'request': context['request'],
        'user': context['user'],
        'friend': friend,
        'shared_friends': shared_friends(context['user'], friend)
    }
register.inclusion_tag('friends/shared_friends.inc', takes_context=True)(shared_friends)
