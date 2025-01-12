import os
import csv
import glob
import hashlib
import json
import ijson
import requests
import gzip
import logging
from urllib.parse import urlparse
from pathlib import Path
from schema import SCHEMA

log = logging.getLogger()
logging.basicConfig(level=logging.INFO)

file_handler = logging.FileHandler('log.txt', 'a')
file_handler.setLevel(logging.DEBUG)

log.addHandler(file_handler)

from collections import namedtuple
Row = namedtuple('Row', ['filename', 'data'])


def data_import(filename):

    with open(filename, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        objs = set()

        for row in reader:
            objs.add(tuple(row[f] for f in fieldnames))

        return objs


def hashdict(data):

    if not data:
        raise ValueError

    sorted_tups = sorted(data.items())
    dict_as_bytes = json.dumps(sorted_tups).encode('utf-8')
    dict_hash = hashlib.sha256(dict_as_bytes).hexdigest()[:16]

    return dict_hash


def in_network_item_to_rows(item, root_hash_key):

    rows = []

    in_network_vals = {
        'negotiation_arrangement':   item['negotiation_arrangement'],
        'name':                      item['name'],
        'billing_code_type':         item['billing_code_type'],
        'billing_code_type_version': item['billing_code_type_version'],
        'billing_code':              item['billing_code'],
        'description':               item['description'],
        'root_hash_key':             root_hash_key,
    }

    in_network_hash_key = hashdict(in_network_vals)
    in_network_vals['in_network_hash_key'] = in_network_hash_key

    rows.append(Row('in_network', in_network_vals))

    for neg_rate in item.get('negotiated_rates', []):
        neg_rates_hash_key = hashdict(neg_rate)

        for provider_group in neg_rate['provider_groups']:
            provider_group_vals = {
                'npi_numbers':               provider_group['npi'],
                'tin_type':                  provider_group['tin']['type'],
                'tin_value':                 provider_group['tin']['value'],
                'negotiated_rates_hash_key': neg_rates_hash_key,
                'in_network_hash_key':       in_network_hash_key,
                'root_hash_key':             root_hash_key,
            }

            rows.append(Row('provider_groups', provider_group_vals))

        for neg_price in neg_rate['negotiated_prices']:

            neg_price_vals = {
                'billing_class':             neg_price['billing_class'],
                'negotiated_type':           neg_price['negotiated_type'],
                'expiration_date':           neg_price['expiration_date'],
                'negotiated_rate':           neg_price['negotiated_rate'],
                'in_network_hash_key':       in_network_hash_key,
                'negotiated_rates_hash_key': neg_rates_hash_key,
                'service_code':              None if not (v := neg_price.get('service_code')) else v,
                'additional_information':    neg_price.get('additional_information'),
                'billing_code_modifier':     None if not (v := neg_price.get('billing_code_modifier')) else v,
                'root_hash_key':             root_hash_key,
            }

            rows.append(Row('negotiated_prices', neg_price_vals))

    for bundle in item.get('bundled_codes', []):

        bundle_vals = {
            'billing_code_type':         bundle['billing_code_type'],
            'billing_code_type_version': bundle['billing_code_type_version'],
            'billing_code':              bundle['billing_code'],
            'description':               bundle['description'],
            'in_network_hash_key':       in_network_hash_key,
            'root_hash_key':             root_hash_key,
        }

        rows.append(Row('bundled_codes', bundle_vals))

    return rows


class InvalidMRF(Exception):
    pass


class MRFOpen:

    def __init__(self, loc):
        self.loc = loc
        self.f = None
        self.r = None
        self.suffix = ''.join(Path(urlparse(self.loc).path).suffixes)

        if self.suffix not in ('.json.gz', '.json'):
            log.critical(f'Not JSON: {self.loc}')
            raise InvalidMRF

    def __enter__(self):
        is_remote = urlparse(self.loc).scheme in ('http', 'https')

        if is_remote:
            self.r = requests.get(self.loc, stream = True)

        if self.suffix == '.json.gz':
            if is_remote:
                self.f = gzip.GzipFile(fileobj = self.r.raw)
            else:
                self.f = gzip.open(self.loc, 'r')
            try:
                self.f.read(1)
            except Exception as e:
                log.critical(e)
                raise InvalidMRF
        else:
            if is_remote:
                self.r.raw.decode_content = True
                self.f = self.r.raw
            else:
                self.f = open(self.loc, 'r')

        log.info(f'Succesfully opened file: {self.loc}')
        return self.f

    def __exit__(self, exc_type, exc_val, exc_tb):

        if self.r:
            self.r.close()

        if self.f:
            self.f.close()


class MRFObjectBuilder:


    def __init__(self, f):
        self.parser = ijson.parse(f, use_float = True)


    def ffwd(self, to_row):
        for current_row in self.parser:
            if current_row == to_row:
                break


    def build_root(self):
        builder = ijson.ObjectBuilder()

        for (prefix, event, value) in self.parser:
            row = (prefix, event, value)
            if (row in [
                    ('', 'map_key', 'provider_references'),
                    ('', 'map_key', 'in_network')]):
                return builder.value, row
            builder.event(event, value)
        else:
            log.critical('Invalid MRF')
            raise InvalidMRF


    def in_network_items(self, npi_set, code_set, provider_references_map):
        builder = ijson.ObjectBuilder()

        for prefix, event, value in self.parser:

            if (prefix, event, value) == ('in_network', 'end_array', None):
                return

            elif (prefix, event, value) == ('in_network.item', 'end_map', None):
                log.info(f"Found: {billing_code_tup}")
                yield builder.value.pop()
                
            elif (
                (prefix, event) == ('in_network.item.negotiated_rates', 'start_array')
            ):
                billing_code_type = builder.value[-1]['billing_code_type']
                billing_code = str(builder.value[-1]['billing_code'])
                billing_code_tup = billing_code_type, billing_code

                if (
                    code_set
                    and billing_code_tup not in code_set
                ):
                    log.debug(f'Skipping: {billing_code_tup}')                    
                    self.ffwd(('in_network.item', 'end_map', None))
                    builder.value.pop()
                    builder.containers.pop()
                    continue

            elif (
                (prefix, event) == ('in_network.item.negotiated_rates', 'end_array')
                and not builder.value[-1]['negotiated_rates']
            ):
                log.info(f"No rates for {billing_code_tup}")
                self.ffwd(('in_network.item', 'end_map', None))
                builder.value.pop()
                builder.containers.pop()
                builder.containers.pop()
                continue

            elif (
                prefix.endswith('negotiated_rates.item') 
                and event == 'start_map'
            ):
                provider_groups = []

            elif (
                provider_references_map 
                and prefix.endswith('provider_references.item')
                and (grps := provider_references_map.get(value))
            ):
                provider_groups.extend(grps)

            elif (
                prefix.endswith('negotiated_rates.item') 
                and event == 'end_map'
            ):

                if builder.value[-1]['negotiated_rates'][-1].get('provider_references'):
                    builder.value[-1]['negotiated_rates'][-1].pop('provider_references')

                builder.value[-1]['negotiated_rates'][-1].setdefault('provider_groups', [])
                builder.value[-1]['negotiated_rates'][-1]['provider_groups'].extend(provider_groups)

                if not builder.value[-1]['negotiated_rates'][-1].get('provider_groups'):
                    builder.value[-1]['negotiated_rates'].pop()

            elif (
                prefix.endswith('provider_groups.item') 
                and event == 'end_map'
                and not builder.value[-1]['negotiated_rates'][-1]['provider_groups'][-1]['npi']
            ):
                builder.value[-1]['negotiated_rates'][-1]['provider_groups'].pop()

            elif prefix.endswith('npi.item'):
                if (
                    npi_set
                    and value not in npi_set
                ):
                    continue

            elif prefix.endswith('service_code.item'):
                try:
                    value = int(value)
                except ValueError:
                    pass

            
            builder.event(event, value)


    def build_provider_references(self, npi_set):

        local_provider_references, remote_provider_references = self._build_local_provider_references(npi_set)
        new_provider_references = self._build_remote_provider_references(remote_provider_references, npi_set)

        if new_provider_references:
            local_provider_references.extend(new_provider_references)        

        return {
            pref['provider_group_id']: pref['provider_groups'] for pref in local_provider_references
        }


    def _build_local_provider_references(self, npi_set):
        remote_provider_references = []
        builder = ijson.ObjectBuilder()

        for prefix, event, value in self.parser:

            if (
                (prefix, event, value) == ('provider_references', 'end_array', None)
            ):
                local_provider_references = builder.value
                return builder.value, remote_provider_references

            elif (
                prefix.endswith('npi.item')
                and npi_set
                and not value in npi_set
            ):
                continue

            elif (
                prefix.endswith('provider_groups.item')
                and event == 'end_map'
            ):
                if not builder.value[-1].get('provider_groups')[-1]['npi']:
                    builder.value[-1]['provider_groups'].pop()

            elif (
                prefix.endswith('provider_references.item') 
                and event == 'end_map'
            ):
                if builder.value and builder.value[-1].get('location'):
                    remote_provider_references.append(builder.value.pop())

                elif not builder.value[-1].get('provider_groups'):
                    builder.value.pop()


            builder.event(event, value)


    def _build_remote_reference(self, loc, npi_set):

        with MRFOpen(loc) as f:
            builder = ijson.ObjectBuilder()

            parser = ijson.parse(f, use_float = True)
            for prefix, event, value in parser:

                if (
                    prefix.endswith('npi.item') 
                    and npi_set
                    and not value in npi_set
                ):
                    continue

                elif (
                    prefix.endswith('provider_groups.item') 
                    and event == 'end_map'
                ):
                    if not builder.value['provider_groups'][-1]['npi']:
                        builder.value['provider_groups'].pop()

                builder.event(event, value)

        return builder.value


    def _build_remote_provider_references(self, remote_provider_references, npi_set):

        new_provider_references = []

        for pref in remote_provider_references:
            loc = pref.get('location')
            try:
                remote_reference = self._build_remote_reference(loc, npi_set)
                remote_reference['provider_group_id'] = pref['provider_group_id']
                new_provider_references.append(remote_reference)
            except Exception as e:
                log.warn('Error retrieving remote provider references')
                log.warn(loc)
                log.warn(e)
                pass


class MRFWriter:

    def __init__(self):
        self.root_data_written = False


    def _prepare(self, item, root_data):
        root_hash_key = hashdict(root_data)
        rows = in_network_item_to_rows(item, root_hash_key)

        if not self.root_data_written:
            root_data['root_hash_key'] = root_hash_key
            rows.append(Row('root', root_data))

        return rows


    def write_in_network_item(self, item, root_data, out_dir):

        if not os.path.exists(out_dir):
            os.mkdir(out_dir)

        rows = self._prepare(item, root_data)

        for row in rows:
            filename, data = row.filename, row.data
            fieldnames = SCHEMA[filename]
            file_loc = f'{out_dir}/{filename}.csv'
            file_exists = os.path.exists(file_loc)

            with open(file_loc, 'a') as f:
                writer = csv.DictWriter(f, fieldnames = fieldnames)

                if not file_exists:
                    writer.writeheader()

                writer.writerow(data)

        self.root_data_written = True



