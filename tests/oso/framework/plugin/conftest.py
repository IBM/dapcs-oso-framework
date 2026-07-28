#
# (c) Copyright IBM Corp. 2025
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

""""""

import random
import string
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from oso.framework.data.types import V1_3, V1_5


@pytest.fixture(scope="session")
def document_set():
    """
    DocumentList for testing in the above format.

    Returns:

        object:

            Contains OSO and ISV formatted data of the same set.
    """
    oso: list[V1_3.Document] = list()
    isv: list[str] = list()
    for doc in [
        V1_3.Document(
            id=str(uuid4()),
            content="".join(
                random.choices(
                    population=string.ascii_letters + string.digits,
                    k=random.randint(1, 99),
                )
            ),
            metadata="",
        )
        for _ in range(random.randint(1, 99))
    ]:
        oso.append(doc)
        isv.append(f"{doc.id}:{doc.content}")

    return {
        "isv": isv,
        "oso": V1_3.DocumentList(documents=oso, count=len(oso)),
    }


@pytest.fixture(scope="session")
def event_set():
    """
    EventList for testing.

    Returns
    -------
    dict
        Contains an `EventList` and the expected response count.
    """
    events = [
        V1_5.DocumentEvent(
            eventType="DocumentEvent",
            eventId=str(uuid4()),
            eventTimestamp=datetime(1970, 1, 1, 0, 29, 53, 179490, tzinfo=timezone.utc),
            docId=str(uuid4()),
            user="CN=user1,O=EXAMPLE,C=US",
            operationType="approvedBy",
            queueType="POST_CONFIRMATION",
            metadata='{"description": "Valid transaction"}',
        ),
        V1_5.DocumentEvent(
            eventType="DocumentEvent",
            eventId=str(uuid4()),
            eventTimestamp=datetime(1970, 1, 1, 0, 29, 56, 557329, tzinfo=timezone.utc),
            docId=str(uuid4()),
            user="System",
            operationType="toApproved",
            queueType="POST_CONFIRMATION",
            metadata='{"description": "Valid transaction"}',
        ),
    ]
    return {
        "oso": V1_5.EventList(events=events, count=len(events)),
    }
