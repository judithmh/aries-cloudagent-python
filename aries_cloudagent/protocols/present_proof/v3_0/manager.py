"""Classes to manage presentations."""

import logging

from typing import Tuple

from ....connections.models.conn_record import ConnRecord
from ....core.error import BaseError
from ....core.profile import Profile
from ....messaging.responder import BaseResponder
from ....storage.error import StorageNotFoundError

from .messages.pres import V30Pres
from .messages.pres_ack import V30PresAck
from .messages.pres_format import V30PresFormat
from .messages.pres_body import V30PresBody
from .messages.pres_problem_report import V30PresProblemReport, ProblemReportReason
from .messages.pres_proposal import V30PresProposal
from .messages.pres_request import V30PresRequest
from .models.pres_exchange import V30PresExRecord


LOGGER = logging.getLogger(__name__)


class V30PresManagerError(BaseError):
    """Presentation error."""


class V30PresManager:
    """Class for managing presentations."""

    def __init__(self, profile: Profile):
        """
        Initialize a V30PresManager.

        Args:
            profile: The profile instance for this presentation manager
        """

        self._profile = profile

    async def create_exchange_for_proposal(
        self,
        connection_id: str,
        pres_proposal_message: V30PresProposal,
        auto_present: bool = None,
    ):
        """
        Create a presentation exchange record for input presentation proposal.

        Args:
            connection_id: connection identifier
            pres_proposal_message: presentation proposal to serialize
                to exchange record
            auto_present: whether to present proof upon receiving proof request
                (default to configuration setting)

        Returns:
            Presentation exchange record, created

        """
        pres_ex_record = V30PresExRecord(
            connection_id=connection_id,
            thread_id=pres_proposal_message._thread_id,
            initiator=V30PresExRecord.INITIATOR_SELF,
            role=V30PresExRecord.ROLE_PROVER,
            state=V30PresExRecord.STATE_PROPOSAL_SENT,
            pres_proposal=pres_proposal_message,
            auto_present=auto_present,
            trace=(pres_proposal_message._trace is not None),
        )

        async with self._profile.session() as session:
            await pres_ex_record.save(
                session, reason="create v3.0 presentation proposal"
            )

        return pres_ex_record

    async def receive_pres_proposal(
        self, message: V30PresProposal, conn_record: ConnRecord
    ):
        """
        Receive a presentation proposal from message in context on manager creation.

        Returns:
            Presentation exchange record, created

        """
        pres_ex_record = V30PresExRecord(
            connection_id=conn_record.connection_id,
            thread_id=message._thread_id,
            initiator=V30PresExRecord.INITIATOR_EXTERNAL,
            role=V30PresExRecord.ROLE_VERIFIER,
            state=V30PresExRecord.STATE_PROPOSAL_RECEIVED,
            pres_proposal=message,
            trace=(message._trace is not None),
        )

        async with self._profile.session() as session:
            await pres_ex_record.save(
                session, reason="receive v3.0 presentation request"
            )

        return pres_ex_record

    async def create_bound_request(
        self,
        pres_ex_record: V30PresExRecord,
        request_data: dict = None,
        comment: str = None,
    ):
        """
        Create a presentation request bound to a proposal.

        Args:
            pres_ex_record: Presentation exchange record for which
                to create presentation request
            comment: Optional human-readable comment pertaining to request creation

        Returns:
            A tuple (updated presentation exchange record, presentation request message)

        """
        proof_proposal = pres_ex_record.pres_proposal
        # input_formats = proof_proposal.formats
        input_attachments = proof_proposal.attachments
        input_formats = []
        for attach in input_attachments:
            input_formats.append(attach.format)

        request_formats = []
        for format in input_formats:
            pres_exch_format = V30PresFormat.Format.get(format.format)

            if pres_exch_format:
                request_formats.append(
                    await pres_exch_format.handler(self._profile).create_bound_request(
                        pres_ex_record,
                        request_data,
                    )
                )
        if len(request_formats) == 0:
            raise V30PresManagerError(
                "Unable to create presentation request. No supported formats"
            )
        pres_request_message = V30PresRequest(
            # comment=comment, will_confirm=True,
            body=V30PresBody(comment=comment, will_confirm=True),
            # formats=[format for (format, _) in request_formats],
            attachments=[attach for (_, attach) in request_formats],
        )
        pres_request_message._thread = {"thid": pres_ex_record.thread_id}
        pres_request_message.assign_trace_decorator(
            self._profile.settings, pres_ex_record.trace
        )

        pres_ex_record.thread_id = pres_request_message._thread_id
        pres_ex_record.state = V30PresExRecord.STATE_REQUEST_SENT
        pres_ex_record.pres_request = pres_request_message
        async with self._profile.session() as session:
            await pres_ex_record.save(
                session, reason="create (bound) v3.0 presentation request"
            )

        return pres_ex_record, pres_request_message

    async def create_exchange_for_request(
        self,
        connection_id: str,
        pres_request_message: V30PresRequest,
        auto_verify: bool = None,
    ):
        """
        Create a presentation exchange record for input presentation request.

        Args:
            connection_id: connection identifier
            pres_request_message: presentation request to use in creating
                exchange record, extracting indy proof request and thread id

        Returns:
            Presentation exchange record, updated

        """
        pres_ex_record = V30PresExRecord(
            connection_id=connection_id,
            thread_id=pres_request_message._thread_id,
            initiator=V30PresExRecord.INITIATOR_SELF,
            role=V30PresExRecord.ROLE_VERIFIER,
            state=V30PresExRecord.STATE_REQUEST_SENT,
            pres_request=pres_request_message,
            auto_verify=auto_verify,
            trace=(pres_request_message._trace is not None),
        )
        async with self._profile.session() as session:
            await pres_ex_record.save(
                session, reason="create (free) v3.0 presentation request"
            )

        return pres_ex_record

    async def receive_pres_request(self, pres_ex_record: V30PresExRecord):
        """
        Receive a presentation request.

        Args:
            pres_ex_record: presentation exchange record with request to receive

        Returns:
            The presentation exchange record, updated

        """
        pres_ex_record.state = V30PresExRecord.STATE_REQUEST_RECEIVED
        async with self._profile.session() as session:
            await pres_ex_record.save(
                session, reason="receive v3.0 presentation request"
            )

        return pres_ex_record

    async def create_pres(
        self,
        pres_ex_record: V30PresExRecord,
        request_data: dict = {},
        *,
        comment: str = None,
    ) -> Tuple[V30PresExRecord, V30Pres]:
        """
        Create a presentation.

        Args:
            pres_ex_record: record to update
            requested_credentials: indy formatted requested_credentials
            comment: optional human-readable comment
            format_: presentation format

        Example `requested_credentials` format, mapping proof request referents (uuid)
        to wallet referents (cred id):

        ::

            {
                "self_attested_attributes": {
                    "j233ffbc-bd35-49b1-934f-51e083106f6d": "value"
                },
                "requested_attributes": {
                    "6253ffbb-bd35-49b3-934f-46e083106f6c": {
                        "cred_id": "5bfa40b7-062b-4ae0-a251-a86c87922c0e",
                        "revealed": true
                    }
                },
                "requested_predicates": {
                    "bfc8a97d-60d3-4f21-b998-85eeabe5c8c0": {
                        "cred_id": "5bfa40b7-062b-4ae0-a251-a86c87922c0e"
                    }
                }
            }

        Returns:
            A tuple (updated presentation exchange record, presentation message)

        """
        proof_request = pres_ex_record.pres_request
        # input_formats = proof_request.formats
        input_attachments = proof_request.attachments
        input_formats = []
        for attach in input_attachments:
            input_formats.append(attach.format)

        pres_formats = []
        for format in input_formats:
            # TODO: split the format!!!

            pres_exch_format = V30PresFormat.Format.get(format.format)

            if pres_exch_format:
                pres_tuple = await pres_exch_format.handler(self._profile).create_pres(
                    pres_ex_record,
                    request_data,
                )
                if pres_tuple:
                    pres_formats.append(pres_tuple)
                else:
                    raise V30PresManagerError(
                        "Unable to create presentation. ProblemReport message sent"
                    )
        if len(pres_formats) == 0:
            raise V30PresManagerError(
                "Unable to create presentation. No supported formats"
            )
        pres_message = V30Pres(
            body=V30PresBody(comment=comment),
            attachments=[attach for (_, attach) in pres_formats],
        )

        pres_message._thread = {"thid": pres_ex_record.thread_id}
        pres_message.assign_trace_decorator(
            self._profile.settings, pres_ex_record.trace
        )

        # save presentation exchange state
        pres_ex_record.state = V30PresExRecord.STATE_PRESENTATION_SENT
        pres_ex_record.pres = V30Pres(
            body=V30PresBody(),
            # formats=[format for (format, _) in pres_formats],
            attachments=[attach for (_, attach) in pres_formats],
        )
        async with self._profile.session() as session:
            await pres_ex_record.save(session, reason="create v3.0 presentation")
        return pres_ex_record, pres_message

    async def receive_pres(self, message: V30Pres, conn_record: ConnRecord):
        """
        Receive a presentation, from message in context on manager creation.

        Returns:
            presentation exchange record, retrieved and updated

        """

        thread_id = message._thread_id
        conn_id_filter = (
            None
            if conn_record is None
            else {"connection_id": conn_record.connection_id}
        )
        async with self._profile.session() as session:
            try:
                pres_ex_record = await V30PresExRecord.retrieve_by_tag_filter(
                    session, {"thread_id": thread_id}, conn_id_filter
                )
            except StorageNotFoundError:
                # Proof req not bound to any connection: requests_attach in OOB msg
                pres_ex_record = await V30PresExRecord.retrieve_by_tag_filter(
                    session, {"thread_id": thread_id}, None
                )
        input_formats = []
        input_attachments = message.attachments

        for attach in input_attachments:
            input_formats.append(attach.format)

        for format in input_formats:
            pres_format = V30PresFormat.Format.get(format.format)

            if pres_format:
                receive_pres_return = await pres_format.handler(
                    self._profile
                ).receive_pres(
                    message,
                    pres_ex_record,
                )
                if isinstance(receive_pres_return, bool) and not receive_pres_return:
                    raise V30PresManagerError(
                        "Unable to verify received presentation."
                        " ProblemReport message sent"
                    )
        pres_ex_record.pres = message
        pres_ex_record.state = V30PresExRecord.STATE_PRESENTATION_RECEIVED
        if not pres_ex_record.connection_id:
            pres_ex_record.connection_id = conn_record.connection_id
        async with self._profile.session() as session:
            await pres_ex_record.save(session, reason="receive v3.0 presentation")

        return pres_ex_record

    # TODO: change the structure of verify_pres

    async def verify_pres(self, pres_ex_record: V30PresExRecord):
        """
        Verify a presentation.

        Args:
            pres_ex_record: presentation exchange record
                with presentation request and presentation to verify

        Returns:
            presentation exchange record, updated

        """
        pres_request_msg = pres_ex_record.pres_request
        # input_formats = pres_request_msg.formats
        input_attachments = pres_request_msg.attachments
        input_formats = []
        for attach in input_attachments:
            input_formats.append(attach.format)

        for format in input_formats:
            pres_exch_format = V30PresFormat.Format.get(format.format)

            if pres_exch_format:
                pres_ex_record = await pres_exch_format.handler(
                    self._profile
                ).verify_pres(
                    pres_ex_record,
                )

        pres_ex_record.state = V30PresExRecord.STATE_DONE

        async with self._profile.session() as session:
            await pres_ex_record.save(session, reason="verify v3.0 presentation")

        if pres_request_msg.body.will_confirm:
            await self.send_pres_ack(pres_ex_record)

        return pres_ex_record

    async def send_pres_ack(self, pres_ex_record: V30PresExRecord):
        """
        Send acknowledgement of presentation receipt.

        Args:
            pres_ex_record: presentation exchange record with thread id

        """
        responder = self._profile.inject_or(BaseResponder)

        if responder:
            pres_ack_message = V30PresAck()
            pres_ack_message._thread = {"thid": pres_ex_record.thread_id}
            pres_ack_message.assign_trace_decorator(
                self._profile.settings, pres_ex_record.trace
            )

            await responder.send_reply(
                pres_ack_message,
                connection_id=pres_ex_record.connection_id,
            )
        else:
            LOGGER.warning(
                "Configuration has no BaseResponder: cannot ack presentation on %s",
                pres_ex_record.thread_id,
            )

    async def receive_pres_ack(self, message: V30PresAck, conn_record: ConnRecord):
        """
        Receive a presentation ack, from message in context on manager creation.

        Returns:
            presentation exchange record, retrieved and updated

        """
        async with self._profile.session() as session:
            pres_ex_record = await V30PresExRecord.retrieve_by_tag_filter(
                session,
                {"thread_id": message._thread_id},
                {"connection_id": conn_record.connection_id},
            )

            pres_ex_record.state = V30PresExRecord.STATE_DONE

            await pres_ex_record.save(session, reason="receive v3.0 presentation ack")

        return pres_ex_record

    async def receive_problem_report(
        self, message: V30PresProblemReport, connection_id: str
    ):
        """
        Receive problem report.

        Returns:
            presentation exchange record, retrieved and updated

        """
        # FIXME use transaction, fetch for_update
        async with self._profile.session() as session:
            pres_ex_record = await (
                V30PresExRecord.retrieve_by_tag_filter(
                    session,
                    {"thread_id": message._thread_id},
                    {"connection_id": connection_id},
                )
            )

            pres_ex_record.state = V30PresExRecord.STATE_ABANDONED
            code = message.description.get("code", ProblemReportReason.ABANDONED.value)
            pres_ex_record.error_msg = f"{code}: {message.description.get('en', code)}"
            await pres_ex_record.save(session, reason="received problem report")

        return pres_ex_record
