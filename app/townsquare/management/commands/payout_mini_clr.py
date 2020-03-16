'''
    Copyright (C) 2020 Gitcoin Core

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
import time

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core import management
from django.core.management.base import BaseCommand
from django.utils import timezone

from dashboard.models import Activity, Earning, Profile
from dashboard.utils import get_tx_status, get_web3, has_tx_mined
from gas.utils import recommend_min_gas_price_to_confirm_in_time
from townsquare.models import MatchRound
from web3 import HTTPProvider, Web3

abi = json.loads('[{"constant":true,"inputs":[],"name":"mintingFinished","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_from","type":"address"},{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transferFrom","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_to","type":"address"},{"name":"_amount","type":"uint256"}],"name":"mint","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"version","outputs":[{"name":"","type":"string"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_subtractedValue","type":"uint256"}],"name":"decreaseApproval","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[],"name":"finishMinting","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"owner","outputs":[{"name":"","type":"address"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transfer","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_addedValue","type":"uint256"}],"name":"increaseApproval","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"newOwner","type":"address"}],"name":"transferOwnership","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},{"payable":false,"stateMutability":"nonpayable","type":"fallback"},{"anonymous":false,"inputs":[{"indexed":true,"name":"to","type":"address"},{"indexed":false,"name":"amount","type":"uint256"}],"name":"Mint","type":"event"},{"anonymous":false,"inputs":[],"name":"MintFinished","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"previousOwner","type":"address"},{"indexed":true,"name":"newOwner","type":"address"}],"name":"OwnershipTransferred","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"owner","type":"address"},{"indexed":true,"name":"spender","type":"address"},{"indexed":false,"name":"value","type":"uint256"}],"name":"Approval","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"from","type":"address"},{"indexed":true,"name":"to","type":"address"},{"indexed":false,"name":"value","type":"uint256"}],"name":"Transfer","type":"event"}]')

class Command(BaseCommand):

    help = 'creates payouts'

    def add_arguments(self, parser):
        parser.add_argument('what', 
            default='finalize',
            type=str,
            help="what do we do? (finalize, payout, announce)"
            )
        parser.add_argument(
            'minutes_ago',
            type=int,
            help="how many minutes ago to look for a round  (0 to ignore)"
        )
        parser.add_argument(
            'round_number',
            type=int,
            help="what round_number to look at (0 to ignore)"
        )


    def handle(self, *args, **options):

        # setup
        payment_threshold_usd = 1
        network = 'mainnet' if not settings.DEBUG else 'rinkeby'
        from_address = settings.MINICLR_ADDRESS
        from_pk = settings.MINICLR_PRIVATE_KEY
        DAI_ADDRESS = '0x6b175474e89094c44da98b954eedeac495271d0f' if network=='mainnet' else '0x8f2e097e79b1c51be9cba42658862f0192c3e487'

        # find a round that has recently expired
        minutes_ago = options['minutes_ago']
        cursor_time = timezone.now() - timezone.timedelta(minutes=minutes_ago)
        mr = MatchRound.objects.filter(valid_from__lt=cursor_time, valid_to__gt=cursor_time, valid_to__lt=timezone.now()).first()
        if options['round_number']:
            mr = MatchRound.objects.get(number=options['round_number'])
        if not mr:
            print(f'No Match Round Found that ended between {cursor_time} <> {timezone.now()}')
            return
        print(mr)

        # finalize rankings
        if options['what'] == 'finalize':
            rankings = mr.ranking.filter(final=False, paid=False).order_by('-match_total')
            print(rankings.count(), "to finalize")
            for ranking in rankings:
                ranking.final = True
                ranking.save()
            print(rankings.count(), " finalied")

        # payout rankings (round must be finalized first)
        if options['what'] == 'payout':
            rankings = mr.ranking.filter(final=True, paid=False).order_by('-match_total')
            print(rankings.count(), " to pay")
            w3 = get_web3(network)
            for ranking in rankings:

                # figure out amount_owed
                profile = ranking.profile
                owed_rankings = profile.match_rankings.filter(final=True, paid=False)
                amount_owed = sum(owed_rankings.values_list('match_total', flat=True))
                print(f"paying {ranking.profile.handle} who is owed {amount_owed} ({ranking.match_total} from this round)")

                # validate
                error = None
                if amount_owed < payment_threshold_usd:
                    error = ("- less than amount owed; continue")
                address = profile.preferred_payout_address
                if not address:
                    error = ("- address not on file")

                if error:
                    print(error)
                    ranking.payout_tx_status = error
                    ranking.save()
                    continue

                # issue payment
                contract = w3.eth.contract(Web3.toChecksumAddress(DAI_ADDRESS), abi=abi)
                address = Web3.toChecksumAddress(address)
                amount = int(amount_owed * 10**18)
                tx = contract.functions.transfer(address, amount).buildTransaction({
                    'nonce': w3.eth.getTransactionCount(from_address),
                    'gas': 100000,
                    'gasPrice': int(float(recommend_min_gas_price_to_confirm_in_time(1)) * 10**9 * 1.4)
                })

                signed = w3.eth.account.signTransaction(tx, from_pk)
                tx_id = w3.eth.sendRawTransaction(signed.rawTransaction).hex()
                print("paid via", tx_id)

                # wait for tx to clear
                while not has_tx_mined(tx_id, network):
                    time.sleep(1)

                ranking.payout_tx_status, ranking.payout_tx_issued = get_tx_status(tx_id, network, timezone.now())

                ranking.paid = True
                ranking.payout_txid = tx_id
                ranking.save()
                for other_ranking in owed_rankings:
                    other_ranking.paid = True
                    other_ranking.payout_txid = ranking.payout_txid
                    other_ranking.payout_tx_issued = ranking.payout_tx_issued
                    other_ranking.payout_tx_status = ranking.payout_tx_status
                    other_ranking.save()

                # create earning object
                from_profile = Profile.objects.get(handle='gitcoinbot')
                Earning.objects.update_or_create(
                    source_type=ContentType.objects.get(app_label='townsquare', model='matchranking'),
                    source_id=ranking.pk,
                    defaults={
                        "created_on":ranking.created_on,
                        "org_profile":None,
                        "from_profile":from_profile,
                        "to_profile":ranking.profile,
                        "value_usd":amount_owed,
                        "url":'https://gitcoin.co/#clr',
                        "network":network,
                    }
                    )

                Activity.objects.create(
                    created_on=timezone.now(),
                    profile=ranking.profile,
                    activity_type='mini_clr_payout',
                    metadata={
                        "amount":float(amount_owed),
                        "number":int(mr.number),
                        "mr_pk":int(mr.pk),
                        "round_description": f"Mini CLR Round {mr.number}"
                    })


                from marketing.mails import match_distribution
                match_distribution(ranking)

                print("paid ", ranking)
                time.sleep(30)
            
        # announce finalists (round must be finalized first)
        from_profile = Profile.objects.get(handle='gitcoinbot')
        if options['what'] == 'announce':
            copy = f"Mini CLR Round {mr.number} Winners:<BR>"
            rankings = mr.ranking.filter(final=True).order_by('-match_total')[0:10]
            print(rankings.count(), " to announce")
            for ranking in rankings:
                profile_link = f"<a href=/{ranking.profile}>@{ranking.profile}</a>"
                copy += f" - {profile_link} was ranked <strong>#{ranking.number}</strong>. <BR>"
            metadata = {
                'copy': copy,
            }

            Activity.objects.create(
                created_on=timezone.now(),
                profile=from_profile,
                activity_type='consolidated_mini_clr_payout',
                metadata=metadata)
