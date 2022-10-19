import pytest

from asynctest import mock as async_mock, TestCase as AsyncTestCase
from aries_cloudagent.messaging.decorators.attach_decorator2 import AttachDecorator

from aries_cloudagent.protocols.present_proof.v3_0.messages.pres_body import V30PresBody

from ......messaging.request_context import RequestContext
from ......messaging.responder import MockResponder
from ......transport.inbound.receipt import MessageReceipt

from ...messages.pres_proposal import V30PresProposal

from .. import pres_proposal_handler as test_module


class TestV30PresProposalHandler(AsyncTestCase):
    async def test_called(self):
        request_context = RequestContext.test_context()
        request_context.message_receipt = MessageReceipt()
        request_context.settings["debug.auto_respond_presentation_proposal"] = False

        with async_mock.patch.object(
            test_module, "V30PresManager", autospec=True
        ) as mock_pres_mgr:
            mock_pres_mgr.return_value.receive_pres_proposal = async_mock.CoroutineMock(
                return_value=async_mock.MagicMock()
            )
            request_context.message = V30PresProposal()
            request_context.connection_ready = True
            request_context.connection_record = async_mock.MagicMock()
            handler = test_module.V30PresProposalHandler()
            responder = MockResponder()
            await handler.handle(request_context, responder)

        mock_pres_mgr.assert_called_once_with(request_context.profile)
        mock_pres_mgr.return_value.receive_pres_proposal.assert_called_once_with(
            request_context.message, request_context.connection_record
        )
        assert not responder.messages

    async def test_called_auto_request(self):
        request_context = RequestContext.test_context()
        request_context.message = async_mock.MagicMock()
        print(request_context.message)
        print(request_context)
        #request_context.message.body.comment = "hello world"
        request_context.message = V30PresProposal( body = V30PresBody( comment = "hello world"))
        print("#### test 2")
        print(request_context.message)
        print(request_context)
        request_context.message_receipt = MessageReceipt()
        request_context.settings["debug.auto_respond_presentation_proposal"] = True

        with async_mock.patch.object(
            test_module, "V30PresManager", autospec=True
        ) as mock_pres_mgr:
            mock_pres_mgr.return_value.receive_pres_proposal = async_mock.CoroutineMock(
                return_value="presentation_exchange_record"
            )
            mock_pres_mgr.return_value.create_bound_request = async_mock.CoroutineMock(
                return_value=(
                    mock_pres_mgr.return_value.receive_pres_proposal.return_value,
                    "presentation_request_message",
                )
            )
            request_context.message = V30PresProposal()
            request_context.connection_ready = True
            handler = test_module.V30PresProposalHandler()
            responder = MockResponder()
            await handler.handle(request_context, responder)

        # if request_context.message.body:
        #     comment = request_context.message.body.commet,
        # else: comment = None
        mock_pres_mgr.assert_called_once_with(request_context.profile)
        mock_pres_mgr.return_value.create_bound_request.assert_called_once_with(
            pres_ex_record=(
                mock_pres_mgr.return_value.receive_pres_proposal.return_value
            ),
            comment=request_context.message.body.comment,
        )
        messages = responder.messages
        assert len(messages) == 1
        (result, target) = messages[0]
        assert result == "presentation_request_message"
        assert target == {}

    async def test_called_auto_request_x(self):
        request_context = RequestContext.test_context()
        request_context.message = async_mock.MagicMock()
        #request_context.message.body = { "comment" : "hello world",}
        # request_context.message.body["comment"] = "hello world"
        request_context.message_receipt = MessageReceipt()
        request_context.settings["debug.auto_respond_presentation_proposal"] = True

        with async_mock.patch.object(
            test_module, "V30PresManager", autospec=True
        ) as mock_pres_mgr:
            mock_pres_mgr.return_value.receive_pres_proposal = async_mock.CoroutineMock(
                return_value=async_mock.MagicMock(
                    save_error_state=async_mock.CoroutineMock()
                )
            )
            mock_pres_mgr.return_value.create_bound_request = async_mock.CoroutineMock(
                side_effect=test_module.LedgerError()
            )

            request_context.message = V30PresProposal()
            request_context.connection_ready = True
            handler = test_module.V30PresProposalHandler()
            responder = MockResponder()

            with async_mock.patch.object(
                handler._logger, "exception", async_mock.MagicMock()
            ) as mock_log_exc:
                await handler.handle(request_context, responder)
                mock_log_exc.assert_called_once()

    async def test_called_not_ready(self):
        request_context = RequestContext.test_context()
        request_context.message_receipt = MessageReceipt()

        with async_mock.patch.object(
            test_module, "V30PresManager", autospec=True
        ) as mock_pres_mgr:
            mock_pres_mgr.return_value.receive_pres_proposal = (
                async_mock.CoroutineMock()
            )
            request_context.message = V30PresProposal()
            request_context.connection_ready = False
            handler = test_module.V30PresProposalHandler()
            responder = MockResponder()
            with self.assertRaises(test_module.HandlerException):
                await handler.handle(request_context, responder)

        assert not responder.messages
