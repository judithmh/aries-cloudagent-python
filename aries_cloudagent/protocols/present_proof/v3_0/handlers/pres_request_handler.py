"""Presentation request message handler."""

from .....indy.holder import IndyHolderError
from .....ledger.error import LedgerError
from .....messaging.base_handler import BaseHandler, HandlerException
from .....messaging.models.base import BaseModelError
from .....messaging.request_context import RequestContext
from .....messaging.responder import BaseResponder
from .....storage.error import StorageError, StorageNotFoundError
from .....utils.tracing import trace_event, get_timer
from .....wallet.error import WalletNotFoundError

from .. import problem_report_for_record
from ..formats.handler import V30PresFormatHandlerError
from ..manager import V30PresManager
from ..messages.pres_request import V30PresRequest
from ..messages.pres_problem_report import ProblemReportReason
from ..models.pres_exchange import V30PresExRecord


class V30PresRequestHandler(BaseHandler):
    """Message handler class for v2.0 presentation requests."""

    async def handle(self, context: RequestContext, responder: BaseResponder):
        """
        Message handler logic for v2.0 presentation requests.

        Args:
            context: request context
            responder: responder callback

        """
        r_time = get_timer()

        self._logger.debug("V30PresRequestHandler called with context %s", context)
        assert isinstance(context.message, V30PresRequest)
        self._logger.info(
            "Received v2.0 presentation request message: %s",
            context.message.serialize(as_string=True),
        )

        #TODO: check and add this
        ## If connection is present it must be ready for use
        #if context.connection_record and not context.connection_ready:
        #    raise HandlerException("Connection used for presentation request not ready")
#
        ## Find associated oob record
        #oob_processor = context.inject(OobMessageProcessor)
        #oob_record = await oob_processor.find_oob_record_for_inbound_message(context)
#
        ## Either connection or oob context must be present
        #if not context.connection_record and not oob_record:
        #    raise HandlerException(
        #        "No connection or associated connectionless exchange found for"
        #        " presentation request"
        #    )
#       
        #TODO:  check and mybe delete this
        #connection_id = (
        #    context.connection_record.connection_id
        #    if context.connection_record
        #    else None
        #)

        if not context.connection_ready:
            raise HandlerException("No connection established for presentation request")

        profile = context.profile
        pres_manager = V30PresManager(profile)

        # Get pres ex record (holder initiated via proposal)
        # or create it (verifier sent request first)
        #TODO: check and add role if necessary!
        try:
            async with profile.session() as session:
                pres_ex_record = await V30PresExRecord.retrieve_by_tag_filter(
                    session,
                    {"thread_id": context.message._thread_id},
                    {"connection_id": context.connection_record.connection_id
                    #,"role": V20PresExRecord.ROLE_PROVER,
                    },
                )  # holder initiated via proposal
            pres_ex_record.pres_request = context.message
        except StorageNotFoundError:
            # verifier sent this request free of any proposal
            pres_ex_record = V30PresExRecord(
                connection_id=context.connection_record.connection_id,
                thread_id=context.message._thread_id,
                initiator=V30PresExRecord.INITIATOR_EXTERNAL,
                role=V30PresExRecord.ROLE_PROVER,
                pres_request=context.message,
                auto_present=context.settings.get(
                    "debug.auto_respond_presentation_request"
                ),
                trace=(context.message._trace is not None),
            )

        pres_ex_record = await pres_manager.receive_pres_request(
            pres_ex_record
        )  # mgr only saves record: on exception, saving state err is hopeless

        r_time = trace_event(
            context.settings,
            context.message,
            outcome="V30PresRequestHandler.handle.END",
            perf_counter=r_time,
        )

        # If auto_present is enabled, respond immediately with presentation
        if pres_ex_record.auto_present:
            pres_message = None
            try:
                (pres_ex_record, pres_message) = await pres_manager.create_pres(
                    pres_ex_record=pres_ex_record,
                    comment=(
                        f"auto-presented for proof requests"
                        f", pres_ex_record: {pres_ex_record.pres_ex_id}"
                    ),
                )
                await responder.send_reply(pres_message)
            except (
                BaseModelError,
                IndyHolderError,
                LedgerError,
                StorageError,
                WalletNotFoundError,
                V30PresFormatHandlerError,
            ) as err:
                self._logger.exception(err)
                if pres_ex_record:
                    async with profile.session() as session:
                        await pres_ex_record.save_error_state(
                            session,
                            reason=err.roll_up,  # us: be specific
                        )
                    await responder.send_reply(
                        problem_report_for_record(
                            pres_ex_record,
                            ProblemReportReason.ABANDONED.value,  # them: be vague
                        )
                    )
            trace_event(
                context.settings,
                pres_message,
                outcome="V30PresRequestHandler.handle.PRESENT",
                perf_counter=r_time,
            )
