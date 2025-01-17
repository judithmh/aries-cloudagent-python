"""Credential problem report message handler."""

from .....messaging.base_handler import BaseHandler, HandlerException
from .....messaging.request_context import RequestContext
from .....messaging.responder import BaseResponder
from .....storage.error import StorageError, StorageNotFoundError

from ..manager import V30CredManager
from ..messages.cred_problem_report import V30CredProblemReport


class CredProblemReportHandler(BaseHandler):
    """Message handler class for problem reports."""

    async def handle(self, context: RequestContext, responder: BaseResponder):
        """
        Message handler logic for problem reports.

        Args:
            context: request context
            responder: responder callback
        """
        self._logger.debug(
            "Issue-credential v2.0 problem report handler called with context %s",
            context,
        )
        assert isinstance(context.message, V30CredProblemReport)

        # If connection is present it must be ready for use
        if context.connection_record and not context.connection_ready:
            raise HandlerException(
                "Connection used for credential problem report not ready"
            )
        elif not context.connection_record:
            raise HandlerException(
                "Connectionless not supported for credential problem report"
            )

        cred_manager = V30CredManager(context.profile)
        try:
            await cred_manager.receive_problem_report(
                context.message,
                context.connection_record.connection_id,
            )
        except (StorageError, StorageNotFoundError):
            self._logger.exception(
                "Error processing issue-credential v2.0 problem report message"
            )
