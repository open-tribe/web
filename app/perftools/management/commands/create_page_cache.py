'''
    Copyright (C) 2019 Gitcoin Core

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published
    by the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.

'''

import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.db.models import Count, Q
from django.db.models.query import QuerySet
from django.forms.models import model_to_dict
from django.utils.encoding import force_text
from django.utils.functional import Promise

from dashboard.models import Profile
from economy.models import EncodeAnything, SuperModel
from perftools.models import JSONStore
from retail.utils import build_stat_results, programming_languages


def fetchPost(qt='2'):
    import requests
    """Fetch last post from wordpress blog."""
    url = f"https://gitcoin.co/blog/wp-json/wp/v2/posts?_fields=excerpt,title,link,jetpack_featured_media_url&per_page={qt}"
    last_posts = requests.get(url=url).json()
    return last_posts

def create_hidden_profiles_cache():

    handles = list(Profile.objects.hidden().values_list('handle', flat=True))

    view = 'hidden_profiles'
    keyword = 'hidden_profiles'
    with transaction.atomic():
        JSONStore.objects.filter(view=view).all().delete()
        data = handles
        JSONStore.objects.create(
            view=view,
            key=keyword,
            data=data,
            )


def create_tribes_cache():

    _tribes = Profile.objects.filter(data__type='Organization').\
        annotate(follower_count=Count('org')).cache().order_by('-follower_count')[:8]

    tribes = []

    for _tribe in _tribes:
        tribe = {
            'name': _tribe.handle,
            'img': _tribe.avatar_url,
            'followers_count': _tribe.follower_count
        }
        tribes.append(tribe)

    view = 'tribes'
    keyword = 'tribes'
    with transaction.atomic():
        JSONStore.objects.filter(view=view).all().delete()
        data = tribes
        JSONStore.objects.create(
            view=view,
            key=keyword,
            data=data,
            )


def create_post_cache():
    data = fetchPost()
    view = 'posts'
    keyword = 'posts'
    JSONStore.objects.filter(view=view, key=keyword).all().delete()
    data = json.loads(json.dumps(data, cls=EncodeAnything))
    JSONStore.objects.create(
        view=view,
        key=keyword,
        data=data,
        )


def create_avatar_cache():
    from avatar.models import AvatarTheme, CustomAvatar
    for at in AvatarTheme.objects.all():
        at.popularity = at.popularity_cheat_by
        if at.name == 'classic':
            at.popularity += CustomAvatar.objects.filter(active=True, config__icontains='"Ears"').count()
        elif at.name == 'unisex':
            at.popularity += CustomAvatar.objects.filter(active=True, config__theme=["3d"]).count()
            at.popularity += CustomAvatar.objects.filter(active=True, config__icontains='hairTone').exclude(config__icontains="theme").count()
        else:
            at.popularity += CustomAvatar.objects.filter(active=True, config__theme=[at.name]).count()
        at.save()


def create_activity_cache():
    from django.utils import timezone
    from dashboard.models import Activity
    hours = 24 if not settings.DEBUG else 1000

    print('activity.1')
    view = 'activity'
    keyword = '24hcount'
    data = Activity.objects.filter(created_on__gt=timezone.now() - timezone.timedelta(hours=hours)).count()
    JSONStore.objects.filter(view=view, key=keyword).all().delete()
    JSONStore.objects.create(
        view=view,
        key=keyword,
        data=json.loads(json.dumps(data, cls=EncodeAnything)),
        )

    print('activity.2')
    from retail.views import get_specific_activities
    from townsquare.views import tags
    for tag in tags:
        keyword = tag[2]
        data = get_specific_activities(keyword, False, None, None).filter(created_on__gt=timezone.now() - timezone.timedelta(hours=hours)).count()
        JSONStore.objects.filter(view=view, key=keyword).all().delete()
        JSONStore.objects.create(
            view=view,
            key=keyword,
            data=json.loads(json.dumps(data, cls=EncodeAnything)),
            )

def create_grants_cache():
    from grants.utils import generate_leaderboard
    print('grants')
    view = 'grants'
    keyword = 'leaderboard'
    data = generate_leaderboard()
    JSONStore.objects.create(
        view=view,
        key=keyword,
        data=json.loads(json.dumps(data, cls=EncodeAnything)),
        )


def create_quests_cache():
    from quests.helpers import generate_leaderboard
    from quests.views import current_round_number
    for i in range(1, current_round_number+1):
        print(f'quests_{i}')
        view = 'quests'
        keyword = f'leaderboard_{i}'
        data = generate_leaderboard(round_number=i)
        JSONStore.objects.create(
            view=view,
            key=keyword,
            data=json.loads(json.dumps(data, cls=EncodeAnything)),
            )

    from quests.models import Quest
    for quest in Quest.objects.filter(visible=True):
        quest.save()


def create_results_cache():
    print('results')
    keywords = ['']
    if settings.DEBUG:
        keywords = ['']
    view = 'results'
    with transaction.atomic():
        items = []
        JSONStore.objects.filter(view=view).all().delete()
        for keyword in keywords:
            print(f"- executing {keyword}")
            data = build_stat_results(keyword)
            print("- creating")
            items.append(JSONStore(
                view=view,
                key=keyword,
                data=json.loads(json.dumps(data, cls=EncodeAnything)),
                ))
        JSONStore.objects.bulk_create(items)


def create_contributor_landing_page_context():
    print('create_contributor_landing_page_context')
    keywords = [''] + programming_languages
    if settings.DEBUG:
        keywords = ['']
    view = 'contributor_landing_page'
    from retail.views import get_contributor_landing_page_context
    with transaction.atomic():
        items = []
        JSONStore.objects.filter(view=view).all().delete()
        for keyword in keywords:
            print(f"- executing {keyword}")
            data = get_contributor_landing_page_context(keyword)
            print("- creating")
            items.append(JSONStore(
                view=view,
                key=keyword,
                data=json.loads(json.dumps(data, cls=EncodeAnything)),
                ))
        JSONStore.objects.bulk_create(items)



class Command(BaseCommand):

    help = 'generates some /results data'

    def handle(self, *args, **options):
        create_hidden_profiles_cache()
        if not settings.DEBUG:
            create_tribes_cache()
            create_activity_cache()
            create_post_cache()
            create_results_cache()
            create_avatar_cache()
            create_quests_cache()
            create_grants_cache()
            create_contributor_landing_page_context()
