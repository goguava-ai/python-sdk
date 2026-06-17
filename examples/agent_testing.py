import unittest

import guava
from guava import logging_utils
from guava.examples.help_desk import agent as help_desk_agent, on_action_request
from guava.testing import MockCall


class TestHelpDeskAgent(unittest.TestCase):
    def test_intent_handler(self):
        # Test any handler in isolation by using a MockCall object.
        suggested_actions = on_action_request(MockCall(), "make a new purchase")
        assert isinstance(suggested_actions, list)
        self.assertEqual("sales", suggested_actions[0].key)

    def test_new_purchase(self):
        with help_desk_agent.test() as session:
            # Wait for the caller's turn and inject one utterance.
            session.wait_for_turn()
            session.say("Hi im looking to make a new purchase.")

            # Wait for the bot to complete it's transfer.
            session.wait_for_end()

        # You can access the transcript of a session using session.get_transcript()
        # print(session.get_transcript())

        self.assertIn("sales", session.executed_actions)
        self.assertEqual("bot-transfer", session.termination_reason)

    def test_roleplay(self):
        # Run a roleplay conversation with an LLM acting as the caller.
        session = help_desk_agent.test_roleplay("You are a caller trying to buy a new table.")
        self.assertIn("sales", session.executed_actions)
        self.assertEqual("bot-transfer", session.termination_reason)

    def test_patch_agent(self):
        # Agent.patch() returns a cloned copy for us to override callbacks.
        patched = help_desk_agent.patch()

        # We'll override one action and run a roleplay session using our patched agent.
        @patched.on_action("sales")
        def patched_task(call: guava.Call):
            call.hangup(
                "Tell then caller that the sales department is closed and that they should call back tomorrow from 9am to 5pm."
            )

        session = patched.test_roleplay("You are a caller trying to buy a new table.")

        session.evaluate(
            # These criteria must all pass, otherwise the 'evaluate' call fails.
            pass_criteria=["The agent informed the caller of the business hours from 9am to 5pm."],
            # If any of these criteria fail, the 'evaluate' call fails.
            fail_criteria=["The agent transferred the caller to the sales department."],
        )


if __name__ == "__main__":
    logging_utils.configure_logging()
    unittest.main()
