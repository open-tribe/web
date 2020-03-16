import logging

from django.conf import settings
from django.utils.text import slugify

from app.redis_service import RedisService
from celery import app, group
from celery.utils.log import get_task_logger
from dashboard.models import Bounty, HackathonEvent, HackathonRegistration, HackathonSponsor, Profile
from marketing.utils import should_suppress_notification_email
from mattermostdriver import Driver
from mattermostdriver.exceptions import ResourceNotFound

logger = logging.getLogger(__name__)
redis = RedisService().redis

# Lock timeout of 2 minutes (just in the case that the application hangs to avoid a redis deadlock)
LOCK_TIMEOUT = 60 * 2

driver_opts = {
    'scheme': 'https' if settings.CHAT_PORT == 443 else 'http',
    'url': settings.CHAT_SERVER_URL,
    'port': settings.CHAT_PORT,
    'token': settings.CHAT_DRIVER_TOKEN
}


def create_channel_if_not_exists(options):
    try:
        chat_driver.login()
        channel_lookup_response = chat_driver.channels.get_channel_by_name(
            options['team_id'], options['channel_name']
        )
        return False, channel_lookup_response

    except ResourceNotFound as RNF:
        try:
            chat_driver.login()
            new_channel = chat_driver.channels.create_channel(options={
                'team_id': options['team_id'],
                'name': options['channel_name'],
                'purpose': options['channel_purpose'] if 'channel_purpose' in options else '',
                'header': options['channel_header'] if 'channel_header' in options else '',
                'display_name': options['channel_display_name'],
                'type': options['channel_type'] if 'channel_type' in options else 'O'
            })
            if 'message' in new_channel:
                raise ValueError(new_channel['message'])

            return True, new_channel
        except Exception as e:
            logger.error(str(e))


def update_chat_notifications(profile, notification_key, status):
    query_opts = {}
    if profile.chat_id is not '' or profile.chat_id is not None:
        query_opts['chat_id'] = profile.chat_id

    query_opts['handle'] = profile.handle
    # TODO: set this to retreive current chat notification propers and then just patch whats diff
    notify_props = chat_notify_default_props(profile)

    notify_props[notification_key] = "true" if status else "false"

    patch_chat_user.delay(query_opts=query_opts, update_opts={'notify_props': notify_props})


def chat_notify_default_props(profile):
    return {
        "email": "false" if should_suppress_notification_email(profile.user.email, 'chat') else "true",
        "push": "mention",
        "comments": "never",
        "desktop": "all",
        "desktop_sound": "true",
        "mention_keys": f'{profile.handle}, @{profile.handle}',
        "channel": "true",
        "first_name": "false",
        "push_status": "away"
    }


def associate_chat_to_profile(profile):
    chat_driver.login()
    try:

        current_chat_user = chat_driver.users.get_user_by_username(profile.handle)
        profile.chat_id = current_chat_user['id']
        profile_access_token = {'token': ''}
        if profile.gitcoin_chat_access_token is '' or profile.gitcoin_chat_access_token is None:
            try:
                profile_access_tokens = chat_driver.users.get_user_access_token(profile.chat_id)
                for pat in profile_access_tokens:
                    if pat.is_active:
                        profile_access_token = pat
                        break
            except Exception as e:
                logger.error(str(e))
                try:
                    profile_access_token = chat_driver.users.create_user_access_token(user_id=profile.chat_id, options={
                        'description': "Grants Gitcoin access to modify your account"})
                except Exception as e:
                    logger.info('Failed to create access token')
                    logger.error(str(e))

            profile.gitcoin_chat_access_token = profile_access_token['token']

        profile.save()

        return False, profile
    except ResourceNotFound as RNF:
        if not profile.chat_id:
            create_user_response = chat_driver.users.create_user(
                options={
                    "email": profile.user.email,
                    "username": profile.handle,
                    "first_name": profile.user.first_name,
                    "last_name": profile.user.last_name,
                    "nickname": profile.handle,
                    "auth_data": f'{profile.user.id}',
                    "auth_service": "gitcoin",
                    "locale": "en",
                    "props": {},
                    "notify_props": chat_notify_default_props(profile),
                },
                params={
                    "tid": settings.GITCOIN_CHAT_TEAM_ID
                })
            profile.chat_id = create_user_response['id']
            chat_driver.teams.add_user_to_team(
                settings.GITCOIN_HACK_CHAT_TEAM_ID,
                options={'team_id': settings.GITCOIN_HACK_CHAT_TEAM_ID,
                         'user_id': create_user_response['id']}
            )
            try:
                profile_access_tokens = chat_driver.users.get_user_access_token(profile.chat_id)
                for pat in profile_access_tokens:
                    if pat.is_active:
                        profile_access_token = pat
                        break

            except Exception as e:
                logger.error(str(e))
                profile_access_token = chat_driver.users.create_user_access_token(user_id=profile.chat_id, options={
                    'description': "Grants Gitcoin access to modify your account"})

            profile.gitcoin_chat_access_token = profile_access_token['token']

            profile.save()

        return True, profile


def get_chat_url(front_end=False):
    chat_url = settings.CHAT_URL
    if not front_end:
        chat_url = settings.CHAT_SERVER_URL
    if settings.CHAT_PORT not in [80, 443]:
        chat_url = f'http://{chat_url}:{settings.CHAT_PORT}'
    else:
        chat_url = f'https://{chat_url}'
    return chat_url


chat_driver = Driver(driver_opts)


def get_driver():
    chat_driver.login()
    return chat_driver


@app.shared_task(bind=True, max_retries=3)
def create_channel(self, options, bounty_id=None, retry: bool = True) -> None:
    """
    :param options:
    :param retry:
    :return:
    """
    with redis.lock("tasks:create_channel:%s" % options['channel_name'], timeout=LOCK_TIMEOUT):

        chat_driver.login()
        try:
            channel_lookup = chat_driver.channels.get_channel_by_name(
                options['team_id'],
                options['channel_name']
            )
            if bounty_id:
                active_bounty = Bounty.objects.get(id=bounty_id)
                active_bounty.chat_channel_id = channel_lookup['id']
                active_bounty.save()
            return channel_lookup
        except ResourceNotFound as RNF:
            new_channel = chat_driver.channels.create_channel(options={
                'team_id': options['team_id'],
                'name': options['channel_name'],
                'purpose': options['channel_purpose'] if 'channel_purpose' in options else '',
                'header': options['channel_header'] if 'channel_header' in options else '',
                'display_name': options['channel_display_name'],
                'type': options['channel_type'] or 'O'
            })

            if bounty_id:
                active_bounty = Bounty.objects.get(id=bounty_id)
                active_bounty.chat_channel_id = new_channel['id']
                active_bounty.save()
            return new_channel
        except ConnectionError as exc:
            logger.info(str(exc))
            logger.info("Retrying connection")
            self.retry(30)
        except Exception as e:
            print("we got an exception when creating a channel")
            logger.error(str(e))


@app.shared_task(bind=True, max_retries=3)
def hackathon_chat_sync(self, hackathon_id: str, profile_handle: str = None, retry: bool = True) -> None:
    try:
        chat_driver.login()
        hackathon = HackathonEvent.objects.get(id=hackathon_id)
        channels_to_connect = []
        if hackathon.chat_channel_id is '' or hackathon.chat_channel_id is None:
            created, new_channel_details = create_channel_if_not_exists({
                'team_id': settings.GITCOIN_HACK_CHAT_TEAM_ID,
                'channel_display_name': f'general-{hackathon.slug}'[:60],
                'channel_name': f'general-{slugify(hackathon.name)}'[:60]
            })
            print(new_channel_details)
            hackathon.chat_channel_id = new_channel_details['id']
            hackathon.save()
        channels_to_connect.append(hackathon.chat_channel_id)

        profiles_to_connect = []
        if profile_handle is None:

            regs_to_sync = HackathonRegistration.objects.filter(hackathon__id=hackathon_id) \
                .prefetch_related('registrant')

            for reg in regs_to_sync:
                if reg.registrant is None:
                    continue

                if reg.registrant.chat_id is '' or reg.registrant.chat_id is None:
                    created, updated_profile = associate_chat_to_profile(reg.registrant)
                    profiles_to_connect.append(updated_profile.chat_id)
                else:
                    profiles_to_connect.append(reg.registrant.chat_id)
        else:
            profile = Profile.objects.get(handle=profile_handle.lower())
            if profile.chat_id is '' or profile.chat_id is None:
                created, updated_profile = associate_chat_to_profile(profile)
                profiles_to_connect.append(updated_profile.chat_id)
            else:
                profiles_to_connect = [profile.chat_id]

        for sponsor in hackathon.sponsors.all():
            hack_sponsor = HackathonSponsor.objects.get(sponsor=sponsor)
            if hack_sponsor.chat_channel_id is '' or hack_sponsor.chat_channel_id is None:
                created, new_channel_details = create_channel_if_not_exists({
                    'team_id': settings.GITCOIN_HACK_CHAT_TEAM_ID,
                    'channel_display_name': f'company-{slugify(hack_sponsor.sponsor.name)}'[:60],
                    'channel_name': f'company-{hack_sponsor.sponsor.name}'[:60]
                })

                hack_sponsor.chat_channel_id = new_channel_details['id']
                hack_sponsor.save()
            channels_to_connect.append(hack_sponsor.chat_channel_id)

        for channel_id in channels_to_connect:
            try:
                current_channel_members = chat_driver.channels.get_channel_members(channel_id)
            except Exception as e:
                continue

            current_channel_users = [member['user_id'] for member in current_channel_members]
            profiles_to_connect = list(set(profiles_to_connect) - set(current_channel_users))

            if len(profiles_to_connect) > 0:
                add_to_channel.delay(
                    {'id': channel_id},
                    profiles_to_connect
                )

    except Exception as e:
        logger.error(str(e))


@app.shared_task(bind=True, max_retries=3)
def add_to_channel(self, channel_details, chat_user_ids: list, retry: bool = True) -> None:
    """
    :param channel_details:
    :param chat_user_ids:
    :param retry:
    :return:
    """
    chat_driver.login()
    try:
        for chat_user_id in chat_user_ids:
            if chat_user_id is '' or chat_user_id is None:
                continue
            print(chat_user_id)
            print(channel_details)
            chat_driver.channels.add_user(channel_details['id'], options={
                'user_id': chat_user_id
            })

    except ConnectionError as exc:
        logger.info(str(exc))
        logger.info("Retrying connection")
        self.retry(30)
    except Exception as e:
        logger.error(str(e))


@app.shared_task(bind=True, max_retries=1)
def create_user(self, options, params, profile_handle='', retry: bool = True):
    with redis.lock("tasks:create_user:%s" % options['username'], timeout=LOCK_TIMEOUT):
        try:
            chat_driver.login()
            create_user_response = chat_driver.users.create_user(
                options=options,
                params=params
            )
            if profile_handle:
                profile = Profile.objects.get(handle=profile_handle.lower())
                profile.chat_id = create_user_response['id']

                profile_access_token = chat_driver.users.create_user_access_token(user_id=create_user_response['id'],
                                                                                  options={
                                                                                      'description': "Grants Gitcoin access to modify your account"})
                profile.gitcoin_chat_access_token = profile_access_token['id']
                profile.save()

                chat_driver.teams.add_user_to_team(
                    settings.GITCOIN_HACK_CHAT_TEAM_ID,
                    options={'team_id': settings.GITCOIN_HACK_CHAT_TEAM_ID,
                             'user_id': create_user_response['id']}
                )

            return create_user_response
        except ConnectionError as exc:
            logger.info(str(exc))
            logger.info("Retrying connection")
            self.retry(30)
        except Exception as e:
            logger.error(str(e))
            return None


@app.shared_task(bind=True, max_retries=3)
def patch_chat_user(self, query_opts, update_opts, retry: bool = True) -> None:
    """
    :param self:
    :param query_opts:
    :param update_opts:
    :param retry:
    :return: None
    """

    if update_opts is None:
        return

    with redis.lock("tasks:update_user:%s" % query_opts['handle'], timeout=LOCK_TIMEOUT):
        chat_driver.login()

        try:
            chat_id = None
            if query_opts['chat_id'] is None and query_opts['handle']:
                try:
                    chat_user = chat_driver.users.get_user_by_username(query_opts['handle'])
                    chat_id = chat_user['id']
                    user_profile = Profile.objects.filter(handle=query_opts['handle'].lower())
                    user_profile.chat_id = chat_id
                    user_profile.save()
                except Exception as e:
                    logger.info(f"Unable to find chat user for {query_opts['handle']}")
            else:
                chat_id = query_opts['chat_id']
            chat_driver.users.patch_user(chat_id, options=update_opts)
        except ConnectionError as exc:

            logger.info(str(exc))
            logger.info("Retrying connection")
            self.retry(30)
        except Exception as e:
            logger.error(str(e))
