"""
Verify the correctness and completeness of generated AIF
"""

__author__  = "Shahzad Rajput <shahzad.rajput@nist.gov>"
__status__  = "production"
__version__ = "2021.0.1"
__date__    = "7 December 2021"

from aida.object import Object
from aida.logger import Logger
from generate_aif import TA1Annotations, TA3Annotations, LDCTimeRange, LDCTime
from aida.document_mappings import DocumentMappings
from aida.encodings import Encodings
from aida.file_handler import FileHandler
import argparse
import os
import re
import sys
import textwrap
import traceback

ALLOK_EXIT_CODE = 0
ERROR_EXIT_CODE = 255

def dequotify(s):
    return None if s is None else s.replace('"', '')

class Claims(Object):
    def __init__(self, logger, datatype, annotation_or_projection):
        self.logger = logger
        self.claims = {}
        if datatype == 'annotation':
            self.load_annotation(annotation_or_projection)
        elif datatype == 'projection':
            self.load_projection(annotation_or_projection)
        else:
            self.record_event('UNKNOWN_DATATYPE', datatype)

    def get_claim(self, claim_id):
        return self.get('claims').get(claim_id)

    def load_annotation(self, annotation):
        for entry in annotation.get('worksheets').get('claims'):
            claim = Claim(self.get('logger'), 'annotation', entry)
            claim.load_components()
            claim.load_date()
            self.get('claims')[claim.get('claim_id')] = claim

    def load_projection(self, projection):
        for entries in projection.get('projection').get('TA3_queryA.rq.tsv').values():
            for entry in entries:
                claim = Claim(self.get('logger'), 'projection', entry)
                self.get('claims')[claim.get('claim_id')] = claim
        for claim_components in projection.get('projection').get('TA3_queryB.rq.tsv').values():
            for claim_component in claim_components:
                claim_id = claim_component.get('?claim_id')
                component_type = claim_component.get('?component_type')
                name = dequotify(claim_component.get('?name'))
                qnode_id = claim_component.get('?qnode_id')
                qnode_type = claim_component.get('?qnode_type')
                provenance = dequotify(claim_component.get('?provenance'))
                ke = claim_component.get('?ke')
                self.get('claim', claim_id).add_component(component_type,
                                                          name,
                                                          qnode_id,
                                                          qnode_type,
                                                          provenance,
                                                          ke)
        claims = projection.get('projection').get('TA3_queryC.rq.tsv')
        for kb_id in claims:
            claim_id = kb_id.replace('.ttl', '')
            claim_dates = claims.get(kb_id)
            for claim_date in claim_dates:
                self.get('claim', claim_id).add_date(claim_date)

class Claim(Object):
    def __init__(self, logger, datatype, entry):
        self.logger = logger
        self.datatype = datatype
        self.entry = entry
        self.date = None
        self.components = {}

    def get_claim_id(self):
        claim_id = self.get('entry').get('claim_id') or self.get('entry').get('?claim_id')
        if claim_id is not None:
            return claim_id
        self.record_event('CLAIM_ID_MISSING')

    def add_component(self, component_type, name, qnode_id, qnode_type, provenance, ke):
        logger = self.get('logger')
        key = '{}:{}'.format(component_type, name)
        component = self.get('components').setdefault(key, ClaimComponent(logger))
        component.update(component_type=component_type,
                         name=name,
                         qnode_id=qnode_id,
                         qnode_type=qnode_type,
                         provenance=provenance,
                         ke=ke)

    def add_date(self, date):
        if self.get('date') is None:
            self.date = ClaimDateTime(self.get('logger'), 'projection', date)
        else:
            self.record_event('MULTIPLE_CLAIM_DATES', self.get('claim_id'))

    def load_components(self):
        def get_claim_component(entry, component_type, postfix):
            return {
                'componentName': dequotify(entry.get('{}{}'.format(component_type, postfix))),
                'componentIdentity': entry.get('qnode_{}_identity{}'.format(component_type, postfix)),
                'componentTypes': entry.get('qnode_{}_type{}'.format(component_type, postfix)),
                'componentProvenance': dequotify(entry.get('{}_provenance{}'.format(component_type, postfix))),
                'componentKE': entry.get('{}_ke{}'.format(component_type, postfix))
                }
        components = {
            'claimer':               {'key':'claimer',               'component':{}, 'postfixes': ['']},
            'claimer_affiliation':   {'key':'claimerAffiliation',    'component':{}, 'postfixes': ['', '_1', '_2']},
            'claim_location':        {'key':'claimLocation',         'component':{}, 'postfixes': ['']},
            'claim_medium':          {'key':'claimMedium',           'component':{}, 'postfixes': ['']},
            'x_variable':            {'key':'xVariable',             'component':{}, 'postfixes': ['']},
            }
        for component_type in components:
            key = components.get(component_type).get('key')
            postfixes = components.get(component_type).get('postfixes')
            for postfix in postfixes:
                component = get_claim_component(self.get('entry'), component_type, postfix)
                if component.get('componentName') == 'EMPTY_NA':
                    continue
                self.add_component(component_type=key,
                                   name=component.get('componentName'),
                                   qnode_id=component.get('componentIdentity'),
                                   qnode_type=component.get('componentTypes'),
                                   provenance=component.get('componentProvenance'),
                                   ke=component.get('componentKE'))

    def load_date(self):
        logger = self.get('logger')
        self.date = ClaimDateTime(logger, 'annotation', self.get('entry'))

    def __eq__(self, other):
        def getvalue(fields_to_compare, mapping, key, claim):
            def descape(s):
                return s.replace('\\', '').replace('"','')
            value = None
            for field_name in fields_to_compare.get(key):
                value = claim.get('entry').get(field_name)
                if value is not None:
                    return mapping.get(value) if value in mapping else descape(value)
        mapping = {
            'EpistemicTrueCertain': 'true-certain',
            'EpistemicFalseCertain': 'false-certain',
            'EpistemicTrueUncertain': 'true-uncertain',
            'EpistemicFalseUncertain': 'false-uncertain',
            'EpistemicUnknown': 'unknown',
            'SentimentPositive': 'positive',
            'SentimentNegative': 'negative',
            'SentimentMixed': 'mixed',
            'SentimentNeutralUnknown': 'neutral-unknown'
            }
        fields_to_compare = {
            'claim_template': ['claim_template', '?claim_template'],
            'description': ['description', '?description'],
            'epistemic_status': ['epistemic_status', '?epistemic_status'],
            'root_uid': ['root_uid', '?root_uid'],
            'sentiment_status': ['sentiment_status', '?sentiment_status'],
            'subtopic': ['subtopic', '?subtopic'],
            'topic': ['topic', '?topic']
            }
        for key in fields_to_compare:
            myvalue = getvalue(fields_to_compare, mapping, key, self)
            othervalue = getvalue(fields_to_compare, mapping, key, other)
            if myvalue != othervalue:
                self.record_event('CLAIM_FIELD_MISMATCHED', self.get('claim_id'), key, myvalue, othervalue)
                return False
        mycomponents = self.get('components')
        othercomponents = other.get('components')
        keys = set(mycomponents.keys()).union(set(othercomponents.keys()))
        for key in keys:
            mycomponent = mycomponents.get(key)
            othercomponent = othercomponents.get(key)
            for component, annotation_or_projection in [(mycomponent, 'annotation'), (othercomponent, 'SPARQL output')]:
                if component is None:
                    self.record_event('CLAIM_FIELD_MISSING', self.get('claim_id'), key, annotation_or_projection)
                    return False
            subkeys = set(mycomponent.get('values').keys()).union(othercomponent.get('values').keys())
            for subkey in subkeys:
                myvalues = mycomponent.get('values').get(subkey)
                othervalues = othercomponent.get('values').get(subkey)
                if subkey in ['provenance', 'ke'] and othervalues == set(['']):
                    othervalues = None
                if (myvalues is None or myvalues == set(['EMPTY_NA'])) and (othervalues is None or othervalues == set(['EMPTY_NA'])):
                    continue
                if myvalues is None or othervalues is None or myvalues != othervalues:
                    field_name = '{}:{}'.format(key, subkey)
                    self.record_event('CLAIM_FIELD_MISMATCHED', self.get('claim_id'), field_name, myvalues, othervalues)
                    return False
        if self.get('date') != other.get('date'):
            self.record_event('CLAIM_FIELD_MISMATCHED', self.get('claim_id'), 'date', self.get('date').__str__(), other.get('date').__str__())
            return False
        return True

class ClaimComponent(Object):
    def __init__(self, logger):
        self.logger = logger
        self.values = {}

    def update(self, *args, **kwargs):
        for key, value in kwargs.items():
            self.update_field(key, value)

    def update_field(self, key, value):
        if value is not None:
            self.get('values').setdefault(key, set()).add(value)

class ClaimDateTime(Object):
    def __init__(self, logger, annotation_or_projection, entry):
        self.logger = logger
        self.annotation_or_projection = annotation_or_projection
        self.entry = entry
        self.datetime = None
        if annotation_or_projection == 'annotation':
            self.load_date_from_annotation()
        elif annotation_or_projection == 'projection':
            self.load_date_from_projection()
        else:
            self.record_event('UNKNOWN_TYPE')

    def load_date_from_projection(self):
        entry = self.get('entry')
        date_types = {
            'start_after':  '?sa_',
            'end_after':    '?ea_',
            'start_before': '?sb_',
            'end_before':   '?eb_',
            }
        range_fields = {}
        for date_type in date_types:
            day = '{}day'.format(date_types.get(date_type))
            month = '{}month'.format(date_types.get(date_type))
            year = '{}year'.format(date_types.get(date_type))
            d = '{y}-{m}-{d}'.format(d=entry.get(day),
                                     m=entry.get(month),
                                     y=entry.get(year))
            range_fields[date_type] = d
        datetime_str = '(AFTER-{start_after},BEFORE-{start_before})-(AFTER-{end_after},BEFORE-{end_before})'
        self.datetime = dequotify(datetime_str.format(**range_fields))

    def load_date_from_annotation(self):
        logger = self.get('logger')
        elements = self.get('entry').get('claim_datetime').split(' ')
        attribute = elements[0]
        if attribute == 'unknown' or attribute == 'EMPTY_NA':
            attribute = 'unk'
        datestring = elements[1] if len(elements) == 2 else 'EMPTY_NA'
        time =  Object(logger)
        time.set('start_date', datestring)
        time.set('start_date_type', 'start{}'.format(attribute))
        time.set('end_date', datestring)
        time.set('end_date_type', 'end{}'.format(attribute))
        time.set('where', self.get('where'))
        self.datetime = LDCTimeRange(logger, time).__str__()

    def __eq__(self, other):
        return self.get('datetime') == other.get('datetime')

    def __str__(self):
        return self.get('datetime').__str__()

class Mention(Object):
    def __init__(self, logger, document_mappings, entry):
        super().__init__(logger)
        self.entry = entry
        self.document_mappings = document_mappings
        self.augment()
        self.fields = {
            'docid': ['?root_uid', 'root_uid'],
            'doceid': ['?child_uid', 'child_uid'],
            'start_x': ['start_x', '?textoffset_startchar', 'textoffset_startchar'],
            'start_y': ['start_y'],
            'end_x': ['end_x', '?textoffset_endchar', 'textoffset_endchar'],
            'end_y': ['end_y']
            }
        self.span = {'start_y': '0', 'end_y': '0'}
        self.where = entry.get('where')
        self.load()
        if self.is_empty():
            self.record_event('EMPTY_MENTION', self.get('mention_id'), self.get('where'))

    def get_mention_id(self):
        field_names = ['argmention_id', 'eventmention_id', 'relationmention_id']
        for fn in field_names:
            value = self.get('entry').get(fn)
            if value:
                return value

    def augment(self):
        mediamention_coordinates = None
        fields = ['mediamention_coordinates', '?mediamention_coordinates']
        for field_name in fields:
            value = self.get('entry').get(field_name)
            if value and value != 'EMPTY_NA':
                mediamention_coordinates = value
                ulx, uly, lrx, lry = mediamention_coordinates.split(',')
                self.get('entry').set('start_x', ulx)
                self.get('entry').set('start_y', uly)
                self.get('entry').set('end_x', lrx)
                self.get('entry').set('end_y', lry)
                return

    def load(self):
        def trim(s):
            return s.replace('"', '')
        for key in self.get('fields'):
            for field_name in self.get('fields').get(key):
                value = self.get('entry').get(field_name)
                if value and value != 'EMPTY_NA':
                    self.get('span')[key] = trim(value)
        if self.is_empty():
            self.get('entry').set('child_uid', self.get('document_mappings').get('text_document', self.get('entry').get('root_uid')).get('ID'))
            self.get('entry').set('textoffset_startchar', '0')
            self.get('entry').set('textoffset_endchar', '0')
            self.load()

    def is_empty(self):
        for field_name in self.get('fields'):
            value = self.get('span').get(field_name)
            if value is None or value == 'EMPTY_NA':
                return True

    def __str__(self):
        if self.is_empty():
            return
        predicate_justification = self.get('entry').get('?predicate_justification')
        if predicate_justification:
            return predicate_justification
        return '{docid}:{doceid}:({start_x},{start_y})-({end_x},{end_y})'.format(**self.get('span'))

class Attributes(Object):
    def __init__(self, logger, entry):
        super().__init__(logger)
        self.entry = entry

    def __eq__(self, other):
        if self.__str__() == other.__str__():
            return True
        return False

    def __str__(self):
        entry = self.get('entry')
        field_names = ['?attributes', 'attribute']
        for field_name in field_names:
            value = entry.get(field_name)
            if value is not None:
                break
        if value is None:
            return ''
        values = [v.strip().lower() for v in value.split(',')]
        attributes = ','.join(sorted(values))
        return attributes

class Types(Object):
    def __init__(self, logger, entry):
        super().__init__(logger)
        self.entry = entry

    def __eq__(self, other):
        if self.__str__() == other.__str__():
            return True
        return False

    def __str__(self):
        entry = self.get('entry')
        field_names = ['?type', 'qnode_type_id']
        for field_name in field_names:
            value = entry.get(field_name)
            if value is not None:
                break
        if value is None:
            return ''
        values = [v.strip() for v in value.split(',')]
        attributes = ','.join(sorted(values))
        return attributes

class LDCTimeRangeWrapper(Object):
    def __init__(self, logger, projection_or_annotation, entry):
        self.logger = logger
        self.projection_or_annotation = projection_or_annotation
        self.entry = entry

    def __str__(self):
        def trim(s):
            return s.replace('"', '')
        logger = self.get('logger')
        projection_or_annotation = self.get('projection_or_annotation')
        entry = self.get('entry')
        if projection_or_annotation == 'annotation':
            return LDCTimeRange(logger, entry).__str__()
        elif projection_or_annotation == 'projection':
            return "(AFTER-{},BEFORE-{})-(AFTER-{},BEFORE-{})".format(
                trim(entry.get('?start_after')),
                trim(entry.get('?start_before')),
                trim(entry.get('?end_after')),
                trim(entry.get('?end_before')))
        else:
            return

    def __eq__(self, other):
        return self.__str__() == other.__str__()

class AIFProjections(Object):
    def __init__(self, logger, projection, document_mappings):
        super().__init__(logger)
        self.path = projection
        self.document_mappings = document_mappings
        self.projection = {}
        self.load_projection()

    def get_prototype(self, projection_or_annotation, mention_id, annotation=None):
        if projection_or_annotation == 'projection':
            projection = self.get('projection').get('cluster_prototype_member_attribute.rq.tsv')
            for kb in projection:
                for entry in projection.get(kb):
                    if entry.get('?member') == mention_id:
                        return entry.get('?prototype')
        else:
            kb_links = annotation.get('worksheets').get('kb_links')
            for entry in kb_links:
                if entry.get('mention_id') == mention_id:
                    return 'cluster-{}-prototype'.format(entry.get('qnode_kb_id_identity'))
        return

    def verify(self, annotation):
        self.compare_claims(annotation)
        self.compare_event_relation_dates(annotation)
        self.compare_mention_argument_assertions(annotation)
        self.compare_prototype_argument_assertions(annotation)
        self.compare_mention_argument_assetion_attributes(annotation)
        self.check_num_arguments(annotation)
        self.compare_prototype_argument_assertion_attributes(annotation)
        self.compare_cluster_generic_status(annotation)
        self.verify_cluster_and_prototype()
        self.compare_cluster_members(annotation)
        self.compare_mention_spans(annotation)
        self.compare_mention_attributes(annotation)
        self.compare_mention_types(annotation)
        if self.get('task') == 'task1':
            self.compare_subject_justification(annotation)

    def compare_claims(self, annotation):
        # Nothing to do for task1 and task2
        # Method overridden for task3
        pass

    def compare_event_relation_dates(self, annotation):
        logger = self.get('logger')
        dates = {'projection': {}, 'annotation': {}}
        store = self.get('projection').get('event_relation_dates.rq.tsv')
        projection_dates = dates.get('projection')
        for kb in store:
            for entry in store.get(kb):
                mention_id = entry.get('?mention_id')
                date = LDCTimeRangeWrapper(logger, 'projection', entry)
                if mention_id not in projection_dates:
                    projection_dates[mention_id] = date
                elif projection_dates[mention_id] != date:
                    self.record_event('MULTIPLE_MENTION_DATE', projection_dates[mention_id], date)
        annotation_dates = dates.get('annotation')
        for store_name in ['event_KEs', 'relation_KEs']:
            for entry in annotation.get('worksheets').get(store_name):
                mention = Mention(logger, self.get('document_mappings'), entry)
                missing = False
                for field_name in ['{}_date'.format(start_or_end) for start_or_end in ['start', 'end']]:
                    if entry.get(field_name) == 'EMPTY_MIS':
                        missing = True
                if missing:
                    continue
                annotation_dates[mention.get('mention_id')] = LDCTimeRangeWrapper(logger, 'annotation', entry)
        count = 0
        ts = [('projection', 'annotation'), ('annotation', 'projection')]
        for (t1, t2) in ts:
            for mention_id, t1_dates in dates.get(t1).items():
                if mention_id in dates.get(t2):
                    t2_dates = dates.get(t2).get(mention_id)
                    if t1_dates != t2_dates:
                        count += 1
                        self.record_event('UNEXPECTED_DATE', mention_id, t1_dates, t2_dates)
        self.record_event('UNEXPECTED_DATE_COUNT', count if count else 'No')

    def check_num_arguments(self, annotation):
        events_or_relations = {
            'event': {
                'mentions': {},
                'num_arguments': 2,
                },
            'relation': {
                'mentions': {},
                'num_arguments': 2,
                }
            }
        for events_or_relation in events_or_relations:
            KEs = '{}_KEs'.format(events_or_relation)
            for entry in annotation.get('worksheets').get(KEs):
                mention_id = entry.get('{}mention_id'.format(events_or_relation))
                events_or_relations.get(events_or_relation).get('mentions')[mention_id] = set()
            slots = '{}_slots'.format(events_or_relation)
            for entry in annotation.get('worksheets').get(slots):
                mention_id = entry.get('{}mention_id'.format(events_or_relation))
                slot_type = entry.get('general_slot_type')
                if slot_type == 'EMPTY_TBD':
                    continue
                events_or_relations.get(events_or_relation).get('mentions').get(mention_id).add(slot_type)
        for events_or_relation in events_or_relations:
            num_arguments = events_or_relations.get(events_or_relation).get('num_arguments')
            events_or_relations_mentions = events_or_relations.get(events_or_relation).get('mentions')
            for mention_id in events_or_relations_mentions:
                mention_slot_types = events_or_relations_mentions.get(mention_id)
                if len(mention_slot_types) < num_arguments:
                    error_code = 'UNEXPECTED_NUM_ARGUMENTS_WARNING' if events_or_relation == 'event' else 'UNEXPECTED_NUM_ARGUMENTS_ERROR'
                    self.record_event(error_code, mention_id, len(mention_slot_types), num_arguments)

    def compare_prototype_argument_assertion_attributes(self, annotation):
        argument_assertions = {'projection': set(), 'annotation': set()}
        store = self.get('projection').get('prototype_argument_assertions_attributes.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                aa_subject = entry.get('?subject_mention_id')
                predicate = entry.get('?predicate')
                aa_object = entry.get('?object_mention_id')
                attributes = entry.get('?attributes')
                if attributes == 'none':
                    continue
                argument_assertion = '{subject}::{predicate}::{object}::{attributes}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object,
                    attributes = attributes.lower()
                    )
                argument_assertions.get('projection').add(argument_assertion)

        for store_name in ['event_slots', 'relation_slots']:
            for entry in annotation.get('worksheets').get(store_name):
                aa_subject = self.get('prototype', 'annotation', entry.get('eventmention_id') or entry.get('relationmention_id'), annotation=annotation)
                predicate = entry.get('general_slot_type')
                aa_object = self.get('prototype', 'annotation', entry.get('argmention_id'), annotation=annotation)
                attributes = entry.get('attribute')
                if attributes is None or attributes == 'none':
                    continue
                argument_assertion = '{subject}::{predicate}::{object}::{attributes}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object,
                    attributes = attributes.lower()
                    )
                argument_assertions.get('annotation').add(argument_assertion)

        union = argument_assertions.get('projection').union(argument_assertions.get('annotation'))
        intersection = argument_assertions.get('projection').intersection(argument_assertions.get('annotation'))
        missings = union - intersection
        count = 0
        for missing in missings:
            count += 1
            stores = ['projection', 'annotation']
            for store in stores:
                if missing not in argument_assertions.get(store):
                    self.record_event('MISSING_ARGUMENT_ASSERTION_ATTRIBUTE', missing, store)
        self.record_event('MISSING_PROTOTYPE_ARGUMENT_ASSERTION_ATTRIBUTE_COUNT', count if count else 'No')

    def compare_mention_argument_assetion_attributes(self, annotation):
        argument_assertions = {'projection': set(), 'annotation': set()}
        store = self.get('projection').get('mention_argument_assertions_attributes.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                aa_subject = entry.get('?subject_mention_id')
                predicate = entry.get('?predicate')
                aa_object = entry.get('?object_mention_id')
                attributes = entry.get('?attributes')
                if attributes == 'none':
                    continue
                argument_assertion = '{subject}::{predicate}::{object}::{attributes}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object,
                    attributes = attributes.lower()
                    )
                argument_assertions.get('projection').add(argument_assertion)

        for store_name in ['event_slots', 'relation_slots']:
            for entry in annotation.get('worksheets').get(store_name):
                aa_subject = entry.get('eventmention_id') or entry.get('relationmention_id')
                predicate = entry.get('general_slot_type')
                aa_object = entry.get('argmention_id')
                attributes = entry.get('attribute')
                if attributes is None or attributes == 'none':
                    continue
                argument_assertion = '{subject}::{predicate}::{object}::{attributes}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object,
                    attributes = attributes.lower()
                    )
                argument_assertions.get('annotation').add(argument_assertion)

        union = argument_assertions.get('projection').union(argument_assertions.get('annotation'))
        intersection = argument_assertions.get('projection').intersection(argument_assertions.get('annotation'))
        missings = union - intersection
        count = 0
        for missing in missings:
            count += 1
            stores = ['projection', 'annotation']
            for store in stores:
                if missing not in argument_assertions.get(store):
                    self.record_event('MISSING_ARGUMENT_ASSERTION_ATTRIBUTE', missing, store)
        self.record_event('MISSING_ARGUMENT_ASSERTION_ATTRIBUTE_COUNT', count if count else 'No')

    def compare_subject_justification(self, annotation):
        logger = self.get('logger')
        justifications = {'projection': set(), 'annotation': set()}
        store = self.get('projection').get('mention_argument_assertions_justifications.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                subject = entry.get('?subject_mention_id')
                justification = entry.get('?predicate_justification')
                subject_and_justification = '{}::{}'.format(subject, justification.__str__())
                justifications.get('projection').add(subject_and_justification)
        mentions = set()
        for store_name in ['event_slots', 'relation_slots']:
            for entry in annotation.get('worksheets').get(store_name):
                mention_id = entry.get('eventmention_id') or entry.get('relationmention_id')
                mentions.add(mention_id)
        for store_name in ['event_KEs', 'relation_KEs']:
            for entry in annotation.get('worksheets').get(store_name):
                mention = Mention(logger, self.get('document_mappings'), entry)
                subject = mention.get('mention_id')
                if subject in mentions:
                    subject_and_justification = '{}::{}'.format(subject, mention.__str__())
                    justifications.get('annotation').add(subject_and_justification)
        union = justifications.get('projection').union(justifications.get('annotation'))
        intersection = justifications.get('projection').intersection(justifications.get('annotation'))
        missings = union - intersection
        count = 0
        for missing in missings:
            count += 1
            stores = ['projection', 'annotation']
            for store in stores:
                if missing not in justifications.get(store):
                    self.record_event('MISSING_SUBJECT_JUSTIFICATION', missing, store)
        self.record_event('MISSING_SUBJECT_JUSTIFICATION_COUNT', count if count else 'No')

    def compare_prototype_argument_assertions(self, annotation):
        clusters = {'projection': set(), 'annotation': set()}
        store = self.get('projection').get('mention_argument_assertions_justifications.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                aa_subject = self.get('prototype', 'projection', entry.get('?subject_mention_id'))
                predicate = entry.get('?predicate')
                aa_object = self.get('prototype', 'projection', entry.get('?object_mention_id'))
                argument_assertion = '{subject}::{predicate}::{object}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object
                    )
                clusters.get('projection').add(argument_assertion)

        for store_name in ['event_slots', 'relation_slots']:
            for entry in annotation.get('worksheets').get(store_name):
                aa_subject = self.get('prototype', 'annotation', entry.get('eventmention_id') or entry.get('relationmention_id'), annotation=annotation)
                predicate = entry.get('general_slot_type')
                aa_object = self.get('prototype', 'annotation', entry.get('argmention_id'), annotation=annotation)
                argument_assertion = '{subject}::{predicate}::{object}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object,
                    )
                clusters.get('annotation').add(argument_assertion)

        union = clusters.get('projection').union(clusters.get('annotation'))
        intersection = clusters.get('projection').intersection(clusters.get('annotation'))
        missings = union - intersection
        count = 0
        for missing in missings:
            count += 1
            stores = ['projection', 'annotation']
            for store in stores:
                if missing not in clusters.get(store):
                    error_code = 'MISSING_ARGUMENT_ASSERTION_WARNING' if '::EMPTY_TBD::' in missing else 'MISSING_ARGUMENT_ASSERTION_ERROR'
                    self.record_event(error_code, missing, store)
        self.record_event('MISSING_PROTOTYPE_ARGUMENT_ASSERTION_COUNT', count if count else 'No')

    def compare_mention_argument_assertions(self, annotation):
        clusters = {'projection': set(), 'annotation': set()}
        store = self.get('projection').get('mention_argument_assertions_justifications.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                aa_subject = entry.get('?subject_mention_id')
                predicate = entry.get('?predicate')
                aa_object = entry.get('?object_mention_id')
                argument_assertion = '{subject}::{predicate}::{object}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object
                    )
                clusters.get('projection').add(argument_assertion)

        for store_name in ['event_slots', 'relation_slots']:
            for entry in annotation.get('worksheets').get(store_name):
                aa_subject = entry.get('eventmention_id') or entry.get('relationmention_id')
                predicate = entry.get('general_slot_type')
                aa_object = entry.get('argmention_id')
                argument_assertion = '{subject}::{predicate}::{object}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object,
                    )
                clusters.get('annotation').add(argument_assertion)

        union = clusters.get('projection').union(clusters.get('annotation'))
        intersection = clusters.get('projection').intersection(clusters.get('annotation'))
        missings = union - intersection
        count = 0
        for missing in missings:
            count += 1
            stores = ['projection', 'annotation']
            for store in stores:
                if missing not in clusters.get(store):
                    error_code = 'MISSING_ARGUMENT_ASSERTION_WARNING' if '::EMPTY_TBD::' in missing else 'MISSING_ARGUMENT_ASSERTION_ERROR'
                    self.record_event(error_code, missing, store)
        self.record_event('MISSING_ARGUMENT_ASSERTION_COUNT', count if count else 'No')

    def compare_cluster_generic_status(self, annotation):
        clusters = {}
        store = self.get('projection').get('cluster_prototype_member_attribute.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                cluster_id = entry.get('?cluster')
                attributes = entry.get('?attributes')
                generic_status = 'Generic' if 'Generic' in attributes else 'NotGeneric'
                if cluster_id not in clusters:
                    clusters[cluster_id] = {'projection': set()}
                clusters.get(cluster_id).get('projection').add(generic_status)

        for entry in annotation.get('worksheets').get('kb_links'):
            cluster_id = 'cluster-{}'.format(entry.get('qnode_kb_id_identity'))
            generic_status = entry.get('generic_status')
            generic_status = 'Generic' if generic_status == 'generic' else 'NotGeneric'
            if cluster_id not in clusters:
                clusters[cluster_id] = {'annotation': set()}
            if 'annotation' not in clusters.get(cluster_id):
                clusters.get(cluster_id)['annotation'] = set()
            clusters.get(cluster_id).get('annotation').add(generic_status)

        for cluster_id in clusters:
            projection_generic_status = list().append(clusters.get(cluster_id).get('projection'))
            annotation_generic_status = list().append(clusters.get(cluster_id).get('annotation'))
            if projection_generic_status != annotation_generic_status:
                self.record_event('UNEXPECTED_CLUSTER_GENERIC_STATUS', cluster_id, ','.join(projection_generic_status), ','.join(annotation_generic_status))

    def compare_cluster_members(self, annotation):
        clusters = {}
        store = self.get('projection').get('cluster_prototype_member_attribute.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                cluster_id = entry.get('?cluster')
                member_id = entry.get('?member')
                if cluster_id not in clusters:
                    clusters[cluster_id] = {'projection': set()}
                clusters.get(cluster_id).get('projection').add(member_id)

        for entry in annotation.get('worksheets').get('kb_links'):
            cluster_id = 'cluster-{}'.format(entry.get('qnode_kb_id_identity'))
            member_id = entry.get('mention_id')
            if cluster_id not in clusters:
                clusters[cluster_id] = {'annotation': set()}
            if 'annotation' not in clusters.get(cluster_id):
                clusters.get(cluster_id)['annotation'] = set()
            clusters.get(cluster_id).get('annotation').add(member_id)

        for cluster_id in clusters:
            projection_members = list().append(clusters.get(cluster_id).get('projection'))
            annotation_members = list().append(clusters.get(cluster_id).get('annotation'))
            if projection_members != annotation_members:
                self.record_event('UNEXPECTED_CLUSTER_MEMBERS', cluster_id, ','.join(projection_members), ','.join(annotation_members))

    def verify_cluster_and_prototype(self):
        store = self.get('projection').get('cluster_prototype_member_attribute.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                cluster_id = entry.get('?cluster')
                prototype_id = entry.get('?prototype')
                expected_prototype_id = '{}-prototype'.format(cluster_id)
                if prototype_id != expected_prototype_id:
                    self.record_event('UNEXPECTED_PROTOTYPE_ID', prototype_id, expected_prototype_id)

    def compare_mention_types(self, annotation):
        logger = self.get('logger')
        field_names = {
            'argument_KEs': 'argmention_id',
            'event_KEs': 'eventmention_id',
            'relation_KEs': 'relationmention_id'
            }
        mentions = {'projection': {}, 'annotation': {}}

        for store_name in ['text_mentions.rq.tsv', 'image_mentions.rq.tsv']:
            store = self.get('projection').get(store_name)
            for kb in store:
                for entry in store.get(kb):
                    mention_id = entry.get('?mention_id')
                    types = Types(logger, entry)
                    mentions['projection'][mention_id] = types

        for store_name in ['argument_KEs', 'event_KEs', 'relation_KEs']:
            for entry in annotation.get('worksheets').get(store_name):
                mention_id = entry.get(field_names.get(store_name))
                types = Types(logger, entry)
                mentions['annotation'][mention_id] = types

        num_problems = 0
        ts = [('projection', 'annotation'), ('annotation', 'projection')]
        for (t1, t2) in ts:
            for mention_id, t1_types in mentions.get(t1).items():
                if mention_id in mentions.get(t2):
                    t2_types = mentions.get(t2).get(mention_id)
                    if t1_types != t2_types:
                        num_problems += 1
                        self.record_event('UNEXPECTED_TYPES', mention_id, t1, t1_types, t2, t2_types)
        self.record_event('UNEXPECTED_MENTION_TYPES_COUNT', num_problems if num_problems else 'No')

    def compare_mention_attributes(self, annotation):
        logger = self.get('logger')
        field_names = {
            'argument_KEs': 'argmention_id',
            'event_KEs': 'eventmention_id',
            'relation_KEs': 'relationmention_id'
            }
        mentions = {'projection': {}, 'annotation': {}}

        for store_name in ['mention_attributes.rq.tsv']:
            store = self.get('projection').get(store_name)
            for kb in store:
                for entry in store.get(kb):
                    mention_id = entry.get('?member')
                    attributes = Attributes(logger, entry)
                    mentions['projection'][mention_id] = attributes

        for store_name in ['event_KEs', 'relation_KEs']:
            for entry in annotation.get('worksheets').get(store_name):
                mention_id = entry.get(field_names.get(store_name))
                attributes = Attributes(logger, entry)
                mentions['annotation'][mention_id] = attributes

        num_problems = 0
        for mention_id, projection_attributes in mentions.get('projection').items():
            if mention_id in mentions.get('annotation'):
                annotation_attributes = mentions.get('annotation').get(mention_id)
                if projection_attributes != annotation_attributes:
                    num_problems += 1
                    self.record_event('UNEXPECTED_ATTRIBUTES', mention_id, projection_attributes, annotation_attributes)

        self.record_event('UNEXPECTED_MENTION_ATTRIBUTES_COUNT', num_problems if num_problems else 'No')

    def compare_mention_spans(self, annotation):
        logger = self.get('logger')
        mentions = {'projection': {}, 'annotation': {}}

        for store_name in ['text_mentions.rq.tsv', 'image_mentions.rq.tsv']:
            store = self.get('projection').get(store_name)
            for kb in store:
                for entry in store.get(kb):
                    mention = Mention(logger, self.get('document_mappings'), entry)
                    mentions['projection'][mention.__str__()] = mention

        for store_name in ['argument_KEs', 'event_KEs', 'relation_KEs']:
            for entry in annotation.get('worksheets').get(store_name):
                mention = Mention(logger, self.get('document_mappings'), entry)
                mentions['annotation'][mention.__str__()] = mention

        c1 = self.report_missing_mention_spans(mentions, present_in='projection', missing_from='annotation')
        c2 = self.report_missing_mention_spans(mentions, present_in='annotation', missing_from='projection')
        self.record_event('MISSING_MENTION_COUNT', c1+c2 if c1+c2 else 'No')

    def load_projection(self):
        logger = self.get('logger')
        path = self.get('path')
        projection = self.get('projection')
        for kb in os.listdir(path):
            for sparql_output_filename in os.listdir(os.path.join(path, kb)):
                filename = os.path.join(path, kb, sparql_output_filename)
                if sparql_output_filename not in projection:
                    projection[sparql_output_filename] = {}
                if kb not in projection.get(sparql_output_filename):
                    projection[sparql_output_filename][kb] = []
                for entry in FileHandler(logger, filename):
                    projection.get(sparql_output_filename).get(kb).append(entry)

    def report_missing_mention_spans(self, mentions, present_in, missing_from):
        missing_mention_spans = set(mentions.get(present_in).keys()) - set(mentions.get(missing_from).keys())
        count = 0
        for mention_span in missing_mention_spans:
            count += 1
            mention = mentions.get(present_in).get(mention_span)
            self.record_event('MISSING_MENTION', mention_span, present_in, missing_from, mention.get('where'))
        return count

class TA1AIFProjections(AIFProjections):
    def __init__(self, logger, projections, document_mappings):
        super().__init__(logger, projections, document_mappings)
        self.task = 'task1'

class TA2AIFProjections(AIFProjections):
    def __init__(self, logger, projections, document_mappings):
        super().__init__(logger, projections, document_mappings)
        self.task = 'task2'

class TA3AIFProjections(AIFProjections):
    def __init__(self, logger, projections, document_mappings):
        super().__init__(logger, projections, document_mappings)
        self.task = 'task3'

    def compare_claims(self, annotation):
        annotation_claims = Claims(self.get('logger'), 'annotation', annotation)
        projection_claims = Claims(self.get('logger'), 'projection', self)

        mismatched = set()
        for claim_id, annotation_claim in annotation_claims.get('claims').items():
            projection_claim = projection_claims.get('claims').get(claim_id)
            if annotation_claim != projection_claim:
                mismatched.add(claim_id)
        for claim_id, projection_claim in projection_claims.get('claims').items():
            annotation_claim = annotation_claims.get('claims').get(claim_id)
            if annotation_claim != projection_claim:
                mismatched.add(claim_id)
        for claim_id in mismatched:
            self.record_event('CLAIM_MISMATCHED', claim_id)

    def compare_prototype_argument_assertions(self, annotation):
        clusters = {'projection': {}, 'annotation': {}}
        store = self.get('projection').get('mention_argument_assertions_justifications.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                aa_subject_mention_id = entry.get('?subject_mention_id')
                aa_subject = self.get('prototype', 'projection', aa_subject_mention_id)
                predicate = entry.get('?predicate')
                aa_object_mention_id = entry.get('?object_mention_id')
                aa_object = self.get('prototype', 'projection', aa_object_mention_id)
                argument_assertion = '{subject}::{predicate}::{object}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object
                    )
                clusters.get('projection').setdefault(aa_subject_mention_id, set()).add(argument_assertion)

        for store_name in ['event_slots', 'relation_slots']:
            for entry in annotation.get('worksheets').get(store_name):
                aa_subject_mention_id = entry.get('eventmention_id') or entry.get('relationmention_id')
                aa_subject = self.get('prototype', 'annotation', aa_subject_mention_id, annotation=annotation)
                predicate = entry.get('general_slot_type')
                aa_object_mention_id = entry.get('argmention_id')
                aa_object = self.get('prototype', 'annotation', aa_object_mention_id, annotation=annotation)
                argument_assertion = '{subject}::{predicate}::{object}'.format(
                    subject = aa_subject,
                    predicate = predicate,
                    object = aa_object,
                    )
                clusters.get('annotation').setdefault(aa_subject_mention_id, set()).add(argument_assertion)

        count = 0
        for entry in annotation.get('worksheets').get('claims'):
            claim_id = entry.get('claim_id')
            associated_mentions = set()
            for mention_id in entry.get('associated_kes').split(','):
                associated_mentions.add(mention_id.strip())
            argument_assertions = {'projection': set(), 'annotation': set()}
            for mention_id in associated_mentions:
                for key in argument_assertions:
                    if clusters.get(key).get(mention_id):
                        argument_assertions.get(key).update(clusters.get(key).get(mention_id))

            union = argument_assertions.get('projection').union(argument_assertions.get('annotation'))
            intersection = argument_assertions.get('projection').intersection(argument_assertions.get('annotation'))
            missings = union - intersection
            for missing in missings:
                count += 1
                stores = ['projection', 'annotation']
                for store in stores:
                    if missing not in clusters.get(store):
                        error_code = 'MISSING_CLAIM_ARGUMENT_ASSERTION_WARNING' if '::EMPTY_TBD::' in missing else 'MISSING_CLAIM_ARGUMENT_ASSERTION_ERROR'
                        self.record_event(error_code, missing, claim_id, store)
        self.record_event('MISSING_PROTOTYPE_ARGUMENT_ASSERTION_COUNT', count if count else 'No')

    def compare_mention_argument_assertions(self, annotation):
        clusters = {'projection': {}, 'annotation': {}}
        store = self.get('projection').get('mention_argument_assertions_justifications.rq.tsv')
        for kb in store:
            for entry in store.get(kb):
                aa_subject_mention_id = entry.get('?subject_mention_id')
                predicate = entry.get('?predicate')
                aa_object_mention_id = entry.get('?object_mention_id')
                argument_assertion = '{subject}::{predicate}::{object}'.format(
                    subject = aa_subject_mention_id,
                    predicate = predicate,
                    object = aa_object_mention_id
                    )
                clusters.get('projection').setdefault(aa_subject_mention_id, set()).add(argument_assertion)

        for store_name in ['event_slots', 'relation_slots']:
            for entry in annotation.get('worksheets').get(store_name):
                aa_subject_mention_id = entry.get('eventmention_id') or entry.get('relationmention_id')
                predicate = entry.get('general_slot_type')
                aa_object_mention_id = entry.get('argmention_id')
                argument_assertion = '{subject}::{predicate}::{object}'.format(
                    subject = aa_subject_mention_id,
                    predicate = predicate,
                    object = aa_object_mention_id,
                    )
                clusters.get('annotation').setdefault(aa_subject_mention_id, set()).add(argument_assertion)

        count = 0
        for entry in annotation.get('worksheets').get('claims'):
            claim_id = entry.get('claim_id')
            associated_mentions = set()
            for mention_id in entry.get('associated_kes').split(','):
                associated_mentions.add(mention_id.strip())
            argument_assertions = {'projection': set(), 'annotation': set()}
            for mention_id in associated_mentions:
                for key in argument_assertions:
                    if clusters.get(key).get(mention_id):
                        argument_assertions.get(key).update(clusters.get(key).get(mention_id))

            union = argument_assertions.get('projection').union(argument_assertions.get('annotation'))
            intersection = argument_assertions.get('projection').intersection(argument_assertions.get('annotation'))
            missings = union - intersection
            for missing in missings:
                count += 1
                stores = ['projection', 'annotation']
                for store in stores:
                    if missing not in clusters.get(store):
                        error_code = 'MISSING_CLAIM_ARGUMENT_ASSERTION_WARNING' if '::EMPTY_TBD::' in missing else 'MISSING_CLAIM_ARGUMENT_ASSERTION_ERROR'
                        self.record_event(error_code, missing, claim_id, store)
        self.record_event('MISSING_PROTOTYPE_ARGUMENT_ASSERTION_COUNT', count if count else 'No')

def check_paths(args):
    check_for_paths_existance([
                 args.errors, 
                 args.annotations
                 ])
    check_for_paths_non_existance([args.output])

def check_for_paths_existance(paths):
    """
    Checks if the required files and directories were present,
    exit with an error code if any of the required file or directories
    were not found.
    """
    for path in paths:
        if not os.path.exists(path):
            print('Error: Path {} does not exist'.format(path))
            exit(ERROR_EXIT_CODE)

def check_for_paths_non_existance(paths):
    """
    Checks if the required files and directories were not present,
    exit with an error code if any of the required file or directories
    were not found.
    """
    for path in paths:
        if os.path.exists(path):
            print('Error: Path {} exists'.format(path))
            exit(ERROR_EXIT_CODE)

class Task1(Object):
    """
    Generate Task1 AIF.
    """
    def __init__(self, log, errors, encodings_filename, parent_children, annotations, projections):
        check_for_paths_existance([
                 errors,
                 encodings_filename,
                 parent_children,
                 annotations,
                 projections,
                 ])
        check_for_paths_non_existance([])
        self.log_filename = log
        self.log_specifications = errors
        self.encodings_filename = encodings_filename
        self.parent_children = parent_children
        self.annotations = annotations
        self.projections = projections
        self.logger = Logger(self.get('log_filename'),
                        self.get('log_specifications'),
                        sys.argv)

    def __call__(self):
        logger = self.get('logger')
        include_files = {
            'arg_mentions.tab':            'argument_KEs',
            'evt_mentions.tab':            'event_KEs',
            'rel_mentions.tab':            'relation_KEs',
            'evt_slots.tab':               'event_slots',
            'rel_slots.tab':               'relation_slots',
            'kb_linking.tab':              'kb_links',
            }
        encodings = Encodings(logger, self.get('encodings_filename'))
        document_mappings = DocumentMappings(logger, self.get('parent_children'), encodings)
        annotations =  TA1Annotations(logger, self.get('annotations'), include_items=include_files)
        projections = TA1AIFProjections(logger, self.get('projections'), document_mappings)
        projections.verify(annotations)
        print('--done.')
        exit(ALLOK_EXIT_CODE)

    @classmethod
    def add_arguments(myclass, parser):
        parser.add_argument('-l', '--log', default='log.txt', help='Specify a file to which log output should be redirected (default: %(default)s)')
        parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + __version__, help='Print version number and exit')
        parser.add_argument('errors', type=str, help='File containing error specifications')
        parser.add_argument('encodings_filename', type=str, help='File containing list of encoding to modality mappings')
        parser.add_argument('parent_children', type=str, help='parent_children.tab file as received from LDC')
        parser.add_argument('annotations', type=str, help='Task3 annotations as received from LDC')
        parser.add_argument('projections', type=str, help='Projections from AIF generated from annotations as received from LDC')
        parser.set_defaults(myclass=myclass)
        return parser

class Task2(Object):
    """
    Generate Task2 AIF.
    """
    def __init__(self, log, errors, encodings_filename, parent_children, annotations, projections):
        check_for_paths_existance([
                 errors,
                 encodings_filename,
                 parent_children,
                 annotations,
                 projections,
                 ])
        check_for_paths_non_existance([])
        self.log_filename = log
        self.log_specifications = errors
        self.encodings_filename = encodings_filename
        self.parent_children = parent_children
        self.annotations = annotations
        self.projections = projections
        self.logger = Logger(self.get('log_filename'),
                        self.get('log_specifications'),
                        sys.argv)

    def __call__(self):
        logger = self.get('logger')
        include_files = {
            'arg_mentions.tab':            'argument_KEs',
            'evt_mentions.tab':            'event_KEs',
            'rel_mentions.tab':            'relation_KEs',
            'evt_slots.tab':               'event_slots',
            'rel_slots.tab':               'relation_slots',
            'kb_linking.tab':              'kb_links',
            }
        encodings = Encodings(logger, self.get('encodings_filename'))
        document_mappings = DocumentMappings(logger, self.get('parent_children'), encodings)
        annotations =  TA1Annotations(logger, self.get('annotations'), include_items=include_files)
        projections = TA2AIFProjections(logger, self.get('projections'), document_mappings)
        projections.verify(annotations)
        print('--done.')
        exit(ALLOK_EXIT_CODE)

    @classmethod
    def add_arguments(myclass, parser):
        parser.add_argument('-l', '--log', default='log.txt', help='Specify a file to which log output should be redirected (default: %(default)s)')
        parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + __version__, help='Print version number and exit')
        parser.add_argument('errors', type=str, help='File containing error specifications')
        parser.add_argument('encodings_filename', type=str, help='File containing list of encoding to modality mappings')
        parser.add_argument('parent_children', type=str, help='parent_children.tab file as received from LDC')
        parser.add_argument('annotations', type=str, help='Task3 annotations as received from LDC')
        parser.add_argument('projections', type=str, help='Projections from AIF generated from annotations as received from LDC')
        parser.set_defaults(myclass=myclass)
        return parser

class Task3(Object):
    """
    Generate Task3 AIF.
    """
    def __init__(self, log, errors, encodings_filename, parent_children, annotations, projections):
        check_for_paths_existance([
                 errors,
                 encodings_filename,
                 parent_children,
                 annotations,
                 projections,
                 ])
        check_for_paths_non_existance([])
        self.log_filename = log
        self.log_specifications = errors
        self.encodings_filename = encodings_filename
        self.parent_children = parent_children
        self.annotations = annotations
        self.projections = projections
        self.logger = Logger(self.get('log_filename'),
                        self.get('log_specifications'),
                        sys.argv)

    def __call__(self):
        logger = self.get('logger')
        encodings = Encodings(logger, self.get('encodings_filename'))
        document_mappings = DocumentMappings(logger, self.get('parent_children'), encodings)
        annotations = self.load_annotations(self.get('annotations'))
        projections = TA3AIFProjections(logger, self.get('projections'), document_mappings)
        projections.verify(annotations)
        print('--done.')
        exit(ALLOK_EXIT_CODE)

    @classmethod
    def add_arguments(myclass, parser):
        parser.add_argument('-l', '--log', default='log.txt', help='Specify a file to which log output should be redirected (default: %(default)s)')
        parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + __version__, help='Print version number and exit')
        parser.add_argument('errors', type=str, help='File containing error specifications')
        parser.add_argument('encodings_filename', type=str, help='File containing list of encoding to modality mappings')
        parser.add_argument('parent_children', type=str, help='parent_children.tab file as received from LDC')
        parser.add_argument('annotations', type=str, help='Task3 annotations as received from LDC')
        parser.add_argument('projections', type=str, help='Projections from AIF generated from annotations as received from LDC')
        parser.set_defaults(myclass=myclass)
        return parser

    def load_annotations(self, path):
        if os.path.isfile(path) and path.endswith('xlsx'):
            include_worksheets = {
                'TA3_arg_KEs':                 'argument_KEs',
                'TA3_evt_KEs':                 'event_KEs',
                'TA3_rel_KEs':                 'relation_KEs',
                'TA3_evt_slots':               'event_slots',
                'TA3_rel_slots':               'relation_slots',
                'TA3_kb_linking':              'kb_links',
                'ClaimFrameTemplate Examples': 'claims',
                'TA3_cross_claim_relations.tab E': 'cross_claim_relations'
                }
            return TA3Annotations(self.get('logger'), self.get('annotations'), include_items=include_worksheets)
        elif os.path.isdir(path):
            include_files = {
                'claim_frames.tab':            'claims',
                'arg_kes.tab':                 'argument_KEs',
                'evt_kes.tab':                 'event_KEs',
                'rel_kes.tab':                 'relation_KEs',
                'evt_slots.tab':               'event_slots',
                'rel_slots.tab':               'relation_slots',
                'kb_linking.tab':              'kb_links',
                'cross_claim_relations.tab':   'cross_claim_relations'
                }
            return TA1Annotations(self.get('logger'), self.get('annotations'), include_items=include_files)
        else:
            self.record_event('UNEXPECTED_PATH', path)

myclasses = [
    Task1,
    Task2,
    Task3
    ]

def main(args=sys.argv[1:]):
    parser = argparse.ArgumentParser(prog='verify_aif',
                                description='Verify AIF generated from LDC annotations')
    subparser = parser.add_subparsers()
    subparsers = {}
    for myclass in myclasses:
        hyphened_name = re.sub('([A-Z])', r'-\1', myclass.__name__).lstrip('-').lower()
        help_text = myclass.__doc__.split('\n')[0]
        desc = textwrap.dedent(myclass.__doc__.rstrip())

        class_subparser = subparser.add_parser(hyphened_name,
                            help=help_text,
                            description=desc,
                            formatter_class=argparse.RawDescriptionHelpFormatter)
        myclass.add_arguments(class_subparser)
        subparsers[myclass] = class_subparser

    namespace = vars(parser.parse_args(args))
    try:
        myclass = namespace.pop('myclass')
    except KeyError:
        parser.print_help()
        return
    try:
        obj = myclass(**namespace)
    except ValueError as e:
        subparsers[myclass].error(str(e) + "\n" + traceback.format_exc())
    result = obj()
    if result is not None:
        print(result)

if __name__ == '__main__':
    main()