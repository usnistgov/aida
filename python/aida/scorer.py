"""
AIDA Scorer class.
"""

__author__  = "Shahzad Rajput <shahzad.rajput@nist.gov>"
__status__  = "production"
__version__ = "0.0.0.1"
__date__    = "3 February 2020"

from aida.object import Object
from aida.container import Container
from tqdm import tqdm

class Scorer(Object):
    """
    AIDA Scorer class.
    """

    def __init__(self, logger, **kwargs):
        super().__init__(logger)
        for key in kwargs:
            self.set(key, kwargs[key])
        self.score_responses()

    def get_cluster(self, system_or_gold, document_id, cluster_id):
        cluster = None
        if document_id in self.get('{}_responses'.format(system_or_gold)).get('document_clusters'):
            if cluster_id in self.get('{}_responses'.format(system_or_gold)).get('document_clusters').get(document_id):
                cluster = self.get('{}_responses'.format(system_or_gold)).get('document_clusters').get(document_id).get(cluster_id)
        return cluster

    def get_frame(self, system_or_gold, document_id, cluster_id):
        frame = None
        if document_id in self.get('{}_responses'.format(system_or_gold)).get('document_frames'):
            if cluster_id in self.get('{}_responses'.format(system_or_gold)).get('document_frames').get(document_id):
                frame = self.get('{}_responses'.format(system_or_gold)).get('document_frames').get(document_id).get(cluster_id)
        return frame

    def get_core_documents(self):
        return self.get('gold_responses').get('document_mappings').get('core_documents')

    def get_languages(self, score, scores):
        languages = [score.get('language')]
        flag = True
        for element in scores.values():
            if element.get('language') == 'ALL':
                flag = False
        if flag:
            languages.append('ALL')
        return languages

    def get_metatypes(self, score, scores):
        metatypes = [score.get('metatype')]
        flag = True
        for element in scores.values():
            if element.get('metatype') == 'ALL':
                flag = False
        if flag:
            metatypes.append('ALL')
        return metatypes

    def aggregate_scores(self, scores, score_class):
        aggregates = {}
        for score in tqdm(scores.values(), desc='aggregating {} scores'.format(self.__class__.__name__)):
            languages = self.get('languages', score, scores)
            metatypes = self.get('metatypes', score, scores)
            for language in languages:
                for metatype in metatypes:
                    group_by = language + ',' + metatype
                    if group_by not in aggregates:
                        aggregates[group_by] = score_class(self.get('logger'),
                                                           aggregate=True,
                                                           language=language,
                                                           metatype=metatype,
                                                           run_id=self.get('run_id'),
                                                           summary=True,
                                                           elements=Container(self.get('logger')))
                    aggregate_scores = aggregates[group_by]
                    aggregate_scores.get('elements').add(score)
        for score in sorted(aggregates.values(), key=self.order):
            scores.add(score)

    def order(self, k):
        language, metatype = k.get('language'), k.get('metatype')
        metatype = '_ALL' if metatype == 'ALL' else metatype
        language = '_ALL' if language == 'ALL' else language
        return '{language}:{metatype}'.format(metatype=metatype, language=language)

    def print_scores(self, filename, separator):
        scores = self.get('scores')
        scores.set('separator', separator)
        fh = open(filename, 'w')
        fh.write(scores.to_string())
        fh.close()