from typing import Dict, List
import warnings

import torch
from overrides import overrides

from allennlp.common import Params
from allennlp.common.checks import ConfigurationError
from allennlp.data import Vocabulary
from allennlp.modules.text_field_embedders.text_field_embedder import TextFieldEmbedder
from allennlp.modules.time_distributed import TimeDistributed
from allennlp.modules.token_embedders.token_embedder import TokenEmbedder


@TextFieldEmbedder.register("basic")
class BasicTextFieldEmbedder(TextFieldEmbedder):
    """
    This is a ``TextFieldEmbedder`` that wraps a collection of :class:`TokenEmbedder` objects.  Each
    ``TokenEmbedder`` embeds or encodes the representation output from one
    :class:`~allennlp.data.TokenIndexer`.  As the data produced by a
    :class:`~allennlp.data.fields.TextField` is a dictionary mapping names to these
    representations, we take ``TokenEmbedders`` with corresponding names.  Each ``TokenEmbedders``
    embeds its input, and the result is concatenated in an arbitrary order.

    Parameters
    ----------

    token_embedders : ``Dict[str, TokenEmbedder]``, required.
        A dictionary mapping token embedder names to implementations.
        These names should match the corresponding indexer used to generate
        the tensor passed to the TokenEmbedder.
    embedder_to_indexer_map : ``Dict[str, List[str]]``, optional, (default = None)
        Optionally, you can provide a mapping between the names of the TokenEmbedders
        that you are using to embed your TextField and an ordered list of indexer names
        which are needed for running it. In most cases, your TokenEmbedder will only
        require a single tensor, because it is designed to run on the output of a
        single TokenIndexer. For example, the ELMo Token Embedder can be used in
        two modes, one of which requires both character ids and word ids for the
        same text. Note that the list of token indexer names is `ordered`, meaning
        that the tensors produced by the indexers will be passed to the embedders
        in the order you specify in this list.
    """
    def __init__(self,
                 token_embedders: Dict[str, TokenEmbedder],
                 embedder_to_indexer_map: Dict[str, List[str]] = None) -> None:
        super(BasicTextFieldEmbedder, self).__init__()
        self._token_embedders = token_embedders
        self._embedder_to_indexer_map = embedder_to_indexer_map
        for key, embedder in token_embedders.items():
            name = 'token_embedder_%s' % key
            self.add_module(name, embedder)

    @overrides
    def get_output_dim(self) -> int:
        output_dim = 0
        for embedder in self._token_embedders.values():
            output_dim += embedder.get_output_dim()
        return output_dim

    def forward(self, text_field_input: Dict[str, torch.Tensor], num_wrapping_dims: int = 0) -> torch.Tensor:
        if self._token_embedders.keys() != text_field_input.keys():
            message = "Mismatched token keys: %s and %s" % (str(self._token_embedders.keys()),
                                                            str(text_field_input.keys()))
            raise ConfigurationError(message)
        embedded_representations = []
        keys = sorted(self._token_embedders.keys())
        for key in keys:
            # If we pre-specified a mapping explictly, use that.
            if self._embedder_to_indexer_map is not None:
                tensors = [text_field_input[indexer_key] for
                           indexer_key in self._embedder_to_indexer_map[key]]
            else:
                # otherwise, we assume the mapping between indexers and embedders
                # is bijective and just use the key directly.
                tensors = [text_field_input[key]]
            # Note: need to use getattr here so that the pytorch voodoo
            # with submodules works with multiple GPUs.
            embedder = getattr(self, 'token_embedder_{}'.format(key))
            for _ in range(num_wrapping_dims):
                embedder = TimeDistributed(embedder)
            token_vectors = embedder(*tensors)
            embedded_representations.append(token_vectors)
        return torch.cat(embedded_representations, dim=-1)

    # This is some unusual logic, it needs a custom from_params.
    @classmethod
    def from_params(cls, vocab: Vocabulary, params: Params) -> 'BasicTextFieldEmbedder':  # type: ignore
        # pylint: disable=arguments-differ,bad-super-call

        # The original `from_params` for this class was designed in a way that didn't agree
        # with the constructor. The constructor wants a 'token_embedders' parameter that is a
        # `Dict[str, TokenEmbedder]`, but the original `from_params` implementation expected those
        # key-value pairs to be top-level in the params object. In particular, this caused the automatic
        # FromParams.from_params implementation to do the wrong thing with config files that were
        # designed for the (idiosyncratic) old behavior.
        #
        # This updated implementation delegates to the automatic "from_params" method when it can,
        # but (for now) it continues to support the old way with a `DeprecationWarning`.
        if 'token_embedders' in params:
            # We use `TextFieldEmbedder` as the first argument to super() so that we get
            # Registrable.from_params.
            return super(TextFieldEmbedder, cls).from_params(params=params, vocab=vocab)

        # Warn that the original behavior is deprecated
        warnings.warn(DeprecationWarning("the token embedders for BasicTextFieldEmbedder should now "
                                         "be specified as a dict under the 'token_embedders' key, "
                                         "not as top-level key-value pairs"))

        embedder_to_indexer_map = params.pop("embedder_to_indexer_map", None)
        if embedder_to_indexer_map is not None:
            embedder_to_indexer_map = embedder_to_indexer_map.as_dict(quiet=True)

        token_embedders = {}
        keys = list(params.keys())
        for key in keys:
            embedder_params = params.pop(key)
            token_embedders[key] = TokenEmbedder.from_params(vocab=vocab, params=embedder_params)
        params.assert_empty(cls.__name__)
        return cls(token_embedders, embedder_to_indexer_map)
