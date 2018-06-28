import logging
from typing import List, Tuple
import warnings

from allennlp.common.params import Params
from allennlp.data.iterators.data_iterator import DataIterator
from allennlp.data.iterators.bucket_iterator import BucketIterator

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


@DataIterator.register("epoch_tracking_bucket")
class EpochTrackingBucketIterator(BucketIterator):
    """
    This is essentially a :class:`allennlp.data.iterators.BucketIterator` with just one difference.
    It keeps track of the epoch number, and adds that as an additional meta field to each instance.
    That way, ``Model.forward`` will have access to this information. We do this by keeping track of
    epochs globally, and incrementing them whenever the iterator is called. However, the iterator is
    called both for training and validation sets. So, we keep a dict of epoch numbers, one key per
    dataset.

    Parameters
    ----------
    See :class:`BucketIterator`.
    """
    def __init__(self,
                 sorting_keys: List[Tuple[str, str]],
                 padding_noise: float = 0.1,
                 biggest_batch_first: bool = False,
                 batch_size: int = 32,
                 instances_per_epoch: int = None,
                 max_instances_in_memory: int = None,
                 cache_instances: bool = False) -> None:
        super().__init__(sorting_keys=sorting_keys,
                         padding_noise=padding_noise,
                         biggest_batch_first=biggest_batch_first,
                         batch_size=batch_size,
                         instances_per_epoch=instances_per_epoch,
                         max_instances_in_memory=max_instances_in_memory,
                         track_epoch=True,
                         cache_instances=cache_instances)
        warnings.warn("EpochTrackingBucketIterator is deprecated, "
                      "please just use BucketIterator with track_epoch=True",
                      DeprecationWarning)

    @classmethod
    def from_params(cls, params: Params) -> 'BucketIterator':
        sorting_keys = params.pop('sorting_keys')
        padding_noise = params.pop_float('padding_noise', 0.1)
        biggest_batch_first = params.pop_bool('biggest_batch_first', False)
        batch_size = params.pop_int('batch_size', 32)
        instances_per_epoch = params.pop_int('instances_per_epoch', None)
        max_instances_in_memory = params.pop_int('max_instances_in_memory', None)
        cache_instances = params.pop_bool('cache_instances', False)
        params.assert_empty(cls.__name__)

        return cls(sorting_keys=sorting_keys,
                   padding_noise=padding_noise,
                   biggest_batch_first=biggest_batch_first,
                   batch_size=batch_size,
                   instances_per_epoch=instances_per_epoch,
                   max_instances_in_memory=max_instances_in_memory,
                   cache_instances=cache_instances)
