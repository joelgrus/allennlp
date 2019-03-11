from collections import defaultdict
from typing import Dict, Generic, List, TypeVar, Tuple

import torch

from allennlp.common.registrable import FromParams
from allennlp.state_machines import util
from allennlp.state_machines.states import State
from allennlp.state_machines.transition_functions import TransitionFunction

StateType = TypeVar('StateType', bound=State)  # pylint: disable=invalid-name


class BeamSearch(FromParams, Generic[StateType]):
    """
    This class implements beam search over transition sequences given an initial ``State`` and a
    ``TransitionFunction``, returning the highest scoring final states found by the beam (the
    states will keep track of the transition sequence themselves).

    The initial ``State`` is assumed to be `batched`.  The value we return from the search is a
    dictionary from batch indices to ranked finished states.

    IMPORTANT: We assume that the ``TransitionFunction`` that you are using returns possible next
    states in sorted order, so we do not do an additional sort inside of ``BeamSearch.search()``.
    If you're implementing your own ``TransitionFunction``, you must ensure that you've sorted the
    states that you return.

    Parameters
    ----------
    beam_size : ``int``
        The beam size to use.
    per_node_beam_size : ``int``, optional (default = beam_size)
        The maximum number of candidates to consider per node, at each step in the search.
        If not given, this just defaults to `beam_size`. Setting this parameter
        to a number smaller than `beam_size` may give better results, as it can introduce
        more diversity into the search. See Freitag and Al-Onaizan 2017,
        "Beam Search Strategies for Neural Machine Translation".
    """
    def __init__(self,
                 beam_size: int,
                 per_node_beam_size: int = None,
                 initial_sequence: torch.Tensor = None,
                 keep_beam_details: bool = False) -> None:
        self._beam_size = beam_size
        self._per_node_beam_size = per_node_beam_size or beam_size

        if initial_sequence is not None:
            # construct_prefix_tree wants a tensor of shape (batch_size, num_sequences, sequence_length)
            # so we need to add the first two dimensions in. This returns a list, but we're assuming
            # batch size 1, so we extract the first element.
            self._allowed_transitions = util.construct_prefix_tree(initial_sequence.view(1, 1, -1))[0]
        else:
            self._allowed_transitions = None

        if keep_beam_details:
            self.beams: List[List[Tuple[float, List[int]]]] = []
        else:
            self.beams = None

    def constrained_to(self, initial_sequence: torch.Tensor, keep_beam_details: bool = True) -> 'BeamSearch':
        """
        Return a new BeamSearch instance that's like this one but with the specified constraint.
        """
        return BeamSearch(self._beam_size, self._per_node_beam_size, initial_sequence, keep_beam_details)

    def search(self,
               num_steps: int,
               initial_state: StateType,
               transition_function: TransitionFunction,
               keep_final_unfinished_states: bool = True) -> Dict[int, List[StateType]]:
        """
        Parameters
        ----------
        num_steps : ``int``
            How many steps should we take in our search?  This is an upper bound, as it's possible
            for the search to run out of valid actions before hitting this number, or for all
            states on the beam to finish.
        initial_state : ``StateType``
            The starting state of our search.  This is assumed to be `batched`, and our beam search
            is batch-aware - we'll keep ``beam_size`` states around for each instance in the batch.
        transition_function : ``TransitionFunction``
            The ``TransitionFunction`` object that defines and scores transitions from one state to the
            next.
        keep_final_unfinished_states : ``bool``, optional (default=True)
            If we run out of steps before a state is "finished", should we return that state in our
            search results?

        Returns
        -------
        best_states : ``Dict[int, List[StateType]]``
            This is a mapping from batch index to the top states for that instance.
        """
        finished_states: Dict[int, List[StateType]] = defaultdict(list)
        states = [initial_state]
        step_num = 1

        # Erase stored beams, if we're tracking them.
        if self.beams is not None:
            self.beams.clear()

        while states and step_num <= num_steps:
            next_states: Dict[int, List[StateType]] = defaultdict(list)
            grouped_state = states[0].combine_states(states)

            # The only possible constraint on allowed actions is that we're still following
            # the specified initial sequence, which we can check by seeing if the first
            # action history appears in our allowed transitions.
            allowed_actions = None

            if self._allowed_transitions:
                key = tuple(grouped_state.action_history[0])
                if key in self._allowed_transitions:
                    allowed_actions = [self._allowed_transitions[key]]

            for next_state in transition_function.take_step(grouped_state,
                                                            max_actions=self._per_node_beam_size,
                                                            allowed_actions=allowed_actions):
                # NOTE: we're doing state.batch_indices[0] here (and similar things below),
                # hard-coding a group size of 1.  But, our use of `next_state.is_finished()`
                # already checks for that, as it crashes if the group size is not 1.
                batch_index = next_state.batch_indices[0]
                if next_state.is_finished():
                    finished_states[batch_index].append(next_state)
                else:
                    if step_num == num_steps and keep_final_unfinished_states:
                        finished_states[batch_index].append(next_state)
                    next_states[batch_index].append(next_state)
            states = []
            for batch_index, batch_states in next_states.items():
                # The states from the generator are already sorted, so we can just take the first
                # ones here, without an additional sort.
                states.extend(batch_states[:self._beam_size])

                if self.beams is not None:
                    # Add to beams
                    self.beams.append([(state.score[0].item(), state.action_history[0])
                                       for state in batch_states])
            step_num += 1

        # Add finished states to the stored beams as well.
        if self.beams is not None:
            for state in finished_states[0]:
                score = state.score[0].item()
                action_history = state.action_history[0]

                while len(self.beams) < len(action_history):
                    self.beams.append([])

                self.beams[len(action_history) - 1].append((score, action_history))

        best_states: Dict[int, List[StateType]] = {}
        for batch_index, batch_states in finished_states.items():
            # The time this sort takes is pretty negligible, no particular need to optimize this
            # yet.  Maybe with a larger beam size...
            finished_to_sort = [(-state.score[0].item(), state) for state in batch_states]
            finished_to_sort.sort(key=lambda x: x[0])
            best_states[batch_index] = [state[1] for state in finished_to_sort[:self._beam_size]]
        return best_states
