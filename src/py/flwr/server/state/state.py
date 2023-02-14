# Copyright 2022 Adap GmbH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Abstract base class State."""


import abc
from logging import ERROR
from typing import List, Optional, Set, Union
from uuid import UUID

from google.protobuf.json_format import MessageToJson

from flwr.common.logger import log
from flwr.proto.task_pb2 import TaskIns, TaskRes


def is_valid_task(message: Union[TaskIns, TaskRes]) -> bool:
    """Validate message of type TaskIns or TaskRes.

    If the message is not valid return False and log the validation
    error.
    """
    if message.task.consumer.anonymous and message.task.consumer.node_id != 0:
        log(
            ERROR,
            "`task.consumer.anonymous` is `True` then `node_id` must be 0\n%s",
            MessageToJson(message, including_default_value_fields=True),
        )
        return False

    if not message.task.consumer.anonymous and message.task.consumer.node_id == 0:
        log(
            ERROR,
            "`task.consumer.anonymous` is `False` then `node_id` must not be 0\n%s",
            MessageToJson(message, including_default_value_fields=True),
        )
        return False

    if message.task.HasField("producer"):
        if message.task.producer.anonymous and message.task.producer.node_id != 0:
            log(
                ERROR,
                "`task.producer.anonymous` is `True` then `node_id` must be 0\n%s",
                MessageToJson(message, including_default_value_fields=True),
            )
            return False

        if not message.task.producer.anonymous and message.task.producer.node_id == 0:
            log(
                ERROR,
                "`task.producer.anonymous` is `False` then `node_id` must not be 0\n%s",
                MessageToJson(message, including_default_value_fields=True),
            )
            return False

    # A task TaskRes message has to have at least one ancestor for the embedded task
    if isinstance(message, TaskRes):
        if len(message.task.ancestry) == 0:
            log(
                ERROR,
                "`task_res.task.ancestry` may not be empty:\n%s",
                MessageToJson(message, including_default_value_fields=True),
            )
            return False

    return True


class State(abc.ABC):
    """Abstract State."""

    @abc.abstractmethod
    def store_task_ins(self, task_ins: TaskIns) -> Optional[UUID]:
        """Store one TaskIns.

        Usually, the Driver API calls this to schedule instructions.

        Stores the value of the task_ins in the state and, if successful, returns the
        task_id (UUID) of the task_ins. If, for any reason, storing the task_ins fails,
        `None` is returned.

        Constraints
        -----------
        If `task_ins.task.consumer.anonymous` is `True`, then
        `task_ins.task.consumer.node_id` MUST NOT be set (equal 0). Any implemenation
        may just override it with zero instead of validating.

        If `task_ins.task.consumer.anonymous` is `False`, then
        `task_ins.task.consumer.node_id` MUST be set (not 0)
        """

    @abc.abstractmethod
    def get_task_ins(
        self, node_id: Optional[int], limit: Optional[int]
    ) -> List[TaskIns]:
        """Get TaskIns optionally filtered by node_id.

        Usually, the Fleet API calls this for Nodes planning to work on one or more
        TaskIns.

        Constraints
        -----------
        If `node_id` is not `None`, retrieve all TaskIns where

            1. the `task_ins.task.consumer.node_id` equals `node_id` AND
            2. the `task_ins.task.consumer.anonymous` equals `False` AND
            3. the `task_ins.task.delivered_at` equals `""`.

        If `node_id` is `None`, retrieve all TaskIns where the
        `task_ins.task.consumer.node_id` equals `0` and
        `task_ins.task.consumer.anonymous` is set to `True`.

        If `delivered_at` MUST BE set (not `""`) otherwise the TaskIns MUST not be in
        the result.

        If `limit` is not `None`, return, at most, `limit` number of `task_ins`. If
        `limit` is set, it has to be greater zero.
        """

    @abc.abstractmethod
    def store_task_res(self, task_res: TaskRes) -> Optional[UUID]:
        """Store one TaskRes.

        Usually, the Fleet API calls this for Nodes returning results.

        Stores the TaskRes and, if successful, returns the `task_id` (UUID) of
        the `task_res`. If storing the `task_res` fails, `None` is returned.

        Constraints
        -----------
        If `task_res.task.consumer.anonymous` is `True`, then
        `task_res.task.consumer.node_id` MUST NOT be set (equal 0). Any implemenation
        may just override it with zero instead of validating.

        If `task_res.task.consumer.anonymous` is `False`, then
        `task_res.task.consumer.node_id` MUST be set (not 0)
        """

    @abc.abstractmethod
    def get_task_res(self, task_ids: Set[UUID], limit: Optional[int]) -> List[TaskRes]:
        """Get TaskRes for task_ids.

        Usually, the Driver API calls this for Nodes planning to work on one or more
        TaskIns.

        Retrieves all TaskRes for the given `task_ids` and returns and empty list of
        none could be found.

        Constraints
        -----------
        If `limit` is not `None`, return, at most, `limit` number of TaskRes. The limit
        will only take effect if enough task_ids are in the set AND are currently
        available. If `limit` is set, it has to be greater zero.
        """

    @abc.abstractmethod
    def delete_tasks(self, task_ids: Set[UUID]) -> None:
        """Delete all delivered TaskIns/TaskRes pairs."""

    @abc.abstractmethod
    def register_node(self, node_id: int) -> None:
        """Store `node_id` in state."""

    @abc.abstractmethod
    def unregister_node(self, node_id: int) -> None:
        """Remove `node_id` from state."""

    @abc.abstractmethod
    def get_nodes(self) -> Set[int]:
        """Retrieve all currently stored node IDs as a set."""
