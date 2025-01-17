"""
Class for variant # 4 of the type metric scores to be used in phase 3.
"""
__author__  = "Shahzad Rajput <shahzad.rajput@nist.gov>"
__status__  = "production"
__version__ = "0.0.0.1"
__date__    = "12 September 2022"

from aida.score_printer import ScorePrinter
from aida.scorer import Scorer
from aida.type_metric_v4_score import TypeMetricScoreV4
from aida.utility import multisort
from tqdm import tqdm

class TypeMetricScorerV4(Scorer):
    """
    Class for variant # 4 of the type metric scores to be used in phase 3.

    This variant of the scorer computes mean type_similarity computed over the unaligned clusters and the pairs of aligned clusters.
    """

    printing_specs = [{'name': 'document_id',      'header': 'DocID',           'format': 's',    'justify': 'L'},
                      {'name': 'run_id',           'header': 'RunID',           'format': 's',    'justify': 'L'},
                      {'name': 'language',         'header': 'Language',        'format': 's',    'justify': 'L'},
                      {'name': 'metatype',         'header': 'Metatype',        'format': 's',    'justify': 'L'},
                      {'name': 'gold_cluster_id',  'header': 'GoldClusterID',   'format': 's',    'justify': 'L'},
                      {'name': 'system_cluster_id','header': 'SystemClusterID', 'format': 's',    'justify': 'L'},
                      {'name': 'type_similarity',  'header': 'TypeSimilarity',  'format': '6.4f', 'justify': 'R', 'mean_format': '6.4f'}]

    def __init__(self, logger, **kwargs):
        super().__init__(logger, **kwargs)

    def get_type_similarity(self, document_id, cluster_ids):
        system_cluster_id = cluster_ids.get('system')
        gold_cluster_id = cluster_ids.get('gold')
        type_similarity = 0
        document_type_similarities = self.get('type_similarities').get('document_type_similarities', document_id)
        if system_cluster_id in document_type_similarities and gold_cluster_id in document_type_similarities.get(system_cluster_id):
            type_similarity = float(document_type_similarities.get(system_cluster_id).get(gold_cluster_id))
        return type_similarity

    def get_metatype(self, document_id, cluster_ids):
        responses = {
            'gold': self.get('gold_responses'),
            'system': self.get('system_responses')
            }
        metatype = None
        for system_or_gold in cluster_ids:
            cluster_id = cluster_ids.get(system_or_gold)
            if cluster_id == 'None': continue
            cluster = responses.get(system_or_gold).get('document_clusters').get(document_id).get(cluster_id)
            if cluster is None: continue
            metatype = cluster.get('metatype')
        if metatype not in ['Event', 'Relation', 'Entity', None]:
            self.record_event('DEFAULT_CRITICAL_ERROR', 'Unknown metatype: {} for {}:{}'.format(metatype, system_or_gold.upper(), cluster_id), self.get('code_location'))
        return metatype

    def score_responses(self):
        scores = []
        for document_id in tqdm(self.get('core_documents'), desc='scoring {}'.format(self.__class__.__name__)):
            # add scores corresponding to all gold clusters
            document = self.get('gold_responses').get('document_mappings').get('documents').get(document_id)
            # skip those core documents that do not have an entry in the parent-children table
            if document is None: continue
            language = document.get('language')

            document_gold_to_system = self.get('cluster_alignment').get('gold_to_system').get(document_id)
            for gold_cluster_id in document_gold_to_system if document_gold_to_system else []:
                if gold_cluster_id == 'None': continue
                system_cluster_id = document_gold_to_system.get(gold_cluster_id).get('aligned_to')
                type_similarity = 0.0000
                if system_cluster_id != 'None':
                    type_similarity = self.get('type_similarity', document_id, {'system': system_cluster_id, 'gold':gold_cluster_id})
                metatype = self.get('metatype', document_id, {'system': system_cluster_id, 'gold':gold_cluster_id})
                if metatype not in ['Entity', 'Event']: continue
                score = TypeMetricScoreV4(logger=self.logger,
                                           run_id=self.get('run_id'),
                                           document_id=document_id,
                                           language=language,
                                           metatype=metatype,
                                           gold_cluster_id=gold_cluster_id,
                                           system_cluster_id=system_cluster_id,
                                           type_similarity=type_similarity)
                scores.append(score)
            # add scores unaligned system clusters
            document_system_to_gold = self.get('cluster_alignment').get('system_to_gold').get(document_id)
            for system_cluster_id in document_system_to_gold if document_system_to_gold else []:
                gold_cluster_id = document_system_to_gold.get(system_cluster_id).get('aligned_to')
                aligned_similarity = document_system_to_gold.get(system_cluster_id).get('aligned_similarity')
                if system_cluster_id != 'None':
                    metatype = self.get('metatype', document_id, {'system': system_cluster_id, 'gold':gold_cluster_id})
                    if metatype not in ['Entity', 'Event']: continue
                    if gold_cluster_id == 'None':
                        score = TypeMetricScoreV4(logger=self.logger,
                                                   run_id=self.get('run_id'),
                                                   document_id=document_id,
                                                   language=language,
                                                   metatype=metatype,
                                                   gold_cluster_id=gold_cluster_id,
                                                   system_cluster_id=system_cluster_id,
                                                   type_similarity=0.0000)
                        scores.append(score)
                    elif aligned_similarity == 0:
                        self.record_event('DEFAULT_CRITICAL_ERROR', 'aligned_similarity=0')
        scores_printer = ScorePrinter(self.logger, self.printing_specs)
        for score in multisort(scores, (('document_id', False),
                                        ('metatype', False),
                                        ('gold_cluster_id', False),
                                        ('system_cluster_id', False))):
            scores_printer.add(score)
        self.aggregate_scores(scores_printer, TypeMetricScoreV4)
        self.scores = scores_printer